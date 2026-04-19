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
        return {"status": "mock", "system_id": "BIS", "host": host, "sap_release": "ECC 6.0 EHP8",
                "client": client, "message": f"PyRFC not installed - mock mode active. Connection to {host} will be simulated."}
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
            return {"status": "mock", "system_id": "S4H", "host": host, "sap_release": "S/4HANA 2023 FPS02",
                    "message": f"PyRFC not installed - mock mode. Target {host} will be simulated."}
        except Exception as e:
            return {"status": "error", "message": f"Connection failed: {str(e)}"}
    elif conn_type == "odata":
        api_url = params.get("api_url", host)
        return {"status": "mock", "system_id": "S4HC", "host": api_url, "sap_release": "S/4HANA Cloud",
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


async def start_pipeline_async(mode="full", generate_pdf_after=False):
    global _active_run
    async with _lock:
        if _active_run["status"] == "running":
            return {"error": "Pipeline already running"}
        if mode == "convert":
            last_results = _active_run.get("results", {})
            if not last_results or not last_results.get("code_analysis"):
                return {"error": "Phase 2 must be completed before running Phase 3 (convert)"}
        elif mode == "complete":
            last_results = _active_run.get("results", {})
            if not last_results or not last_results.get("sum_dmo"):
                return {"error": "Phase 3 must be completed before running Phases 4-5 (complete)"}
        _active_run = {"status": "running", "results": None, "run_id": None,
                       "started": time.time(), "mode": mode,
                       "generate_pdf_after": generate_pdf_after}

    # Clear old progress steps
    _progress_steps.clear()
    _add_progress_step("pipeline", "Pipeline started", "IN_PROGRESS", {"mode": mode})

    async def _run():
        global _active_run
        try:
            cmd = [sys.executable, os.path.join(PROJECT_DIR, "run_local_pipeline.py")]

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
                # Don't silently fall back to mock — tell the user to re-test.
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
                _add_progress_step("connection", "Using mock ECC data (no live connection)", "WARNING")

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
