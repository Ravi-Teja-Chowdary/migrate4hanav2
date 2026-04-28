"""
transport-import-executor
==========================
Imports a transport into the target via tp (SSM), TMS RFC, or manual gate.
This is the ONE supported path where we trigger an SAP-shipped tool to
mutate the target — and that tool IS `tp`, which is the canonical SAP
Transport Tool. Zero custom RFC writes.
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
    method = event.get("import_method", "tp_ssm")
    target_sid = event["target_sid"]
    target_client = event.get("target_client", "100")

    log_stage_event(run_id, "transport-executor", "started",
                    {"transport_id": tr_id, "method": method})

    try:
        if method == "tp_ssm":
            res = _tp_ssm(event, tr_id, target_sid, target_client)
        elif method == "tms_rfc":
            res = _tms_rfc(event, tr_id, target_sid, target_client)
        elif method == "manual":
            res = {"status": "manual_gate",
                   "instruction": f"STMS_QUEUE → import {tr_id} into {target_sid}/{target_client}"}
        else:
            raise ValueError(f"unknown import_method: {method}")

        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/transports/{tr_id}/import-result.json",
                      Body=json.dumps(res, default=str).encode())
        log_stage_event(run_id, "transport-executor", res.get("status", "unknown"),
                        {"transport_id": tr_id})
        return res

    except Exception as e:
        logger.exception("transport-executor failed")
        log_stage_event(run_id, "transport-executor", "failed", {"error": str(e)})
        return {"status": "failed", "transport_id": tr_id, "error": str(e)}


def _tp_ssm(event, tr_id, sid, client) -> dict:
    bastion = event["target_bastion_instance_id"]
    sidadm = sid.lower() + "adm"
    pf = f"/usr/sap/trans/bin/TP_DOMAIN_{sid}.PFL"
    cmds = [
        f"su - {sidadm} -c 'tp addtobuffer {tr_id} {sid} pf={pf}'",
        f"su - {sidadm} -c 'tp import {tr_id} {sid} client={client} U16 pf={pf} 2>&1'",
    ]
    res = ssm_run(bastion, cmds, comment=f"tp-import-{tr_id}", timeout_seconds=3600)
    rc = _extract_tp_rc(res.get("stdout", ""))
    return {"status": "success" if rc in (0, 4) else "failed",
            "transport_id": tr_id, "method": "tp_ssm",
            "tp_return_code": rc, "ssm_status": res.get("status"),
            "stdout_tail": (res.get("stdout") or "")[-3000:],
            "stderr_tail": (res.get("stderr") or "")[-1000:]}


def _tms_rfc(event, tr_id, sid, client) -> dict:
    return {"status": "manual_gate", "method": "tms_rfc",
            "note": "TMS RFC path requires TMS domain config — not auto-orchestrated in v1"}


def _extract_tp_rc(stdout: str) -> int:
    rc = 0
    for line in stdout.splitlines():
        if "return code" in line.lower():
            try:
                rc = max(rc, int(line.split()[-1]))
            except Exception:
                pass
    return rc
