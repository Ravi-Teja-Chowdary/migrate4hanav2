"""
Migrate4HANA — Azure Container Apps Entrypoint (Unified Docker Wrapper)
========================================================================
This is the single entrypoint for the container. It wraps the existing
handler logic so we can reuse all Python code (PyRFC BAPI calls, AST
engine, data scrubber, etc.) without any rewrites.

Environment Variables (set by Azure Container Apps / Durable Functions):
  STAGE_TARGET          — Which handler to run: discovery-engine | code-analyzer | data-loader
  DURABLE_FUNCTIONS_URL — Base URL of the Durable Functions app (e.g. https://func-migrate4hana.azurewebsites.net)
  INSTANCE_ID           — Durable Functions orchestration instance ID for callbacks
  CONTAINER_INPUT       — JSON-encoded state payload (same structure as Lambda event)

The container raises external events on the Durable Functions orchestrator
when done, so the orchestrator can seamlessly pass output to the next
stage — identical behaviour to the previous orchestrator integration.
"""

import json
import os
import sys
import logging
import threading
import traceback
import importlib

import requests

# ── Logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("container-entrypoint")

# ── Constants ────────────────────────────────
HEARTBEAT_INTERVAL = 120  # seconds
TASK_HUB = "migrate4hana"

VALID_STAGES = {
    "discovery-engine",
    "code-analyzer",
    "data-loader",
}


def _build_raise_event_url(base_url, instance_id, event_name):
    """Build the Durable Functions raiseEvent URL."""
    return (
        f"{base_url.rstrip('/')}/runtime/webhooks/durabletask/instances/"
        f"{instance_id}/raiseEvent/{event_name}?taskHub={TASK_HUB}"
    )


# ── Heartbeat Thread ─────────────────────────
def _heartbeat_loop(base_url, instance_id, stop_event):
    """Send periodic heartbeats to Durable Functions while the handler runs."""
    url = _build_raise_event_url(base_url, instance_id, "heartbeat")
    while not stop_event.is_set():
        try:
            resp = requests.post(
                url,
                json={"status": "alive", "pid": os.getpid()},
                timeout=30,
            )
            resp.raise_for_status()
            logger.debug("Heartbeat sent")
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
        stop_event.wait(HEARTBEAT_INTERVAL)


# ── Container Context ────────────────────────
class _ContainerContext:
    """Minimal shim so existing handler(event, context) signatures work."""

    def __init__(self, stage):
        self.function_name = f"container-{stage}"
        self.memory_limit_in_mb = 16384
        self.invoked_function_arn = ""
        self.log_group_name = f"container/migrate4hana/{stage}"
        self.log_stream_name = stage
        self.request_id = f"container-{stage}-{os.getpid()}"

    def get_remaining_time_in_millis(self):
        return 14400000  # 4 hours — effectively unlimited


# ── Main ─────────────────────────────────────
def main():
    stage = os.environ.get("STAGE_TARGET")
    durable_url = os.environ.get("DURABLE_FUNCTIONS_URL")
    instance_id = os.environ.get("INSTANCE_ID")
    input_json = os.environ.get("CONTAINER_INPUT", "{}")

    # ── Validate ──
    if not stage:
        raise SystemExit("STAGE_TARGET environment variable is required")
    if stage not in VALID_STAGES:
        raise SystemExit(f"Unknown STAGE_TARGET '{stage}'. Valid: {VALID_STAGES}")
    if not durable_url:
        raise SystemExit("DURABLE_FUNCTIONS_URL environment variable is required")
    if not instance_id:
        raise SystemExit("INSTANCE_ID environment variable is required")

    logger.info("═══ Migrate4HANA Container Worker ═══")
    logger.info("  Stage       : %s", stage)
    logger.info("  Instance ID : %s", instance_id)
    logger.info("  PID         : %d", os.getpid())

    # ── Parse input payload ──
    event = json.loads(input_json)

    # ── Set up Python path so the handler's relative imports work ──
    handler_dir = f"/app/lambda/{stage}"
    utils_dir = "/app/lambda/utils"
    sys.path.insert(0, handler_dir)
    sys.path.insert(0, utils_dir)
    sys.path.insert(0, "/app/lambda/data-hygiene")
    sys.path.insert(0, "/app/lambda/code-analyzer")

    os.chdir(handler_dir)

    # ── Start heartbeat thread ──
    stop_event = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(durable_url, instance_id, stop_event),
        daemon=True,
    )
    hb_thread.start()

    try:
        # ── Import and invoke the existing handler ──
        handler_module = importlib.import_module("handler")
        context = _ContainerContext(stage)

        logger.info("Invoking handler.lambda_handler for stage=%s", stage)
        result = handler_module.lambda_handler(event, context)

        # ── Raise success event on Durable Functions orchestrator ──
        output = {"Payload": result}
        success_url = _build_raise_event_url(durable_url, instance_id, "success")
        resp = requests.post(success_url, json=output, timeout=30)
        resp.raise_for_status()
        logger.info("Stage %s completed successfully. Callback sent.", stage)

    except Exception as exc:
        error_msg = str(exc)[:256]
        cause = traceback.format_exc()[:32768]
        logger.error("Stage %s FAILED:\n%s", stage, cause)

        try:
            failure_url = _build_raise_event_url(durable_url, instance_id, "failure")
            resp = requests.post(
                failure_url,
                json={"error": error_msg, "cause": cause},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as cb_exc:
            logger.critical("CRITICAL: Failed to notify Durable Functions of failure: %s", cb_exc)
            sys.exit(2)
        sys.exit(1)

    finally:
        stop_event.set()
        hb_thread.join(timeout=10)
        if hb_thread.is_alive():
            logger.warning("Heartbeat thread did not terminate within timeout")


if __name__ == "__main__":
    main()
