"""
azure_logger.py — Azure Web PubSub telemetry logger for Migrate4HANA
=====================================================================
Replaces the AWS logger that used API Gateway WebSocket + DynamoDB
connections table. Uses Azure Web PubSub to broadcast structured
telemetry events to all connected WebSocket clients in real time.

Broadcasts to:
  1. Python logger (always — captured by Azure Monitor / Application Insights)
  2. Azure Web PubSub (when configured — real-time UI streaming)

Environment:
    AZURE_WEB_PUBSUB_CONNECTION_STRING  — Web PubSub connection string
    AZURE_WEB_PUBSUB_HUB               — Hub name (default "telemetry")

Graceful fallback:
    If Web PubSub is not configured, events are logged only to the
    standard Python logger so the pipeline never breaks.
"""

import json
import time
import logging
import os
import uuid
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("Migrate4HANA_Telemetry")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
_WEB_PUBSUB_CONNECTION_STRING = os.environ.get("AZURE_WEB_PUBSUB_CONNECTION_STRING", "")
_WEB_PUBSUB_HUB = os.environ.get("AZURE_WEB_PUBSUB_HUB", "telemetry")

# Thread-safe cached client
_lock = threading.Lock()
_pubsub_client = None
_pubsub_available: Optional[bool] = None


def _get_pubsub_client():
    """
    Return a cached WebPubSubServiceClient, creating it on first call.
    Returns None if Web PubSub is not configured.
    Thread-safe initialisation.
    """
    global _pubsub_client, _pubsub_available

    if _pubsub_available is False:
        return None

    if _pubsub_client is not None:
        return _pubsub_client

    with _lock:
        if _pubsub_client is not None:
            return _pubsub_client

        if not _WEB_PUBSUB_CONNECTION_STRING:
            logger.info(
                "AZURE_WEB_PUBSUB_CONNECTION_STRING not set — "
                "telemetry will log to Python logger only"
            )
            _pubsub_available = False
            return None

        try:
            from azure.messaging.webpubsubservice import WebPubSubServiceClient

            _pubsub_client = WebPubSubServiceClient.from_connection_string(
                connection_string=_WEB_PUBSUB_CONNECTION_STRING,
                hub=_WEB_PUBSUB_HUB,
            )
            _pubsub_available = True
            logger.info(
                "WebPubSubServiceClient initialised for hub '%s'", _WEB_PUBSUB_HUB
            )
            return _pubsub_client

        except ImportError:
            logger.warning(
                "azure-messaging-webpubsubservice package not installed — "
                "telemetry will log to Python logger only"
            )
            _pubsub_available = False
            return None
        except Exception as exc:
            logger.warning(
                "Failed to initialise Web PubSub client: %s — "
                "telemetry will log to Python logger only",
                exc,
            )
            _pubsub_available = False
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def log_stage_event(
    stage: str,
    action: str,
    status: str,
    details: Any = None,
    duration_ms: float = 0.0,
) -> None:
    """
    Emit a structured JSON telemetry event.

    Broadcasts to:
      1. Python logger (always — Azure Monitor / App Insights)
      2. Azure Web PubSub (when configured — real-time UI)

    Args:
        stage:       Pipeline stage name (e.g. "code-analyzer").
        action:      What happened (e.g. "ast_analysis_complete").
        status:      "ok", "warning", "error", "skipped".
        details:     Optional payload (will be snippeted if > 300 chars).
        duration_ms: Elapsed time in milliseconds.
    """
    details_str = str(details) if details is not None else ""
    if len(details_str) > 300:
        snippet = details_str[:297] + "..."
    else:
        snippet = details_str

    log_entry: Dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "stage": stage,
        "action": action,
        "status": status,
        "duration_ms": duration_ms,
        "timestamp": int(time.time() * 1000),
        "payload_snippet": snippet,
    }

    # 1. Always emit to Python logger (captured by Azure Monitor)
    logger.info(json.dumps(log_entry))

    # 2. Broadcast to Web PubSub connected clients
    broadcast_message(log_entry)


def broadcast_message(message_dict: Dict[str, Any]) -> None:
    """
    Send a JSON message to all connected WebSocket clients via Azure Web PubSub.

    If Web PubSub is not configured, this is a no-op (graceful fallback).
    Telemetry broadcast is best-effort — failures never break the pipeline.

    Args:
        message_dict: Message payload to broadcast as JSON.
    """
    client = _get_pubsub_client()
    if client is None:
        return

    try:
        payload = json.dumps(message_dict)

        # Azure Web PubSub has a 1 MB message size limit
        if len(payload) > 1_048_576:
            message_dict["payload_snippet"] = (
                message_dict.get("payload_snippet", "")[:200] + "...[truncated]"
            )
            payload = json.dumps(message_dict)

        client.send_to_all(
            message=payload,
            content_type="application/json",
        )

    except Exception as exc:
        # Telemetry broadcast is best-effort — never break the pipeline
        logger.debug("Web PubSub broadcast failed (non-fatal): %s", exc)
