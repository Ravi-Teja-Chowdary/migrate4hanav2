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
from typing import Optional

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

# Shared state for active runs
_active_run = {"status": "idle", "results": None, "run_id": None}
_lock = asyncio.Lock()

# Real-time progress steps for telemetry
_progress_steps = []
_progress_lock = asyncio.Lock()

# In-memory ECC password (set after successful connection test, never persisted)
_ecc_passwd = ""


def _add_progress_step(stage, action, status="IN_PROGRESS", details=None, duration_ms=None):
    """Add a progress step to the real-time telemetry feed."""
    import asyncio as _aio
    step = {
        "event_id": secrets.token_hex(6),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "action": action,
        "status": status,
        "details": details or {},
        "duration_ms": duration_ms,
    }
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
    """Ensure a JWT secret exists; generate and persist one if not set."""
    global _JWT_SECRET
    if _JWT_SECRET:
        return
    secret_file = os.path.join(PROJECT_DIR, ".jwt_secret")
    if os.path.isfile(secret_file):
        with open(secret_file, "r", encoding="utf-8") as f:
            _JWT_SECRET = f.read().strip()
        if _JWT_SECRET:
            return
    _JWT_SECRET = secrets.token_hex(32)
    with open(secret_file, "w", encoding="utf-8") as f:
        f.write(_JWT_SECRET)
    print(f"  [Auth] Generated JWT secret -> .jwt_secret (keep this file secure)")


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
def list_runs():
    runs = []
    if not os.path.isdir(OUTPUT_DIR):
        return runs
    for entry in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if entry.startswith("run_"):
            report_path = os.path.join(OUTPUT_DIR, entry, "final-report.json")
            if os.path.isfile(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                runs.append({"id": entry, "timestamp": entry.replace("run_", ""),
                             "has_execution": "cutover" in data, "results": data})
    return runs


def get_run(run_id):
    report_path = os.path.join(OUTPUT_DIR, run_id, "final-report.json")
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def start_pipeline_async(mode="full", generate_pdf_after=False, pipeline_kind="in_place"):
    global _active_run
    async with _lock:
        if _active_run["status"] == "running":
            return {"error": "Pipeline already running"}
        _active_run = {"status": "running", "results": None, "run_id": None,
                       "started": time.time(), "mode": mode,
                       "generate_pdf_after": generate_pdf_after}

    # Clear old progress steps
    _progress_steps.clear()
    _add_progress_step("pipeline", "Pipeline started", "IN_PROGRESS",
                        {"mode": mode, "kind": pipeline_kind})

    async def _run():
        global _active_run
        try:
            runner = "run_local_lift_and_shift.py" if pipeline_kind == "lift_and_shift" else "run_local_pipeline.py"
            cmd = [sys.executable, os.path.join(PROJECT_DIR, runner)]

            # Determine if live ECC connection is available
            conns = _load_connections()
            ecc_conf = conns.get("ecc") or {}
            has_ecc = bool(ecc_conf.get("ashost"))
            use_live = has_ecc and _ecc_passwd

            if use_live:
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
            else:
                if mode == "assess":
                    cmd.append("--assess-only")
                elif mode == "ecc_full":
                    cmd.extend(["--mode", "ecc_full"])

            _add_progress_step("extraction", "Starting ECC data extraction", "IN_PROGRESS")

            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            if use_live:
                env["M4H_ECC_PASSWD"] = _ecc_passwd

            # Stream stdout line-by-line for real-time progress
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_DIR, env=env)

            # Read stdout lines in real-time for progress updates
            async def _read_stdout():
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    # Parse pipeline output for meaningful progress steps
                    _parse_pipeline_output(text)

            async def _read_stderr():
                data = await proc.stderr.read()
                return data.decode("utf-8", errors="replace") if data else ""

            stderr_task = asyncio.create_task(_read_stderr())
            try:
                await asyncio.wait_for(_read_stdout(), timeout=600)
            except asyncio.TimeoutError:
                pass
            stderr_text = await stderr_task
            await asyncio.wait_for(proc.wait(), timeout=30)

            if proc.returncode != 0:
                err_msg = (stderr_text or "Unknown error").strip()[-500:]
                print(f"  [API] Pipeline subprocess failed (exit {proc.returncode}): {err_msg}")
                _add_progress_step("pipeline", f"Pipeline failed (exit {proc.returncode})", "ERROR",
                                   {"error": err_msg[:200]})

            _add_progress_step("extraction", "ECC data extraction completed", "SUCCESS")

            runs = list_runs()
            latest = runs[0] if runs else None

            # Generate PDF if requested
            pdf_generated = False
            if latest and generate_pdf_after:
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
                if latest:
                    _active_run = {"status": "completed", "run_id": latest["id"],
                                   "results": latest["results"], "mode": mode,
                                   "duration": time.time() - _active_run.get("started", time.time()),
                                   "pdf_generated": pdf_generated}
                    _add_progress_step("pipeline", "Pipeline completed successfully", "SUCCESS",
                                       {"run_id": latest["id"], "pdf_generated": pdf_generated},
                                       duration_ms=int(_active_run["duration"] * 1000))
                else:
                    err_msg = (stderr_text or "Pipeline produced no output").strip()[-500:]
                    _active_run = {"status": "failed", "error": f"Pipeline failed: {err_msg}", "results": None}
                    _add_progress_step("pipeline", "Pipeline failed — no output produced", "ERROR",
                                       {"error": err_msg[:200]})
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
    return {"status": "started", "mode": mode}


