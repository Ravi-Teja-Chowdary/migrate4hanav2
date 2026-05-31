"""
Migrate4HANA — ECS Fargate Entrypoint (Unified Docker Wrapper)
================================================================
This is the single entrypoint for the Fargate container. It supports
two modes:

1. STAGE_TARGET mode (Step Functions integration):
   Wraps the existing Lambda handler logic so we can reuse all Python
   code (PyRFC BAPI calls, AST engine, data scrubber, etc.).
   Env vars:
     STAGE_TARGET    — handler: discovery-engine | code-analyzer | data-loader
     SFN_TASK_TOKEN  — Step Functions callback token
     SFN_INPUT       — JSON-encoded state payload

2. BATTLETEST mode (standalone proof run, no SFN):
   Runs the comprehensive battletest harness against synthetic fixtures
   stored in S3, writes results back to S3.
   Env vars:
     M4H_MODE                     = "battletest"
     M4H_BATTLETEST_SCALE         — tiny / small / medium / large / xlarge
     M4H_BATTLETEST_S3_BUCKET     — S3 bucket for fixtures + results
     M4H_BATTLETEST_S3_FIXTURES_PREFIX  — e.g. "battletest/scale-large/"
     M4H_BATTLETEST_S3_RESULTS_PREFIX   — e.g. "battletest/results/"
     M4H_BATTLETEST_THREADS       — defaults to 16
     M4H_BATTLETEST_CODE_REM      — "1" to include code remediation
"""

import json
import os
import sys
import logging
import threading
import traceback
import importlib

import boto3

# ── Logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("ecs-entrypoint")

# ── Constants ────────────────────────────────
HEARTBEAT_INTERVAL = 120  # seconds — must be < HeartbeatSeconds in SFN (300)

# Map of valid STAGE_TARGET values → handler directory names
VALID_STAGES = {
    "discovery-engine",
    "code-analyzer",
    "data-loader",
}


# ── Heartbeat Thread ─────────────────────────
# Long-running stages (FINS polling ≈ 4 h, 15 K+ program scans)
# would otherwise hit the Step Functions heartbeat timeout.
def _heartbeat_loop(task_token, stop_event):
    """Send periodic heartbeats to Step Functions while the handler runs."""
    sfn = boto3.client("stepfunctions")
    while not stop_event.is_set():
        try:
            sfn.send_task_heartbeat(taskToken=task_token)
            logger.debug("Heartbeat sent")
        except Exception as exc:
            logger.warning("Heartbeat failed (task may have timed out): %s", exc)
            break
        stop_event.wait(HEARTBEAT_INTERVAL)


# ── Fake Lambda Context ─────────────────────
class _FargateContext:
    """Minimal shim so existing handler(event, context) signatures work."""

    def __init__(self, stage):
        self.function_name = f"ecs-{stage}"
        self.memory_limit_in_mb = 16384
        self.invoked_function_arn = ""
        self.log_group_name = os.environ.get("AWS_LOG_GROUP", "/ecs/migrate4hana")
        self.log_stream_name = stage
        self.aws_request_id = f"ecs-{stage}-{os.getpid()}"

    def get_remaining_time_in_millis(self):
        return 14400000  # 4 hours — effectively unlimited


