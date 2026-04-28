"""
Migrate4HANA - Manual-Gate Lambda
=================================

Step Functions states use the lambda:invoke.waitForTaskToken pattern when they
need a human approval. The state passes us a TaskToken; we persist the gate
metadata to DynamoDB (or S3 fallback) and return without calling
SendTaskSuccess. The token sits "in flight" until the operator clicks
Approve/Reject in the UI, which calls /api/gates/<gate_id>/approve and
hits states:SendTaskSuccess for us.

Persisted record shape:
  {
    gate_id:    "<sfn execution name>-<gate>",
    run_id:     execution name (from SFN context, if available),
    gate:       "basis_handover" | "pre_cutover" | "final_go_live" | "bods_lane",
    token:      <opaque SFN task token>,
    status:     "pending",
    input:      <copy of the upstream state input for context>,
    created_at: <iso8601>
  }
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

GATES_TABLE = os.environ.get("GATES_TABLE", "")
GATES_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")
GATES_TOPIC_ARN = os.environ.get("GATES_SNS_TOPIC_ARN", "")

_dynamo = boto3.client("dynamodb") if GATES_TABLE else None
_s3 = boto3.client("s3")
_sns = boto3.client("sns") if GATES_TOPIC_ARN else None


def _persist_dynamo(rec):
    _dynamo.put_item(
        TableName=GATES_TABLE,
        Item={
            "gate_id":    {"S": rec["gate_id"]},
            "run_id":     {"S": rec["run_id"]},
            "gate":       {"S": rec["gate"]},
            "token":      {"S": rec["token"]},
            "status":     {"S": rec["status"]},
            "input":      {"S": json.dumps(rec.get("input", {}))[:380000]},
            "created_at": {"S": rec["created_at"]},
        },
    )


def _persist_s3(rec):
    key = "gates/{run_id}/{gate}.json".format(run_id=rec["run_id"], gate=rec["gate"])
    _s3.put_object(
        Bucket=GATES_BUCKET,
        Key=key,
        Body=json.dumps(rec).encode("utf-8"),
        ContentType="application/json",
    )


def _notify(rec):
    if not _sns:
        return
    try:
        _sns.publish(
            TopicArn=GATES_TOPIC_ARN,
            Subject="[Migrate4HANA] Manual gate pending: {}".format(rec["gate"]),
            Message=json.dumps({
                "run_id": rec["run_id"],
                "gate":   rec["gate"],
                "gate_id": rec["gate_id"],
                "approve_endpoint": "POST /api/gates/{}/approve".format(rec["gate_id"]),
                "reject_endpoint":  "POST /api/gates/{}/reject".format(rec["gate_id"]),
            }, indent=2),
        )
    except ClientError:
        pass


def lambda_handler(event, context=None):
    """Receive a gate event from a Step Functions waitForTaskToken state."""
    gate = event.get("gate") or "unknown_gate"
    token = event.get("token") or ""
    input_payload = event.get("input") or {}

    run_id = (
        (input_payload.get("run_id") if isinstance(input_payload, dict) else None)
        or (input_payload.get("execution_id") if isinstance(input_payload, dict) else None)
        or "run-{}".format(int(time.time()))
    )
    gate_id = "{}__{}".format(run_id, gate)

    record = {
        "gate_id":    gate_id,
        "run_id":     run_id,
        "gate":       gate,
        "token":      token,
        "status":     "pending",
        "input":      input_payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    persisted_via = None
    if _dynamo and GATES_TABLE:
        try:
            _persist_dynamo(record)
            persisted_via = "dynamodb"
        except ClientError as e:
            print("manual-gate: DynamoDB persist failed ({}); falling back to S3".format(e))
    if persisted_via is None:
        _persist_s3(record)
        persisted_via = "s3"

    _notify(record)

    return {
        "status": "pending",
        "gate_id": gate_id,
        "gate": gate,
        "persisted_via": persisted_via,
    }


# Aliased so the handler registration matches every other Lambda in this repo.
handler = lambda_handler
