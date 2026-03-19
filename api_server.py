"""
Migrate4HANA — API Server
==========================
HTTP API for the migration platform.
Handles SAP connections, pipeline execution, and PDF report generation.

Usage:
    python api_server.py

Starts on port 8000. The Vite dev server proxies /api/* here.

Authentication:
    All endpoints except GET /api/health require a valid JWT Bearer token.
    Generate a token:   python api_server.py --generate-token
    Set the secret:     M4H_JWT_SECRET environment variable (auto-generated if unset)
    Set API key:        M4H_API_KEY environment variable (alternative to JWT)

    Header:  Authorization: Bearer <token>
         or  X-API-Key: <api_key>
"""

import http.server
import json
import os
import sys
import threading
import time
import hashlib
import hmac
import base64
import secrets
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_DIR, "test-output")
CONNECTIONS_FILE = os.path.join(PROJECT_DIR, "connections.json")

# Shared state for active runs
_active_run = {"status": "idle", "results": None, "run_id": None}
_lock = threading.Lock()

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
    print(f"  [Auth] Generated JWT secret → .jwt_secret (keep this file secure)")


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


def verify_jwt(token: str) -> dict | None:
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


def authenticate_request(handler) -> bool:
    """
    Check Authorization header for a valid JWT Bearer token or API key.
    Returns True if authenticated, False otherwise.
    """
    path = handler.path.split("?")[0].rstrip("/")
    if path in _PUBLIC_PATHS:
        return True

    # Check Bearer token
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if verify_jwt(token):
            return True

    # Check query-string token (for links opened in new tabs, e.g. PDF downloads)
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(handler.path).query)
    qs_token = qs.get("token", [None])[0]
    if qs_token and verify_jwt(qs_token):
        return True

    # Check API key
    api_key = handler.headers.get("X-API-Key", "")
    if _API_KEY and hmac.compare_digest(api_key, _API_KEY):
        return True

    return False


# =============================================================================
# CONNECTION MANAGEMENT
# =============================================================================
def _load_connections():
    """Load saved connections from disk."""
    if os.path.isfile(CONNECTIONS_FILE):
        with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ecc": None, "s4hana": None}


