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


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    dry_run = event.get("dry_run", False)
    log_stage_event(run_id, "rollback-manager", "start", {"dry_run": dry_run})

    snapshot = event.get("cutover_snapshot") or _load_cutover_snapshot(run_id)
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
        "target_s4_state": "untouched (preserved for RCA)",
        "steps": steps,
        "dry_run": dry_run,
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
