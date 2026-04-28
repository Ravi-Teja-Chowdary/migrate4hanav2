"""
code-deployer (lift-and-shift) — STMS-only.

Code goes to S/4HANA via SAP-shipped transport mechanism only (CTS+/STMS).
We do NOT call RPY_PROGRAM_INSERT/UPDATE or RS_CORR_INSERT.

Flow:
    1. Read remediated ABAP from S3 (produced by code-analyzer in remediate mode)
    2. Hand off to ``transport-artifact-builder`` with object_kind="code"
    3. Builder creates the workbench transport on the BUILD system
    4. transport-file-placer + transport-import-executor + verifier ship it.

This Lambda is therefore a thin coordinator — most of the actual work
runs in the chained orchestrators.
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
ARTIFACT_BUILDER_FN = os.environ.get("TRANSPORT_ARTIFACT_BUILDER_FN", "transport-artifact-builder")
FILE_PLACER_FN     = os.environ.get("TRANSPORT_FILE_PLACER_FN",     "transport-file-placer")
IMPORT_EXEC_FN     = os.environ.get("TRANSPORT_IMPORT_EXECUTOR_FN", "transport-import-executor")
IMPORT_VERIFY_FN   = os.environ.get("TRANSPORT_IMPORT_VERIFIER_FN", "transport-import-verifier")


def _invoke(fn: str, payload: dict) -> dict:
    resp = LAMBDA.invoke(FunctionName=fn, InvocationType="RequestResponse",
                         Payload=json.dumps(payload).encode("utf-8"))
    body = resp["Payload"].read().decode("utf-8") if resp.get("Payload") else "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"status": "error", "raw": body}


def _list_remediated_objects(run_id: str) -> list:
    prefix = f"runs/{run_id}/code-analyzer/remediated/"
    out = []
    paginator = S3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=STAGING_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            name = key[len(prefix):].split("/")[0]
            if name and not key.endswith("/"):
                out.append({"name": name, "s3_key": key, "object_kind": "code"})
    return out


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    log_stage_event(run_id, "code-deployer", "start", {})

    code_objects = event.get("code_objects") or _list_remediated_objects(run_id)
    if not code_objects:
        log_stage_event(run_id, "code-deployer", "skipped", {"reason": "no remediated code"})
        return {"status": "skipped", "reason": "no remediated code objects found", "run_id": run_id}

    build = _invoke(ARTIFACT_BUILDER_FN, {
        "run_id": run_id, "object_kind": "code", "objects": code_objects,
    })
    if build.get("status") not in ("ok", "success"):
        log_stage_event(run_id, "code-deployer", "error", {"stage": "build", "result": build})
        return {"status": "error", "stage": "build", "detail": build, "run_id": run_id}

    transport = build.get("transport_request") or build.get("trkorr")

    place = _invoke(FILE_PLACER_FN, {"run_id": run_id, "transport_request": transport,
                                      "cofile_s3": build.get("cofile_s3"),
                                      "datafile_s3": build.get("datafile_s3")})
    if place.get("status") not in ("ok", "success"):
        log_stage_event(run_id, "code-deployer", "error", {"stage": "place", "result": place})
        return {"status": "error", "stage": "place", "detail": place, "run_id": run_id}

    imp = _invoke(IMPORT_EXEC_FN, {"run_id": run_id, "transport_request": transport})
    verify = _invoke(IMPORT_VERIFY_FN, {"run_id": run_id, "transport_request": transport})

    summary = {
        "run_id": run_id,
        "status": "ok" if imp.get("rc", 99) <= 4 and verify.get("status") == "ok" else "warning",
        "transport_request": transport,
        "import_rc": imp.get("rc"),
        "verify": verify,
        "object_count": len(code_objects),
    }
    log_stage_event(run_id, "code-deployer", summary["status"], summary)
    return summary
