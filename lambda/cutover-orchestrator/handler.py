"""
cutover-orchestrator (lift-and-shift) — ECC-lock-first, then delta gate.

CRITICAL ORDERING (the original plan had this inverted):

    1. lock_ecc          - block end-user logons + set system message
    2. delta-extractor   - now safe to read final delta (no new writes coming)
    3. final delta load via MC
    4. final reconciliation
    5. integration flip (DNS / Route 53 / endpoints) - external trigger

This Lambda only does step 1 directly (the SAP-supported way: customer
admin runs SU10 / RZ04 / SM02 in scope; we expose it as a runbook +
optional SSM script gate). It hands the rest to the chain.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

try:
    from sap_host_runner import run_command  # type: ignore
except Exception:  # pragma: no cover
    run_command = None

S3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")


def _build_ecc_lock_runbook(run_id: str, ecc_sid: str) -> str:
    return (
        f"# ECC lock-down runbook — run_id={run_id}, SID={ecc_sid}\n\n"
        "1. Broadcast SM02 system message: 'Migration cutover in progress, "
        "system read-only as of <time>'.\n"
        "2. SU10 mass-lock all non-Basis users (exclude DDIC, SAP*, BASIS, "
        "and the migration service users).\n"
        "3. RZ04 disable batch-job operation modes for application servers.\n"
        "4. SMQR / SMQS deregister all queues to stop inbound IDoc/qRFC.\n"
        "5. SE16 -> TBTCO: cancel scheduled jobs that would create new data.\n"
        "6. Set RFC destinations from external systems to UNREACHABLE so "
        "they queue rather than write to ECC.\n"
        "7. Confirm zero new entries in CDHDR for the past 5 minutes "
        "before proceeding to delta extract.\n"
    )


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    action = event.get("action", "lock_ecc")
    log_stage_event(run_id, "cutover-orchestrator", "start", {"action": action})

    if action == "lock_ecc":
        ecc_sid = event.get("ecc_sid", "ERP")
        runbook = _build_ecc_lock_runbook(run_id, ecc_sid)
        rb_key = f"runs/{run_id}/cutover/ecc_lock_runbook.md"
        S3.put_object(Bucket=STAGING_BUCKET, Key=rb_key,
                      Body=runbook.encode(), ContentType="text/markdown")

        # Optional: if customer has authorized us to run SU10 mass-lock via
        # SSM script on ECC host, run it. Otherwise, manual_gate.
        if event.get("auto_lock") and run_command:
            instance_id = event.get("ecc_instance_id")
            cmd = event.get("lock_command",
                            "/usr/sap/scripts/m4h_mass_lock.sh")
            try:
                rc, out = run_command(instance_id, [cmd], timeout=120)
                ecc_locked = rc == 0
            except Exception as e:
                ecc_locked = False
                out = f"auto-lock failed: {e}"
        else:
            ecc_locked = bool(event.get("manual_lock_confirmed", False))
            out = "manual lock — set manual_lock_confirmed=true after running runbook"

        summary = {
            "run_id": run_id, "status": "ok" if ecc_locked else "manual_gate",
            "ecc_locked": ecc_locked, "runbook": f"s3://{STAGING_BUCKET}/{rb_key}",
            "detail": out,
            "next_stage_blocked_until": "ecc_locked == true",
        }
        log_stage_event(run_id, "cutover-orchestrator", summary["status"], summary)
        return summary

    if action == "unlock_ecc":
        # Used by rollback-manager to re-open ECC.
        return {"run_id": run_id, "status": "ok", "ecc_locked": False,
                "note": "Unlock instructions emitted; customer admin runs SU10 mass-unlock."}

    return {"run_id": run_id, "status": "error", "reason": f"unknown action '{action}'"}
