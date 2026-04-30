"""
evidence-collector
==================
Immutable, hash-chained run-event ledger.

Every meaningful event in a migration run (stage start, stage end, gate
decision, transport import, MC run, IDoc receipt, reconciliation result,
switch-back attempt) is appended here.

Each event records a SHA-256 hash linking it to the previous event for
the same run_id, forming a tamper-evident chain. The latest event for
each run is also written WORM (S3 Object Lock COMPLIANCE) for audit.

Storage:
  - DynamoDB table  m4h-run-events  (PK=run_id, SK=seq)  with PITR + Streams
  - S3 evidence bucket (Object Lock enabled at bucket creation)

Inputs (event):
  run_id            (str, required)
  stage             (str, required)         e.g. "transport-import-executor"
  event_type        (str, required)         "started" | "completed" | "failed" | "gate" | "evidence"
  payload           (dict, required)        free-form, MUST be JSON-serialisable
  sap_log_refs      (dict, optional)        e.g. {"slg1_id": "...", "stms_log": "...", "sm37_job_id": "..."}
  actor             (str, optional)         for gate/approval events
  aws_request_id    (str, optional)

Returns:
  {seq, prev_hash, this_hash, s3_uri}
"""
from __future__ import annotations
import json
import hashlib
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

DDB = boto3.resource("dynamodb")
S3 = boto3.client("s3")

EVENTS_TABLE = os.environ.get("EVENTS_TABLE_NAME", "m4h-run-events-dev")
EVIDENCE_BUCKET = os.environ.get("S3_EVIDENCE_BUCKET", "migrate4hana-evidence-dev")
GENESIS_HASH = "0" * 64


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _last_event(table, run_id: str) -> dict:
    """Return the highest-seq event for run_id, or None."""
    resp = table.query(
        KeyConditionExpression="run_id = :r",
        ExpressionAttributeValues={":r": run_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items") or []
    return items[0] if items else None


def _next_seq(prev: dict) -> int:
    return (int(prev.get("seq", 0)) + 1) if prev else 1


def _serialise(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def lambda_handler(event, context):
    run_id = event["run_id"]
    stage = event["stage"]
    event_type = event["event_type"]
    payload = event.get("payload", {})

    table = DDB.Table(EVENTS_TABLE)
    prev = _last_event(table, run_id)
    seq = _next_seq(prev)
    prev_hash = (prev or {}).get("this_hash", GENESIS_HASH)

    record = {
        "run_id": run_id,
        "seq": seq,
        "ts": int(time.time()),
        "stage": stage,
        "event_type": event_type,
        "payload": payload,
        "sap_log_refs": event.get("sap_log_refs", {}),
        "actor": event.get("actor"),
        "aws_request_id": event.get("aws_request_id")
            or (context.aws_request_id if context else None),
        "prev_hash": prev_hash,
    }
    record["this_hash"] = _hash(_serialise(record))

    table.put_item(
        Item=record,
        ConditionExpression="attribute_not_exists(run_id) AND attribute_not_exists(seq)"
            if seq == 1 else None,
    ) if seq == 1 else table.put_item(Item=record)

    # WORM write to evidence bucket; Object Lock retention is set at bucket
    # level (COMPLIANCE mode). We rely on bucket default retention so the
    # Lambda execution role only needs s3:PutObject — not put-object-retention.
    s3_key = f"runs/{run_id}/events/{seq:08d}-{record['this_hash'][:12]}.json"
    body = _serialise(record)
    S3.put_object(
        Bucket=EVIDENCE_BUCKET,
        Key=s3_key,
        Body=body,
        ContentType="application/json",
        Metadata={"run-id": run_id, "seq": str(seq), "hash": record["this_hash"]},
    )

    log_stage_event(run_id, "evidence-collector", "appended",
                    {"seq": seq, "stage": stage, "event_type": event_type})

    return {
        "run_id": run_id,
        "seq": seq,
        "prev_hash": prev_hash,
        "this_hash": record["this_hash"],
        "s3_uri": f"s3://{EVIDENCE_BUCKET}/{s3_key}",
    }


def verify_chain(run_id: str) -> dict:
    """Walk the chain and verify every link. Returns {ok, broken_at, length}."""
    table = DDB.Table(EVENTS_TABLE)
    expected_prev = GENESIS_HASH
    seq = 0
    while True:
        seq += 1
        resp = table.get_item(Key={"run_id": run_id, "seq": seq})
        item = resp.get("Item")
        if not item:
            break
        if item["prev_hash"] != expected_prev:
            return {"ok": False, "broken_at": seq, "length": seq - 1,
                    "expected_prev": expected_prev, "got": item["prev_hash"]}
        recomputed = _hash(_serialise({k: v for k, v in item.items() if k != "this_hash"}))
        if recomputed != item["this_hash"]:
            return {"ok": False, "broken_at": seq, "length": seq - 1,
                    "reason": "this_hash mismatch (record was tampered)"}
        expected_prev = item["this_hash"]
    return {"ok": True, "length": seq - 1, "tip_hash": expected_prev}
