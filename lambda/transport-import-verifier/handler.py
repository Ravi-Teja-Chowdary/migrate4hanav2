"""
transport-import-verifier
==========================
Reads tp/TMS import logs, scores RC, captures inactive objects.
Pure read-only.
"""
import json
import logging
import os
import sys
import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore
from sap_host_runner import run as ssm_run  # type: ignore

logger = logging.getLogger()
logger.setLevel(logging.INFO)
s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    tr_id = event["transport_id"]
    bastion = event["target_bastion_instance_id"]

    log_stage_event(run_id, "transport-verifier", "started", {"transport_id": tr_id})

    try:
        cmds = [
            "cat /usr/sap/trans/log/SLOG*.LOG 2>/dev/null | tail -500 || true",
            "cat /usr/sap/trans/log/ALOG*.LOG 2>/dev/null | tail -500 || true",
            f"ls -la /usr/sap/trans/log/ 2>/dev/null | grep -E '{tr_id[-5:]}' || true",
        ]
        res = ssm_run(bastion, cmds, comment=f"verify-{tr_id}", timeout_seconds=120)
        stdout = res.get("stdout", "")

        rc = _scan_rc(stdout, tr_id)
        warnings = _scan_warnings(stdout)
        inactive = _scan_inactive(stdout)

        log_key = f"runs/{run_id}/transports/{tr_id}/import.log"
        s3.put_object(Bucket=STAGING_BUCKET, Key=log_key, Body=stdout.encode())

        verdict = "success" if rc in (0, 4) and not inactive else \
                  "warnings" if rc == 4 else "failed"

        result = {"transport_id": tr_id, "verdict": verdict,
                  "tp_return_code": rc, "warnings": warnings[:50],
                  "inactive_objects": inactive[:50],
                  "log_s3": f"s3://{STAGING_BUCKET}/{log_key}"}
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/transports/{tr_id}/verification.json",
                      Body=json.dumps(result, default=str).encode())

        log_stage_event(run_id, "transport-verifier", verdict, {"transport_id": tr_id, "rc": rc})
        return {"status": verdict, **result}

    except Exception as e:
        logger.exception("transport-verifier failed")
        log_stage_event(run_id, "transport-verifier", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _scan_rc(stdout, tr_id):
    rc = 0
    for line in stdout.splitlines():
        if tr_id[-5:] in line and "return code" in line.lower():
            try:
                rc = max(rc, int(line.split()[-1]))
            except Exception:
                pass
    return rc


def _scan_warnings(stdout):
    return [l for l in stdout.splitlines() if "WARNING" in l.upper() or "RC=4" in l][:200]


def _scan_inactive(stdout):
    return [l for l in stdout.splitlines() if "INACTIVE" in l.upper() or "SYNTAX ERROR" in l.upper()][:200]
