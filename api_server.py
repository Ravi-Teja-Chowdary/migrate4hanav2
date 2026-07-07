"""
Migrate4HANA - API Server (FastAPI)
====================================
Production-grade HTTP API for the migration platform.
Handles SAP connections, pipeline execution, and PDF report generation.

Usage:
    uvicorn api_server:app --host 0.0.0.0 --port 8000
    python api_server.py                     # starts uvicorn programmatically
    python api_server.py --generate-token    # generate a JWT and exit

Authentication:
    All endpoints except GET /api/health require a valid JWT Bearer token.
    Generate a token:   python api_server.py --generate-token
    Set the secret:     M4H_JWT_SECRET environment variable (auto-generated if unset)
    Set API key:        M4H_API_KEY environment variable (alternative to JWT)

    Header:  Authorization: Bearer <token>
         or  X-API-Key: <api_key>
"""

import json
import os
import sys
import asyncio

# Configure the bundled SAP NW RFC SDK (Windows: sapnwrfc/lib, Linux:
# nwrfcsdk-linux/lib) before any module imports pyrfc.
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
try:
    import sapnwrfc  # noqa: F401  (configures SAP NW RFC SDK paths)
except Exception:
    pass
import hashlib
import hmac
import base64
import secrets
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import List, Optional

# Windows Python 3.7 uses SelectorEventLoop by default, which does not support
# asyncio.create_subprocess_exec. Switch to ProactorEventLoop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_DIR, "test-output")
CONNECTIONS_FILE = os.path.join(PROJECT_DIR, "connections.json")

# F6 - version_matrix module lives under lambda/utils
_VERSION_MATRIX_DIR = os.path.join(PROJECT_DIR, "lambda", "utils")
if _VERSION_MATRIX_DIR not in sys.path:
    sys.path.insert(0, _VERSION_MATRIX_DIR)
try:
    import version_matrix as _vm   # noqa: E402
except Exception as _vm_e:
    _vm = None
    _vm_import_err = str(_vm_e)

# Shared state for active runs
_active_run = {"status": "idle", "results": None, "run_id": None}
_lock = asyncio.Lock()

# Real-time progress steps for telemetry
_progress_steps = []
_progress_lock = asyncio.Lock()

# In-memory ECC + S/4 passwords (set after successful connection test, never persisted)
_ecc_passwd = ""
_s4_passwd = ""

# ── Multi-tenant: per-client in-memory passwords + persisted client registry ──
# Everything else in the file continues to use the single _ecc_passwd above to
# stay backwards-compatible. New tenants live alongside; the "default" client
# proxies the legacy single-tenant path so existing setups still work.
CLIENTS_FILE = os.path.join(PROJECT_DIR, "clients.json")
_clients_passwds = {}   # client_id -> {"ecc": "...", "s4": "..."}


