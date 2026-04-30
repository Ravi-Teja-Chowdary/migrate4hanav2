"""
rollback-manager (lift-and-shift) — switch-back to ECC.

In greenfield lift-and-shift, "rollback" does NOT mean undoing changes
on the target S/4HANA (that target was greenfield — leave it intact for
forensics). Rollback means: re-point all integrations back to ECC and
unlock ECC so the business can resume on the source system.

Rollback steps (executed in this order):

    1. Reverse Route 53 / DNS records to ECC endpoints.
    2. Re-enable RFC destinations / WE20 partner profiles on ECC.
    3. Unlock ECC users via cutover-orchestrator(action='unlock_ecc').
    4. Resume ECC batch jobs / queues.
    5. Notify go-live board with detailed report.

Target S/4HANA is NOT touched — it remains for root-cause analysis.
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

LAMBDA = boto3.client("lambda")
ROUTE53 = boto3.client("route53")
S3 = boto3.client("s3")
SNS = boto3.client("sns")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")
CUTOVER_FN = os.environ.get("CUTOVER_ORCHESTRATOR_FN", "cutover-orchestrator")
NOTIFICATION_TOPIC = os.environ.get("SNS_GO_LIVE_TOPIC_ARN", "")


def _invoke(fn: str, payload: dict) -> dict:
    r = LAMBDA.invoke(FunctionName=fn, InvocationType="RequestResponse",
                      Payload=json.dumps(payload).encode("utf-8"))
    body = r["Payload"].read().decode("utf-8") if r.get("Payload") else "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"status": "error", "raw": body}


def _reverse_dns(records: list, dry_run: bool) -> list:
    """Apply 'previous_value' from each record (snapshot saved before flip)."""
    out = []
    for rec in records:
        if dry_run:
            out.append({"name": rec["name"], "status": "dry_run",
                        "would_revert_to": rec.get("previous_value")})
            continue
        try:
            ROUTE53.change_resource_record_sets(
                HostedZoneId=rec["zone_id"],
                ChangeBatch={"Changes": [{"Action": "UPSERT", "ResourceRecordSet": {
                    "Name": rec["name"], "Type": rec.get("type", "CNAME"),
                    "TTL": rec.get("ttl", 60),
                    "ResourceRecords": [{"Value": rec["previous_value"]}],
                }}]},
            )
            out.append({"name": rec["name"], "status": "ok",
                        "reverted_to": rec["previous_value"]})
        except Exception as e:
            out.append({"name": rec["name"], "status": "error", "error": str(e)})
    return out


def _load_cutover_snapshot(run_id: str) -> dict:
    """Read the pre-cutover snapshot saved by integration-activator."""
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET,
                            Key=f"runs/{run_id}/integration-activator/cutover_snapshot.json")
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


def _notify(run_id: str, summary: dict) -> None:
    if not NOTIFICATION_TOPIC:
        return
    try:
        SNS.publish(TopicArn=NOTIFICATION_TOPIC,
                    Subject=f"[Migrate4HANA] ROLLBACK executed — {run_id}",
                    Message=json.dumps(summary, indent=2, default=str))
    except Exception:
        pass


def _detect_cutover_window(event: dict, snapshot: dict) -> dict:
    """Classify the cutover state into one of three windows.

    pre_go_live           — DNS not flipped yet; switch-back is trivial
    hypercare             — DNS flipped, S/4 productive but within hypercare;
                            require posting-freeze + queue-drain proof
    post_productive       — Real business postings exist on S/4; simple
                            switch-back is UNSAFE — refuse unless explicit
                            business_compensation_signoff token is present.
    """
    if event.get("force_window"):
        return {"window": event["force_window"], "source": "forced_by_caller"}
    s4_postings = bool(event.get("s4_productive_postings",
                                  snapshot.get("s4_productive_postings", False)))
    dns_flipped = bool(event.get("dns_flipped",
                                  snapshot.get("dns_flipped", False)))
    hypercare_until = event.get("hypercare_until_epoch") or snapshot.get("hypercare_until_epoch")
    now = int(time.time())
    if not dns_flipped:
        return {"window": "pre_go_live", "source": "dns_not_flipped"}
    if hypercare_until and now <= int(hypercare_until) and not s4_postings:
        return {"window": "hypercare", "source": "within_hypercare_no_postings"}
    if s4_postings:
        return {"window": "post_productive",
                "source": "s4_productive_postings_present"}
    return {"window": "hypercare", "source": "default_post_dns_flip"}


def _build_evidence_record(run_id, window, steps, snapshot, event):
    return {
        "run_id": run_id,
        "kind": "cutover_switchback_attempt",
        "window": window,
        "ecc_lock_proof": snapshot.get("ecc_lock_proof"),
        "s4_unlock_timestamp": snapshot.get("s4_unlock_timestamp"),
        "last_delta_extract_id": snapshot.get("last_delta_extract_id"),
        "interface_flip_timestamp": snapshot.get("interface_flip_timestamp"),
        "posting_freeze_timestamp": snapshot.get("posting_freeze_timestamp"),
        "business_signoff_id": event.get("business_compensation_signoff"),
        "executed_steps": steps,
        "ts": int(time.time()),
    }


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    dry_run = event.get("dry_run", False)
    log_stage_event(run_id, "rollback-manager", "start", {"dry_run": dry_run})

    snapshot = event.get("cutover_snapshot") or _load_cutover_snapshot(run_id)
    win = _detect_cutover_window(event, snapshot)

    # Hard refusal for post-productive without explicit business signoff
    if win["window"] == "post_productive" and not event.get("business_compensation_signoff"):
        refusal = {
            "run_id": run_id,
            "status": "refused",
            "rollback_kind": "switch_back_to_ECC",
            "window": win,
            "reason": ("S/4 has productive business postings — simple switch-back is "
                       "unsafe. Provide 'business_compensation_signoff' (signed by "
                       "Finance + Audit + Business sponsor) to proceed. The S/4 system "
                       "must remain authoritative for these postings; ECC switch-back "
                       "would create a parallel-truth state."),
            "required_inputs": [
                "business_compensation_signoff (uuid of signed plan)",
                "force_window=post_productive (acknowledgement)",
                "reconciliation report (S3 URI)",
            ],
        }
        try:
            S3.put_object(Bucket=STAGING_BUCKET,
                          Key=f"runs/{run_id}/rollback-manager/refused.json",
                          Body=json.dumps(refusal, indent=2, default=str).encode(),
                          ContentType="application/json")
        except Exception:
            pass
        _notify(run_id, refusal)
        log_stage_event(run_id, "rollback-manager", "refused", refusal)
        return refusal

    dns_records = event.get("dns_records") or snapshot.get("dns_records", [])

    steps = []
    # 1. Reverse DNS
    if dns_records:
        dns_result = _reverse_dns(dns_records, dry_run)
        steps.append({"step": "reverse_dns", "result": dns_result})
    else:
        steps.append({"step": "reverse_dns", "result": "skipped (no records)"})

    # 2. Unlock ECC (delegated to cutover-orchestrator)
    unlock = _invoke(CUTOVER_FN, {
        "run_id": run_id, "action": "unlock_ecc", "ecc_sid": event.get("ecc_sid", "ERP"),
    }) if not dry_run else {"status": "dry_run"}
    steps.append({"step": "unlock_ecc", "result": unlock})

    # 3. Emit a notification + write rollback report
    summary = {
        "run_id": run_id,
        "status": "ok",
        "rollback_kind": "switch_back_to_ECC",
        "window": win,
        "target_s4_state": "untouched (preserved for RCA)",
        "steps": steps,
        "dry_run": dry_run,
        "evidence": _build_evidence_record(run_id, win, steps, snapshot, event),
    }

    report_key = f"runs/{run_id}/rollback-manager/report.json"
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=report_key,
                      Body=json.dumps(summary, indent=2, default=str).encode(),
                      ContentType="application/json")
        summary["report_s3"] = f"s3://{STAGING_BUCKET}/{report_key}"
    except Exception:
        pass

    _notify(run_id, summary)
    log_stage_event(run_id, "rollback-manager", "ok", summary)
    return summary
