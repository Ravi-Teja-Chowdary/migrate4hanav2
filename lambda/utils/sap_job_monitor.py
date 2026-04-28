"""
sap_job_monitor — poll SM37 for SAP background job completion and
collect job logs. Used by transport-import-executor, MC orchestrator,
LTMOM orchestrator.

Pattern extracted from sum-orchestrator's job-watch loop.
"""
import logging
import time

logger = logging.getLogger(__name__)


def watch(rfc_conn, jobname: str, jobcount: str = "",
          poll_interval_s: int = 30, timeout_s: int = 14400) -> dict:
    """Poll BP_JOB_STATUS_GET / RFC equivalent until job finishes.

    Returns: {status, runtime_s, log_lines, job_log_id}
    Status values: F=Finished, A=Aborted, R=Running (timeout)
    """
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        try:
            res = rfc_conn.call(
                "BAPI_XBP_JOB_STATUS_GET",
                JOBNAME=jobname,
                JOBCOUNT=jobcount,
                EXTERNAL_USER_NAME="MIGRATE4HANA",
            )
            status = res.get("STATUS", "?")
            last_status = status
            if status in ("F", "A", "X"):
                # collect joblog
                log = rfc_conn.call(
                    "BAPI_XBP_JOB_JOBLOG_READ",
                    JOBNAME=jobname,
                    JOBCOUNT=jobcount,
                    EXTERNAL_USER_NAME="MIGRATE4HANA",
                )
                return {
                    "status": status,
                    "runtime_s": int(time.time()),
                    "log_lines": log.get("JOBLOG_TBL", []),
                    "joblog_id": log.get("JOBLOG_ID", ""),
                }
        except Exception as e:
            logger.warning("job-status poll failed: %s", e)
        time.sleep(poll_interval_s)
    return {"status": "R", "runtime_s": timeout_s, "last_seen": last_status}