def _load_clients():
    """Read clients.json or seed a default registry."""
    if os.path.isfile(CLIENTS_FILE):
        try:
            with open(CLIENTS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "clients" in d:
                return d
        except Exception:
            pass
    return {"clients": {"default": {"id": "default", "name": "Default tenant",
                                       "created_at": datetime.now(timezone.utc).isoformat()}},
            "default_client_id": "default"}


def _save_clients(data):
    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _client_id_for(request: Request) -> str:
    """Resolve the active tenant from header > query > JWT > 'default'."""
    cid = request.headers.get("X-Client-Id") or request.query_params.get("client_id")
    if cid:
        return cid.strip()
    # Try to read it out of the JWT (set when the customer signed in to their tenant).
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        payload = verify_jwt(auth[7:]) or {}
        if payload.get("client_id"):
            return payload["client_id"]
    return "default"


def _client_outputs_dir(client_id: str) -> str:
    """Per-tenant outputs directory. The 'default' client keeps using the
    legacy flat layout so existing runs remain visible."""
    if client_id == "default":
        return OUTPUT_DIR
    base = os.path.join(OUTPUT_DIR, "clients", client_id)
    os.makedirs(base, exist_ok=True)
    return base


def _add_progress_step(stage, action, status="IN_PROGRESS", details=None, duration_ms=None):
    """Add a progress step to the real-time telemetry feed.

    The step carries both the legacy keys (stage, action, timestamp) and
    the convenience keys (step, message, ts, phase) that downstream
    consumers (tail_logs, conversion-progress, the v2 frontend) expect.
    Keeping all keys in one row means we never lose data through a
    shape translation."""
    import asyncio as _aio
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ms  = int(time.time() * 1000)
    msg = f"{stage}.{action}" if action else (stage or "")
    step = {
        "event_id":    secrets.token_hex(6),
        "timestamp":   now_iso,
        "ts":          now_ms,                # epoch-ms for tail_logs/UI
        "stage":       stage,
        "phase":       stage,                 # alias - tail_logs reads this
        "action":      action,
        "step":        msg,                   # composite key the UI expects
        "status":      status,
        "message":     (details or {}).get("message") if isinstance(details, dict) else None,
        "details":     details or {},
        "duration_ms": duration_ms,
    }
    if not step["message"]:
        step["message"] = msg
    _progress_steps.append(step)
    return step

# =============================================================================
# AUTHENTICATION
# =============================================================================
_JWT_SECRET = os.environ.get("M4H_JWT_SECRET", "")
_API_KEY = os.environ.get("M4H_API_KEY", "")

# Public endpoints that don't require authentication
_PUBLIC_PATHS = {"/api/health", "/api/auth/token"}


def _ensure_jwt_secret():
    """Resolve a JWT signing secret in this priority order:
       1. M4H_JWT_SECRET env var (12-factor; production)
       2. AWS Secrets Manager (M4H_JWT_SECRET_ARN env var) — production
       3. .jwt_secret file (LOCAL DEV ONLY — refused if M4H_ENV=prod)
       4. auto-generate + persist to .jwt_secret (LOCAL DEV ONLY)

    Production must use option 1 or 2. Plaintext file fallback is gated
    behind M4H_ENV != 'prod' so a misconfigured prod deploy fails closed
    instead of silently writing a secret to disk.
    """
    global _JWT_SECRET
    if _JWT_SECRET:
        return

    arn = os.environ.get("M4H_JWT_SECRET_ARN", "")
    if arn:
        try:
            import boto3  # local import: keep startup fast in dev
            sm = boto3.client("secretsmanager")
            resp = sm.get_secret_value(SecretId=arn)
            _JWT_SECRET = (resp.get("SecretString") or "").strip()
            if _JWT_SECRET:
                return
        except Exception as e:
            raise RuntimeError(
                f"M4H_JWT_SECRET_ARN={arn} set but Secrets Manager fetch failed: {e}. "
                "Refusing to fall back to plaintext file in production path."
            )

    env = os.environ.get("M4H_ENV", "dev").lower()
    if env in ("prod", "production"):
        raise RuntimeError(
            "M4H_ENV=prod but no JWT secret available. "
            "Set M4H_JWT_SECRET or M4H_JWT_SECRET_ARN. "
            "Plaintext .jwt_secret fallback is disabled in production."
        )

    secret_file = os.path.join(PROJECT_DIR, ".jwt_secret")
    if os.path.isfile(secret_file):
        with open(secret_file, "r", encoding="utf-8") as f:
            _JWT_SECRET = f.read().strip()
        if _JWT_SECRET:
            return
    _JWT_SECRET = secrets.token_hex(32)
    with open(secret_file, "w", encoding="utf-8") as f:
        f.write(_JWT_SECRET)
    try:
        os.chmod(secret_file, 0o600)
    except Exception:
        pass
    print("  [Auth] Generated dev-only JWT secret -> .jwt_secret (DO NOT use in prod)")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def generate_jwt(subject: str = "migrate4hana", expiry_hours: int = 24) -> str:
    """Create a minimal HS256 JWT token."""
    _ensure_jwt_secret()
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64url_encode(json.dumps({
        "sub": subject,
        "iat": now,
        "exp": now + expiry_hours * 3600,
    }).encode())
    signing_input = f"{header}.{payload}"
    sig = hmac.new(_JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def verify_jwt(token: str) -> Optional[dict]:
    """Verify a HS256 JWT. Returns the payload dict or None if invalid."""
    _ensure_jwt_secret()
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        signing_input = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(
            _JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Role-aware JWT (carries email, role, client_scopes, allowed_operations).
# Backward-compatible with the legacy /api/auth/token format: legacy tokens
# have no "role" claim and default to "iam" with empty scope (deny by default
# on protected operations until a real login replaces the token).
# ─────────────────────────────────────────────────────────────────────────────
def generate_user_jwt(*, email: str, role: str,
                      client_scopes: Optional[List[str]] = None,
                      allowed_operations: Optional[List[str]] = None,
                      expiry_hours: int = 12) -> str:
    """Issue a JWT carrying the full identity claim. Used by /api/auth/login."""
    _ensure_jwt_secret()
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64url_encode(json.dumps({
        "sub":   email,
        "email": email,
        "role":  role,
        "scopes": client_scopes or [],
        "ops":    allowed_operations or [],
        "iat":   now,
        "exp":   now + expiry_hours * 3600,
    }).encode())
    signing_input = f"{header}.{payload}"
    sig = hmac.new(_JWT_SECRET.encode(), signing_input.encode(),
                   hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


# =============================================================================
# AUTH DEPENDENCY
# =============================================================================
async def require_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """FastAPI dependency for JWT/API-key authentication."""
    path = request.url.path.rstrip("/")
    if path in _PUBLIC_PATHS:
        return True

    # Check Bearer token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if verify_jwt(token):
            return True

    # Check query-string token (for PDF download links opened in new tabs)
    qs_token = request.query_params.get("token")
    if qs_token and verify_jwt(qs_token):
        return True

    # Check API key
    if _API_KEY and x_api_key and hmac.compare_digest(x_api_key, _API_KEY):
        return True

    raise HTTPException(
        status_code=401,
        detail={
            "error": "Authentication required",
            "hint": "Set Authorization: Bearer <jwt> or X-API-Key: <key>",
        },
        headers={"WWW-Authenticate": 'Bearer realm="migrate4hana"'},
    )


# Clients (multi-tenant) endpoints — defined further below, after `app =
# FastAPI(...)`. The data model lives up here so it's parseable before app init.
class ClientCreate(BaseModel):
    id: str
    name: Optional[str] = None


# =============================================================================
# CONNECTION MANAGEMENT
# =============================================================================
def _load_connections():
    if os.path.isfile(CONNECTIONS_FILE):
        with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ecc": None, "s4hana": None}


def _save_connections(data):
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def test_ecc_connection(params):
    global _ecc_passwd
    host = params.get("ashost", "")
    sysnr = params.get("sysnr", "")
    client = params.get("client", "")
    user = params.get("user", "")
    passwd = params.get("passwd", "")
    if not all([host, sysnr, client, user]):
        return {"status": "error", "message": "Missing required fields: ashost, sysnr, client, user"}
    try:
        import pyrfc
        conn_params = {"ashost": host, "sysnr": sysnr, "client": client, "user": user, "passwd": passwd}
        if params.get("saprouter"):
            conn_params["saprouter"] = params["saprouter"]
        conn = pyrfc.Connection(**conn_params)
        try:
            result = conn.call("RFC_SYSTEM_INFO")
            sys_info = result.get("RFCSI_EXPORT", {})
            # Store password in memory for pipeline use
            _ecc_passwd = passwd
            # Auto-save connection details on successful test so pipeline can find them
            conns = _load_connections()
            conns["ecc"] = {
                "ashost": host, "sysnr": sysnr, "client": client,
                "user": user, "saprouter": params.get("saprouter", ""),
                "saved_at": datetime.now().isoformat(),
            }
            _save_connections(conns)
            return {
                "status": "connected", "system_id": sys_info.get("RFCSYSID", ""),
                "host": sys_info.get("RFCHOST", host), "db_system": sys_info.get("RFCDBSYS", ""),
                "sap_release": sys_info.get("RFCSAPRL", ""), "kernel": sys_info.get("RFCKERNRL", ""),
                "client": client,
                "message": f"Connected to {sys_info.get('RFCSYSID', host)} (ECC {sys_info.get('RFCSAPRL', '')})",
            }
        finally:
            conn.close()
    except ImportError:
        return {"status": "error", "message": "PyRFC is not installed. Install pyrfc to connect to SAP ECC."}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


def test_s4hana_connection(params):
    host = params.get("ashost", "")
    conn_type = params.get("connection_type", "rfc")
    if not host:
        return {"status": "error", "message": "Missing required field: ashost (hostname)"}
    if conn_type == "rfc":
        sysnr = params.get("sysnr", "")
        client = params.get("client", "")
        user = params.get("user", "")
        if not all([sysnr, client, user]):
            return {"status": "error", "message": "Missing required fields for RFC: sysnr, client, user"}
        try:
            import pyrfc
            conn = pyrfc.Connection(ashost=host, sysnr=sysnr, client=client, user=user, passwd=params.get("passwd", ""))
            try:
                result = conn.call("RFC_SYSTEM_INFO")
                sys_info = result.get("RFCSI_EXPORT", {})
            finally:
                conn.close()
            return {"status": "connected", "system_id": sys_info.get("RFCSYSID", ""), "host": host,
                    "sap_release": sys_info.get("RFCSAPRL", ""),
                    "message": f"Connected to S/4HANA {sys_info.get('RFCSYSID', host)}"}
        except ImportError:
            return {"status": "error", "system_id": "", "host": host, "sap_release": "",
                    "message": "PyRFC not installed on the server. Install pyrfc + SAP NW RFC SDK to test live RFC connections."}
        except Exception as e:
            return {"status": "error", "message": f"Connection failed: {str(e)}"}
    elif conn_type == "odata":
        api_url = params.get("api_url", host)
        return {"status": "pending", "system_id": "S4HC", "host": api_url, "sap_release": "S/4HANA Cloud",
                "message": f"OData endpoint {api_url} registered. Will use Communication Arrangements in target."}
    return {"status": "error", "message": f"Unknown connection type: {conn_type}"}


# =============================================================================
# RUN MANAGEMENT
# =============================================================================
def list_runs(client_id: str = "default"):
    """List runs scoped to one tenant. The 'default' client sees the legacy
    flat layout (so old runs remain visible); other tenants only see runs
    under outputs/clients/<client_id>/."""
    runs = []
    base = _client_outputs_dir(client_id)
    if not os.path.isdir(base):
        return runs
    for entry in sorted(os.listdir(base), reverse=True):
        if entry.startswith("run_"):
            report_path = os.path.join(base, entry, "final-report.json")
            if os.path.isfile(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                runs.append({"id": entry, "timestamp": entry.replace("run_", ""),
                             "client_id": client_id,
                             "has_execution": "cutover" in data, "results": data})
    return runs


def get_run(run_id, client_id: str = "default"):
    """Read a run's final-report.json, scoped to one tenant. Falls back to the
    legacy flat path if the tenant directory doesn't have it — useful when a
    run was created before tenancy was introduced."""
    base = _client_outputs_dir(client_id)
    report_path = os.path.join(base, run_id, "final-report.json")
    if not os.path.isfile(report_path) and client_id != "default":
        # Legacy back-compat: look in the flat outputs dir.
        report_path = os.path.join(OUTPUT_DIR, run_id, "final-report.json")
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def start_pipeline_async(mode="full", generate_pdf_after=False, pipeline_kind="in_place",
                                 run_id=None, load_to_s4=False, simulation_mode=False,
                                 max_rows=None, preserve_source_numbers=False):
    global _active_run
    # The wizard hands us its own run_id (e.g. wiz-20260615T120117Z-b539783e);
    # keep it so logs/state files/UI all use the same identifier instead of
    # the runner inventing a fresh `local-<ts>` id.
    pipeline_run_id = run_id or f"run-{int(time.time())}"
    async with _lock:
        if _active_run["status"] == "running":
            return {"error": "Pipeline already running"}
        _active_run = {"status": "running", "results": None,
                       "run_id": pipeline_run_id,
                       "started": time.time(), "mode": mode,
                       "generate_pdf_after": generate_pdf_after,
                       "load_to_s4": load_to_s4,
                       "simulation_mode": simulation_mode}

    # Clear old progress steps + reset the parser state used by
    # _parse_pipeline_output (phase tracker, last-stage-step pointer).
    _progress_steps.clear()
    try:
        _parse_state["phase"] = None
        _parse_state["last_stage_step"] = None
    except NameError:
        pass
    _add_progress_step("pipeline", "Pipeline started", "IN_PROGRESS",
                        {"mode": mode, "kind": pipeline_kind})

    async def _run():
        global _active_run
        try:
            runner = "run_local_lift_and_shift.py" if pipeline_kind == "lift_and_shift" else "run_local_pipeline.py"
            # `-u` = unbuffered binary stdout/stderr. Without this, Windows
            # Python pipes block-buffer print() and the UI sees zero events
            # for ~30s while discovery scans 20k+ programs. PYTHONUNBUFFERED=1
            # below covers any nested subprocess too.
            cmd = [sys.executable, "-u", os.path.join(PROJECT_DIR, runner)]

            # Determine if live ECC connection is available
            conns = _load_connections()
            ecc_conf = conns.get("ecc") or {}
            s4_conf  = conns.get("s4hana") or {}
            has_ecc = bool(ecc_conf.get("ashost"))
            use_live = has_ecc and _ecc_passwd

            if use_live:
                # The classic runner (run_local_pipeline.py) accepts --live as a
                # no-op back-compat flag; run_local_lift_and_shift.py does NOT
                # have a --live arg (argparse exits 2 on unknown args). Live
                # mode for both runners is signalled by M4H_ECC_PASSWD env var.
                if pipeline_kind != "lift_and_shift":
                    cmd.append("--live")
                _add_progress_step("connection", "Using live ECC connection", "SUCCESS",
                                   {"host": ecc_conf.get("ashost", "")})
            elif has_ecc and not _ecc_passwd:
                # Connection is saved but password expired (server restarted).
                _add_progress_step("connection",
                                   "ECC connection saved but session expired. "
                                   "Please re-test the connection on the Connections page to re-authenticate.",
                                   "ERROR")
                async with _lock:
                    _active_run = {"status": "failed",
                                   "error": "ECC password not in memory. Re-test the connection to re-authenticate.",
                                   "results": None}
                return
            else:
                # Mock mode has been removed — a live ECC connection is required.
                _add_progress_step("connection",
                                   "No ECC connection configured. "
                                   "Save and test an ECC connection on the Connections page before starting a run.",
                                   "ERROR")
                async with _lock:
                    _active_run = {"status": "failed",
                                   "error": "No live ECC connection configured. Mock mode has been removed.",
                                   "results": None}
                return

            if pipeline_kind == "lift_and_shift":
                # run_local_lift_and_shift.py uses --through <stage_id> to scope.
                _LS_THROUGH = {"assess": "stage3", "code": "stage9c", "data": "stage18"}
                if mode in _LS_THROUGH:
                    cmd.extend(["--through", _LS_THROUGH[mode]])
                # Propagate the run id so the wizard, log files, and pipeline
                # state all share one identifier instead of the runner
                # inventing a fresh `local-<ts>` id.
                cmd.extend(["--run-id", str(pipeline_run_id)])
                # Pass saved hosts; the runner falls back to env if these
                # are blank.
                if ecc_conf.get("ashost"):
                    cmd.extend(["--ecc-host", ecc_conf["ashost"]])
                if s4_conf.get("ashost"):
                    cmd.extend(["--target-host", s4_conf["ashost"]])
            else:
                if mode == "assess":
                    cmd.append("--assess-only")
                elif mode == "ecc_full":
                    cmd.extend(["--mode", "ecc_full"])

            _add_progress_step("extraction", "Starting ECC data extraction", "IN_PROGRESS")

            env = {**os.environ, "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1"}
            if use_live:
                env["M4H_ECC_PASSWD"] = _ecc_passwd
                if _s4_passwd:
                    env["M4H_TARGET_PASSWD"] = _s4_passwd

            # Data-migrator behaviour: extract-only (writes Migration Cockpit
            # CSV templates, no S/4 writes) vs live load (calls BAPIs against
            # S/4 immediately). Flipping load_to_s4=True causes real writes -
            # an explicit progress banner so the operator can see the choice
            # they made reflected in Live Ops.
            # Per-object row cap from the wizard — overrides the data-migrator
            # env default. Clamped defensively; a bad payload from the UI
            # should never widen the cap beyond a sane ceiling.
            if preserve_source_numbers:
                env["M4H_PRESERVE_SRC_NUMBERS"] = "1"
                _add_progress_step(
                    "mode",
                    "Source document numbers will be preserved on S/4 (external "
                    "number range required per PREREQ_RUNBOOK.md §C).",
                    "INFO", {"preserve_source_numbers": True})
            if max_rows is not None:
                try:
                    cap = max(1, min(1_000_000, int(max_rows)))
                    env["M4H_LOAD_MAX_ROWS"] = str(cap)
                    _add_progress_step("mode",
                                       f"Row cap set from wizard: {cap:,} rows/object",
                                       "INFO", {"max_rows": cap})
                except Exception:
                    pass  # bad value → fall back to Lambda's own default

            if load_to_s4:
                env["M4H_LOAD_TO_S4"] = "1"
                if simulation_mode:
                    # Route through BAPI TEST_RUN + staging tables (spines
                    # already honour this env; nothing commits). Kept as an
                    # env var, not a runner CLI flag, so the same value flows
                    # through every subprocess boundary.
                    env["M4H_SIMULATE"] = "1"
                    _add_progress_step("mode",
                                       "SIMULATION mode: BAPIs called with TEST_RUN, "
                                       "staging tables used - no commits to S/4HANA.",
                                       "INFO",
                                       {"load_to_s4": True, "simulation_mode": True})
                else:
                    env.pop("M4H_SIMULATE", None)
                    _add_progress_step("mode",
                                       "LIVE LOAD enabled: data-migrator will call "
                                       "BAPIs against S/4HANA. Writes are not reversible.",
                                       "WARNING",
                                       {"load_to_s4": True, "simulation_mode": False})
            else:
                _add_progress_step("mode",
                                   "EXTRACT-ONLY mode: data lands in Migration Cockpit "
                                   "CSV templates under local-staging/. No S/4 writes "
                                   "until you re-run with Load to S/4HANA enabled.",
                                   "INFO",
                                   {"load_to_s4": False, "simulation_mode": False})

            # Non-Unicode ECC handshake. Default to codepage 1100 (SAP_LATIN1)
            # which is what every IDES EHP < 8 Unicode-disabled system runs;
            # the saved connection's `codepage` field overrides this. Without
            # this hint pyrfc on Windows negotiates 4103 (UTF-16LE) and the
            # server replies RFC_CONVERSION_FAILURE (rc=22) during handshake.
            # MFC_CODEPAGE is read natively by the NW RFC SDK, so every
            # handler benefits without per-handler changes.
            ecc_codepage = (ecc_conf.get("codepage") or "").strip()
            if not ecc_codepage:
                # Heuristic default: most CAL IDES profiles + classic ECC 6.0
                # are non-Unicode 1100. Unicode systems (EHP8+ Unicode, S/4)
                # ignore the hint, so this is safe as a global default.
                ecc_codepage = os.environ.get("M4H_ECC_CODEPAGE", "1100")
            env["M4H_ECC_CODEPAGE"] = ecc_codepage
            env["MFC_CODEPAGE"] = ecc_codepage
            _add_progress_step("connection",
                               f"RFC codepage set to {ecc_codepage} (override with the saved "
                               f"connection's codepage field or M4H_ECC_CODEPAGE env)",
                               "INFO")

            # Stream stdout line-by-line for real-time progress
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_DIR, env=env)

            # Stream BOTH stdout and stderr line-by-line. Discovery uses
            # logger.info(...) which goes to stderr, so if we don't drain
            # stderr live the UI sees nothing during a 30s scan and then
            # everything in a burst at the end.
            stderr_lines = []

            async def _read_stdout():
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    _parse_pipeline_output(text)

            async def _read_stderr():
                while True:
                    line = await proc.stderr.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if not text:
                        continue
                    stderr_lines.append(text)
                    # Surface notable stderr lines as live progress so the
                    # operator watches discovery happen in Live Ops instead
                    # of staring at a frozen window. Filter out the SDK's
                    # chatty boto/timer noise.
                    if any(k in text for k in
                            ("INFO:", "WARNING:", "ERROR:", "scan_",
                             "Scanning", "Found", "Discovery", "rc=",
                             "key=", "RFC ")):
                        _add_progress_step("runner", text[:200], "INFO")

            # Heartbeat: every 15s while the subprocess is alive, emit a
            # "still scanning..." event so the operator knows we haven't
            # frozen even if a long RFC call is in flight.
            async def _heartbeat():
                t0 = time.time()
                while proc.returncode is None:
                    await asyncio.sleep(15)
                    if proc.returncode is None:
                        elapsed = int(time.time() - t0)
                        _add_progress_step("runner",
                                           f"Subprocess alive, {elapsed}s elapsed "
                                           f"(discovery typically takes ~30s)",
                                           "IN_PROGRESS")

            heartbeat_task = asyncio.create_task(_heartbeat())

            # ROOT CAUSE FIX (commit 25daadd added a 600s wait_for around
            # _read_stdout; lift-and-shift runs take ~13min on a 20k-program
            # ECC, so stdout reading was being CANCELLED mid-run. The final
            # "[stageN]" + "Run X finished rc=0" markers - which trigger the
            # Project tracker reconciliation - were never read, even though
            # the subprocess finished cleanly and stderr kept flowing).
            #
            # Now we drain both pipes concurrently with a generous wall-clock
            # cap, so both naturally terminate when the subprocess closes
            # them on exit.
            PIPELINE_MAX_SECONDS = 3600  # 1 hour - covers worst-case real ECCs
            try:
                await asyncio.wait_for(
                    asyncio.gather(_read_stdout(), _read_stderr()),
                    timeout=PIPELINE_MAX_SECONDS,
                )
            except asyncio.TimeoutError:
                # Genuine wall-clock timeout: kill the subprocess so proc.wait
                # below doesn't hang. Caller branch handles the error verdict.
                try:
                    proc.kill()
                except Exception:
                    pass
            stderr_text = "\n".join(stderr_lines)
            heartbeat_task.cancel()
            try: await heartbeat_task
            except (asyncio.CancelledError, Exception): pass
            # Subprocess has already exited (or been killed) - this is just
            # the final reap so proc.returncode is populated.
            try:
                await asyncio.wait_for(proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

            if proc.returncode != 0:
                err_msg = (stderr_text or "Unknown error").strip()[-500:]
                print(f"  [API] Pipeline subprocess failed (exit {proc.returncode}): {err_msg}")
                _add_progress_step("pipeline", f"Pipeline failed (exit {proc.returncode})", "ERROR",
                                   {"error": err_msg[:200]})
                _add_progress_step("extraction",
                                   "ECC data extraction halted (pipeline failed before completion)",
                                   "ERROR")
            else:
                _add_progress_step("extraction", "ECC data extraction completed", "SUCCESS")

            # Locate the run output. The two runners write to different roots:
            #   classic run_local_pipeline.py -> outputs/run_<ts>/final-report.json
            #   run_local_lift_and_shift.py   -> local-staging/m4h-local/runs/<run_id>/
            # so we check the lift-and-shift path explicitly when the runner
            # was the lift-and-shift one. Otherwise fall through to list_runs.
            latest = None
            if pipeline_kind == "lift_and_shift":
                ls_root = os.path.join(PROJECT_DIR, "local-staging", "m4h-local",
                                        "runs", str(pipeline_run_id))
                if os.path.isdir(ls_root):
                    # Build a minimal "results" dict by listing the per-stage
                    # subdirectories the runner wrote. Each one corresponds to
                    # a handler that produced artifacts.
                    artefacts = sorted(
                        d for d in os.listdir(ls_root)
                        if os.path.isdir(os.path.join(ls_root, d))
                    )
                    pdf_existing = os.path.join(ls_root, "report", "migration-report.pdf")
                    latest = {
                        "id": str(pipeline_run_id),
                        "results": {"kind": "lift_and_shift",
                                     "artefact_dirs": artefacts,
                                     "report_pdf": pdf_existing if os.path.isfile(pdf_existing) else None,
                                     "root": ls_root},
                    }
            if latest is None:
                runs = list_runs()
                latest = runs[0] if runs else None

            # Generate PDF if requested. For lift-and-shift the runner's
            # stage27 already wrote one, so we just confirm it landed.
            pdf_generated = False
            if latest and pipeline_kind == "lift_and_shift":
                pdf_path = (latest.get("results") or {}).get("report_pdf")
                if pdf_path and os.path.isfile(pdf_path):
                    pdf_generated = True
                    _add_progress_step("pdf-generation",
                                       f"PDF report ready ({os.path.getsize(pdf_path) // 1024} KB)",
                                       "SUCCESS", {"path": pdf_path})
            elif latest and generate_pdf_after:
                _add_progress_step("pdf-generation", "Generating PDF report", "IN_PROGRESS")
                t0 = time.time()
                try:
                    pdf_path = generate_pdf_for_run(latest["id"])
                    if pdf_path and os.path.isfile(pdf_path):
                        pdf_generated = True
                        _add_progress_step("pdf-generation",
                                           f"PDF report generated ({os.path.getsize(pdf_path) // 1024} KB)",
                                           "SUCCESS", {"path": pdf_path},
                                           duration_ms=int((time.time() - t0) * 1000))
                    else:
                        _add_progress_step("pdf-generation", "PDF generation returned no file", "WARNING")
                except Exception as e:
                    _add_progress_step("pdf-generation", f"PDF generation failed: {str(e)[:200]}", "ERROR")

            async with _lock:
                # Honest verdict: the subprocess rc is the source of truth.
                # If rc==0 AND we found a run directory, it's a success even
                # if the legacy list_runs() can't see it.
                if proc.returncode == 0 and latest:
                    _active_run = {"status": "completed", "run_id": latest["id"],
                                   "results": latest["results"], "mode": mode,
                                   "duration": time.time() - _active_run.get("started", time.time()),
                                   "pdf_generated": pdf_generated}
                    _add_progress_step("pipeline", "Pipeline completed successfully", "SUCCESS",
                                       {"run_id": latest["id"], "pdf_generated": pdf_generated},
                                       duration_ms=int(_active_run["duration"] * 1000))
                elif proc.returncode == 0:
                    # rc=0 but no output dir found - genuinely unusual; surface it.
                    err_msg = (stderr_text or "Pipeline produced no output").strip()[-500:]
                    _active_run = {"status": "failed", "error": f"Pipeline failed: {err_msg}", "results": None}
                    _add_progress_step("pipeline", "Pipeline finished cleanly but no run directory was written",
                                       "ERROR", {"error": err_msg[:200]})
                else:
                    # rc!=0 - the earlier 'Pipeline failed (exit N)' step
                    # already carries the operator-actionable message.
                    err_msg = (stderr_text or "Subprocess returned non-zero").strip()[-500:]
                    _active_run = {"status": "failed", "error": f"Pipeline failed: {err_msg}", "results": None}
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            async with _lock:
                _active_run = {"status": "failed", "error": "Pipeline timed out after 600s", "results": None}
            _add_progress_step("pipeline", "Pipeline timed out after 600s", "ERROR")
        except Exception as e:
            err_detail = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}: {repr(e)}"
            print(f"  [API] Pipeline exception: {err_detail}")
            async with _lock:
                _active_run = {"status": "failed", "error": err_detail, "results": None}
            _add_progress_step("pipeline", f"Pipeline error: {err_detail[:200]}", "ERROR")

    asyncio.create_task(_run())
    return {"status": "started", "mode": mode, "run_id": pipeline_run_id}


import re as _re

# Map a runner stage id (stage1, stage9a, gate1, ...) to its PHASE id (ASSESS,
# CODE, ...) so the UI can roll up 28 stages into 8 high-level buckets without
# the api_server having to know the full STAGES table.
_STAGE_PHASE_MAP = {
    "stage1": "ASSESS", "stage2": "ASSESS", "stage3": "ASSESS",
    "stage4": "PROVISION", "gate1": "PROVISION", "stage5": "PROVISION",
    "stage6": "CODE", "stage7": "CODE", "stage8": "CODE",
    "stage9a": "CODE", "stage9b": "CODE", "stage9c": "CODE",
    "stage10": "CONFIG", "stage11": "CONFIG", "stage12": "CONFIG",
    "stage12a": "CONFIG", "stage12b": "CONFIG", "stage12c": "CONFIG",
    "stage13": "DATA_PREP", "stage14": "DATA_PREP", "stage15": "DATA_PREP",
    "stage16": "DATA_LOAD", "stage17": "DATA_LOAD", "stage18": "DATA_LOAD",
    "stage19": "VALIDATE", "stage20": "VALIDATE", "stage21": "VALIDATE",
    "gate2": "VALIDATE",
    "stage22": "CUTOVER", "stage23": "CUTOVER", "stage24": "CUTOVER",
    "stage25": "CUTOVER", "stage26": "CUTOVER", "gate3": "CUTOVER",
    "stage27": "RUN",
}

# Mutable state owned by _parse_pipeline_output - tracks the current PHASE
# and the most recent stage row so `status=success` can update the right one.
_parse_state = {"phase": None, "last_stage_step": None}


def _parse_pipeline_output(line):
    """Parse a line of pipeline stdout and emit progress steps.

    Two flavors of step are emitted:
    - "real stage" rows (details.is_stage == True) - one per [stageN] header,
      keyed by PHASE id so the Project tracker can roll up 28 stages into 8
      buckets. These are what the Project counter ("3/28 stages") reads.
    - "log echo" rows (the rest) for the Live Ops feed - chatty but useful
      for showing the user the pipeline is alive. Project ignores these.
    """
    stripped = line.strip()
    low = stripped.lower()

    # === PHASE X === banner from the runner
    m_phase = _re.match(r"^=+\s*phase\s+([a-z_]+)\s*=+$", low)
    if m_phase:
        _parse_state["phase"] = m_phase.group(1).upper()
        _add_progress_step("phase-banner",
                           f"Entering phase {_parse_state['phase']}", "IN_PROGRESS",
                           details={"phase": _parse_state["phase"]})
        return

    # [stageN] handler.module - a real stage starting
    m_stage = _re.match(r"^\[([a-z0-9]+)\]\s+(.+?)$", stripped, _re.IGNORECASE)
    if m_stage:
        sid = m_stage.group(1).lower()
        handler = m_stage.group(2).strip()
        phase_id = _STAGE_PHASE_MAP.get(sid) or _parse_state.get("phase") or "UNKNOWN"
        step = _add_progress_step(
            phase_id, f"{sid}: {handler}", "IN_PROGRESS",
            details={"is_stage": True, "stage_id": sid, "phase": phase_id,
                      "handler": handler}
        )
        _parse_state["last_stage_step"] = step
        return

    # "  status=success" / "  status=blocked" follow a [stageN] line; update
    # the most recently emitted stage row in place so the tracker flips to
    # SUCCESS/ERROR instead of staying IN_PROGRESS. Be liberal about what
    # counts as success - handlers return many synonyms ("ok",
    # "completed", "success", "done", "no_op") and we don't want a parser
    # miss to keep a finished stage stuck on IN_PROGRESS.
    m_status = _re.match(r"^status=([a-z0-9_-]+)$", low)
    if m_status:
        outcome = m_status.group(1)
        FAILURE = {"blocked", "error", "failed", "fatal", "aborted"}
        WARNING = {"skipped", "noop", "no_op", "partial"}
        if outcome in FAILURE:
            target = "ERROR"
        elif outcome in WARNING:
            target = "WARNING"
        else:
            # Anything not explicitly failure/warning is treated as success.
            # Handlers return success under many names; matching the full
            # set is brittle, and the alternative (stages stuck on
            # IN_PROGRESS after a clean run) is much worse for the operator.
            target = "SUCCESS"
        last = _parse_state.get("last_stage_step")
        if last:
            last["status"] = target
            last["details"] = {**(last.get("details") or {}), "outcome": outcome}
        else:
            _add_progress_step("stage-outcome", f"status={outcome}", target)
        return

    # "Run <id> finished rc=N" - the final marker.
    m_finish = _re.match(r"^run\s+\S+\s+finished\s+rc=(\d+)$", low)
    if m_finish:
        rc = int(m_finish.group(1))
        # Reconcile straggler stages whose status line we missed. On a
        # clean exit (rc=0) every is_stage row stuck on IN_PROGRESS is a
        # parse miss - mark them SUCCESS so the Project tracker matches
        # the subprocess's own verdict. On failure, only the in-flight
        # stage inherits ERROR; earlier in-flight rows are ambiguous so
        # leave them alone.
        for s in _progress_steps:
            if not (s.get("details") or {}).get("is_stage"):
                continue
            if s.get("status") != "IN_PROGRESS":
                continue
            if rc == 0:
                s["status"] = "SUCCESS"
                s["details"] = {**(s.get("details") or {}), "outcome": "rc=0 reconciled"}
            elif s is _parse_state.get("last_stage_step"):
                s["status"] = "ERROR"
                s["details"] = {**(s.get("details") or {}), "outcome": f"rc={rc}"}
        _add_progress_step("runner",
                            f"Run finished rc={rc}",
                            "SUCCESS" if rc == 0 else "ERROR")
        return

    # Everything else: low-volume log echo for Live Ops (Project ignores it).
    if any(kw in low for kw in ["warning:", "caution"]):
        _add_progress_step("runner", stripped, "WARNING")
    elif any(kw in low for kw in ["error:", "exception in", "traceback"]):
        _add_progress_step("runner", stripped, "ERROR")
    elif stripped.startswith(">"):
        _add_progress_step("runner", stripped.lstrip("> "), "IN_PROGRESS")
    elif any(stripped.startswith(m) for m in ["V ", "o ", "! ", "X "]):
        marker = stripped[0]
        status = {"V": "SUCCESS", "o": "IN_PROGRESS",
                   "!": "WARNING", "X": "ERROR"}.get(marker, "IN_PROGRESS")
        _add_progress_step("runner", stripped[2:].strip(), status)
    else:
        # Plain prints - useful as crumbs in Live Ops, not Project.
        _add_progress_step("runner", stripped, "INFO")


def generate_pdf_for_run(run_id):
    run_dir = os.path.join(OUTPUT_DIR, run_id)
    pdf_path = os.path.join(run_dir, "post-migration-report.pdf")
    if os.path.isfile(pdf_path):
        return pdf_path
    # Check reports/ subdirectory for multi-volume PDFs
    reports_dir = os.path.join(run_dir, "reports")
    if os.path.isdir(reports_dir):
        pdf_files = sorted(f for f in os.listdir(reports_dir) if f.endswith(".pdf"))
        if pdf_files:
            return os.path.join(reports_dir, pdf_files[0])
    json_path = os.path.join(run_dir, "post-migration-report.json")
    if not os.path.isfile(json_path):
        final_path = os.path.join(run_dir, "final-report.json")
        if not os.path.isfile(final_path):
            return None
        with open(final_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        report_data = data.get("post_migration_report")
        if not report_data:
            return None
    else:
        with open(json_path, "r", encoding="utf-8") as f:
            report_data = json.load(f)
    from pdf_report_generator import generate_pdf
    generate_pdf(report_data, pdf_path)
    return pdf_path


# =============================================================================
# PYDANTIC MODELS
# =============================================================================
class ECCConnection(BaseModel):
    ashost: str = ""
    sysnr: str = "00"
    client: str = "100"
    user: str = ""
    passwd: str = ""
    saprouter: str = ""
    # SAP codepage hint for the RFC handshake. 1100 = SAP_LATIN1 (non-Unicode,
    # the default for IDES EHP < 8 and classic ECC 6.0). 4103 = UTF-16LE
    # (Unicode-enabled ECC). Leave blank to let the SDK pick.
    codepage: str = ""

class S4HANAConnection(BaseModel):
    connection_type: str = "rfc"
    ashost: str = ""
    sysnr: str = "00"
    client: str = "100"
    user: str = ""
    passwd: str = ""
    api_url: str = ""
    saprouter: str = ""


class TargetLiftAndShiftConnection(BaseModel):
    # Greenfield S/4HANA target — RFC for reads/monitoring (never writes)
    target_ashost: str = ""
    target_sysnr: str = "00"
    target_client: str = "100"
    target_user: str = ""
    target_saprouter: str = ""
    # Migration Cockpit
    mc_base_url: str = ""           # e.g. https://s4.example.com/sap/opu/odata/sap/...
    mc_user: str = ""
    # LTMOM
    ltmom_user: str = ""
    # IDoc inbound
    idoc_endpoint: str = ""         # e.g. https://s4.example.com/sap/bc/idoc_xml
    idoc_partner: str = ""
    idoc_partner_type: str = "LS"
    # CTS+ / Transport host (SSM-managed)
    transport_host_instance_id: str = ""  # EC2 instance ID with /usr/sap/trans
    cts_token_name: str = ""        # name of secret in Secrets Manager (no value here)



# =============================================================================
# APP STARTUP
# =============================================================================
@asynccontextmanager
async def lifespan(application: FastAPI):
    _ensure_jwt_secret()
    print(f"\n  Migrate4HANA API Server (FastAPI)")
    print(f"  {'='*35}")
    print(f"  Auth: JWT Bearer token or X-API-Key header required")
    print(f"  Pipeline: 17-stage, 5-phase SAP Activate\n")
    yield


app = FastAPI(
    title="Migrate4HANA API",
    version="3.0",
    description="SAP ECC to S/4HANA Migration Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("M4H_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTES - CLIENTS (multi-tenant)
# =============================================================================
# A "client" is one customer's migration context — their ECC + S/4 credentials,
# their runs, their outputs. Most existing endpoints honor the X-Client-Id
# header; if absent, they fall back to the "default" client (single-tenant
# behavior, unchanged from before tenancy was added). Defined here (after the
# `app = FastAPI(...)` block) because @app.get must run after app exists.
@app.get("/api/clients", dependencies=[Depends(require_auth)])
async def list_clients():
    d = _load_clients()
    clients = list(d.get("clients", {}).values())
    for c in clients:
        cid = c.get("id", "")
        c["has_ecc_session"] = bool(_clients_passwds.get(cid, {}).get("ecc")) or (cid == "default" and bool(_ecc_passwd))
    return {"clients": clients, "default_client_id": d.get("default_client_id", "default")}


@app.post("/api/clients", dependencies=[Depends(require_auth)])
async def create_client(body: ClientCreate):
    if not body.id or not body.id.strip():
        raise HTTPException(400, detail="Client id is required")
    import re as _ree
    if not _ree.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", body.id):
        raise HTTPException(400, detail="Client id must be lowercase a-z, 0-9, _ or -, 2-64 chars")
    d = _load_clients()
    if body.id in d["clients"]:
        raise HTTPException(409, detail=f"Client '{body.id}' already exists")
    d["clients"][body.id] = {
        "id":   body.id,
        "name": (body.name or body.id).strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_clients(d)
    return d["clients"][body.id]


@app.delete("/api/clients/{client_id}", dependencies=[Depends(require_auth)])
async def delete_client(client_id: str):
    if client_id == "default":
        raise HTTPException(400, detail="Cannot delete the default client")
    d = _load_clients()
    if client_id not in d["clients"]:
        raise HTTPException(404, detail=f"Client '{client_id}' not found")
    d["clients"].pop(client_id, None)
    _save_clients(d)
    _clients_passwds.pop(client_id, None)
    return {"deleted": client_id}


# =============================================================================
# ROUTES - PUBLIC
# =============================================================================
@app.get("/api/health")
async def health():
    return {
        "status": "ok", "version": "3.0", "stages": 17, "phases": 5,
        "pipeline": "SAP Activate 5-Phase",
        "phase_map": {
            "1_prepare": "Stages 1-4: Assessment & Pre-Checks",
            "2_explore": "Stages 5-8: Application Preparation",
            "3_realize": "Stages 9-10: Technical System Conversion (SUM/DMO)",
            "4_post_conversion": "Stages 11-14: Deploy, Configure & Validate",
            "5_deploy_and_run": "Stages 15-17: Integration, Validation & Go-Live",
        },
    }


@app.post("/api/auth/token")
async def create_token():
    """Legacy token endpoint - kept for backwards compatibility with the
    pre-2026-06-15 UI. The new UI uses /api/auth/login (root) and
    /api/auth/iam-login (IAM). Legacy tokens are role-less and fail the
    new can() check on any operation guarded by require_can()."""
    token = generate_jwt()
    return {"token": token, "expires_in": 86400, "type": "Bearer"}


# ─────────────────────────────────────────────────────────────────────────────
# User store (lazy import so api_server.py boots without the new deps in
# environments that haven't pulled them yet)
# ─────────────────────────────────────────────────────────────────────────────
_user_store = None


def _get_user_store():
    global _user_store
    if _user_store is None:
        # The lambda/utils path is added at module init by the api server
        # bootstrap; if we're running standalone, add it now.
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        from auth_users import UserStore, ensure_root_user
        _user_store = UserStore()
        # First-run bootstrap if M4H_ROOT_EMAIL + M4H_ROOT_PASSWORD are set.
        try:
            ensure_root_user(_user_store)
        except Exception as e:
            import logging as _logging
            _logging.getLogger("api_server").warning(
                "root bootstrap skipped: %s", e)
    return _user_store


class LoginRequest(BaseModel):
    email:    str
    password: str
    # IAM logins must specify the client they're logging into; root logins
    # ignore this field. AWS-style root = no client; AWS-style IAM = one client.
    client_id: Optional[str] = None


@app.post("/api/auth/login")
async def auth_login_root(body: LoginRequest):
    """AWS-style ROOT login.

    The root user is account-level superuser; cannot be scoped to a single
    client. UI uses the 'Root user' tab.
    """
    from auth_users import verify_password, ROLE_ROOT
    store = _get_user_store()
    user = store.get_user(body.email)
    if not user or user.role != ROLE_ROOT or user.disabled:
        # Use the same error shape for unknown user + wrong-role + disabled so
        # an attacker can't enumerate which roles exist.
        raise HTTPException(status_code=401,
                            detail={"error": "invalid root credentials"})
    if not verify_password(body.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401,
                            detail={"error": "invalid root credentials"})
    user.last_login_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        store.put_user(user)
    except Exception:
        pass
    token = generate_user_jwt(email=user.email, role=user.role,
                              client_scopes=[],
                              allowed_operations=["*"],
                              expiry_hours=12)
    return {"token": token, "type": "Bearer", "expires_in": 12 * 3600,
            "user": user.public_dict()}


@app.post("/api/auth/iam-login")
async def auth_login_iam(body: LoginRequest):
    """AWS-style IAM login.

    The user must specify the client_id they're logging into. The login
    succeeds only if the IAM user is scoped to that client and not disabled.
    """
    from auth_users import verify_password, ROLE_IAM
    if not body.client_id:
        raise HTTPException(status_code=400,
                            detail={"error": "client_id is required for IAM login"})
    store = _get_user_store()
    user = store.get_user(body.email)
    if not user or user.role != ROLE_IAM or user.disabled:
        raise HTTPException(status_code=401,
                            detail={"error": "invalid IAM credentials"})
    if not verify_password(body.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401,
                            detail={"error": "invalid IAM credentials"})
    cid = body.client_id.strip().lower()
    if cid not in [s.lower() for s in user.client_scopes]:
        raise HTTPException(status_code=403,
                            detail={"error": "user is not scoped to this client",
                                    "client_id": cid})
    user.last_login_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        store.put_user(user)
    except Exception:
        pass
    token = generate_user_jwt(email=user.email, role=user.role,
                              client_scopes=[cid],   # narrow to login client
                              allowed_operations=user.allowed_operations,
                              expiry_hours=12)
    return {"token": token, "type": "Bearer", "expires_in": 12 * 3600,
            "active_client_id": cid,
            "user": user.public_dict()}


@app.get("/api/auth/me", dependencies=[Depends(require_auth)])
async def auth_me(request: Request):
    """Return the current principal's identity claim as carried by the JWT."""
    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else \
            (request.query_params.get("token") or "")
    payload = verify_jwt(token) if token else None
    if not payload:
        # Legacy token-only flow (no role claim) is treated as anonymous-iam.
        return {"email": "anonymous", "role": "legacy", "scopes": [], "ops": []}
    return {
        "email":  payload.get("email") or payload.get("sub"),
        "role":   payload.get("role", "legacy"),
        "scopes": payload.get("scopes") or [],
        "ops":    payload.get("ops") or [],
    }


@app.post("/api/auth/logout")
async def auth_logout():
    """Stateless JWT logout: nothing to revoke server-side; the UI drops
    the token. We surface a 200 so the UI can confirm the call."""
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Role-aware auth dependencies for new endpoints
# ─────────────────────────────────────────────────────────────────────────────
def _principal_from_request(request: Request) -> dict:
    """Extract role/scopes/ops from the JWT carried by the request. Used by
    role-aware dependencies. Returns {} when the request has no JWT (the
    legacy /api/auth/token flow) so legacy callers still get 401 from
    require_can on protected operations."""
    auth = request.headers.get("authorization", "") or \
           request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else \
            (request.query_params.get("token") or "")
    if not token:
        return {}
    payload = verify_jwt(token) or {}
    return {
        "email":  payload.get("email") or payload.get("sub"),
        "role":   payload.get("role"),
        "scopes": payload.get("scopes") or [],
        "ops":    payload.get("ops") or [],
    }


def require_role(*allowed_roles: str):
    """FastAPI dependency: 403 unless the principal's role is in the
    allowed list. Root passes everything; this is the right gate for
    superuser-only endpoints like /api/admin/*."""
    async def _check(request: Request, _auth=Depends(require_auth)):
        p = _principal_from_request(request)
        if p.get("role") == "root":
            return p
        if p.get("role") in allowed_roles:
            return p
        raise HTTPException(status_code=403,
                            detail={"error": "role not permitted",
                                    "required_roles": list(allowed_roles)})
    return _check


def require_can(operation: str):
    """FastAPI dependency: 403 unless the principal can perform this
    operation. Root passes everything. IAM users need the operation in
    their token's `ops` claim AND, when client_id is given as a path/query
    param, the client must be in their `scopes` claim."""
    async def _check(request: Request, _auth=Depends(require_auth)):
        p = _principal_from_request(request)
        if p.get("role") == "root":
            return p
        ops = p.get("ops") or []
        if "*" not in ops and operation not in ops:
            raise HTTPException(status_code=403,
                                detail={"error": "operation not permitted",
                                        "required_operation": operation})
        # If the route is scoped to a client_id, the IAM user must be in scope.
        cid = (request.query_params.get("client_id") or
               request.path_params.get("client_id") or "")
        if cid:
            cid = cid.strip().lower()
            scopes = [s.lower() for s in (p.get("scopes") or [])]
            if cid not in scopes:
                raise HTTPException(status_code=403,
                                    detail={"error": "client not in scope",
                                            "client_id": cid})
        return p
    return _check


# ─────────────────────────────────────────────────────────────────────────────
# Root-only user management endpoints
# ─────────────────────────────────────────────────────────────────────────────
class IAMUserCreate(BaseModel):
    email:              str
    password:           str
    client_scopes:      List[str]
    allowed_operations: Optional[List[str]] = None


class IAMUserUpdate(BaseModel):
    client_scopes:      Optional[List[str]] = None
    allowed_operations: Optional[List[str]] = None
    disabled:           Optional[bool]      = None
    new_password:       Optional[str]       = None


@app.get("/api/users", dependencies=[Depends(require_role("root"))])
async def list_users():
    store = _get_user_store()
    return {"users": [u.public_dict() for u in store.list_users()]}


@app.post("/api/users", dependencies=[Depends(require_role("root"))])
async def create_iam_user(body: IAMUserCreate, request: Request):
    from auth_users import (User, hash_password, ROLE_IAM,
                              DEFAULT_IAM_OPERATIONS, OPERATIONS)
    store = _get_user_store()
    if store.get_user(body.email):
        raise HTTPException(status_code=409, detail={"error": "user already exists"})
    if not body.client_scopes:
        raise HTTPException(status_code=400,
                            detail={"error": "client_scopes must be non-empty for IAM user"})
    ops = body.allowed_operations or list(DEFAULT_IAM_OPERATIONS)
    invalid = [o for o in ops if o not in OPERATIONS]
    if invalid:
        raise HTTPException(status_code=400,
                            detail={"error": "unknown operation slug(s)",
                                    "invalid": invalid,
                                    "valid": sorted(OPERATIONS)})
    h, s = hash_password(body.password)
    principal = _principal_from_request(request)
    user = User(
        email=body.email, role=ROLE_IAM,
        password_hash=h, password_salt=s,
        client_scopes=[c.strip().lower() for c in body.client_scopes],
        allowed_operations=ops,
        created_by=principal.get("email", "root"),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    store.put_user(user)
    return {"ok": True, "user": user.public_dict()}


@app.patch("/api/users/{email}", dependencies=[Depends(require_role("root"))])
async def update_iam_user(email: str, body: IAMUserUpdate):
    from auth_users import hash_password, OPERATIONS
    store = _get_user_store()
    user = store.get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail={"error": "user not found"})
    if body.client_scopes is not None:
        user.client_scopes = [c.strip().lower() for c in body.client_scopes]
    if body.allowed_operations is not None:
        invalid = [o for o in body.allowed_operations if o not in OPERATIONS]
        if invalid:
            raise HTTPException(status_code=400,
                                detail={"error": "unknown operation slug(s)",
                                        "invalid": invalid})
        user.allowed_operations = body.allowed_operations
    if body.disabled is not None:
        user.disabled = bool(body.disabled)
    if body.new_password:
        user.password_hash, user.password_salt = hash_password(body.new_password)
    store.put_user(user)
    return {"ok": True, "user": user.public_dict()}


@app.delete("/api/users/{email}", dependencies=[Depends(require_role("root"))])
async def delete_iam_user(email: str):
    store = _get_user_store()
    user = store.get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail={"error": "user not found"})
    if user.role == "root":
        raise HTTPException(status_code=400,
                            detail={"error": "cannot delete root via the API"})
    ok = store.delete_user(email)
    return {"ok": ok}


@app.get("/api/operations", dependencies=[Depends(require_auth)])
async def list_operations():
    from auth_users import OPERATIONS, DEFAULT_IAM_OPERATIONS
    return {"operations": OPERATIONS,
            "default_iam": DEFAULT_IAM_OPERATIONS}


# =============================================================================
# WIZARD STATE (per-user, per-run, DDB-backed)
# =============================================================================
_wizard_store = None


def _get_wizard_store():
    global _wizard_store
    if _wizard_store is None:
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        from wizard_state import WizardStore
        _wizard_store = WizardStore()
    return _wizard_store


class WizardCreate(BaseModel):
    client_id: Optional[str] = None
    page:      Optional[str] = "wizard-1-versions"
    body:      Optional[dict] = None


class WizardPatch(BaseModel):
    page:                      Optional[str] = None
    ecc_version:               Optional[str] = None
    s4_version:                Optional[str] = None
    migration_type:            Optional[str] = None
    selective_objects:         Optional[List[str]] = None
    ecc_conn:                  Optional[dict] = None
    s4_conn:                   Optional[dict] = None
    connection_test_results:   Optional[dict] = None
    permission_check_results:  Optional[dict] = None
    started_at:                Optional[str] = None


@app.post("/api/wizard", dependencies=[Depends(require_auth)])
async def wizard_create(body: WizardCreate, request: Request):
    """Create a new wizard run for the current user. Returns the run_id
    the UI uses for subsequent /api/wizard/{run_id} calls."""
    from wizard_state import new_run_id
    p = _principal_from_request(request)
    email = p.get("email")
    if not email:
        raise HTTPException(status_code=401,
                            detail={"error": "user identity unavailable"})
    run_id = new_run_id()
    state = {
        "run_id":     run_id,
        "user_email": email,
        "client_id":  body.client_id or (p.get("scopes") or [""])[0],
        "page":       body.page or "wizard-1-versions",
        **(body.body or {}),
    }
    saved = _get_wizard_store().put(state)
    return {"ok": True, "run_id": run_id, "state": saved}


@app.get("/api/wizard", dependencies=[Depends(require_auth)])
async def wizard_list(request: Request):
    """In-flight wizards for the current user, newest first."""
    p = _principal_from_request(request)
    email = p.get("email")
    if not email:
        return {"wizards": []}
    return {"wizards": _get_wizard_store().list_for_user(email)}


@app.get("/api/wizard/{run_id}", dependencies=[Depends(require_auth)])
async def wizard_get(run_id: str, request: Request):
    p = _principal_from_request(request)
    email = p.get("email")
    state = _get_wizard_store().get(email, run_id)
    if not state:
        raise HTTPException(status_code=404, detail={"error": "wizard not found"})
    return state


@app.patch("/api/wizard/{run_id}", dependencies=[Depends(require_auth)])
async def wizard_patch(run_id: str, body: WizardPatch, request: Request):
    p = _principal_from_request(request)
    email = p.get("email")
    if not email:
        raise HTTPException(status_code=401, detail={"error": "user identity unavailable"})
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"ok": True, "state": _get_wizard_store().patch(email, run_id, **fields)}


@app.delete("/api/wizard/{run_id}", dependencies=[Depends(require_auth)])
async def wizard_delete(run_id: str, request: Request):
    p = _principal_from_request(request)
    email = p.get("email")
    ok = _get_wizard_store().delete(email, run_id)
    return {"ok": ok}


# =============================================================================
# CONNECTION + PERMISSION VALIDATION (perm-aware test for the wizard)
# =============================================================================
class ConnectionTestRequest(BaseModel):
    creds:             dict
    migration_type:    str = "full"            # "full" | "selective"
    selected_objects:  Optional[List[str]] = None


@app.post("/api/connections/ecc/test-with-permissions",
           dependencies=[Depends(require_auth)])
async def connection_test_ecc_permaware(body: ConnectionTestRequest):
    global _ecc_passwd
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from connection_validator import validate_ecc
    res = validate_ecc(body.creds, migration_type=body.migration_type,
                       selected_objects=body.selected_objects)
    # If the probe successfully opened an RFC channel, the password is
    # known-good. Stash it so the pipeline doesn't need a second round-trip.
    if res.get("login_ok") and body.creds.get("passwd"):
        _ecc_passwd = body.creds["passwd"]
        # Also persist the connection metadata so the start-migration path
        # can find it without a separate save call.
        try:
            conns = _load_connections()
            conns["ecc"] = {
                "ashost":    body.creds.get("ashost", ""),
                "sysnr":     body.creds.get("sysnr", ""),
                "client":    body.creds.get("client", ""),
                "user":      body.creds.get("user", ""),
                "saprouter": body.creds.get("saprouter", ""),
                "saved_at":  datetime.now().isoformat(),
            }
            _save_connections(conns)
        except Exception:
            pass
    return res


@app.post("/api/connections/s4/test-with-permissions",
           dependencies=[Depends(require_auth)])
async def connection_test_s4_permaware(body: ConnectionTestRequest):
    global _s4_passwd
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from connection_validator import validate_s4
    res = validate_s4(body.creds, migration_type=body.migration_type,
                      selected_objects=body.selected_objects)
    if res.get("login_ok") and body.creds.get("passwd"):
        _s4_passwd = body.creds["passwd"]
        try:
            conns = _load_connections()
            conns["s4hana"] = {
                "connection_type": "rfc",
                "ashost":    body.creds.get("ashost", ""),
                "sysnr":     body.creds.get("sysnr", ""),
                "client":    body.creds.get("client", ""),
                "user":      body.creds.get("user", ""),
                "saprouter": body.creds.get("saprouter", ""),
                "saved_at":  datetime.now().isoformat(),
            }
            _save_connections(conns)
        except Exception:
            pass
    return res


# =============================================================================
# CONVERSION MAPPING (the simplified dashboard's data source)
# =============================================================================
@app.get("/api/mapping", dependencies=[Depends(require_auth)])
async def mapping_all():
    """Full curated source->target mapping catalog."""
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import list_all_mappings, list_by_category
    return {"mappings": list_all_mappings(),
            "by_category": list_by_category()}


@app.get("/api/mapping/{object_name}", dependencies=[Depends(require_auth)])
async def mapping_one(object_name: str):
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import get_mapping
    m = get_mapping(object_name)
    if not m:
        raise HTTPException(status_code=404,
                            detail={"error": "unknown object", "object": object_name})
    return m


@app.get("/api/mapping-by-ecc-table/{table}", dependencies=[Depends(require_auth)])
async def mapping_reverse(table: str):
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import find_by_ecc_table
    return {"table": table, "matches": find_by_ecc_table(table)}


@app.get("/api/runs/{run_id}/conversion-progress",
         dependencies=[Depends(require_auth)])
async def conversion_progress(run_id: str):
    """Live conversion dashboard data: each mapping entry merged with the
    per-object progress for this run.

    Two sources, merged with file-on-disk winning:
    1. local-staging/m4h-local/runs/<run_id>/data-migrator/summary.json
       - written by stage13 (extract) + stage15 (templates). Authoritative
         once those stages run; per-object row_count + status.
    2. Live spine.<Object>.progress events from _progress_steps - used while
       a stage is mid-flight before the summary file lands.
    """
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import summarise_run
    per_object = {}

    # ── Source 1: live spine events ────────────────────────────────────
    try:
        for step in _progress_steps:
            name = step.get("step") or f"{step.get('stage','')}.{step.get('action','')}"
            details = step.get("details") or {}
            if name.startswith("spine.") and ".progress" in name:
                parts = name.split(".")
                if len(parts) >= 2:
                    obj = parts[1]
                    per_object[obj] = {
                        "rows_loaded": int(details.get("rows_loaded", 0) or 0),
                        "rows_total":  int(details.get("rows_total", 0) or 0),
                        "rps":         float(details.get("rps", 0) or 0),
                        "status":      details.get("status", "running"),
                    }
    except Exception:
        pass

    # ── Source 2: data-migrator summary on disk ────────────────────────
    summary_path = os.path.join(
        PROJECT_DIR, "local-staging", "m4h-local",
        "runs", run_id, "data-migrator", "summary.json"
    )
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            for r in (summary.get("results") or []):
                if not isinstance(r, dict):
                    continue
                obj = r.get("object")
                if not obj:
                    continue
                rows = int(r.get("row_count") or 0)
                outcome = (r.get("status") or "").lower()
                # data-migrator's stage13/15 are extract-and-stage-CSV
                # operations; "ok" means rows landed in the staging CSV
                # ready for the MC import. We expose this as rows_loaded
                # against rows_total for parity with the dashboard's
                # progress-bar model.
                status_map = {"ok": "complete", "partial": "running",
                                "error": "failed", "skipped": "pending"}
                per_object[obj] = {
                    "rows_loaded": rows if outcome in ("ok", "partial") else 0,
                    "rows_total":  rows,
                    "rps":         per_object.get(obj, {}).get("rps", 0),
                    "status":      status_map.get(outcome, "pending"),
                }
        except Exception as exc:
            log.warning("conversion-progress: failed to read %s: %s",
                        summary_path, exc)

    return {"run_id": run_id, "rows": summarise_run(per_object)}


# =============================================================================
# SUPERUSER COMMAND BOARD (root-only)
# =============================================================================
@app.get("/api/admin/commands",
         dependencies=[Depends(require_role("root"))])
async def admin_list_commands(category: Optional[str] = None):
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from superuser_commands import list_commands, categories
    return {"commands": list_commands(category=category),
            "categories": categories()}


@app.get("/api/admin/commands/{command_id}",
         dependencies=[Depends(require_role("root"))])
async def admin_get_command(command_id: str):
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from superuser_commands import get_command
    cmd = get_command(command_id)
    if not cmd:
        raise HTTPException(status_code=404,
                            detail={"error": "unknown command_id"})
    return cmd


class CommandExecuteRequest(BaseModel):
    params: Optional[dict] = None


@app.post("/api/admin/commands/{command_id}/execute",
          dependencies=[Depends(require_role("root"))])
async def admin_execute_command(command_id: str, body: CommandExecuteRequest):
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from superuser_commands import get_command, validate_params
    cmd = get_command(command_id)
    if not cmd:
        raise HTTPException(status_code=404,
                            detail={"error": "unknown command_id"})
    supplied = body.params or {}
    val = validate_params(command_id, supplied)
    if not val.get("ok"):
        raise HTTPException(status_code=400, detail={"error": "invalid params",
                                                       **val})
    # Dispatch — wired conservatively. Each branch is a SAFE-EXECUTE
    # path that the existing infra already supports; we never invent a
    # new shell call from user input.
    runs = cmd.get("runs")
    target = cmd.get("run_target", "")
    if runs == "lambda":
        import boto3
        try:
            payload = dict(cmd.get("payload") or {})
            payload.update(supplied)
            resp = boto3.client("lambda").invoke(
                FunctionName=target,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode("utf-8"))
            body_bytes = resp["Payload"].read() if resp.get("Payload") else b""
            try:
                result = json.loads(body_bytes.decode("utf-8") or "null")
            except Exception:
                result = {"raw": body_bytes.decode("utf-8", errors="replace")}
            return {"ok": True, "command_id": command_id,
                    "lambda": target, "result": result}
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail={"error": "lambda invoke failed",
                                        "message": str(e)[:200]})
    if runs == "api":
        # API target is a server-side route the caller can hit; we don't
        # try to internally re-dispatch (avoids re-entrancy + auth issues).
        return {"ok": True, "command_id": command_id,
                "next_call": target,
                "hint": "Issue a subsequent request to next_call from the UI."}
    if runs == "shell":
        # Shell scripts are NOT dispatched by the API server (the api-server
        # task does not have a shell to PowerShell into). Return the script
        # path + the supplied params so the operator runs it locally.
        return {"ok": True, "command_id": command_id, "runs": "shell",
                "script": target, "params": supplied,
                "hint": "Run this script locally with the supplied params."}
    raise HTTPException(status_code=500,
                        detail={"error": f"unknown runs type: {runs}"})


# =============================================================================
# ROUTES - CONNECTIONS (authenticated)
# =============================================================================
@app.get("/api/connections", dependencies=[Depends(require_auth)])
async def get_connections():
    return _load_connections()


@app.post("/api/connections/ecc", dependencies=[Depends(require_auth)])
async def save_ecc_connection(body: ECCConnection):
    """Persist ECC connection metadata AND keep the password in process
    memory for the runtime.

    The wizard calls this right after the perm-aware test passes, with the
    plaintext password. We never write the password to disk, but holding it
    in memory is the difference between "Start migration" working and
    failing with 'session expired'.
    """
    global _ecc_passwd
    conns = _load_connections()
    conns["ecc"] = {"ashost": body.ashost, "sysnr": body.sysnr, "client": body.client,
                    "user": body.user, "saprouter": body.saprouter,
                    "codepage": body.codepage, "saved_at": datetime.now().isoformat()}
    _save_connections(conns)
    if body.passwd:
        _ecc_passwd = body.passwd
    return {"status": "saved", "connection": conns["ecc"],
            "session_has_passwd": bool(_ecc_passwd)}


@app.post("/api/connections/s4hana", dependencies=[Depends(require_auth)])
async def save_s4hana_connection(body: S4HANAConnection):
    """Persist S/4 connection metadata AND keep the password in process
    memory. Same pattern as ECC save above."""
    global _s4_passwd
    conns = _load_connections()
    conns["s4hana"] = {"connection_type": body.connection_type, "ashost": body.ashost,
                       "sysnr": body.sysnr, "client": body.client, "user": body.user,
                       "api_url": body.api_url, "saprouter": body.saprouter,
                       "saved_at": datetime.now().isoformat()}
    _save_connections(conns)
    if body.passwd:
        _s4_passwd = body.passwd
    return {"status": "saved", "connection": conns["s4hana"],
            "session_has_passwd": bool(_s4_passwd)}


@app.post("/api/connections/ecc/test", dependencies=[Depends(require_auth)])
async def test_ecc(body: ECCConnection):
    return test_ecc_connection(body.model_dump())


@app.get("/api/connections/ecc/status", dependencies=[Depends(require_auth)])
async def ecc_connection_status():
    """Check if a live ECC connection is ready (saved + password in memory)."""
    conns = _load_connections()
    has_ecc = bool((conns.get("ecc") or {}).get("ashost"))
    has_passwd = bool(_ecc_passwd)
    return {"live_ready": has_ecc and has_passwd,
            "has_connection": has_ecc,
            "has_password": has_passwd}


@app.post("/api/connections/s4hana/test", dependencies=[Depends(require_auth)])
async def test_s4(body: S4HANAConnection):
    return test_s4hana_connection(body.model_dump())


@app.post("/api/connections/lift-and-shift-target", dependencies=[Depends(require_auth)])
async def save_lift_and_shift_target(body: TargetLiftAndShiftConnection):
    """Save greenfield S/4HANA target system credentials for the lift-and-shift pipeline.

    Stores everything except secrets. Passwords / CTS+ tokens go to AWS Secrets Manager
    referenced by name (cts_token_name); we never persist secret material in connections.json.
    """
    conns = _load_connections()
    payload = body.model_dump()
    payload["saved_at"] = datetime.now().isoformat()
    conns["lift_and_shift_target"] = payload
    _save_connections(conns)
    return {"status": "saved", "connection": payload}



# =============================================================================
# ROUTES - VERSION MATRIX (F6)
# =============================================================================
# Exposes the source-ECC + target-S/4 version catalogue to the UI, plus an
# RFC-driven auto-detect, plus the user's saved selection. The data-migrator
# and downstream Lambdas consume the saved selection at runtime to route the
# extract path, package size, template format, and BAPI version.

class VersionSelection(BaseModel):
    """User's chosen (source, target) pair + optional DB hint for HANA override."""
    source_code: str         # e.g. "ECC60_EHP8"
    target_code: str         # e.g. "S4HANA_2023"
    source_db:   Optional[str] = None    # "HANA" or "ANY_DB"; None = use catalogue default
    detected_at: Optional[str] = None    # ISO timestamp when last auto-detected (informational)


def _vm_or_503():
    """Surface a 503 if the version_matrix module isn't importable (deploy bug)."""
    if _vm is None:
        raise HTTPException(status_code=503,
                            detail=f"version_matrix unavailable: {_vm_import_err}")


def _detect_ecc_via_rfc() -> dict:
    """Call RFC_SYSTEM_INFO on the saved ECC connection. Returns {detected: EccVersion|None, error: str|None}."""
    try:
        from pyrfc import Connection   # type: ignore
    except Exception as e:
        return {"detected": None, "error": f"pyrfc unavailable: {e}"}
    conns = _load_connections()
    ecc = conns.get("ecc") or {}
    if not (ecc.get("ashost") and _ecc_passwd):
        return {"detected": None, "error": "no live ECC session (configure + test the connection first)"}
    try:
        c = Connection(ashost=ecc["ashost"], sysnr=ecc.get("sysnr", "00"),
                       client=ecc["client"], user=ecc["user"],
                       passwd=_ecc_passwd, lang="EN")
        info = c.call("RFC_SYSTEM_INFO")
        c.close()
    except Exception as e:
        return {"detected": None, "error": f"RFC call failed: {e}"}
    v = _vm.detect_source_ecc_version(info)
    if v is None:
        return {"detected": None, "error": "RFC_SYSTEM_INFO returned a release we can't map (paste it to support)"}
    from dataclasses import asdict
    return {"detected": asdict(v), "error": None, "raw": info.get("RFCSI_EXPORT")}


def _detect_s4_via_rfc() -> dict:
    """Read CVERS from the saved S/4 connection. Returns {detected: S4Release|None, error: str|None}."""
    try:
        from pyrfc import Connection   # type: ignore
    except Exception as e:
        return {"detected": None, "error": f"pyrfc unavailable: {e}"}
    conns = _load_connections()
    s4 = conns.get("s4hana") or conns.get("lift_and_shift_target") or {}
    if not s4.get("ashost"):
        return {"detected": None, "error": "no S/4 connection configured"}
    s4_passwd = globals().get("_s4_passwd", "")     # set by test-s4 handler if available
    if not s4_passwd:
        return {"detected": None,
                "error": "no live S/4 session; run the S/4 connection test once so the password is cached"}
    try:
        c = Connection(ashost=s4["ashost"], sysnr=s4.get("sysnr", "00"),
                       client=s4["client"], user=s4["user"], passwd=s4_passwd, lang="EN")
        # CVERS layout: COMPONENT (CHAR 30), RELEASE (CHAR 10) - reading both as text rows
        resp = c.call("RFC_READ_TABLE", QUERY_TABLE="CVERS",
                      FIELDS=[{"FIELDNAME": "COMPONENT"}, {"FIELDNAME": "RELEASE"}],
                      ROWCOUNT=100)
        c.close()
    except Exception as e:
        return {"detected": None, "error": f"CVERS read failed: {e}"}
    # Parse the column-positional rows
    fields = resp.get("FIELDS") or []
    rows = []
    for r in (resp.get("DATA") or []):
        wa = (r.get("WA") or "").rstrip()
        item = {}
        for f in fields:
            off = int(f.get("OFFSET", 0))
            ln  = int(f.get("LENGTH", 0))
            item[f["FIELDNAME"]] = wa[off:off + ln].strip()
        rows.append(item)
    r = _vm.detect_target_s4_release(rows)
    if r is None:
        return {"detected": None, "error": "CVERS has no S4CORE row or release unmapped"}
    from dataclasses import asdict
    return {"detected": asdict(r), "error": None, "rows": rows[:10]}


@app.get("/api/versions/supported", dependencies=[Depends(require_auth)])
async def versions_supported():
    """Static catalogue of all (source, target) pairs the tool supports."""
    _vm_or_503()
    return _vm.matrix_payload()


@app.get("/api/versions/detected", dependencies=[Depends(require_auth)])
async def versions_detected():
    """Live RFC detection of source ECC and target S/4 versions."""
    _vm_or_503()
    return {"source": _detect_ecc_via_rfc(), "target": _detect_s4_via_rfc()}


@app.get("/api/versions/selected", dependencies=[Depends(require_auth)])
async def versions_selected():
    """Return the currently saved (source, target) selection, or empty if not set."""
    _vm_or_503()
    conns = _load_connections()
    sel = conns.get("versions") or {}
    if not sel:
        return {"selected": None, "routing": None}
    try:
        plan = _vm.routing_for_pair(sel["source_code"], sel["target_code"],
                                     source_db=sel.get("source_db"))
        return {"selected": sel, "routing": plan.to_dict()}
    except _vm.VersionIncompatibilityError as e:
        return {"selected": sel, "routing": None, "error": str(e)}


@app.post("/api/versions/selected", dependencies=[Depends(require_auth)])
async def versions_save_selection(body: VersionSelection):
    """Validate the selection against the matrix; persist to connections.json on success."""
    _vm_or_503()
    try:
        plan = _vm.routing_for_pair(body.source_code, body.target_code,
                                     source_db=body.source_db)
    except _vm.VersionIncompatibilityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conns = _load_connections()
    conns["versions"] = {
        "source_code": body.source_code,
        "target_code": body.target_code,
        "source_db":   body.source_db,
        "detected_at": body.detected_at,
        "saved_at":    datetime.now().isoformat(),
    }
    _save_connections(conns)
    return {"status": "saved", "selected": conns["versions"], "routing": plan.to_dict()}


# =============================================================================
# ROUTES - PIPELINE
# =============================================================================
@app.post("/api/pipeline/assess", dependencies=[Depends(require_auth)])
async def pipeline_assess():
    return await start_pipeline_async(mode="assess")

@app.post("/api/pipeline/convert", dependencies=[Depends(require_auth)])
async def pipeline_convert():
    return await start_pipeline_async(mode="convert")

@app.post("/api/pipeline/complete", dependencies=[Depends(require_auth)])
async def pipeline_complete():
    return await start_pipeline_async(mode="complete")

@app.post("/api/pipeline/full", dependencies=[Depends(require_auth)])
async def pipeline_full():
    return await start_pipeline_async(mode="full")

@app.post("/api/pipeline/ecc_full", dependencies=[Depends(require_auth)])
async def pipeline_ecc_full():
    return await start_pipeline_async(mode="ecc_full")

@app.post("/api/pipeline/run_and_report", dependencies=[Depends(require_auth)])
async def pipeline_run_and_report():
    """Unified endpoint: run full ECC extraction + conversion + PDF generation."""
    return await start_pipeline_async(mode="ecc_full", generate_pdf_after=True)

@app.post("/api/pipeline/migrate", dependencies=[Depends(require_auth)])
async def pipeline_migrate():
    return await start_pipeline_async(mode="full")

@app.post("/api/start/assess", dependencies=[Depends(require_auth)])
async def start_assess():
    return await start_pipeline_async(mode="assess")

@app.post("/api/start/convert", dependencies=[Depends(require_auth)])
async def start_convert():
    return await start_pipeline_async(mode="convert")

@app.post("/api/start/complete", dependencies=[Depends(require_auth)])
async def start_complete():
    return await start_pipeline_async(mode="complete")

@app.post("/api/start/full", dependencies=[Depends(require_auth)])
async def start_full():
    return await start_pipeline_async(mode="full")

@app.post("/api/run", dependencies=[Depends(require_auth)])
async def legacy_run():
    return await start_pipeline_async(mode="full")


# =============================================================================
# ROUTES - LIFT-AND-SHIFT (greenfield S/4HANA target via SAP-shipped tools)
# =============================================================================
class _LiftAndShiftRequest(BaseModel):
    """Optional payload from the v2 wizard. We accept anything; only run_id is
    threaded through to the runner so logs/state files all share one id."""
    run_id: Optional[str] = None
    migration_type: Optional[str] = None
    selective_objects: Optional[List[str]] = None
    ecc_version: Optional[str] = None
    s4_version:  Optional[str] = None
    # load_to_s4 toggles the data-migrator from extract-only (writes CSV
    # templates for Migration Cockpit upload, no S/4 writes) to live load
    # (calls BAPIs against S/4 immediately). Default OFF for safety: the
    # extract-only mode is reversible; live load is not.
    load_to_s4: Optional[bool] = False
    # simulation_mode is the safety gate for live load: when True, spines
    # call the BAPIs' TEST_RUN mode where supported and staging tables
    # otherwise; nothing commits. Ignored (no effect) when load_to_s4 is
    # False since extract-only is already non-committing.
    simulation_mode: Optional[bool] = False
    # Per-object row cap (M4H_LOAD_MAX_ROWS). Wizard user sets this before
    # clicking "Start migration". None => use the data-migrator default
    # (see lambda/data-migrator/handler.py:83). Clamped to [1, 1_000_000].
    max_rows: Optional[int] = None
    # Preserve source document numbers (VBELN, EBELN, delivery/billing nums).
    # When True, transactional spines pass the source doc number into the
    # BAPI's external-number field so the S/4 record inherits the ECC number
    # instead of getting a fresh internal-range number. Prereq: the target
    # S/4 doc types must be marked external range (see PREREQ_RUNBOOK.md §C).
    preserve_source_numbers: Optional[bool] = False


def _ls_args(body):
    """Pluck the wizard payload fields start_pipeline_async cares about."""
    if not body:
        return {"run_id": None, "load_to_s4": False, "simulation_mode": False,
                "max_rows": None, "preserve_source_numbers": False}
    return {"run_id": body.run_id,
            "load_to_s4": bool(body.load_to_s4),
            "simulation_mode": bool(body.simulation_mode),
            "max_rows": body.max_rows,
            "preserve_source_numbers": bool(body.preserve_source_numbers)}


@app.post("/api/pipeline/lift-and-shift", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift(body: Optional[_LiftAndShiftRequest] = None):
    """Run the full 28-stage lift-and-shift pipeline (orchestration plane only).

    Every S/4 write goes through Migration Cockpit / LTMOM / IDoc inbound /
    CTS+/tp - we never call BAPIs against the target. See
    MIGRATE4HANA-LIFT-AND-SHIFT.md for the architecture charter."""
    return await start_pipeline_async(mode="full", pipeline_kind="lift_and_shift",
                                       **_ls_args(body))


@app.post("/api/pipeline/lift-and-shift/assess", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_assess(body: Optional[_LiftAndShiftRequest] = None):
    """Phase 0 only - discovery, sizing, object routing. No writes."""
    return await start_pipeline_async(mode="assess", pipeline_kind="lift_and_shift",
                                       **_ls_args(body))


@app.post("/api/pipeline/lift-and-shift/code", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_code(body: Optional[_LiftAndShiftRequest] = None):
    """Phases 0-2 only - up through code transport import + verify."""
    return await start_pipeline_async(mode="code", pipeline_kind="lift_and_shift",
                                       **_ls_args(body))


@app.post("/api/pipeline/lift-and-shift/data", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_data(body: Optional[_LiftAndShiftRequest] = None):
    """Phases 0-5 - up through data load via MC/LTMOM/IDoc lanes."""
    return await start_pipeline_async(mode="data", pipeline_kind="lift_and_shift",
                                       **_ls_args(body))


@app.get("/api/pipeline/lift-and-shift/stages", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_stages():
    """Return the 28-stage definition for UI display (mirrors run_local_lift_and_shift.STAGES)."""
    try:
        sys.path.insert(0, PROJECT_DIR)
        from run_local_lift_and_shift import STAGES as _stages  # type: ignore
        return {"stages": [{"id": sid, "phase": phase, "handler": mod, "extra": extra}
                            for sid, phase, mod, extra in _stages]}
    except Exception as e:
        return {"error": str(e), "stages": []}


# =============================================================================
# ROUTES - S/4 PREP-SCRIPT GENERATION (auto-generated ABAP for SE38 or auto-run)
# =============================================================================
# Turns "connect + click migrate" into a truly one-click flow. Before the
# wizard's Start button unlocks, the user (or the tool itself, if auto-run
# is enabled) needs the S/4 target to have the customizing rows the ECC data
# references. This route family does:
#   POST /api/pipeline/prep-script/generate  - scan ECC + emit ABAP report
#   GET  /api/runs/{run_id}/prep-script.abap      - download prep script
#   GET  /api/runs/{run_id}/prep-script-undo.abap - download rollback script
#   POST /api/pipeline/prep-script/auto-run  - optional: exec on S/4 via RFC
class _PrepScriptRequest(BaseModel):
    run_id:                  Optional[str] = None
    preserve_source_numbers: Optional[bool] = False


def _prep_dir(run_id: str) -> str:
    d = os.path.join(PROJECT_DIR, "local-staging", "m4h-local",
                     "runs", run_id, "prep-script")
    os.makedirs(d, exist_ok=True)
    return d


@app.post("/api/pipeline/prep-script/generate",
          dependencies=[Depends(require_auth)])
async def prep_script_generate(body: Optional[_PrepScriptRequest] = None):
    """Scan ECC customizing and emit a self-contained ABAP report the S/4
    admin runs in SE38 to create every customizing row the migration will
    reference. Saves to `runs/<run_id>/prep-script/` and returns the source
    text + summary for inline display in the wizard."""
    body = body or _PrepScriptRequest()
    run_id = body.run_id or f"prep-{int(time.time())}"
    preserve_nums = bool(body.preserve_source_numbers)

    conns = _load_connections()
    ecc_conf = conns.get("ecc") or {}
    s4_conf  = conns.get("s4hana") or {}
    if not (ecc_conf.get("ashost") and _ecc_passwd):
        return JSONResponse(status_code=400, content={
            "status": "error",
            "message": "No active ECC connection. Save + test an ECC "
                        "connection first."})

    try:
        import pyrfc
    except ImportError:
        return JSONResponse(status_code=500, content={
            "status": "error",
            "message": "pyrfc unavailable on the server — cannot scan ECC."})

    try:
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        from abap_generator import scan_ecc, generate_prep_abap
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "error", "message": f"generator import failed: {e}"})

    conn_params = {"ashost": ecc_conf["ashost"], "sysnr": ecc_conf["sysnr"],
                    "client": ecc_conf["client"], "user": ecc_conf["user"],
                    "passwd": _ecc_passwd}
    if ecc_conf.get("saprouter"):
        conn_params["saprouter"] = ecc_conf["saprouter"]

    try:
        conn = pyrfc.Connection(**conn_params)
        try:
            scan = scan_ecc(conn)
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=502, content={
            "status": "error", "message": f"ECC scan failed: {type(e).__name__}: {e}"})

    result = generate_prep_abap(
        scan, run_id=run_id,
        ecc_host=ecc_conf.get("ashost", ""),
        s4_host=s4_conf.get("ashost", ""),
        preserve_source_numbers=preserve_nums,
    )

    # Persist so download endpoints can stream the file
    d = _prep_dir(run_id)
    prep_path = os.path.join(d, "prep.abap")
    undo_path = os.path.join(d, "undo.abap")
    summary_path = os.path.join(d, "summary.json")
    with open(prep_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(result["abap"])
    with open(undo_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(result["undo_abap"])
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"summary": result["summary"],
                   "warnings": result["warnings"]}, f, indent=2)

    return {
        "status": "ok",
        "run_id": run_id,
        "abap":   result["abap"],
        "undo_abap": result["undo_abap"],
        "summary":   result["summary"],
        "warnings":  result["warnings"],
        "download_url":      f"/api/runs/{run_id}/prep-script.abap",
        "download_undo_url": f"/api/runs/{run_id}/prep-script-undo.abap",
    }


@app.get("/api/runs/{run_id}/prep-script.abap",
         dependencies=[Depends(require_auth)])
async def prep_script_download(run_id: str):
    """Download the generated ABAP prep report for SE38 upload."""
    p = os.path.join(_prep_dir(run_id), "prep.abap")
    if not os.path.isfile(p):
        raise HTTPException(status_code=404,
                            detail=f"prep script not generated yet for {run_id}")
    return FileResponse(p, media_type="text/plain",
                         filename=f"ZM4H_PREP_{run_id}.abap")


@app.get("/api/runs/{run_id}/prep-script-undo.abap",
         dependencies=[Depends(require_auth)])
async def prep_script_undo_download(run_id: str):
    """Download the companion undo (rollback) ABAP report."""
    p = os.path.join(_prep_dir(run_id), "undo.abap")
    if not os.path.isfile(p):
        raise HTTPException(status_code=404,
                            detail=f"undo script not generated yet for {run_id}")
    return FileResponse(p, media_type="text/plain",
                         filename=f"ZM4H_UNDO_{run_id}.abap")


class _PrepAutoRunRequest(BaseModel):
    run_id: str


@app.post("/api/pipeline/prep-script/auto-run",
          dependencies=[Depends(require_auth)])
async def prep_script_auto_run(body: _PrepAutoRunRequest):
    """Optional: hand the already-generated prep script to S/4 for immediate
    execution via RFC_ABAP_INSTALL_AND_RUN. Many production S/4 tenants
    disable this RFC — the response surfaces {status: 'disabled'} in that
    case so the wizard can prompt for manual SE38 upload instead."""
    prep_path = os.path.join(_prep_dir(body.run_id), "prep.abap")
    if not os.path.isfile(prep_path):
        raise HTTPException(status_code=404,
                            detail="Generate the prep script first, then auto-run.")
    with open(prep_path, "r", encoding="utf-8") as f:
        abap_source = f.read()

    conns = _load_connections()
    s4_conf = conns.get("s4hana") or {}
    if not (s4_conf.get("ashost") and _s4_passwd):
        return JSONResponse(status_code=400, content={
            "status": "error",
            "message": "No active S/4 connection. Save + test S/4 first."})

    try:
        import pyrfc
        from abap_generator import auto_run_on_s4  # already on sys.path from generate
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "error", "message": f"import failed: {e}"})

    conn_params = {"ashost": s4_conf["ashost"], "sysnr": s4_conf["sysnr"],
                    "client": s4_conf["client"], "user": s4_conf["user"],
                    "passwd": _s4_passwd}
    if s4_conf.get("saprouter"):
        conn_params["saprouter"] = s4_conf["saprouter"]

    try:
        conn = pyrfc.Connection(**conn_params)
        try:
            outcome = auto_run_on_s4(conn, abap_source)
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=502, content={
            "status": "error",
            "message": f"S/4 connection failed: {type(e).__name__}: {e}"})

    outcome["run_id"] = body.run_id
    return outcome


# =============================================================================
# ROUTES - MANUAL GATES (lambda:invoke.waitForTaskToken approval flow)
# =============================================================================
def _gates_clients():
    import boto3 as _b
    return _b.client("s3"), _b.client("stepfunctions"), _b.client("dynamodb")


def _gates_bucket():
    return os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")


def _gates_table():
    return os.environ.get("GATES_TABLE", "")


@app.get("/api/gates", dependencies=[Depends(require_auth)])
async def list_pending_gates():
    """List all pending manual gates. Reads DynamoDB if GATES_TABLE is set,
    else falls back to scanning s3://<bucket>/gates/<run_id>/<gate>.json."""
    s3, _, ddb = _gates_clients()
    table = _gates_table()
    items = []
    if table:
        try:
            resp = ddb.scan(
                TableName=table,
                FilterExpression="#s = :p",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":p": {"S": "pending"}},
            )
            for it in resp.get("Items", []):
                items.append({
                    "gate_id":    it["gate_id"]["S"],
                    "run_id":     it["run_id"]["S"],
                    "gate":       it["gate"]["S"],
                    "status":     it["status"]["S"],
                    "created_at": it.get("created_at", {}).get("S", ""),
                })
            return {"source": "dynamodb", "gates": items}
        except Exception as e:
            # fall through to S3
            pass
    # S3 fallback
    try:
        bucket = _gates_bucket()
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix="gates/"):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue
                body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                try:
                    rec = json.loads(body)
                    if rec.get("status") == "pending":
                        items.append({
                            "gate_id":    rec.get("gate_id", ""),
                            "run_id":     rec.get("run_id", ""),
                            "gate":       rec.get("gate", ""),
                            "status":     rec.get("status", ""),
                            "created_at": rec.get("created_at", ""),
                        })
                except Exception:
                    continue
        return {"source": "s3", "gates": items}
    except Exception as e:
        return {"source": "error", "gates": [], "error": str(e)}


def _resolve_gate(gate_id: str):
    """Find a gate record. Returns (record_dict, location, key_or_pk)."""
    s3, _, ddb = _gates_clients()
    table = _gates_table()
    if table:
        try:
            resp = ddb.get_item(TableName=table, Key={"gate_id": {"S": gate_id}})
            it = resp.get("Item")
            if it:
                rec = {
                    "gate_id": it["gate_id"]["S"],
                    "run_id":  it["run_id"]["S"],
                    "gate":    it["gate"]["S"],
                    "token":   it["token"]["S"],
                    "status":  it["status"]["S"],
                }
                return rec, "dynamodb", gate_id
        except Exception:
            pass
    # S3 fallback - gate_id format is "<run_id>__<gate>"
    if "__" not in gate_id:
        return None, None, None
    run_id, gate = gate_id.split("__", 1)
    bucket = _gates_bucket()
    key = "gates/{run}/{gate}.json".format(run=run_id, gate=gate)
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body), "s3", key
    except Exception:
        return None, None, None


