"""
target-provisioner — Phase 1, Stage 4
======================================
Stand up a brand-new S/4HANA system on AWS for the lift-and-shift.

Production path: AWS Launch Wizard for SAP (preferred) — submits a
deployment via the Launch Wizard API and waits for completion.

Sandbox path: provision EC2 + EBS via Terraform output, then drive
unattended SWPM via SSM Run Command with a customer-supplied parameter
file.

Production-grade install of HANA System Replication, ASCS/ERS clusters,
backups, SAP Host Agent etc. is OUT OF SCOPE for this Lambda — the
Basis-handover gate (Stage 5) is where Basis takes over.
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
launchwizard = boto3.client("launch-wizard") if "launch-wizard" in boto3.Session().get_available_services() else None

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    cfg = event.get("target_config", {})
    mode = cfg.get("mode", "sandbox")  # sandbox | launch_wizard | basis_handover_only

    log_stage_event(run_id, "target-provisioner", "started", {"mode": mode})

    try:
        if mode == "launch_wizard":
            result = _provision_via_launch_wizard(cfg, run_id)
        elif mode == "sandbox":
            result = _provision_via_swpm(cfg, run_id)
        elif mode == "basis_handover_only":
            result = {"deployment_id": "external", "note": "Basis owns this install; Lambda will only validate."}
        else:
            raise ValueError(f"unknown target-provisioner mode: {mode}")

        manifest_key = f"runs/{run_id}/target-provisioner/manifest.json"
        s3.put_object(Bucket=STAGING_BUCKET, Key=manifest_key,
                      Body=json.dumps(result, default=str).encode())

        log_stage_event(run_id, "target-provisioner", "completed", {"mode": mode})
        return {"status": "success", "mode": mode, "manifest": f"s3://{STAGING_BUCKET}/{manifest_key}", **result}

    except Exception as e:
        logger.exception("target-provisioner failed")
        log_stage_event(run_id, "target-provisioner", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _provision_via_launch_wizard(cfg: dict, run_id: str) -> dict:
    if launchwizard is None:
        raise RuntimeError("Launch Wizard service not available in this region")
    resp = launchwizard.create_deployment(
        deploymentPatternName=cfg.get("pattern", "SapHanaSingle"),
        name=f"m4h-{run_id}",
        workloadName="SAP",
        specifications=cfg.get("specifications", {}),
    )
    return {"deployment_id": resp.get("deploymentId"), "method": "launch_wizard"}


def _provision_via_swpm(cfg: dict, run_id: str) -> dict:
    """Sandbox-only: drive SWPM unattended via SSM."""
    instance_id = cfg["bastion_instance_id"]
    swpm_dir = cfg.get("swpm_dir", "/sapmnt/swpm")
    inifile_s3 = cfg["inifile_s3"]
    cmds = [
        f"aws s3 cp {inifile_s3} /tmp/inifile.params",
        f"cd {swpm_dir} && ./sapinst SAPINST_INPUT_PARAMETERS_URL=/tmp/inifile.params SAPINST_EXECUTE_PRODUCT_ID=NW_ABAP_OneHost:S4HANA2023.CORE.HDB.PD SAPINST_SKIP_DIALOGS=true 2>&1 | tee /tmp/sapinst.log",
    ]
    res = ssm_run(instance_id, cmds, comment=f"swpm-{run_id}", timeout_seconds=14400)
    return {"deployment_id": res.get("command_id"), "method": "swpm",
            "ssm_status": res.get("status"), "stdout_tail": (res.get("stdout") or "")[-2000:]}