def _save_connections(data):
    """Save connections to disk."""
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def test_ecc_connection(params):
    """Test SAP ECC RFC connection."""
    host = params.get("ashost", "")
    sysnr = params.get("sysnr", "")
    client = params.get("client", "")
    user = params.get("user", "")

    if not all([host, sysnr, client, user]):
        return {"status": "error", "message": "Missing required fields: ashost, sysnr, client, user"}

    # Try real PyRFC connection if available
    try:
        import pyrfc
        conn_params = {
            "ashost": host,
            "sysnr": sysnr,
            "client": client,
            "user": user,
            "passwd": params.get("passwd", ""),
        }
        if params.get("saprouter"):
            conn_params["saprouter"] = params["saprouter"]

        conn = pyrfc.Connection(**conn_params)
        result = conn.call("RFC_SYSTEM_INFO")
        sys_info = result.get("RFCSI_EXPORT", {})
        conn.close()

        return {
            "status": "connected",
            "system_id": sys_info.get("RFCSYSID", ""),
            "host": sys_info.get("RFCHOST", host),
            "db_system": sys_info.get("RFCDBSYS", ""),
            "sap_release": sys_info.get("RFCSAPRL", ""),
            "kernel": sys_info.get("RFCKERNRL", ""),
            "client": client,
            "message": f"Connected to {sys_info.get('RFCSYSID', host)} (ECC {sys_info.get('RFCSAPRL', '')})",
        }
    except ImportError:
        # PyRFC not installed — use mock mode
        return {
            "status": "mock",
            "system_id": "BIS",
            "host": host,
            "sap_release": "ECC 6.0 EHP8",
            "client": client,
            "message": f"PyRFC not installed — mock mode active. Connection to {host} will be simulated.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


def test_s4hana_connection(params):
    """Test S/4HANA target connection."""
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
            conn = pyrfc.Connection(
                ashost=host, sysnr=sysnr, client=client,
                user=user, passwd=params.get("passwd", ""),
            )
            result = conn.call("RFC_SYSTEM_INFO")
            sys_info = result.get("RFCSI_EXPORT", {})
            conn.close()

            return {
                "status": "connected",
                "system_id": sys_info.get("RFCSYSID", ""),
                "host": host,
                "sap_release": sys_info.get("RFCSAPRL", ""),
                "message": f"Connected to S/4HANA {sys_info.get('RFCSYSID', host)}",
            }
        except ImportError:
            return {
                "status": "mock",
                "system_id": "S4H",
                "host": host,
                "sap_release": "S/4HANA 2023 FPS02",
                "message": f"PyRFC not installed — mock mode. Target {host} will be simulated.",
            }
        except Exception as e:
            return {"status": "error", "message": f"Connection failed: {str(e)}"}

    elif conn_type == "odata":
        # OData / API-based connection for S/4HANA Cloud
        api_url = params.get("api_url", host)
        return {
            "status": "mock",
            "system_id": "S4HC",
            "host": api_url,
            "sap_release": "S/4HANA Cloud",
            "message": f"OData endpoint {api_url} registered. Will use Communication Arrangements in target.",
        }

    return {"status": "error", "message": f"Unknown connection type: {conn_type}"}


def list_runs():
    """List all completed pipeline runs."""
    runs = []
    if not os.path.isdir(OUTPUT_DIR):
        return runs
    for entry in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if entry.startswith("run_"):
            report_path = os.path.join(OUTPUT_DIR, entry, "final-report.json")
            if os.path.isfile(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                runs.append({
                    "id": entry,
                    "timestamp": entry.replace("run_", ""),
                    "has_execution": "cutover" in data,
                    "results": data,
                })
    return runs


def get_run(run_id):
    """Get a specific run's results."""
    report_path = os.path.join(OUTPUT_DIR, run_id, "final-report.json")
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def start_pipeline_async(mode="full"):
    """Start a pipeline run in a background thread.

    5-Phase SAP Activate pipeline modes:
        'assess'   - Phases 1-2 only (stages 1-8)
        'convert'  - Phase 3 only (stages 9-10), requires Phase 2 complete
        'complete' - Phases 4-5 (stages 11-17), requires Phase 3 complete
        'full'     - All 5 phases (stages 1-17)
    """
    global _active_run

    with _lock:
        if _active_run["status"] == "running":
            return {"error": "Pipeline already running"}

        # Validate prerequisites for phase-specific modes
        if mode == "convert":
            last_results = _active_run.get("results", {})
            if not last_results or not last_results.get("code_analysis"):
                return {"error": "Phase 2 must be completed before running Phase 3 (convert)"}
        elif mode == "complete":
            last_results = _active_run.get("results", {})
            if not last_results or not last_results.get("sum_dmo"):
                return {"error": "Phase 3 must be completed before running Phases 4-5 (complete)"}

        _active_run = {
            "status": "running", "results": None, "run_id": None,
            "started": time.time(), "mode": mode,
        }

    def _run():
        global _active_run
        try:
            import subprocess
            cmd = [sys.executable, os.path.join(PROJECT_DIR, "run_local_pipeline.py")]
            if mode == "assess":
                cmd.append("--assess-only")
            # For 'convert' and 'complete' modes, we run full pipeline
            # (the pipeline internally handles phase gating)
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=PROJECT_DIR, timeout=600,
                env=env,
            )
            if result.returncode != 0:
                err_msg = (result.stderr or result.stdout or "Unknown error").strip()[-500:]
                print(f"  [API] Pipeline subprocess failed (exit {result.returncode}): {err_msg}")
            # Find the latest run directory
            runs = list_runs()
            latest = runs[0] if runs else None
            with _lock:
                if latest:
                    _active_run = {
                        "status": "completed",
                        "run_id": latest["id"],
                        "results": latest["results"],
                        "mode": mode,
                        "duration": time.time() - _active_run.get("started", time.time()),
                    }
                else:
                    err_msg = (result.stderr or result.stdout or "Pipeline produced no output").strip()[-500:]
                    _active_run = {
                        "status": "failed",
                        "error": f"Pipeline failed: {err_msg}",
                        "results": None,
                    }
        except Exception as e:
            with _lock:
                _active_run = {"status": "failed", "error": str(e), "results": None}

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "mode": mode}


