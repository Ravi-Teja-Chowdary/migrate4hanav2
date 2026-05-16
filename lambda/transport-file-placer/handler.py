"""
transport-file-placer
======================
Copies cofile + datafile from S3 to the TARGET system's /usr/sap/trans/
directories via SSM. Filesystem operation — no SAP-data write.
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


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")

    # If the upstream artifact-builder ran in manual mode (no transport
    # actually created — typical for systems without RFC-enabled TR APIs),
    # there is nothing to place. Surface the manual gate cleanly.
    upstream = event.get("stage8") or event.get("transport_artifact") or {}
    if (event.get("mode") == "manual_assembly_required"
            or upstream.get("mode") == "manual_assembly_required"
            or "transport_id" not in event):
        log_stage_event(run_id, "transport-placer", "completed",
                        {"mode": "manual_assembly_required"})
        return {"status": "manual_required", "mode": "manual_assembly_required",
                "reason": "Upstream stage emitted a manual manifest; no cofile/datafile to place."}

    tr_id = event["transport_id"]
    cofile_s3 = event["cofile_s3"]
    datafile_s3 = event["datafile_s3"]
    target_bastion = event["target_bastion_instance_id"]
    target_sid = event["target_sid"]

    log_stage_event(run_id, "transport-placer", "started", {"transport_id": tr_id})

    try:
        sidadm = target_sid.lower() + "adm"
        cmds = [
            f"aws s3 cp {cofile_s3} /usr/sap/trans/cofiles/K{tr_id[-5:]}.{target_sid}",
            f"aws s3 cp {datafile_s3} /usr/sap/trans/data/R{tr_id[-5:]}.{target_sid}",
            f"chown {sidadm}:sapsys /usr/sap/trans/cofiles/K{tr_id[-5:]}.{target_sid} || true",
            f"chown {sidadm}:sapsys /usr/sap/trans/data/R{tr_id[-5:]}.{target_sid} || true",
            f"chmod 660 /usr/sap/trans/cofiles/K{tr_id[-5:]}.{target_sid} /usr/sap/trans/data/R{tr_id[-5:]}.{target_sid}",
        ]
        res = ssm_run(target_bastion, cmds, comment=f"place-{tr_id}", timeout_seconds=300)

        ok = res.get("status") == "Success"
        log_stage_event(run_id, "transport-placer",
                        "completed" if ok else "failed",
                        {"transport_id": tr_id, "ssm_status": res.get("status")})
        return {"status": "success" if ok else "failed",
                "transport_id": tr_id, "ssm_status": res.get("status"),
                "stderr": (res.get("stderr") or "")[:1000]}

    except Exception as e:
        logger.exception("transport-placer failed")
        log_stage_event(run_id, "transport-placer", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}