def _mark_gate(location: str, key: str, status: str, decided_by: str = ""):
    s3, _, ddb = _gates_clients()
    if location == "dynamodb":
        ddb.update_item(
            TableName=_gates_table(),
            Key={"gate_id": {"S": key}},
            UpdateExpression="SET #s = :v, decided_by = :u, decided_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":v": {"S": status},
                ":u": {"S": decided_by or "anonymous"},
                ":t": {"S": _utc_iso()},
            },
        )
    elif location == "s3":
        body = s3.get_object(Bucket=_gates_bucket(), Key=key)["Body"].read()
        rec = json.loads(body)
        rec["status"] = status
        rec["decided_by"] = decided_by or "anonymous"
        rec["decided_at"] = _utc_iso()
        s3.put_object(Bucket=_gates_bucket(), Key=key,
                      Body=json.dumps(rec).encode("utf-8"),
                      ContentType="application/json")


def _utc_iso():
    from datetime import datetime as _dt, timezone as _tz
    return _dt.now(_tz.utc).isoformat()


@app.post("/api/gates/{gate_id}/approve", dependencies=[Depends(require_auth)])
async def approve_gate(gate_id: str, request: Request):
    """Approve a pending gate - sends SendTaskSuccess to Step Functions,
    unblocking the waiting state. Body may contain {"decided_by": "<user>",
    "output": <dict>}."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    rec, location, key = _resolve_gate(gate_id)
    if not rec:
        raise HTTPException(404, "gate not found: {}".format(gate_id))
    if rec.get("status") != "pending":
        raise HTTPException(409, "gate is not pending (status={})".format(rec.get("status")))
    _, sfn, _ = _gates_clients()
    out = body.get("output") or {"approved": True, "decided_by": body.get("decided_by", "")}
    try:
        sfn.send_task_success(taskToken=rec["token"], output=json.dumps(out))
    except Exception as e:
        raise HTTPException(500, "SendTaskSuccess failed: {}".format(e))
    _mark_gate(location, key, "approved", decided_by=body.get("decided_by", ""))
    return {"status": "approved", "gate_id": gate_id}


@app.post("/api/gates/{gate_id}/reject", dependencies=[Depends(require_auth)])
async def reject_gate(gate_id: str, request: Request):
    """Reject a pending gate - sends SendTaskFailure to Step Functions, which
    triggers the Catch -> RollbackManager branch."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    rec, location, key = _resolve_gate(gate_id)
    if not rec:
        raise HTTPException(404, "gate not found: {}".format(gate_id))
    if rec.get("status") != "pending":
        raise HTTPException(409, "gate is not pending (status={})".format(rec.get("status")))
    _, sfn, _ = _gates_clients()
    try:
        sfn.send_task_failure(
            taskToken=rec["token"],
            error="GateRejected",
            cause=body.get("reason", "human reviewer rejected the gate"),
        )
    except Exception as e:
        raise HTTPException(500, "SendTaskFailure failed: {}".format(e))
    _mark_gate(location, key, "rejected", decided_by=body.get("decided_by", ""))
    return {"status": "rejected", "gate_id": gate_id}