# ── Battletest mode ──────────────────────────
def run_battletest_mode():
    """Standalone battletest run. Reads fixtures from S3, runs the
    orchestrator, writes results to S3. No Step Functions integration."""
    scale = os.environ.get("M4H_BATTLETEST_SCALE", "small")
    bucket = os.environ.get("M4H_BATTLETEST_S3_BUCKET")
    fix_prefix = os.environ.get("M4H_BATTLETEST_S3_FIXTURES_PREFIX",
                                f"battletest/scale-{scale}/")
    res_prefix = os.environ.get("M4H_BATTLETEST_S3_RESULTS_PREFIX",
                                "battletest/results/")
    abap_prefix = os.environ.get("M4H_BATTLETEST_S3_ABAP_PREFIX",
                                 "battletest/abap-suite/")
    threads = int(os.environ.get("M4H_BATTLETEST_THREADS", "16"))
    include_cr = os.environ.get("M4H_BATTLETEST_CODE_REM", "1") == "1"

    if not bucket:
        raise SystemExit("M4H_BATTLETEST_S3_BUCKET is required for battletest mode")

    logger.info("BATTLETEST mode: scale=%s bucket=%s threads=%d code_rem=%s",
                scale, bucket, threads, include_cr)

    # Stage 1: download fixtures from S3 to /tmp
    import tempfile, time
    from pathlib import Path

    work_dir = Path(tempfile.mkdtemp(prefix="battletest-"))
    fixtures_dir = work_dir / "fixtures"
    fixtures_dir.mkdir()
    abap_dir = work_dir / "abap-suite"
    abap_dir.mkdir()

    s3 = boto3.client("s3")
    logger.info("Downloading fixtures from s3://%s/%s ...", bucket, fix_prefix)
    paginator = s3.get_paginator("list_objects_v2")
    fix_count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=fix_prefix):
        for obj in (page.get("Contents") or []):
            key = obj["Key"]
            name = key.rsplit("/", 1)[-1]
            local = fixtures_dir / name
            s3.download_file(bucket, key, str(local))
            fix_count += 1
    logger.info("Downloaded %d fixture files", fix_count)

    if include_cr:
        # NB: use the explicit abap_prefix env var, NOT a relative "/../" path
        # off fix_prefix. S3 keys are flat strings; "/.." is literal, not
        # resolved. Previous bug: cr_prefix="battletest/scale-large/../abap-suite/"
        # matched zero objects so code remediation silently skipped.
        logger.info("Downloading ABAP suite from s3://%s/%s ...", bucket, abap_prefix)
        abap_count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=abap_prefix):
            for obj in (page.get("Contents") or []):
                key = obj["Key"]
                name = key.rsplit("/", 1)[-1]
                local = abap_dir / name
                s3.download_file(bucket, key, str(local))
                abap_count += 1
        logger.info("Downloaded %d ABAP suite files", abap_count)
        if abap_count == 0:
            logger.warning("ABAP suite is empty at s3://%s/%s - "
                           "code remediation will be skipped",
                           bucket, abap_prefix)

    # Stage 2: run the orchestrator
    sys.path.insert(0, "/app/battletest")
    sys.path.insert(0, "/app/lambda/utils")
    sys.path.insert(0, "/app/lambda/code-analyzer")

    import orchestrator
    from orchestrator import run

    logger.info("Launching orchestrator (scale=%s) ...", scale)
    t0 = time.time()
    result = run(scale_name=scale,
                 fixtures_dir=fixtures_dir,
                 abap_suite_dir=abap_dir if include_cr else None,
                 threads=threads,
                 include_code_remediation=include_cr)
    elapsed = time.time() - t0
    logger.info("Orchestrator finished in %.1fs", elapsed)

    # Stage 3: upload results JSON back to S3
    result_dict = result.to_dict()
    result_dict["aws_run_metadata"] = {
        "fargate_task_arn": os.environ.get("ECS_TASK_ARN", ""),
        "cluster_arn": os.environ.get("ECS_CLUSTER", ""),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "elapsed_wall_s": round(elapsed, 2),
    }
    ts = int(time.time())
    result_key = f"{res_prefix.rstrip('/')}/battletest-{scale}-aws-{ts}.json"
    s3.put_object(Bucket=bucket, Key=result_key,
                  Body=json.dumps(result_dict, indent=2).encode("utf-8"),
                  ContentType="application/json")
    logger.info("Results written to s3://%s/%s", bucket, result_key)

    # Stage 4: print summary to CloudWatch logs
    print(f"\n{'='*78}\nBATTLETEST COMPLETE (scale={scale})\n{'='*78}")
    for s in result.stages:
        print(f"  {s.name:30s} {s.elapsed_s:>7.2f}s  in={s.records_in:>12,d}  "
              f"out={s.records_out:>12,d}  throughput={s.throughput_per_s:>10,.0f}/s")
    print(f"\nTotal issues: {len(result.issues)}")
    print(f"Cutover verdict: {(result.cutover_verdict or {}).get('verdict')}")
    print(f"Results: s3://{bucket}/{result_key}")


# ── Main ─────────────────────────────────────
def main():
    # Battletest mode takes precedence over Step Functions mode
    if os.environ.get("M4H_MODE") == "battletest":
        run_battletest_mode()
        return

    stage = os.environ.get("STAGE_TARGET")
    task_token = os.environ.get("SFN_TASK_TOKEN")
    input_json = os.environ.get("SFN_INPUT", "{}")

    # ── Validate ──
    if not stage:
        raise SystemExit("STAGE_TARGET environment variable is required")
    if stage not in VALID_STAGES:
        raise SystemExit(f"Unknown STAGE_TARGET '{stage}'. Valid: {VALID_STAGES}")
    if not task_token:
        raise SystemExit("SFN_TASK_TOKEN environment variable is required")

    logger.info("═══ Migrate4HANA ECS Worker ═══")
    logger.info("  Stage : %s", stage)
    logger.info("  PID   : %d", os.getpid())

    # ── Parse input payload ──
    event = json.loads(input_json)

    # ── Set up Python path so the handler's relative imports work ──
    handler_dir = f"/app/lambda/{stage}"
    utils_dir = "/app/lambda/utils"
    sys.path.insert(0, handler_dir)
    sys.path.insert(0, utils_dir)
    # data-loader imports from data-hygiene
    sys.path.insert(0, "/app/lambda/data-hygiene")
    # code-analyzer imports its own sub-modules
    sys.path.insert(0, "/app/lambda/code-analyzer")

    os.chdir(handler_dir)

    # ── Start heartbeat thread ──
    stop_event = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(task_token, stop_event),
        daemon=True,
    )
    hb_thread.start()

    sfn = boto3.client("stepfunctions")

    try:
        # ── Import and invoke the existing handler ──
        handler_module = importlib.import_module("handler")
        context = _FargateContext(stage)

        logger.info("Invoking handler.lambda_handler for stage=%s", stage)
        result = handler_module.lambda_handler(event, context)

        # ── Wrap output to match Lambda integration format ──
        # Step Functions Lambda integration returns {"Payload": ...}
        # Downstream states reference $.discovery.Payload, etc.
        output = json.dumps({"Payload": result})

        sfn.send_task_success(taskToken=task_token, output=output)
        logger.info("Stage %s completed successfully. Callback sent.", stage)

    except Exception as exc:
        error_msg = str(exc)[:256]
        cause = traceback.format_exc()[:32768]
        logger.error("Stage %s FAILED:\n%s", stage, cause)

        try:
            sfn.send_task_failure(
                taskToken=task_token,
                error=error_msg,
                cause=cause,
            )
        except Exception as cb_exc:
            logger.critical("CRITICAL: Failed to notify Step Functions of failure: %s", cb_exc)
            sys.exit(2)
        sys.exit(1)

    finally:
        stop_event.set()
        hb_thread.join(timeout=10)
        if hb_thread.is_alive():
            logger.warning("Heartbeat thread did not terminate within timeout")


if __name__ == "__main__":
    main()
