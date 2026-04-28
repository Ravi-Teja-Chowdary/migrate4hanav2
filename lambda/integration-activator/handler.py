"""
integration-activator (lift-and-shift) — customizing-transport + AWS-side flip.

Splits cleanly along the two-plane line:

    SAP plane  (writes via transport):
        SM59 RFC destinations, WE20 partner profiles, WE21 ports, BD64 model
        views, PI/PO channels — all packed into a customizing transport on
        the BUILD system and shipped through CTS+. We never call
        RFC_MODIFY_R3_DESTINATION / IDOC_PORT_CREATE / EDI_PARTNER_*.

    AWS plane  (cutover-only):
        DNS flip, Route 53 weighted records, ALB target group switch,
        SQS / EventBridge / API Gateway endpoint repointing.
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
S3 = boto3.client("s3")
ROUTE53 = boto3.client("route53")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

ARTIFACT_BUILDER_FN = os.environ.get("TRANSPORT_ARTIFACT_BUILDER_FN", "transport-artifact-builder")
FILE_PLACER_FN     = os.environ.get("TRANSPORT_FILE_PLACER_FN",     "transport-file-placer")
IMPORT_EXEC_FN     = os.environ.get("TRANSPORT_IMPORT_EXECUTOR_FN", "transport-import-executor")
IMPORT_VERIFY_FN   = os.environ.get("TRANSPORT_IMPORT_VERIFIER_FN", "transport-import-verifier")


def _invoke(fn: str, payload: dict) -> dict:
    r = LAMBDA.invoke(FunctionName=fn, InvocationType="RequestResponse",
                      Payload=json.dumps(payload).encode("utf-8"))
    body = r["Payload"].read().decode("utf-8") if r.get("Payload") else "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"status": "error", "raw": body}


def _flip_route53(records: list, dry_run: bool) -> list:
    """Update DNS A/CNAME records to repoint integrations to S/4HANA."""
    out = []
    for rec in records:
        zone_id = rec["zone_id"]; name = rec["name"]; new_value = rec["new_value"]
        rec_type = rec.get("type", "CNAME"); ttl = rec.get("ttl", 60)
        if dry_run:
            out.append({"name": name, "status": "dry_run"})
            continue
        try:
            ROUTE53.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={"Changes": [{"Action": "UPSERT", "ResourceRecordSet": {
                    "Name": name, "Type": rec_type, "TTL": ttl,
                    "ResourceRecords": [{"Value": new_value}],
                }}]},
            )
            out.append({"name": name, "status": "ok", "new_value": new_value})
        except Exception as e:
            out.append({"name": name, "status": "error", "error": str(e)})
    return out


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    mode = event.get("mode", "transport_build")  # transport_build | dns_flip
    log_stage_event(run_id, "integration-activator", "start", {"mode": mode})

    if mode == "dns_flip":
        records = event.get("dns_records", [])
        dry = event.get("dry_run", False)
        results = _flip_route53(records, dry)
        ok = sum(1 for r in results if r["status"] == "ok")
        summary = {"run_id": run_id, "status": "ok" if ok == len(results) else "partial",
                   "dns_records": results}
        log_stage_event(run_id, "integration-activator", summary["status"], summary)
        return summary

    # transport_build: pack SM59/WE20/WE21/BD64 into a customizing transport
    integration_objects = event.get("integration_objects") or [
        {"object": "RFCD", "obj_name": d} for d in event.get("rfc_destinations", [])
    ] + [
        {"object": "EDPP", "obj_name": p} for p in event.get("partner_profiles", [])
    ] + [
        {"object": "EDIP", "obj_name": p} for p in event.get("idoc_ports", [])
    ]

    if not integration_objects:
        log_stage_event(run_id, "integration-activator", "skipped", {"reason": "no objects"})
        return {"status": "skipped", "reason": "no integration objects to ship", "run_id": run_id}

    build = _invoke(ARTIFACT_BUILDER_FN, {"run_id": run_id, "object_kind": "config",
                                             "objects": integration_objects})
    transport = build.get("transport_request") or build.get("trkorr")
    place = _invoke(FILE_PLACER_FN, {"run_id": run_id, "transport_request": transport,
                                       "cofile_s3": build.get("cofile_s3"),
                                       "datafile_s3": build.get("datafile_s3")})
    imp = _invoke(IMPORT_EXEC_FN, {"run_id": run_id, "transport_request": transport})
    verify = _invoke(IMPORT_VERIFY_FN, {"run_id": run_id, "transport_request": transport})

    summary = {
        "run_id": run_id,
        "status": "ok" if imp.get("rc", 99) <= 4 else "warning",
        "transport_request": transport,
        "import_rc": imp.get("rc"),
        "objects_shipped": len(integration_objects),
        "next_step": "Run again with mode='dns_flip' at cutover.",
    }
    log_stage_event(run_id, "integration-activator", summary["status"], summary)
    return summary
