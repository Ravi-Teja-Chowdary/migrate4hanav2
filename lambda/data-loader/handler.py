"""
data-loader (lift-and-shift) — pure orchestrator.

In the lift-and-shift / two-plane architecture this handler does NOT
write into S/4HANA itself. It receives the routed DAG from
``object-router`` and dispatches each migration object to its
configured lane (MC / LTMOM / IDoc / BODS / Transport).

The old in-place version (BAPI_ACC_DOCUMENT_POST, BAPI_BUPA_*, etc.)
is preserved at ``lambda/_deprecated/originals/data-loader/`` for
reference but must NEVER be invoked from the lift-and-shift pipeline.
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
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

LANE_TO_LAMBDA = {
    "MC":       os.environ.get("MC_ORCHESTRATOR_FN", "migration-cockpit-orchestrator"),
    "LTMOM":    os.environ.get("LTMOM_ORCHESTRATOR_FN", "ltmom-orchestrator"),
    "IDOC":     os.environ.get("IDOC_ORCHESTRATOR_FN", "idoc-orchestrator"),
}


def _invoke(fn_name: str, payload: dict) -> dict:
    resp = LAMBDA.invoke(
        FunctionName=fn_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = resp["Payload"].read().decode("utf-8") if resp.get("Payload") else "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"status": "error", "raw": body}


def _dispatch_one(obj: dict, run_id: str) -> dict:
    lane = (obj.get("lane") or "").upper()
    fn = LANE_TO_LAMBDA.get(lane)
    if fn is None:
        return {
            "object": obj.get("object"),
            "lane": lane,
            "status": "manual_gate",
            "reason": f"Lane '{lane}' has no automated orchestrator (BODS/manual).",
        }
    payload = {"run_id": run_id, "object_spec": obj}
    result = _invoke(fn, payload)
    result["object"] = obj.get("object")
    result["lane"] = lane
    return result


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    dag = (event.get("routing") or {}).get("dag") or event.get("dag") or []
    if not dag:
        log_stage_event(run_id, "data-loader", "blocked", {"reason": "no DAG from object-router"})
        return {"status": "blocked", "reason": "object-router DAG missing", "run_id": run_id}

    log_stage_event(run_id, "data-loader", "start", {"object_count": len(dag)})

    results = []
    counts = {"ok": 0, "error": 0, "manual_gate": 0, "skipped": 0}
    for obj in dag:
        if obj.get("manual_gate") is True:
            counts["manual_gate"] += 1
            results.append({"object": obj.get("object"), "status": "manual_gate", "lane": obj.get("lane")})
            continue
        r = _dispatch_one(obj, run_id)
        s = r.get("status", "error")
        counts[s] = counts.get(s, 0) + 1
        results.append(r)

    summary = {
        "run_id": run_id,
        "status": "ok" if counts["error"] == 0 else "partial",
        "counts": counts,
        "results_count": len(results),
    }

    key = f"runs/{run_id}/data-loader/results.json"
    try:
        S3.put_object(
            Bucket=STAGING_BUCKET, Key=key,
            Body=json.dumps({"summary": summary, "results": results}, default=str).encode(),
            ContentType="application/json",
        )
        summary["s3_uri"] = f"s3://{STAGING_BUCKET}/{key}"
    except Exception as e:
        summary["s3_error"] = str(e)

    log_stage_event(run_id, "data-loader", summary["status"], counts)
    return summary