def _parse_pipeline_output(line):
    """Parse a line of pipeline stdout and emit meaningful progress steps."""
    low = line.lower()

    # Detect stage headers
    if "[stage " in low or "stage " in low and "/17]" in low:
        _add_progress_step("pipeline-stage", line.strip(" =\t"), "IN_PROGRESS")
    elif "phase " in low and (":" in line or "--" in line):
        _add_progress_step("pipeline-phase", line.strip(" =\t"), "IN_PROGRESS")
    # Detect completion markers
    elif any(kw in low for kw in ["complete", "finished", "done", "saved", "generated"]):
        _add_progress_step("pipeline-step", line.strip(), "SUCCESS")
    # Detect warnings
    elif any(kw in low for kw in ["warning", "caution", "deprecated"]):
        _add_progress_step("pipeline-step", line.strip(), "WARNING")
    # Detect errors
    elif any(kw in low for kw in ["error", "failed", "exception", "traceback"]):
        _add_progress_step("pipeline-step", line.strip(), "ERROR")
    # Detect scanning/analysis actions
    elif any(kw in low for kw in ["scanning", "analyzing", "extracting", "checking",
                                   "validating", "running", "processing", "loading",
                                   "reconcil", "migrat", "converting"]):
        _add_progress_step("pipeline-step", line.strip(), "IN_PROGRESS")
    # Detect section markers (lines with ">" prefix from pipeline)
    elif line.strip().startswith(">"):
        _add_progress_step("pipeline-section", line.strip().lstrip("> "), "IN_PROGRESS")
    # Status lines with checkmarks or bullet markers
    elif any(line.strip().startswith(m) for m in ["V ", "o ", "! ", "X "]):
        marker = line.strip()[0]
        status = {"V": "SUCCESS", "o": "IN_PROGRESS", "!": "WARNING", "X": "ERROR"}.get(marker, "IN_PROGRESS")
        _add_progress_step("pipeline-detail", line.strip()[2:].strip(), status)


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
    token = generate_jwt()
    return {"token": token, "expires_in": 86400, "type": "Bearer"}


# =============================================================================
# ROUTES - CONNECTIONS (authenticated)
# =============================================================================
@app.get("/api/connections", dependencies=[Depends(require_auth)])
async def get_connections():
    return _load_connections()


@app.post("/api/connections/ecc", dependencies=[Depends(require_auth)])
async def save_ecc_connection(body: ECCConnection):
    conns = _load_connections()
    conns["ecc"] = {"ashost": body.ashost, "sysnr": body.sysnr, "client": body.client,
                    "user": body.user, "saprouter": body.saprouter, "saved_at": datetime.now().isoformat()}
    _save_connections(conns)
    return {"status": "saved", "connection": conns["ecc"]}


@app.post("/api/connections/s4hana", dependencies=[Depends(require_auth)])
async def save_s4hana_connection(body: S4HANAConnection):
    conns = _load_connections()
    conns["s4hana"] = {"connection_type": body.connection_type, "ashost": body.ashost,
                       "sysnr": body.sysnr, "client": body.client, "user": body.user,
                       "api_url": body.api_url, "saprouter": body.saprouter,
                       "saved_at": datetime.now().isoformat()}
    _save_connections(conns)
    return {"status": "saved", "connection": conns["s4hana"]}


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
@app.post("/api/pipeline/lift-and-shift", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift():
    """Run the full 28-stage lift-and-shift pipeline (orchestration plane only).

    Every S/4 write goes through Migration Cockpit / LTMOM / IDoc inbound /
    CTS+/tp - we never call BAPIs against the target. See
    MIGRATE4HANA-LIFT-AND-SHIFT.md for the architecture charter."""
    return await start_pipeline_async(mode="full", pipeline_kind="lift_and_shift")


@app.post("/api/pipeline/lift-and-shift/assess", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_assess():
    """Phase 0 only - discovery, sizing, object routing. No writes."""
    return await start_pipeline_async(mode="assess", pipeline_kind="lift_and_shift")


@app.post("/api/pipeline/lift-and-shift/code", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_code():
    """Phases 0-2 only - up through code transport import + verify."""
    return await start_pipeline_async(mode="code", pipeline_kind="lift_and_shift")


@app.post("/api/pipeline/lift-and-shift/data", dependencies=[Depends(require_auth)])
async def pipeline_lift_and_shift_data():
    """Phases 0-5 - up through data load via MC/LTMOM/IDoc lanes."""
    return await start_pipeline_async(mode="data", pipeline_kind="lift_and_shift")


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
async def get_runs():
    return list_runs()

@app.get("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
async def get_run_by_id(run_id: str):
    if run_id == "latest":
        runs = list_runs()
        run_id = runs[0]["id"] if runs else None
    data = get_run(run_id) if run_id else None
    if data:
        return data
    raise HTTPException(status_code=404, detail="Run not found")

@app.get("/api/runs/{run_id}/pdf", dependencies=[Depends(require_auth)])
async def get_run_pdf(run_id: str):
    if run_id == "latest":
        runs = list_runs()
        run_id = runs[0]["id"] if runs else None
    if not run_id:
        raise HTTPException(status_code=404, detail="No runs found")
    pdf_path = generate_pdf_for_run(run_id)
    if pdf_path and os.path.isfile(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf",
                            filename=f"migration-report-{run_id}.pdf")
    raise HTTPException(status_code=404, detail="Report not available for this run")


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
