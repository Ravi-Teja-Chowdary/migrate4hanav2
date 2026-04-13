"""
Migrate4HANA — ECS Fargate Entrypoint (Unified Docker Wrapper)
================================================================
This is the single entrypoint for the Fargate container. It wraps
the existing Lambda handler logic so we can reuse all Python code
(PyRFC BAPI calls, AST engine, data scrubber, etc.) without any
rewrites.

Environment Variables (set by Step Functions ContainerOverrides):
  STAGE_TARGET    — Which handler to run: discovery-engine | code-analyzer | data-loader
  SFN_TASK_TOKEN  — Step Functions callback token (waitForTaskToken pattern)
  SFN_INPUT       — JSON-encoded state payload (same structure as Lambda event)

The container calls SendTaskSuccess/Failure back to Step Functions
when done, so the orchestrator can seamlessly pass output to the
next stage — identical behaviour to the Lambda integration.
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


# ── Main ─────────────────────────────────────
def main():
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