def generate_pdf_for_run(run_id):
    """Generate a PDF report for a given run, return the file path."""
    run_dir = os.path.join(OUTPUT_DIR, run_id)
    json_path = os.path.join(run_dir, "post-migration-report.json")
    pdf_path = os.path.join(run_dir, "post-migration-report.pdf")

    if os.path.isfile(pdf_path):
        return pdf_path

    if not os.path.isfile(json_path):
        # Try to build from final-report.json
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


class APIHandler(http.server.BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _require_auth(self):
        """Returns True if request is authenticated, sends 401 and returns False otherwise."""
        if authenticate_request(self):
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("WWW-Authenticate", 'Bearer realm="migrate4hana"')
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "error": "Authentication required",
            "hint": "Set Authorization: Bearer <jwt> or X-API-Key: <key>",
        }).encode())
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._require_auth():
            return
        path = self.path.rstrip("/")

        if path == "/api/health":
            self._json_response({
                "status": "ok", "version": "3.0", "stages": 17, "phases": 5,
                "pipeline": "SAP Activate 5-Phase",
                "phase_map": {
                    "1_prepare": "Stages 1-4: Assessment & Pre-Checks",
                    "2_explore": "Stages 5-8: Application Preparation",
                    "3_realize": "Stages 9-10: Technical System Conversion (SUM/DMO)",
                    "4_post_conversion": "Stages 11-14: Deploy, Configure & Validate",
                    "5_deploy_and_run": "Stages 15-17: Integration, Validation & Go-Live",
                },
            })

        elif path == "/api/connections":
            self._json_response(_load_connections())

        elif path == "/api/runs":
            self._json_response(list_runs())

        elif path.startswith("/api/runs/") and path.endswith("/pdf"):
            # Download PDF
            run_id = path.split("/api/runs/")[1].replace("/pdf", "")
            if run_id == "latest":
                runs = list_runs()
                run_id = runs[0]["id"] if runs else None
            if not run_id:
                self._json_response({"error": "No runs found"}, 404)
                return
            pdf_path = generate_pdf_for_run(run_id)
            if pdf_path and os.path.isfile(pdf_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="migration-report-{run_id}.pdf"')
                self._cors()
                self.end_headers()
                with open(pdf_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._json_response({"error": "Report not available for this run"}, 404)

        elif path.startswith("/api/runs/"):
            run_id = path.split("/api/runs/")[1]
            if run_id == "latest":
                runs = list_runs()
                run_id = runs[0]["id"] if runs else None
            data = get_run(run_id) if run_id else None
            if data:
                self._json_response(data)
            else:
                self._json_response({"error": "Run not found"}, 404)

        elif path == "/api/status":
            with _lock:
                self._json_response(_active_run)

        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._require_auth():
            return
        path = self.path.rstrip("/")
        body = self._read_body()

        if path == "/api/connections/ecc":
            conns = _load_connections()
            conns["ecc"] = {
                "ashost": body.get("ashost", ""),
                "sysnr": body.get("sysnr", "00"),
                "client": body.get("client", "100"),
                "user": body.get("user", ""),
                "saprouter": body.get("saprouter", ""),
                "saved_at": datetime.now().isoformat(),
            }
            _save_connections(conns)
            self._json_response({"status": "saved", "connection": conns["ecc"]})

        elif path == "/api/connections/s4hana":
            conns = _load_connections()
            conns["s4hana"] = {
                "connection_type": body.get("connection_type", "rfc"),
                "ashost": body.get("ashost", ""),
                "sysnr": body.get("sysnr", "00"),
                "client": body.get("client", "100"),
                "user": body.get("user", ""),
                "api_url": body.get("api_url", ""),
                "saprouter": body.get("saprouter", ""),
                "saved_at": datetime.now().isoformat(),
            }
            _save_connections(conns)
            self._json_response({"status": "saved", "connection": conns["s4hana"]})

        elif path == "/api/connections/ecc/test":
            result = test_ecc_connection(body)
            self._json_response(result)

        elif path == "/api/connections/s4hana/test":
            result = test_s4hana_connection(body)
            self._json_response(result)

        elif path in ("/api/pipeline/assess", "/api/start/assess"):
            # Phases 1-2 (stages 1-8)
            result = start_pipeline_async(mode="assess")
            self._json_response(result)

        elif path in ("/api/pipeline/convert", "/api/start/convert"):
            # Phase 3 (stages 9-10) — requires Phase 2 complete
            result = start_pipeline_async(mode="convert")
            self._json_response(result)

        elif path in ("/api/pipeline/complete", "/api/start/complete"):
            # Phases 4-5 (stages 11-17) — requires Phase 3 complete
            result = start_pipeline_async(mode="complete")
            self._json_response(result)

        elif path in ("/api/pipeline/full", "/api/start/full"):
            # All 5 phases (stages 1-17)
            result = start_pipeline_async(mode="full")
            self._json_response(result)

        elif path == "/api/auth/token":
            # Public endpoint — generate a JWT for local/dev usage
            token = generate_jwt()
            self._json_response({"token": token, "expires_in": 86400, "type": "Bearer"})

        elif path == "/api/pipeline/migrate":
            # Legacy endpoint — runs full pipeline
            result = start_pipeline_async(mode="full")
            self._json_response(result)

        elif path == "/api/run":
            # Legacy endpoint
            result = start_pipeline_async(mode="full")
            self._json_response(result)

        else:
            self._json_response({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print(f"  [API] {args[0]}")


def main():
    import sys as _sys

    _ensure_jwt_secret()

    # CLI: generate a token and exit
    if "--generate-token" in _sys.argv:
        token = generate_jwt()
        print(f"Bearer token (valid 24h):\n{token}")
        return

    port = 8000
    server = http.server.HTTPServer(("", port), APIHandler)
    print(f"\n  Migrate4HANA API Server")
    print(f"  {'='*25}")
    print(f"  Listening on http://localhost:{port}")
    print(f"  Auth: JWT Bearer token or X-API-Key header required")
    print(f"  Generate token: python api_server.py --generate-token")
    print(f"  Pipeline: 17-stage, 5-phase SAP Activate")
    print(f"  Endpoints:")
    print(f"    GET  /api/health             — Health check (public)")
    print(f"    GET  /api/connections         — Saved connections")
    print(f"    POST /api/connections/ecc     — Save ECC connection")
    print(f"    POST /api/connections/s4hana  — Save S/4HANA connection")
    print(f"    POST /api/connections/ecc/test    — Test ECC connection")
    print(f"    POST /api/connections/s4hana/test — Test S/4HANA connection")
    print(f"    POST /api/pipeline/assess     — Run Phases 1-2 (stages 1-8)")
    print(f"    POST /api/pipeline/convert    — Run Phase 3 (stages 9-10, requires Phase 2)")
    print(f"    POST /api/pipeline/complete   — Run Phases 4-5 (stages 11-17, requires Phase 3)")
    print(f"    POST /api/pipeline/full       — Run all 5 phases (stages 1-17)")
    print(f"    POST /api/pipeline/migrate    — Legacy: full migration")
    print(f"    GET  /api/status              — Pipeline status")
    print(f"    GET  /api/runs                — List all runs")
    print(f"    GET  /api/runs/ID             — Get run results")
    print(f"    GET  /api/runs/ID/pdf         — Download PDF report\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
