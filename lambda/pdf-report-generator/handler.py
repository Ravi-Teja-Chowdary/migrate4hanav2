"""
migrate4hana-pdf-report-generator-prod
======================================
Stage 27 of the lift-and-shift state machine. Aggregates every per-stage
artifact written to S3 by upstream stages, maps them into the schema the
PDF generator consumes, renders the PDF, and uploads both the JSON and
the PDF back to S3 under runs/<run_id>/report/.

Input event shape (passed by the state machine):
    {"run_id": "...", "input": {...}, ...}

Output:
    {"status": "success",
     "report_pdf_s3":  "s3://<staging>/runs/<run_id>/report/migration-report.pdf",
     "report_json_s3": "s3://<staging>/runs/<run_id>/report/report_input.json",
     "stage_count": N}
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdf_report_generator  # bundled at repo-root level inside the zip
from aggregator import aggregate_run_artifacts  # bundled inside the zip

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-prod")
STATE_MACHINE_NAME = os.environ.get(
    "STATE_MACHINE_NAME", "migrate4hana-lift-and-shift-prod")


def _download_run_artifacts(bucket: str, run_id: str) -> Path:
    """Mirror s3://<bucket>/runs/<run_id>/ and s3://<bucket>/migrations/<run_id>/
    to a temp dir so the aggregator (which walks rglob('*.json')) can find them."""
    tmp = Path(tempfile.mkdtemp(prefix=f"m4h-report-{run_id}-"))
    n = 0
    for prefix in (f"runs/{run_id}/", f"migrations/{run_id}/"):
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue
                rel = key[len(prefix):]
                if not rel:
                    continue
                local = tmp / prefix.rstrip("/") / rel
                local.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(local))
                n += 1
    logger.info("Downloaded %d artifacts for run %s under %s", n, run_id, tmp)
    return tmp


def _harvest_sfn_outputs(run_id: str, staging_root: Path) -> int:
    """Pull each Lambda's output from the SFN execution history and write it as
    a synthetic artifact under runs/<run_id>/sfn-stage-outputs/ so the aggregator
    sees the full per-stage payload (most Lambdas only return through state, not
    to S3). This is what closes the gap between the AWS PDF and the local PDF."""
    written = 0
    try:
        # Find the execution by name = run_id under the prod state machine
        sm_arn = None
        for page in sfn.get_paginator("list_state_machines").paginate():
            for sm in page.get("stateMachines", []) or []:
                if sm.get("name") == STATE_MACHINE_NAME:
                    sm_arn = sm.get("stateMachineArn")
                    break
            if sm_arn:
                break
        if not sm_arn:
            logger.warning("State machine %s not found", STATE_MACHINE_NAME)
            return 0
        exec_arn = sm_arn.replace(":stateMachine:", ":execution:") + ":" + run_id

        # Walk the history, capture each TaskStateExited output as JSON
        out_dir = staging_root / "runs" / run_id / "sfn-stage-outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        token = None
        while True:
            kwargs = {"executionArn": exec_arn, "maxResults": 1000,
                      "includeExecutionData": True}
            if token:
                kwargs["nextToken"] = token
            try:
                resp = sfn.get_execution_history(**kwargs)
            except Exception as e:
                logger.warning("get_execution_history failed: %s", e)
                break
            for ev in resp.get("events", []) or []:
                if ev.get("type") != "TaskStateExited":
                    continue
                det = ev.get("stateExitedEventDetails") or {}
                name = det.get("name") or "unknown"
                output_raw = det.get("output")
                if not output_raw:
                    continue
                try:
                    parsed = json.loads(output_raw)
                except Exception:
                    parsed = {"_raw_output": output_raw[:2000]}
                safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
                (out_dir / f"{safe_name}.json").write_text(
                    json.dumps(parsed, default=str, indent=2), encoding="utf-8")
                written += 1
            token = resp.get("nextToken")
            if not token:
                break
    except Exception as e:
        logger.exception("SFN harvest failed: %s", e)
    logger.info("Wrote %d SFN stage-output artifacts", written)
    return written


def lambda_handler(event, context):
    run_id = event.get("run_id") or (event.get("input") or {}).get("run_id") or "unknown"
    bucket = os.environ.get("S3_STAGING_BUCKET", STAGING_BUCKET)
    logger.info("PDF report generator: run_id=%s bucket=%s", run_id, bucket)

    try:
        staging_root = _download_run_artifacts(bucket, run_id)
        sfn_artifacts = _harvest_sfn_outputs(run_id, staging_root)
        logger.info("Aggregating S3 artifacts + %d SFN stage outputs", sfn_artifacts)
        aggregated = aggregate_run_artifacts(staging_root, run_id)
    except Exception as e:
        logger.exception("Aggregation failed")
        return {"status": "error", "stage": "aggregate", "reason": str(e), "run_id": run_id}

    out_dir = Path(tempfile.mkdtemp(prefix=f"m4h-pdf-{run_id}-"))
    json_path = out_dir / "report_input.json"
    pdf_path  = out_dir / "migration-report.pdf"
    json_path.write_text(json.dumps(aggregated, indent=2, default=str), encoding="utf-8")

    try:
        pdf_report_generator.generate_pdf(aggregated, str(pdf_path))
    except Exception as e:
        logger.exception("PDF render failed; uploading JSON only")
        json_key = f"runs/{run_id}/report/report_input.json"
        s3.upload_file(str(json_path), bucket, json_key)
        return {"status": "partial", "stage": "render",
                "reason": str(e),
                "report_json_s3": f"s3://{bucket}/{json_key}",
                "run_id": run_id}

    pdf_key  = f"runs/{run_id}/report/migration-report.pdf"
    json_key = f"runs/{run_id}/report/report_input.json"
    s3.upload_file(str(pdf_path),  bucket, pdf_key)
    s3.upload_file(str(json_path), bucket, json_key)

    return {
        "status": "success",
        "run_id": run_id,
        "report_pdf_s3":  f"s3://{bucket}/{pdf_key}",
        "report_json_s3": f"s3://{bucket}/{json_key}",
        "stage_count": aggregated.get("stage_count", 0),
    }
