"""
basis-validator — Phase 1, Stage 5
===================================
Validate that the newly stood-up S/4HANA target is ready for downstream
phases. Runs after Basis-handover gate. See sap_prereq_checks for the
check list.
"""
import json
import logging
import os
import sys
import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore
from sap_prereq_checks import check_target  # type: ignore

try:
    import sapnwrfc  # noqa: F401
except Exception:
    pass
try:
    from pyrfc import Connection
except ImportError:
    Connection = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets = boto3.client("secretsmanager")
s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    target_creds_arn = event.get("target_creds_arn") or os.environ.get("TARGET_SECRETS_ARN")

    log_stage_event(run_id, "basis-validator", "started", {})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=target_creds_arn)["SecretString"])
        if Connection is None:
            raise RuntimeError("pyrfc not available")
        conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"], client=creds["client"],
                          user=creds["user"], passwd=creds["passwd"])
        report = check_target(conn)

        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/basis-validator/report.json",
                      Body=json.dumps(report, default=str).encode())

        log_stage_event(run_id, "basis-validator", "completed",
                        {"ready": report["ready"], "check_count": len(report["checks"])})
        return {"status": "success" if report["ready"] else "blocked",
                "ready": report["ready"], "checks": report["checks"]}

    except Exception as e:
        logger.exception("basis-validator failed")
        log_stage_event(run_id, "basis-validator", "failed", {"error": str(e)})
        return {"status": "failed", "ready": False, "error": str(e)}
