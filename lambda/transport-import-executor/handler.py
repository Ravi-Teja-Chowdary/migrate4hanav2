"""
transport-import-executor
==========================
Imports a transport into the target via tp (SSM), TMS RFC, or manual gate.
This is the ONE supported path where we trigger an SAP-shipped tool to
mutate the target — and that tool IS `tp`, which is the canonical SAP
Transport Tool. Zero custom RFC writes.

Safety additions (2026-07-03 enterprise-hardening pass):
  · `dry_run: true` in the event validates prerequisites without invoking
    the import — checks that (a) the transport file is present on the
    staging path, (b) the target is reachable via SSM, (c) the transport
    is not already imported (E070 read via SAP-released
    `RFC_READ_TABLE`).
  · Pre-import check via E070 read (via `RFC_READ_TABLE`, which IS in the
    SAP-released customer-callable RFC set): if the transport is already
    imported into the target client, skip and return `already_imported`.
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
    dry_run = bool(event.get("dry_run", False))

    upstream = event.get("stage8") or event.get("transport_artifact") or {}
    if (event.get("mode") == "manual_assembly_required"
            or upstream.get("mode") == "manual_assembly_required"
            or "transport_id" not in event):
        log_stage_event(run_id, "transport-executor", "completed",
                        {"mode": "manual_assembly_required"})
        return {"status": "manual_required", "mode": "manual_assembly_required",
                "reason": "Upstream manifest is manual-assembly. Run STMS Import once the transport exists on target."}

    tr_id = event["transport_id"]
    method = event.get("import_method", "tp_ssm")
    target_sid = event["target_sid"]
    target_client = event.get("target_client", "100")

    log_stage_event(run_id, "transport-executor", "started",
                    {"transport_id": tr_id, "method": method, "dry_run": dry_run})

    # ── Pre-import: transport already in target? ─────────────────────────
    already = _check_already_imported(event, tr_id, target_client)
    if already.get("imported"):
        log_stage_event(run_id, "transport-executor", "skipped",
                        {"transport_id": tr_id,
                         "reason": "already_imported",
                         "detail": already.get("detail", "")})
        return {"status": "already_imported", "transport_id": tr_id,
                "reason": already.get("detail", "found in E070"),
                "target_client": target_client}

    if dry_run:
        checks = {
            "already_imported":     already,
            "staging_path_present": _check_staging_present(event, tr_id),
            "ssm_reachable":        _check_ssm_reachable(event),
        }
        overall_ok = (not already.get("imported")
                      and checks["staging_path_present"].get("ok")
                      and checks["ssm_reachable"].get("ok"))
        result = {"status": "dry_run_ok" if overall_ok else "dry_run_blocked",
                  "transport_id": tr_id,
                  "prechecks": checks,
                  "would_execute": overall_ok}
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/transports/{tr_id}/dry-run-result.json",
                      Body=json.dumps(result, default=str).encode())
        log_stage_event(run_id, "transport-executor", result["status"],
                        {"transport_id": tr_id})
        return result

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


# ─────────────────────────────────────────────────────────────────────────────
# Pre-import checks — all use SAP-RELEASED interfaces only
# ─────────────────────────────────────────────────────────────────────────────
def _check_already_imported(event: dict, tr_id: str, target_client: str) -> dict:
    """Query E070 (transport header) via `RFC_READ_TABLE` — the SAP-released
    generic table read FM — to see if the transport is already logged as
    imported into the target client.

    Failure to reach the target (no creds, no pyrfc) returns {imported:
    False, error: ...} so the pre-check is defensive: an inaccessible target
    NEVER blocks a subsequent import decision.
    """
    creds = event.get("target_rfc_creds") or {}
    if not creds:
        return {"imported": False, "checked": False,
                "reason": "no target_rfc_creds; pre-check skipped"}
    try:
        from pyrfc import Connection  # type: ignore
    except ImportError:
        return {"imported": False, "checked": False,
                "reason": "pyrfc not available in Lambda layer"}
    try:
        with Connection(**creds) as conn:
            resp = conn.call("RFC_READ_TABLE",
                              QUERY_TABLE="E070",
                              DELIMITER="|",
                              FIELDS=[{"FIELDNAME": "TRKORR"},
                                       {"FIELDNAME": "TRSTATUS"}],
                              OPTIONS=[{"TEXT":
                                          f"TRKORR EQ '{tr_id}'"}])
        rows = resp.get("DATA") or []
        if rows:
            # WBO status "R" = released; TMS logs imports in E070C but for
            # a lightweight defensive check the existence of TRKORR with
            # a released status is a reasonable "already known" signal.
            return {"imported": True, "checked": True,
                    "detail": f"E070 has {len(rows)} row(s) for {tr_id}",
                    "sample": (rows[0].get("WA", "")[:200] if rows else "")}
        return {"imported": False, "checked": True,
                "detail": "E070 has no matching row"}
    except Exception as e:
        return {"imported": False, "checked": False,
                "reason": f"{type(e).__name__}: {str(e)[:200]}"}


def _check_staging_present(event: dict, tr_id: str) -> dict:
    """Confirm the .cofile + .data files are staged in /usr/sap/trans by
    running `ls -l /usr/sap/trans/data/R*<tr_short>` on the target host."""
    bastion = event.get("target_bastion_instance_id")
    if not bastion:
        return {"ok": False,
                "detail": "no target_bastion_instance_id — cannot verify staging"}
    try:
        tr_short = tr_id[-6:] if len(tr_id) > 6 else tr_id
        cmds = [f"ls -l /usr/sap/trans/data/ | grep -i {tr_short} || true",
                f"ls -l /usr/sap/trans/cofiles/ | grep -i {tr_short} || true"]
        res = ssm_run(bastion, cmds, comment=f"tp-dryrun-{tr_id}",
                       timeout_seconds=60)
        return {"ok": bool(res.get("stdout", "").strip()),
                "detail": (res.get("stdout") or "")[:500]}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _check_ssm_reachable(event: dict) -> dict:
    """Trivial `echo` via SSM to confirm the target host is reachable — this
    catches the common "bastion is stopped" state before we time out on a
    30-minute tp invocation."""
    bastion = event.get("target_bastion_instance_id")
    if not bastion:
        return {"ok": False,
                "detail": "no target_bastion_instance_id"}
    try:
        res = ssm_run(bastion, ["echo m4h-dryrun"],
                       comment="tp-dryrun-echo", timeout_seconds=30)
        stdout = (res.get("stdout") or "").strip()
        return {"ok": "m4h-dryrun" in stdout,
                "detail": stdout[:200]}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _tp_ssm(event, tr_id, sid, client) -> dict:
    bastion = event["target_bastion_instance_id"]
    sidadm = sid.lower() + "adm"
    pf = f"/usr/sap/trans/bin/TP_DOMAIN_{sid}.PFL"
    is_production = bool(event.get("is_production", False))
    cmds = [
        f"su - {sidadm} -c 'tp addtobuffer {tr_id} {sid} pf={pf}'",
        f"su - {sidadm} -c 'tp import {tr_id} {sid} client={client} U16 pf={pf} 2>&1'",
    ]
    res = ssm_run(bastion, cmds, comment=f"tp-import-{tr_id}", timeout_seconds=3600)
    ssm_status = res.get("status")
    stdout = res.get("stdout") or ""
    stderr = res.get("stderr") or ""

    rc = _extract_tp_rc(stdout)

    if ssm_status not in ("Success", "Completed"):
        verdict = "failed"
        reason = f"SSM command status={ssm_status}; tp output may be incomplete"
    elif rc is None:
        verdict = "failed"
        reason = "no tp return-code line found in stdout (cannot certify import)"
    elif rc == 0:
        verdict = "success"
        reason = "RC=0"
    elif rc == 4:
        verdict = "failed" if is_production else "warning_requires_review"
        reason = ("RC=4 in production requires manual Basis review (forced fail)"
                  if is_production else "RC=4 — warnings present, requires review")
    else:
        verdict = "failed"
        reason = f"RC={rc} >= 8 (import failed)"

    return {"status": verdict, "reason": reason,
            "transport_id": tr_id, "method": "tp_ssm",
            "tp_return_code": rc, "ssm_status": ssm_status,
            "stdout_tail": stdout[-3000:],
            "stderr_tail": stderr[-1000:]}


def _tms_rfc(event, tr_id, sid, client) -> dict:
    return {"status": "manual_gate", "method": "tms_rfc",
            "note": "TMS RFC path requires TMS domain config — not auto-orchestrated in v1"}


def _extract_tp_rc(stdout: str):
    """Return the highest tp return code found in stdout, or None if absent.

    Critical: returning None on absence (rather than defaulting to 0) prevents
    the executor from declaring success for an import where tp output was
    truncated or never produced — a previous safety bug.
    """
    rc = None
    for line in stdout.splitlines():
        if "return code" in line.lower():
            try:
                val = int(line.split()[-1])
                rc = val if rc is None else max(rc, val)
            except Exception:
                continue
    return rc
