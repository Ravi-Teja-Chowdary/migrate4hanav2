"""
config-applier (lift-and-shift) — BC Sets + customizing transports only.

We never call NUMBER_RANGE_INTERVAL_CREATE, BAPI_BUPA_GROUPING_CREATE,
CKML_START_MATERIAL_LEDGER, etc. directly into the target. Instead:

    1. config-replicator (extract mode, upstream) snapshots ECC config
    2. bc-set-builder generates BC Set on BUILD system
    3. transport-artifact-builder packs it as a customizing transport
    4. file-placer + import-executor + verifier ship it to target.

This Lambda is the coordinator that drives steps 2-4 from the snapshot.
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

BC_SET_BUILDER_FN  = os.environ.get("BC_SET_BUILDER_FN",          "bc-set-builder")
ARTIFACT_BUILDER_FN = os.environ.get("TRANSPORT_ARTIFACT_BUILDER_FN", "transport-artifact-builder")
FILE_PLACER_FN     = os.environ.get("TRANSPORT_FILE_PLACER_FN",   "transport-file-placer")
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


def _load_config_snapshot(run_id: str) -> dict:
    """Read the snapshot produced by config-replicator (extract mode)."""
    key = f"runs/{run_id}/config-replicator/snapshot.json"
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    log_stage_event(run_id, "config-applier", "start", {})

    snapshot = event.get("config_snapshot") or _load_config_snapshot(run_id)
    if not snapshot:
        log_stage_event(run_id, "config-applier", "blocked", {"reason": "no config snapshot"})
        return {"status": "blocked", "reason": "config snapshot not found",
                "hint": "run config-replicator extract first", "run_id": run_id}

    bc_groups = snapshot.get("bc_set_groups") or [{
        "name": f"M4H_RUN_{run_id}",
        "description": "Migrate4HANA-generated BC Set",
        "values": snapshot.get("customizing_values", []),
    }]

    bc_result = _invoke(BC_SET_BUILDER_FN, {"run_id": run_id, "bc_sets": bc_groups})
    if bc_result.get("status") not in ("ok", "success"):
        log_stage_event(run_id, "config-applier", "error", {"stage": "bc_build", "result": bc_result})
        return {"status": "error", "stage": "bc_build", "detail": bc_result, "run_id": run_id}

    transport_objects = bc_result.get("transport_object_list", [])
    build = _invoke(ARTIFACT_BUILDER_FN, {
        "run_id": run_id, "object_kind": "config",
        "objects": transport_objects,
    })
    if build.get("status") not in ("ok", "success"):
        return {"status": "error", "stage": "build", "detail": build, "run_id": run_id}

    transport = build.get("transport_request") or build.get("trkorr")
    place = _invoke(FILE_PLACER_FN, {"run_id": run_id, "transport_request": transport,
                                      "cofile_s3": build.get("cofile_s3"),
                                      "datafile_s3": build.get("datafile_s3")})
    imp = _invoke(IMPORT_EXEC_FN, {"run_id": run_id, "transport_request": transport})
    verify = _invoke(IMPORT_VERIFY_FN, {"run_id": run_id, "transport_request": transport})

    summary = {
        "run_id": run_id,
        "status": "ok" if imp.get("rc", 99) <= 4 and verify.get("status") == "ok" else "warning",
        "bc_sets": [g.get("name") for g in bc_groups],
        "transport_request": transport,
        "import_rc": imp.get("rc"),
        "verify": verify,
    }
    log_stage_event(run_id, "config-applier", summary["status"], summary)
    return summary