# =============================================================================
# ROUTES - RUNS & STATUS
# =============================================================================
@app.get("/api/status", dependencies=[Depends(require_auth)])
async def pipeline_status():
    return _active_run

@app.get("/api/spine/progress", dependencies=[Depends(require_auth)])
async def spine_progress(run_id: str = "latest"):
    """Live progress for the master-spine orchestrator (pipeline_spine_master).

    Reads the most recent run's progress.json (connectivity boards + per-stage
    return codes) written under local-staging/spine-runs/. 404 if no run yet.
    """
    root = os.path.join(PROJECT_DIR, "local-staging", "spine-runs")
    if not os.path.isdir(root):
        raise HTTPException(status_code=404, detail="No spine runs found")
    if run_id and run_id != "latest":
        candidate = os.path.join(root, run_id, "progress.json")
        runs = [candidate] if os.path.isfile(candidate) else []
    else:
        runs = []
        for name in os.listdir(root):
            pf = os.path.join(root, name, "progress.json")
            if os.path.isfile(pf):
                runs.append(pf)
        runs.sort(key=os.path.getmtime, reverse=True)
    if not runs:
        raise HTTPException(status_code=404, detail="No spine progress available")
    try:
        with open(runs[0], "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"progress unreadable: {e}")


def _gate_controller():
    """Lazily build the spine GateController (lives in lambda/utils)."""
    try:
        utils_dir = os.path.join(PROJECT_DIR, "lambda", "utils")
        if utils_dir not in sys.path:
            sys.path.insert(0, utils_dir)
        from governance import GateController
        return GateController()
    except Exception:
        return None


@app.get("/api/spine/gates", dependencies=[Depends(require_auth)])
async def spine_gates():
    """List pending human-approval gates for the master spine (Pillar 3)."""
    gc = _gate_controller()
    if gc is None:
        return {"gates": [], "error": "governance module unavailable"}
    # never expose the HMAC signature in a list response
    return {"gates": [{k: v for k, v in g.items() if k != "signature"}
                      for g in gc.list_pending()]}


@app.post("/api/spine/approve", dependencies=[Depends(require_auth)])
async def spine_approve(request: Request):
    """Signed resume webhook (Pillar 3). Body: {gate_id, signature, decided_by,
    action?: approve|reject}. The HMAC signature is the cutover fence — only a
    holder of the run's gate secret can pass it; the pipeline stays frozen otherwise."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    gate_id = body.get("gate_id")
    signature = body.get("signature")
    decided_by = body.get("decided_by", "")
    action = str(body.get("action", "approve")).lower()
    if not gate_id or not signature:
        raise HTTPException(status_code=400, detail="gate_id and signature are required")
    gc = _gate_controller()
    if gc is None:
        raise HTTPException(status_code=503, detail="governance module unavailable")
    res = (gc.reject(gate_id, signature, decided_by) if action == "reject"
           else gc.approve(gate_id, signature, decided_by))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "gate decision failed"))
    return res

@app.get("/api/progress", dependencies=[Depends(require_auth)])
async def pipeline_progress(since: int = 0):
    """Return real-time progress steps. Use ?since=N to get only steps after index N."""
    steps = _progress_steps[since:] if since > 0 else _progress_steps
    return {
        "status": _active_run.get("status", "idle"),
        "mode": _active_run.get("mode"),
        "run_id": _active_run.get("run_id"),
        "pdf_generated": _active_run.get("pdf_generated", False),
        "total_steps": len(_progress_steps),
        "since": since,
        "steps": steps,
    }

@app.get("/api/runs", dependencies=[Depends(require_auth)])
async def get_runs(request: Request):
    return list_runs(_client_id_for(request))

@app.get("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
async def get_run_by_id(run_id: str, request: Request):
    cid = _client_id_for(request)
    if run_id == "latest":
        runs = list_runs(cid)
        run_id = runs[0]["id"] if runs else None
    data = get_run(run_id, cid) if run_id else None
    if data:
        return data
    raise HTTPException(status_code=404, detail="Run not found")

@app.get("/api/runs/{run_id}/pdf", dependencies=[Depends(require_auth)])
async def get_run_pdf(run_id: str, request: Request):
    cid = _client_id_for(request)
    if run_id == "latest":
        runs = list_runs(cid)
        run_id = runs[0]["id"] if runs else None
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    # Lift-and-shift runs land here first: the runner's stage27 already wrote
    # the PDF to local-staging/m4h-local/runs/<run_id>/report/migration-report.pdf
    # before exiting, so we don't need to regenerate it.
    ls_pdf = os.path.join(PROJECT_DIR, "local-staging", "m4h-local",
                           "runs", run_id, "report", "migration-report.pdf")
    if os.path.isfile(ls_pdf):
        return FileResponse(ls_pdf, media_type="application/pdf",
                            filename=f"migration-report-{run_id}.pdf")
    pdf_path = generate_pdf_for_run(run_id)
    if pdf_path and os.path.isfile(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf",
                            filename=f"migration-report-{run_id}.pdf")
    raise HTTPException(status_code=404, detail="Report not available for this run")


def _ls_run_dir(run_id: str) -> str:
    return os.path.join(PROJECT_DIR, "local-staging", "m4h-local", "runs", run_id)


@app.get("/api/runs/{run_id}/telemetry", dependencies=[Depends(require_auth)])
async def get_run_telemetry(run_id: str):
    """Slim aggregated JSON for the dashboard metric cards.

    Shape is spec-locked in lambda/utils/telemetry.aggregate_run_telemetry
    (see tests/test_telemetry.py). The frontend polls this at ~2Hz instead
    of reading raw stderr, so payload size stays under 300 bytes.
    """
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from telemetry import aggregate_run_telemetry
    # Only pass the active-run state when its run_id matches; otherwise a
    # stale in-memory pointer would leak "Processing" into a completed run's
    # dashboard.
    active = _active_run if _active_run.get("run_id") == run_id else None
    return aggregate_run_telemetry(_ls_run_dir(run_id), active_state=active)


@app.get("/api/runs/{run_id}/error-buckets", dependencies=[Depends(require_auth)])
async def get_run_error_buckets(run_id: str):
    """Group identical failure signatures into triage cards.

    Sorted by count desc; each entry carries the operator remediation hint,
    the set of objects that hit it, and up to 3 sample source keys.
    """
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from telemetry import bucket_errors
    return {"run_id": run_id, "buckets": bucket_errors(_ls_run_dir(run_id))}


@app.get("/api/runs/{run_id}/failed-records.csv",
         dependencies=[Depends(require_auth)])
async def get_run_failed_records_csv(run_id: str):
    """Download exactly the failing rows as a CSV the operator can open in
    Excel, fix, and hand back to the migration lead."""
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from telemetry import failed_records_csv
    data = failed_records_csv(_ls_run_dir(run_id))
    from fastapi.responses import Response as _Resp
    fname = f"failed-records-{run_id}.csv"
    return _Resp(content=data, media_type="text/csv; charset=utf-8",
                 headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/runs/{run_id}/evidence-pack",
         dependencies=[Depends(require_auth)])
async def get_run_evidence_pack(run_id: str):
    """Return the tamper-proof evidence manifest for the run.

    The manifest is built by lambda/utils/reconciler.EvidencePack from the
    run's data-migrator summary + audit chain and cached under
    <run>/report/evidence_pack_<run_id>.json. If it isn't on disk yet
    (older runs) we build it on the fly from whatever artefacts exist.
    """
    run_dir = _ls_run_dir(run_id)
    report_dir = os.path.join(run_dir, "report")
    cached = os.path.join(report_dir, f"evidence_pack_{run_id}.json")
    if not os.path.isfile(cached):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        try:
            from reconciler import EvidencePack
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail={"error": "reconciler module unavailable",
                                        "message": str(e)[:200]})
        # Pull summary + audit chain if present; missing pieces just render
        # empty in the manifest (evidence is honest, not fabricated).
        summary_path = os.path.join(run_dir, "data-migrator", "summary.json")
        try:
            summary = json.loads(open(summary_path, encoding="utf-8").read()) \
                if os.path.isfile(summary_path) else {}
        except Exception:
            summary = {}
        pack = EvidencePack(run_id=run_id, chain=None)
        manifest = pack.build_manifest(
            system_config={"run_id": run_id},
            data_quality=summary.get("data_quality") or {},
            reconciliation=summary.get("reconciliation") or {},
        )
        pack.write(manifest, out_dir=report_dir)
    return FileResponse(cached, media_type="application/json",
                        filename=f"evidence_pack_{run_id}.json")


@app.get("/api/mapping-template.csv",
         dependencies=[Depends(require_auth)])
async def get_mapping_template():
    """Emit a blank field-mapping template built from the conversion catalog.

    Each row is one migratable object; operators fill the `target_field` /
    `transformation` columns and re-upload via /api/mapping/validate.
    """
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import list_all_mappings
    import io as _io
    import csv as _csv
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["object", "category", "ecc_tables", "s4_targets",
                "source_field", "target_field", "transformation", "notes"])
    for m in list_all_mappings():
        w.writerow([
            m.get("object", ""),
            m.get("category", ""),
            "|".join(m.get("ecc_tables") or []),
            "|".join(m.get("s4_targets") or []),
            "", "", "", "",   # operator-filled columns
        ])
    from fastapi.responses import Response as _Resp
    return _Resp(content=buf.getvalue().encode("utf-8"),
                 media_type="text/csv; charset=utf-8",
                 headers={"Content-Disposition":
                          'attachment; filename="mapping-template.csv"'})


@app.post("/api/mapping-validate",
          dependencies=[Depends(require_auth)])
async def validate_mapping_upload(request: Request):
    """Accept an uploaded CSV of field mappings and return a pass/fail list.

    Slim payload:
        {ok: bool, row_count: N, errors: [{row, column, message}, ...]}
    """
    import io as _io
    import csv as _csv
    sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
    from conversion_mapping import list_all_mappings

    body = await request.body()
    try:
        text = body.decode("utf-8-sig")
    except Exception:
        return {"ok": False, "row_count": 0,
                "errors": [{"row": 0, "column": "", "message": "not valid UTF-8"}]}
    try:
        reader = list(_csv.DictReader(_io.StringIO(text)))
    except Exception as e:
        return {"ok": False, "row_count": 0,
                "errors": [{"row": 0, "column": "", "message": f"CSV parse: {e}"}]}
    known_objects = {m["object"] for m in list_all_mappings()}
    errors = []
    for idx, row in enumerate(reader, start=2):  # header is row 1
        obj = (row.get("object") or "").strip()
        if not obj:
            errors.append({"row": idx, "column": "object",
                           "message": "object is required"})
            continue
        if obj not in known_objects:
            errors.append({"row": idx, "column": "object",
                           "message": f"unknown object: {obj}"})
        tf = (row.get("target_field") or "").strip()
        sf = (row.get("source_field") or "").strip()
        # If the operator filled EITHER side of a mapping, both must be present.
        if (tf and not sf) or (sf and not tf):
            errors.append({"row": idx, "column": "source_field/target_field",
                           "message": "source_field and target_field must be paired"})
    return {"ok": not errors, "row_count": len(reader), "errors": errors}


@app.get("/api/runs/{run_id}/report", dependencies=[Depends(require_auth)])
async def get_run_report_sections(run_id: str, request: Request):
    cid = _client_id_for(request)
    """Return a UI-friendly, sectioned view of the same data the PDF report
    renders — so the Migration Report page can show it live (refresh every
    5-10s) without waiting for the PDF to be generated at the end of the run.

    Section order matches pdf_report_generator.py. Any section the run hasn't
    populated yet is returned with empty data — the UI shows it as "pending"
    rather than hiding it (gives the customer a sense of overall progress)."""
    if run_id == "latest":
        runs = list_runs(cid)
        run_id = runs[0]["id"] if runs else None
    data = get_run(run_id, cid) if run_id else None
    if not data:
        # Run may be in-flight — fall back to whatever partial files exist.
        partial = {}
        base = os.path.join(_client_outputs_dir(cid), run_id) if run_id else None
        if base and os.path.isdir(base):
            for fname in ("summary.json", "data-quality.json", "post-migration-report.json"):
                fp = os.path.join(base, fname)
                if os.path.isfile(fp):
                    try:
                        with open(fp, "r", encoding="utf-8") as fh:
                            partial[fname.replace(".json", "").replace("-", "_")] = json.load(fh)
                    except Exception:
                        pass
        data = partial or None

    if not data:
        return {"run_id": run_id, "status": "no_data", "sections": []}

    # The PDF reads "post_migration_report" by convention; some older runs put
    # the same content at the top level. Accept either.
    pmr = data.get("post_migration_report") or data
    ex  = pmr.get("executive_summary") or {}
    ssa = pmr.get("source_system_assessment") or {}
    cr  = pmr.get("code_remediation") or {}
    dm  = pmr.get("data_migration") or {}
    cfg = pmr.get("configuration") or {}
    auth = pmr.get("roles_and_authorizations") or {}
    intg = pmr.get("integrations") or {}
    sc  = pmr.get("go_live_scorecard") or {}
    risk = pmr.get("risk_assessment") or {}
    roadmap = pmr.get("post_go_live_roadmap") or {}
    tech = pmr.get("technical_metrics") or {}
    dq  = data.get("data_quality") or pmr.get("data_quality") or {}

    def _present(d):
        return bool(d) and any(v not in (None, "", 0, [], {}) for v in d.values()) if isinstance(d, dict) else bool(d)

    sections = [
        {"id": "executive",    "title": "1. Executive Summary",
         "ready": _present(ex) or _present(ssa), "data": {"executive_summary": ex, "source_system_assessment": ssa}},
        {"id": "code",         "title": "2. Code Remediation",
         "ready": _present(cr), "data": cr},
        {"id": "data",         "title": "3. Data Migration",
         "ready": _present(dm), "data": dm},
        {"id": "data_quality", "title": "Dead-Letter SLO / Data Quality",
         "ready": _present(dq), "data": dq},
        {"id": "config",       "title": "4. Configuration",
         "ready": _present(cfg), "data": cfg},
        {"id": "auth",         "title": "5. Roles & Authorizations",
         "ready": _present(auth), "data": auth},
        {"id": "integrations", "title": "6. Integrations",
         "ready": _present(intg), "data": intg},
        {"id": "scorecard",    "title": "7. Go-Live Scorecard",
         "ready": _present(sc), "data": sc},
        {"id": "risk",         "title": "8. Risk Assessment",
         "ready": _present(risk), "data": risk},
        {"id": "roadmap",      "title": "9. Post Go-Live Roadmap",
         "ready": _present(roadmap), "data": roadmap},
        {"id": "tech",         "title": "10. Technical Metrics",
         "ready": _present(tech), "data": tech},
    ]
    ready_n = sum(1 for s in sections if s["ready"])
    return {
        "run_id": run_id,
        "status": data.get("status") or ("complete" if ready_n == len(sections) else "in_progress"),
        "ready_sections": ready_n,
        "total_sections": len(sections),
        "sections": sections,
    }


@app.get("/api/v1/reports/{run_id}/volumes", dependencies=[Depends(require_auth)])
async def get_report_volumes(run_id: str):
    """List all PDF volumes for a given run."""
    if run_id == "latest":
        runs = list_runs()
        run_id = runs[0]["id"] if runs else None
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    reports_dir = os.path.join(OUTPUT_DIR, run_id, "reports")
    if not os.path.isdir(reports_dir):
        raise HTTPException(status_code=404, detail="No report volumes found for this run")
    volumes = []
    for fname in sorted(os.listdir(reports_dir)):
        if fname.endswith(".pdf"):
            fpath = os.path.join(reports_dir, fname)
            volumes.append({
                "filename": fname,
                "size_bytes": os.path.getsize(fpath),
                "size_kb": round(os.path.getsize(fpath) / 1024, 1),
            })
    if not volumes:
        raise HTTPException(status_code=404, detail="No PDF volumes found")
    return {"run_id": run_id, "total_volumes": len(volumes), "volumes": volumes}


@app.get("/api/v1/reports/{run_id}/download/{volume_number}", dependencies=[Depends(require_auth)])
async def download_report_volume(run_id: str, volume_number: int):
    """Download a specific PDF volume by number (1-based)."""
    if run_id == "latest":
        runs = list_runs()
        run_id = runs[0]["id"] if runs else None
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    reports_dir = os.path.join(OUTPUT_DIR, run_id, "reports")
    if not os.path.isdir(reports_dir):
        raise HTTPException(status_code=404, detail="No report volumes found")
    pdf_files = sorted(f for f in os.listdir(reports_dir) if f.endswith(".pdf"))
    if not pdf_files:
        raise HTTPException(status_code=404, detail="No PDF volumes found in reports directory")
    if volume_number < 1 or volume_number > len(pdf_files):
        raise HTTPException(status_code=404,
                            detail=f"Volume {volume_number} not found. Available: 1-{len(pdf_files)}")
    pdf_path = os.path.join(reports_dir, pdf_files[volume_number - 1])
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=pdf_files[volume_number - 1])


# =============================================================================
# ROUTES - LOGS (CloudWatch + local progress)
# =============================================================================
# Surfaces pipeline + Lambda + Fargate logs to the UI. In the cloud build,
# events come from CloudWatch Logs (boto3.client("logs")). In the local
# build (laptop dev), we fall back to the in-memory progress steps + any
# local log files under outputs/<run_id>/.
#
# Retention: every Lambda + the api-server log group is created with a 30-day
# retention policy in terraform/modules/lambda/main.tf and
# terraform/modules/api-server/main.tf. That's the cap the UI advertises.
import re as _re

_LOG_GROUP_PREFIX = os.environ.get("M4H_LOG_GROUP_PREFIX", "/aws/lambda/migrate4hana-")
_ECS_LOG_GROUP    = os.environ.get("M4H_ECS_LOG_GROUP",    "/ecs/migrate4hana-api-server-prod")
_SFN_LOG_GROUP    = os.environ.get("M4H_SFN_LOG_GROUP",    "/aws/vendedlogs/states/migrate4hana-lift-and-shift-prod")
_LOG_RETENTION_DAYS = 30  # advertised to the UI; enforced via terraform


def _cloudwatch_client():
    """Cached boto3 logs client. Returns None if boto3 / creds unavailable
    (which is the case on the dev laptop without M4H_AWS=1)."""
    if not getattr(_cloudwatch_client, "_c", None):
        try:
            import boto3 as _b
            _cloudwatch_client._c = _b.client("logs")
        except Exception:
            _cloudwatch_client._c = None
    return _cloudwatch_client._c


def _list_log_groups():
    """Return the known set of log groups for the migration platform.

    Always offers a "local" source (in-memory progress steps + on-disk
    log files under outputs/<run_id>/) so the UI works without AWS
    creds. CloudWatch sources are appended only when they actually exist;
    a missing log group is silently skipped so we don't hand the UI a
    source that 404s on selection.
    """
    out = []
    # Local source is always present and free; default for dev.
    out.append({"key": "local", "name": "local",
                 "label": "Local (in-memory progress + outputs/)"})
    cw = _cloudwatch_client()
    if not cw:
        return out
    # CloudWatch is reachable - probe each candidate group's existence
    # before advertising it. Missing groups are silently skipped so we
    # don't fail tail_logs with ResourceNotFoundException.
    def _group_exists(name: str) -> bool:
        if not name:
            return False
        try:
            resp = cw.describe_log_groups(logGroupNamePrefix=name, limit=1)
            return any(g.get("logGroupName") == name for g in resp.get("logGroups", []))
        except Exception:
            return False

    if _group_exists(_SFN_LOG_GROUP):
        out.append({"key": "sfn", "name": _SFN_LOG_GROUP, "label": "Step Functions executions"})
    if _group_exists(_ECS_LOG_GROUP):
        out.append({"key": "api", "name": _ECS_LOG_GROUP, "label": "API server (Fargate)"})
    try:
        resp = cw.describe_log_groups(logGroupNamePrefix=_LOG_GROUP_PREFIX, limit=50)
        for g in resp.get("logGroups", []):
            name = g.get("logGroupName", "")
            short = name.replace(_LOG_GROUP_PREFIX, "").replace("-prod", "")
            out.append({"key": f"lambda-{short}", "name": name, "label": f"Lambda · {short}"})
    except Exception:
        pass
    return out


def _read_local_log(run_id: str, max_lines: int = 5000):
    """Local fallback: stitch together every *.log under outputs/<run_id>/."""
    events = []
    base = os.path.join(OUTPUT_DIR, run_id) if run_id else OUTPUT_DIR
    if not os.path.isdir(base):
        return events
    for root, _, files in os.walk(base):
        for fn in files:
            if not fn.endswith((".log", ".out", ".txt")):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        events.append({
                            "ts": int(os.path.getmtime(fp) * 1000),
                            "msg": line.rstrip("\n"),
                            "src": os.path.relpath(fp, OUTPUT_DIR),
                        })
                        if len(events) >= max_lines:
                            return events
            except Exception:
                continue
    return events


@app.get("/api/logs/sources", dependencies=[Depends(require_auth)])
async def get_log_sources():
    """List every log group the UI can tail, plus retention info."""
    return {
        "retention_days": _LOG_RETENTION_DAYS,
        "sources": _list_log_groups(),
        "has_cloudwatch": _cloudwatch_client() is not None,
    }


@app.get("/api/logs/tail", dependencies=[Depends(require_auth)])
async def tail_logs(
    source: str = "sfn",
    run_id: Optional[str] = None,
    next_token: Optional[str] = None,
    start_ms: Optional[int] = None,
    limit: int = 500,
    q: Optional[str] = None,
):
    """Page through log events. If source resolves to a CloudWatch group we
    use FilterLogEvents (server-side string match on `q`); otherwise we fall
    back to the local outputs directory. Returns {events, next_token}."""
    cw = _cloudwatch_client()
    sources = {s["key"]: s["name"] for s in _list_log_groups()}
    group = sources.get(source)
    # The "local" pseudo-source always uses the local fallback below, even
    # when CloudWatch creds are present. Only real CW groups go to CW.
    if cw and group and source != "local" and group != "local":
        kwargs = {"logGroupName": group, "limit": min(max(int(limit), 1), 1000)}
        if next_token: kwargs["nextToken"] = next_token
        if start_ms:   kwargs["startTime"] = int(start_ms)
        if q:          kwargs["filterPattern"] = q
        if run_id:
            # If we know the run id, narrow further with it (CloudWatch will
            # AND it with the user filter).
            kwargs["filterPattern"] = f'"{run_id}" {q or ""}'.strip()
        try:
            resp = cw.filter_log_events(**kwargs)
            events = [{
                "ts":    e.get("timestamp", 0),
                "msg":   e.get("message", "").rstrip(),
                "src":   e.get("logStreamName", ""),
                "id":    e.get("eventId", ""),
            } for e in resp.get("events", [])]
            return {"events": events, "next_token": resp.get("nextToken"),
                    "source": source, "group": group, "via": "cloudwatch"}
        except Exception as exc:
            return {"events": [], "next_token": None, "source": source,
                    "group": group, "via": "cloudwatch", "error": str(exc)}
    # Local fallback
    events = _read_local_log(run_id, max_lines=limit)
    if q:
        events = [e for e in events if q.lower() in e["msg"].lower()]
    # Always splice the in-memory progress steps in too (they're not in files).
    # `step.ts` is already epoch-ms (set by _add_progress_step). Do NOT multiply
    # by 1000 again or you get year-58k timestamps in the UI.
    for s in (_progress_steps or []):
        raw_ts = s.get("ts")
        if isinstance(raw_ts, (int, float)) and raw_ts > 0:
            ts_ms = int(raw_ts) if raw_ts > 1e11 else int(raw_ts * 1000)
        else:
            ts_ms = int(time.time() * 1000)
        events.append({
            "ts":  ts_ms,
            "msg": f"[{s.get('phase','-')}] {s.get('message','')}",
            "src": "progress",
        })
    events.sort(key=lambda e: e.get("ts", 0))
    return {"events": events[-limit:], "next_token": None,
            "source": source, "group": None, "via": "local"}


@app.get("/api/logs/download", dependencies=[Depends(require_auth)])
async def download_logs(source: str = "sfn", run_id: Optional[str] = None,
                        hours: int = 24, q: Optional[str] = None):
    """Download a window of logs as a plain-text .log file."""
    import io
    start_ms = int((time.time() - max(1, min(hours, 24 * _LOG_RETENTION_DAYS)) * 3600) * 1000)
    cw = _cloudwatch_client()
    sources = {s["key"]: s["name"] for s in _list_log_groups()}
    group = sources.get(source)
    buf = io.StringIO()
    buf.write(f"# Migrate4HANA logs — source={source} group={group or '(local)'} "
              f"run_id={run_id or '-'} window={hours}h q={q or '-'}\n")
    if cw and group and source != "local" and group != "local":
        next_tok = None
        total = 0
        try:
            while True:
                kwargs = {"logGroupName": group, "limit": 1000, "startTime": start_ms}
                if next_tok: kwargs["nextToken"] = next_tok
                if q:        kwargs["filterPattern"] = q
                if run_id:   kwargs["filterPattern"] = f'"{run_id}" {q or ""}'.strip()
                resp = cw.filter_log_events(**kwargs)
                for e in resp.get("events", []):
                    ts = datetime.fromtimestamp(e.get("timestamp", 0) / 1000, tz=timezone.utc).isoformat()
                    buf.write(f"{ts}  {e.get('logStreamName','-')}  {e.get('message','').rstrip()}\n")
                    total += 1
                next_tok = resp.get("nextToken")
                if not next_tok or total >= 50000:
                    break
        except Exception as exc:
            buf.write(f"\n# error: {exc}\n")
    else:
        for e in _read_local_log(run_id, max_lines=20000):
            ts = datetime.fromtimestamp(e.get("ts", 0) / 1000, tz=timezone.utc).isoformat()
            buf.write(f"{ts}  {e.get('src','-')}  {e.get('msg','')}\n")
    data = buf.getvalue().encode("utf-8")
    fname = f"migrate4hana-{source}-{run_id or 'all'}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.log"
    from fastapi.responses import Response as _Resp
    return _Resp(content=data, media_type="text/plain; charset=utf-8",
                 headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# =============================================================================
# ROUTES - WHITELISTED SCRIPT RUNNER
# =============================================================================
# Exposes a small, locked-down catalogue of server-side scripts the UI can
# trigger without giving the user a shell. Each script is registered with:
#   - a stable id (used by the UI)
#   - the exact argv list to run (no shell interpolation)
#   - optional parameter schema (UI renders form fields, server validates)
# Output is captured (stdout/stderr/return-code) and returned synchronously
# for short scripts, or pushed to a job log for long ones.
import subprocess
import threading
import uuid

# Registry: id → {description, command, params, max_seconds}
# `command` is an argv list. Placeholders like "{user}" get substituted
# from the validated params dict (str-cast, never shell-evaluated).
SCRIPT_REGISTRY = {
    # ── Connectivity tests ─────────────────────────────────────────
    "test-ecc-rfc": {
        "title": "Test ECC RFC connectivity",
        "description": "Verify pyrfc against the configured ECC. Honest pass/fail.",
        "category": "diagnostics",
        "command": [sys.executable, "test_rfc_connectivity.py"],
        "params": [],
        "max_seconds": 90,
    },
    "diag-login": {
        "title": "Test S/4 login",
        "description": "Verify S/4HANA RFC + OData login.",
        "category": "diagnostics",
        "command": [sys.executable, "diag_login.py"],
        "params": [],
        "max_seconds": 60,
    },
    "bp-bapi-probe": {
        "title": "BP BAPI probe",
        "description": "Live BUPA_CREATE_FROM_DATA / role-attach probe.",
        "category": "diagnostics",
        "command": [sys.executable, "bp_bapi_probe.py"],
        "params": [],
        "max_seconds": 90,
    },
    "material-diag": {
        "title": "Material BAPI diag",
        "description": "BAPI_MATERIAL_SAVEDATA probe with field-coverage classifier.",
        "category": "diagnostics",
        "command": [sys.executable, "material_diag.py"],
        "params": [],
        "max_seconds": 120,
    },
    "mc-role-probe": {
        "title": "MC role probe",
        "description": "Migration Cockpit role membership check.",
        "category": "diagnostics",
        "command": [sys.executable, "mc_role_probe.py"],
        "params": [],
        "max_seconds": 60,
    },
    "idoc-prove": {
        "title": "IDoc inbound prove",
        "description": "IDoc inbound proof flow.",
        "category": "diagnostics",
        "command": [sys.executable, "idoc_prove.py"],
        "params": [],
        "max_seconds": 120,
    },
    "idoc-setup-probe": {
        "title": "IDoc setup probe",
        "description": "Validate SICF/WE20/SM59 wiring for IDoc inbound.",
        "category": "diagnostics",
        "command": [sys.executable, "idoc_setup_probe.py"],
        "params": [],
        "max_seconds": 60,
    },
    "check-partner": {
        "title": "Check Business Partner",
        "description": "Look up a BP by various keys to verify creates.",
        "category": "diagnostics",
        "command": [sys.executable, "check_partner.py", "{partner_id}"],
        "params": [{"name": "partner_id", "label": "Partner ID", "type": "text", "required": True}],
        "max_seconds": 30,
    },
    "audit-pipeline": {
        "title": "Audit pipeline",
        "description": "Walk the hash-chained audit ledger for a run.",
        "category": "diagnostics",
        "command": [sys.executable, "audit_pipeline.py", "{run_id}"],
        "params": [{"name": "run_id", "label": "Run ID", "type": "text", "required": True}],
        "max_seconds": 30,
    },
    # ── Pipeline ──
    "list-stages": {
        "title": "List pipeline stages",
        "description": "Print the ordered 27-stage table.",
        "category": "pipeline",
        "command": [sys.executable, "run_local_lift_and_shift.py", "--list-stages"],
        "params": [],
        "max_seconds": 15,
    },
    "pipeline-assess": {
        "title": "Run assessment (read-only)",
        "description": "Phases 1-2: discovery + readiness + simplification + assessment.",
        "category": "pipeline",
        "command": [sys.executable, "run_local_lift_and_shift.py", "--through", "stage21"],
        "params": [],
        "max_seconds": 1800,
    },
    "pipeline-full": {
        "title": "Run full lift & shift",
        "description": "All 27 stages end-to-end. Long-running.",
        "category": "pipeline",
        "command": [sys.executable, "run_local_lift_and_shift.py", "--run-id", "{run_id}"],
        "params": [{"name": "run_id", "label": "Run ID", "type": "text", "required": True, "default": "RUN-001"}],
        "max_seconds": 7200,
    },
    # ── Spine ──
    "spine-run": {
        "title": "Run master spine",
        "description": "Natuvion → Syniti → SmartShift → Governance. Writes progress.json.",
        "category": "spine",
        "command": [sys.executable, "pipeline_spine_master.py"],
        "params": [],
        "max_seconds": 1800,
    },
    "spine-self-test": {
        "title": "Data-spine self-test",
        "description": "FK integrity, deterministic self-heal, hash-chained idempotency.",
        "category": "spine",
        "command": [sys.executable, "data_spine_orchestrator.py"],
        "params": [],
        "max_seconds": 900,
    },
    # ── Reports ──
    "pdf-local": {
        "title": "Render PDF (local)",
        "description": "Render a PDF from a local run artifact directory.",
        "category": "reports",
        "command": [sys.executable, "pdf_report_generator.py", "{run_id}"],
        "params": [{"name": "run_id", "label": "Run ID", "type": "text", "required": True}],
        "max_seconds": 120,
    },
    "pdf-multi": {
        "title": "Render multi-volume PDF",
        "description": "Produce the multi-volume executive report.",
        "category": "reports",
        "command": [sys.executable, "multi_volume_report_generator.py", "{run_id}"],
        "params": [{"name": "run_id", "label": "Run ID", "type": "text", "required": True}],
        "max_seconds": 180,
    },
}

# In-memory job store: job_id → {script_id, status, started, finished, returncode, stdout, stderr}
SCRIPT_JOBS: dict = {}
SCRIPT_JOBS_LOCK = threading.Lock()


class ScriptRunRequest(BaseModel):
    script_id: str
    params: dict = {}


@app.get("/api/scripts/list", dependencies=[Depends(require_auth)])
async def list_scripts():
    """Return the catalogue of UI-runnable server-side scripts."""
    out = []
    for sid, s in SCRIPT_REGISTRY.items():
        out.append({
            "id": sid,
            "title": s["title"],
            "description": s["description"],
            "category": s.get("category", "other"),
            "params": s.get("params", []),
            "max_seconds": s.get("max_seconds", 60),
        })
    return {"scripts": out}


def _run_script_job(job_id: str, script_id: str, command: list):
    """Background worker: runs the command, captures output, updates the job."""
    try:
        proc = subprocess.run(
            command, cwd=PROJECT_DIR, capture_output=True, text=True,
            timeout=SCRIPT_REGISTRY[script_id].get("max_seconds", 60),
        )
        stdout = (proc.stdout or "")[-50_000:]
        stderr = (proc.stderr or "")[-20_000:]
        with SCRIPT_JOBS_LOCK:
            SCRIPT_JOBS[job_id].update({
                "status":     "completed" if proc.returncode == 0 else "failed",
                "finished":   datetime.now().isoformat(),
                "returncode": proc.returncode,
                "stdout":     stdout,
                "stderr":     stderr,
            })
    except subprocess.TimeoutExpired as e:
        with SCRIPT_JOBS_LOCK:
            SCRIPT_JOBS[job_id].update({
                "status":     "timeout",
                "finished":   datetime.now().isoformat(),
                "returncode": -1,
                "stdout":     (e.stdout or b"").decode("utf-8", "replace")[-10_000:] if e.stdout else "",
                "stderr":     f"Timeout after {e.timeout}s",
            })
    except Exception as ex:
        with SCRIPT_JOBS_LOCK:
            SCRIPT_JOBS[job_id].update({
                "status":     "error",
                "finished":   datetime.now().isoformat(),
                "returncode": -1,
                "stdout":     "",
                "stderr":     f"{type(ex).__name__}: {ex}",
            })


@app.post("/api/scripts/run", dependencies=[Depends(require_auth)])
async def run_script(body: ScriptRunRequest):
    """Run a whitelisted script. Returns a job_id; poll /api/scripts/output/{job_id}."""
    if body.script_id not in SCRIPT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown script: {body.script_id}")
    spec = SCRIPT_REGISTRY[body.script_id]

    # Validate params against schema
    required = {p["name"] for p in spec.get("params", []) if p.get("required")}
    provided = set(body.params.keys())
    missing = required - provided
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing params: {sorted(missing)}")

    # Substitute placeholders (str-cast, never shell-eval)
    command = []
    for arg in spec["command"]:
        if arg.startswith("{") and arg.endswith("}"):
            key = arg[1:-1]
            command.append(str(body.params.get(key, "")))
        else:
            command.append(arg)

    job_id = uuid.uuid4().hex[:12]
    with SCRIPT_JOBS_LOCK:
        SCRIPT_JOBS[job_id] = {
            "job_id":     job_id,
            "script_id":  body.script_id,
            "command":    command,
            "status":     "running",
            "started":    datetime.now().isoformat(),
            "finished":   None,
            "returncode": None,
            "stdout":     "",
            "stderr":     "",
        }
    t = threading.Thread(target=_run_script_job, args=(job_id, body.script_id, command), daemon=True)
    t.start()
    return {"job_id": job_id, "status": "running", "script_id": body.script_id}


@app.get("/api/scripts/output/{job_id}", dependencies=[Depends(require_auth)])
async def get_script_output(job_id: str):
    """Return the current state of a script job. UI polls this."""
    with SCRIPT_JOBS_LOCK:
        job = SCRIPT_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# =============================================================================
# MAIN
# =============================================================================
def main():
    _ensure_jwt_secret()
    if "--generate-token" in sys.argv:
        token = generate_jwt()
        print(f"Bearer token (valid 24h):\n{token}")
        return

    import uvicorn
    host = os.environ.get("M4H_HOST", "0.0.0.0")
    port = int(os.environ.get("M4H_PORT", "8000"))
    workers = int(os.environ.get("M4H_WORKERS", "1"))
    ssl_keyfile = os.environ.get("M4H_SSL_KEY")
    ssl_certfile = os.environ.get("M4H_SSL_CERT")

    print(f"\n  Migrate4HANA API Server (FastAPI + Uvicorn)")
    print(f"  {'='*45}")
    print(f"  Listening on {'https' if ssl_certfile else 'http'}://{host}:{port}")
    print(f"  Workers: {workers}")
    if ssl_certfile:
        print(f"  TLS: {ssl_certfile}")
    print(f"  Endpoints:")
    print(f"    GET  /api/health             - Health check (public)")
    print(f"    GET  /api/connections         - Saved connections")
    print(f"    POST /api/connections/ecc     - Save ECC connection")
    print(f"    POST /api/connections/s4hana  - Save S/4HANA connection")
    print(f"    POST /api/connections/ecc/test    - Test ECC connection")
    print(f"    POST /api/connections/s4hana/test - Test S/4HANA connection")
    print(f"    POST /api/pipeline/assess     - Run Phases 1-2 (stages 1-8)")
    print(f"    POST /api/pipeline/convert    - Run Phase 3 (stages 9-10)")
    print(f"    POST /api/pipeline/complete   - Run Phases 4-5 (stages 11-17)")
    print(f"    POST /api/pipeline/full       - Run all 5 phases (stages 1-17)")
    print(f"    POST /api/pipeline/ecc_full   - Run ECC-only mode (stages 1-9.6)")
    print(f"    GET  /api/status              - Pipeline status")
    print(f"    GET  /api/runs                - List all runs")
    print(f"    GET  /api/runs/ID             - Get run results")
    print(f"    GET  /api/runs/ID/pdf         - Download PDF report")
    print(f"    GET  /api/v1/reports/ID/volumes  - List PDF volumes")
    print(f"    GET  /api/v1/reports/ID/download/N - Download volume N")
    print(f"    GET  /docs                    - OpenAPI/Swagger documentation\n")

    uvicorn.run("api_server:app", host=host, port=port, workers=workers,
                ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile, access_log=True)


if __name__ == "__main__":
    main()
