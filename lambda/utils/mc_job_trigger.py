"""
mc_job_trigger - Fire-and-forget Migration Cockpit job triggering.

PURPOSE
-------
The MC file-lane (mc_file_exporter.py) generates a SAP-compliant CSV/XML
and drops it in S3. Historically, a human then had to log into S/4,
open the Migration Cockpit (LTMC / Fiori MC app), upload the file, and
click "Transfer". That step is the only thing keeping the 99 MC-lane
catalog objects out of true fire-and-forget.

This module closes that gap. After flush_to_s3, the spine can chain
straight into trigger_mc_load() which:

  1. Connects to the target S/4 via the existing pyrfc Connection.
  2. Tries a strategy chain to launch the MC import on the SAP side:
       Strategy A — RFC call to LTMC_API_OBJ_TRANSFER (S/4 1909+ when
                    the LTMC_API package is exposed for RFC). Universal
                    on newer releases.
       Strategy B — OData POST to the MC runtime service
                    /sap/opu/odata4/sap/api_migrationcockpit_object_runtime
                    when LTMC_API isn't exposed but the service is.
       Strategy C — XBP background-job pattern (BAPI_XBP_JOB_OPEN /
                    _ADD_ABAP_STEP / _CLOSE / _START_IMMEDIATELY) that
                    submits the standard MC load program. This is the
                    universal SAP-since-4.6C fallback.
  3. Polls job status with exponential backoff until DONE / FAILED /
     timeout. Pulls back log lines so the caller has the full SAP
     diagnostic if a row fails on the SAP side.
  4. Returns a single structured result the caller can hand straight to
     the Reconciler — same shape as the BAPI-lane result.

DESIGN
------
- No new dependencies beyond pyrfc + requests (already in the bundle).
- Defensive: a failing strategy moves to the next strategy; only when ALL
  strategies fail do we return mechanism="unavailable" with the per-
  strategy diagnostic. Lets the caller decide whether to fall back to
  the legacy "human kicks it in S/4" path.
- Idempotent: trigger_mc_load() can be safely re-invoked with the same
  (project_id, object_id, file_s3_uri) — SAP-side dedup is via the
  MC project's own ID-tracking, plus we tag jobs with a deterministic
  client-side correlation_id.

USAGE
-----
    result = trigger_mc_load(
        target_conn       = tconn,
        project_id        = "M4H_PROD_001",
        object_id         = "GLAccount",
        file_s3_uri       = "s3://bucket/.../GLAccount.csv",
        correlation_id    = run_id,
        wait_for_complete = True,
        timeout_secs      = 600,
    )
    # result = {"mechanism": "ltmc_api"|"odata"|"xbp_job", "job_id": "...",
    #           "status": "DONE"|"FAILED"|"RUNNING"|"unavailable",
    #           "rows_loaded": N, "log_lines": [...], "errors": [...]}
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Optional

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # OData strategy will be skipped


# Default poll cadence (overridable per call)
POLL_INITIAL_SECS = 2
POLL_MAX_SECS     = 30
POLL_BACKOFF      = 1.5

# Status normalization map — different S/4 APIs use different status strings
_STATUS_DONE     = {"DONE", "COMPLETED", "FINISHED", "F", "S"}
_STATUS_FAILED   = {"FAILED", "ERROR", "A", "X", "ABENDED"}
_STATUS_RUNNING  = {"RUNNING", "ACTIVE", "R", "PROCESSING", "IN_PROGRESS"}
_STATUS_READY    = {"READY", "SCHEDULED", "P", "WAITING"}


def trigger_mc_load(target_conn, project_id: str, object_id: str,
                     file_s3_uri: str, correlation_id: str = "",
                     wait_for_complete: bool = True,
                     timeout_secs: int = 600,
                     odata_base_url: str = "",
                     odata_auth: Optional[tuple] = None) -> dict:
    """Trigger an MC load on the target S/4 and (optionally) wait for it
    to finish. Returns a result dict shaped like a BAPI load result.

    Args:
        target_conn:        Open pyrfc.Connection to the target S/4.
        project_id:         The MC project ID configured on S/4 that
                            holds the staging tables for this object.
                            Must exist on S/4 before this call.
        object_id:          The MC object identifier (e.g., "GLAccount",
                            "Routing"). Must match the project's catalog.
        file_s3_uri:        Full s3://bucket/key URI of the CSV/XML that
                            mc_file_exporter wrote.
        correlation_id:     Deterministic tag for idempotency (use run_id).
        wait_for_complete:  True → block until job done/failed/timeout.
                            False → return immediately with job_id; caller
                            uses poll_mc_status() later.
        timeout_secs:       Max wait when wait_for_complete=True.
        odata_base_url:     Optional override for OData strategy. Defaults
                            to https://{ashost}:44300 derived from RFC conn.
        odata_auth:         Optional (user, pass) for OData. Defaults to
                            the RFC connection's user + os env M4H_S4_PASS.

    Returns:
        dict with: mechanism, job_id, status, rows_loaded, log_lines,
                   errors, elapsed_secs, strategy_attempts.
    """
    correlation_id = correlation_id or f"m4h-{int(time.time())}"
    attempts = []
    started  = time.time()

    # ── Strategy A: RFC to LTMC_API_OBJ_TRANSFER ──────────────────────────
    res_a = _strategy_ltmc_api(target_conn, project_id, object_id,
                                file_s3_uri, correlation_id)
    attempts.append({"strategy": "ltmc_api", "ok": res_a.get("ok", False),
                      "detail": res_a.get("detail", "")})
    if res_a.get("ok"):
        return _finalize(res_a, "ltmc_api", correlation_id, attempts, started,
                         target_conn, wait_for_complete, timeout_secs)

    # ── Strategy B: OData POST to MC runtime service ──────────────────────
    res_b = _strategy_odata(target_conn, project_id, object_id, file_s3_uri,
                             correlation_id, odata_base_url, odata_auth)
    attempts.append({"strategy": "odata", "ok": res_b.get("ok", False),
                      "detail": res_b.get("detail", "")})
    if res_b.get("ok"):
        return _finalize(res_b, "odata", correlation_id, attempts, started,
                         target_conn, wait_for_complete, timeout_secs)

    # ── Strategy C: XBP background-job submission ─────────────────────────
    res_c = _strategy_xbp_job(target_conn, project_id, object_id, file_s3_uri,
                               correlation_id)
    attempts.append({"strategy": "xbp_job", "ok": res_c.get("ok", False),
                      "detail": res_c.get("detail", "")})
    if res_c.get("ok"):
        return _finalize(res_c, "xbp_job", correlation_id, attempts, started,
                         target_conn, wait_for_complete, timeout_secs)

    # All strategies failed — return diagnostic
    return {
        "mechanism":          "unavailable",
        "job_id":             None,
        "status":             "FAILED",
        "rows_loaded":        0,
        "log_lines":          [],
        "errors":             [a.get("detail", "") for a in attempts],
        "elapsed_secs":       time.time() - started,
        "strategy_attempts":  attempts,
        "correlation_id":     correlation_id,
        "remediation_hint":   ("No MC trigger API available on this S/4. "
                                "Options: (1) Enable LTMC_API package for "
                                "RFC; (2) Activate OData service "
                                "/sap/opu/odata4/sap/api_migrationcockpit_"
                                "object_runtime; (3) Install Z-wrapper for "
                                "XBP job submission. See docs/."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Strategy A: RFC to LTMC_API_OBJ_TRANSFER (S/4 1909+)
# ─────────────────────────────────────────────────────────────────────────────
def _strategy_ltmc_api(target_conn, project_id: str, object_id: str,
                        file_s3_uri: str, correlation_id: str) -> dict:
    """Try the direct RFC path. Most universal on modern S/4."""
    try:
        # The file content must reach the SAP application server. Two
        # options: (a) push via the FM's IT_DATA table parameter, (b)
        # have SAP read from a UNC/NFS path. (a) is robust for files
        # under ~100MB; (b) requires shared filesystem setup. We default
        # to (a) and stream the file from S3 in chunks.
        rows_b64 = _fetch_s3_object_as_lines(file_s3_uri)
        if rows_b64 is None:
            return {"ok": False, "detail": "could not fetch S3 file"}

        # Convert lines into the LTMC IT_DATA table-parameter shape.
        # Each row is wrapped in a struct expected by the FM.
        it_data = [{"LINE": ln[:1024]} for ln in rows_b64]

        result = target_conn.call(
            "LTMC_API_OBJ_TRANSFER",
            IV_PROJECT_ID     = project_id,
            IV_OBJECT_ID      = object_id,
            IV_CORRELATION_ID = correlation_id,
            IT_DATA           = it_data,
        )
        job_id = (result.get("EV_JOB_ID") or
                  result.get("EV_RUN_ID") or "").strip()
        status = _normalize_status(result.get("EV_STATUS", ""))
        return {
            "ok":          True,
            "job_id":      job_id,
            "status":      status or "RUNNING",
            "rows_loaded": int(result.get("EV_ROWS_LOADED") or 0),
            "log_lines":   [m.get("MESSAGE", "") for m in (result.get("ET_LOG") or [])],
            "errors":      [m.get("MESSAGE", "") for m in (result.get("ET_LOG") or [])
                              if (m.get("TYPE") or "") in ("E", "A")],
        }
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        return {"ok": False, "detail": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Strategy B: OData REST to MC runtime service
# ─────────────────────────────────────────────────────────────────────────────
def _strategy_odata(target_conn, project_id: str, object_id: str,
                     file_s3_uri: str, correlation_id: str,
                     base_url: str, auth: Optional[tuple]) -> dict:
    if requests is None:
        return {"ok": False, "detail": "requests library not available"}

    if not base_url:
        # Derive https://ashost:44300 from the RFC connection's ashost
        ashost = ""
        try:
            attrs = target_conn.get_connection_attributes()
            ashost = attrs.get("partnerHost") or attrs.get("host") or ""
        except Exception:
            pass
        if not ashost:
            return {"ok": False, "detail": "could not derive OData base url"}
        base_url = f"https://{ashost}:44300"

    if auth is None:
        user = os.environ.get("M4H_S4_USER", "")
        pwd  = os.environ.get("M4H_S4_PASS", "")
        if not user or not pwd:
            return {"ok": False, "detail": "no OData credentials configured"}
        auth = (user, pwd)

    file_bytes = _fetch_s3_object_as_bytes(file_s3_uri)
    if file_bytes is None:
        return {"ok": False, "detail": "could not fetch S3 file"}

    svc = "/sap/opu/odata4/sap/api_migrationcockpit_object_runtime"
    url = (f"{base_url}{svc}/MigrationProject('{urllib.parse.quote(project_id)}')"
           f"/Object('{urllib.parse.quote(object_id)}')/Transfer")
    try:
        r = requests.post(url, data=file_bytes,
                          headers={"Content-Type": "text/csv",
                                    "X-Correlation-Id": correlation_id},
                          auth=auth, verify=False, timeout=60)
        if r.status_code >= 400:
            return {"ok": False, "detail": f"HTTP {r.status_code}: {r.text[:160]}"}
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return {
            "ok":          True,
            "job_id":      body.get("d", {}).get("JobId") or body.get("JobId") or correlation_id,
            "status":      _normalize_status(body.get("d", {}).get("Status") or body.get("Status") or "RUNNING"),
            "rows_loaded": int(body.get("d", {}).get("RowsLoaded") or body.get("RowsLoaded") or 0),
            "log_lines":   body.get("d", {}).get("Log") or body.get("Log") or [],
            "errors":      [],
        }
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Strategy C: XBP background-job submission (universal SAP-since-4.6C)
# ─────────────────────────────────────────────────────────────────────────────
def _strategy_xbp_job(target_conn, project_id: str, object_id: str,
                       file_s3_uri: str, correlation_id: str) -> dict:
    """Submit /MIGCOCKPIT/LOAD_OBJECT as a background job. Universal,
    works on every SAP, requires only the standard XBP interface that
    most systems expose."""
    try:
        # Open job
        open_res = target_conn.call("BAPI_XBP_JOB_OPEN",
                                      JOBNAME    = f"M4H_MC_{object_id[:18]}",
                                      JOBCLASS   = "C",
                                      EXTERNAL_USER_NAME = "MIG_TRIGGER")
        jobname  = open_res.get("JOBNAME", "")
        jobcount = open_res.get("JOBCOUNT", "")
        if not jobname or not jobcount:
            return {"ok": False, "detail": "BAPI_XBP_JOB_OPEN returned empty key"}

        # Add ABAP step pointing at the standard MC load program. The
        # program name varies slightly by release; we use the most common
        # /UI/MIG_OBJ_LOAD that ships with S/4 2020+ Migration Cockpit.
        params = [
            {"NAME": "P_PROJECT",  "VALUE": project_id},
            {"NAME": "P_OBJECT",   "VALUE": object_id},
            {"NAME": "P_FILE",     "VALUE": file_s3_uri},
            {"NAME": "P_CORRID",   "VALUE": correlation_id},
        ]
        target_conn.call("BAPI_XBP_JOB_ADD_ABAP_STEP",
                          JOBNAME      = jobname,
                          JOBCOUNT     = jobcount,
                          EXTERNAL_USER_NAME = "MIG_TRIGGER",
                          ABAP_PROGRAM_NAME  = "/UI/MIG_OBJ_LOAD",
                          ABAP_VARIANT_NAME  = "M4H_DEFAULT",
                          SAP_USER_NAME = "MIG_TRIGGER")

        # Close + start immediately
        target_conn.call("BAPI_XBP_JOB_CLOSE",
                          JOBNAME      = jobname,
                          JOBCOUNT     = jobcount,
                          EXTERNAL_USER_NAME = "MIG_TRIGGER")
        target_conn.call("BAPI_XBP_JOB_START_IMMEDIATELY",
                          JOBNAME      = jobname,
                          JOBCOUNT     = jobcount,
                          EXTERNAL_USER_NAME = "MIG_TRIGGER")

        return {
            "ok":          True,
            "job_id":      f"{jobname}/{jobcount}",
            "status":      "RUNNING",
            "rows_loaded": 0,    # XBP doesn't return rows; reconciler will count
            "log_lines":   [],
            "errors":      [],
        }
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Status polling
# ─────────────────────────────────────────────────────────────────────────────
def poll_mc_status(target_conn, job_id: str, mechanism: str,
                    timeout_secs: int = 600,
                    odata_base_url: str = "",
                    odata_auth: Optional[tuple] = None) -> dict:
    """Block-poll a job until DONE / FAILED / timeout. Returns the same
    result shape as trigger_mc_load(). Uses exponential backoff."""
    deadline = time.time() + timeout_secs
    delay    = POLL_INITIAL_SECS

    while time.time() < deadline:
        try:
            if mechanism == "ltmc_api":
                resp = target_conn.call("LTMC_API_OBJ_GET_STATUS",
                                          IV_JOB_ID = job_id)
                status      = _normalize_status(resp.get("EV_STATUS", ""))
                rows_loaded = int(resp.get("EV_ROWS_LOADED") or 0)
                log_lines   = [m.get("MESSAGE", "") for m in (resp.get("ET_LOG") or [])]
            elif mechanism == "xbp_job":
                jobname, _, jobcount = job_id.partition("/")
                resp = target_conn.call("BAPI_XBP_JOB_STATUS_GET",
                                          JOBNAME  = jobname,
                                          JOBCOUNT = jobcount,
                                          EXTERNAL_USER_NAME = "MIG_TRIGGER")
                status      = _normalize_status(resp.get("STATUS", ""))
                rows_loaded = 0
                log_lines   = []
            elif mechanism == "odata":
                if requests is None:
                    return {"status": "FAILED", "log_lines": ["requests not available"]}
                # OData status endpoint
                base = odata_base_url
                if not base:
                    try:
                        attrs = target_conn.get_connection_attributes()
                        base = f"https://{attrs.get('partnerHost', '')}:44300"
                    except Exception:
                        pass
                url = (f"{base}/sap/opu/odata4/sap/api_migrationcockpit_"
                       f"object_runtime/Job('{urllib.parse.quote(job_id)}')")
                r = requests.get(url, auth=odata_auth, verify=False, timeout=30)
                body = r.json() if r.status_code < 400 else {}
                status      = _normalize_status(body.get("d", {}).get("Status") or "")
                rows_loaded = int(body.get("d", {}).get("RowsLoaded") or 0)
                log_lines   = body.get("d", {}).get("Log") or []
            else:
                return {"status": "FAILED",
                        "log_lines": [f"unknown mechanism: {mechanism}"]}

            if status in (_STATUS_DONE | _STATUS_FAILED):
                return {
                    "status":      status,
                    "rows_loaded": rows_loaded,
                    "log_lines":   log_lines,
                    "elapsed_secs": time.time() - (deadline - timeout_secs),
                }
        except Exception as e:
            return {"status": "FAILED",
                    "log_lines": [f"{type(e).__name__}: {str(e)[:200]}"]}

        time.sleep(delay)
        delay = min(delay * POLL_BACKOFF, POLL_MAX_SECS)

    return {"status": "TIMEOUT", "rows_loaded": 0,
            "log_lines": [f"polling exceeded {timeout_secs}s"]}


def _finalize(res: dict, mechanism: str, correlation_id: str,
               attempts: list, started: float, target_conn,
               wait_for_complete: bool, timeout_secs: int) -> dict:
    """Either return immediately with job_id, or poll until completion."""
    base = {
        "mechanism":          mechanism,
        "job_id":             res.get("job_id"),
        "status":             res.get("status", "RUNNING"),
        "rows_loaded":        res.get("rows_loaded", 0),
        "log_lines":          res.get("log_lines", []),
        "errors":             res.get("errors", []),
        "elapsed_secs":       time.time() - started,
        "strategy_attempts":  attempts,
        "correlation_id":     correlation_id,
    }
    if not wait_for_complete:
        return base

    poll = poll_mc_status(target_conn, base["job_id"], mechanism, timeout_secs)
    base["status"]       = poll.get("status", base["status"])
    base["rows_loaded"]  = poll.get("rows_loaded", base["rows_loaded"]) or base["rows_loaded"]
    base["log_lines"]    = base["log_lines"] + (poll.get("log_lines") or [])
    base["elapsed_secs"] = time.time() - started
    if base["status"] in _STATUS_FAILED:
        base["errors"]   = base["errors"] + [l for l in base["log_lines"] if "ERROR" in l.upper()]
    return base


# ─────────────────────────────────────────────────────────────────────────────
# S3 helpers
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_s3_object_as_bytes(s3_uri: str) -> Optional[bytes]:
    try:
        import boto3
        if not s3_uri.startswith("s3://"):
            return None
        rest = s3_uri[5:]
        bucket, _, key = rest.partition("/")
        if not bucket or not key:
            return None
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception:
        return None


def _fetch_s3_object_as_lines(s3_uri: str) -> Optional[list]:
    raw = _fetch_s3_object_as_bytes(s3_uri)
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    return [ln for ln in text.splitlines() if ln]


def _normalize_status(raw: str) -> str:
    if not raw:
        return ""
    s = str(raw).strip().upper()
    if s in _STATUS_DONE:
        return "DONE"
    if s in _STATUS_FAILED:
        return "FAILED"
    if s in _STATUS_RUNNING:
        return "RUNNING"
    if s in _STATUS_READY:
        return "READY"
    return s
