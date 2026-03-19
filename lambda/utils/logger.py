"""
logger.py - Granular structured telemetry logging
==================================================
Used by all Lambda stages to emit consistent, structured JSON logs.
Broadcasts to:
  1. CloudWatch Logs (always)
  2. API Gateway WebSocket (when deployed — real-time UI streaming)
  3. Local API server (when running locally via run_local_pipeline.py)
"""
import json
import time
import logging
import os
import uuid
from typing import Any, Dict

logging.basicConfig(level=logging.INFO)
cw_logger = logging.getLogger("Migrate4HANA_Telemetry")
cw_logger.setLevel(logging.INFO)

# WebSocket configuration from environment (set by Terraform Lambda env vars)
_WS_API_ENDPOINT = os.environ.get("TELEMETRY_WS_ENDPOINT", "")
_WS_CONNECTIONS_TABLE = os.environ.get("TELEMETRY_WS_CONNECTIONS_TABLE", "")

# Cached boto3 clients (lazy-init to avoid import cost when not deployed)
_apigw_client = None
_dynamodb_resource = None


def _get_apigw_client():
    global _apigw_client
    if _apigw_client is None and _WS_API_ENDPOINT:
        try:
            import boto3
            # Extract the base URL for the management API
            # WebSocket endpoint: wss://abc123.execute-api.us-east-1.amazonaws.com/dev
            # Management API:     https://abc123.execute-api.us-east-1.amazonaws.com/dev
            endpoint_url = _WS_API_ENDPOINT.replace("wss://", "https://")
            _apigw_client = boto3.client(
                "apigatewaymanagementapi", endpoint_url=endpoint_url
            )
        except Exception:
            pass
    return _apigw_client


def _get_connections_table():
    global _dynamodb_resource
    if _dynamodb_resource is None and _WS_CONNECTIONS_TABLE:
        try:
            import boto3
            _dynamodb_resource = boto3.resource("dynamodb")
        except Exception:
            pass
    if _dynamodb_resource and _WS_CONNECTIONS_TABLE:
        return _dynamodb_resource.Table(_WS_CONNECTIONS_TABLE)
    return None


def log_stage_event(stage_name: str, action: str, status: str, payload: Any, duration_ms: float = 0.0) -> None:
    """Emit a structured JSON telemetry event to CloudWatch + WebSocket UI."""

    # Safely snippet payload
    payload_str = str(payload)
    if len(payload_str) > 300:
        snippet = payload_str[:297] + "..."
    else:
        snippet = payload_str

    log_entry = {
        "event_id": str(uuid.uuid4()),
        "stage": stage_name,
        "action": action,
        "status": status,
        "duration_ms": duration_ms,
        "timestamp": int(time.time() * 1000),
        "payload_snippet": snippet
    }

    # 1. Always emit to CloudWatch
    cw_logger.info(json.dumps(log_entry))

    # 2. Broadcast to connected WebSocket clients
    _broadcast_to_websocket(log_entry)


def _broadcast_to_websocket(log_entry: Dict[str, Any]) -> None:
    """Push log event to all connected WebSocket clients via API Gateway Management API."""
    apigw = _get_apigw_client()
    table = _get_connections_table()

    if not apigw or not table:
        return

    message = json.dumps(log_entry).encode("utf-8")

    try:
        # Scan all active connections
        response = table.scan(ProjectionExpression="connectionId")
        connections = response.get("Items", [])

        stale_connections = []
        for conn in connections:
            connection_id = conn["connectionId"]
            try:
                apigw.post_to_connection(
                    ConnectionId=connection_id, Data=message
                )
            except apigw.exceptions.GoneException:
                # Client disconnected — mark for cleanup
                stale_connections.append(connection_id)
            except Exception:
                # Non-fatal — don't let telemetry failures break pipeline
                pass

        # Clean up stale connections
        for cid in stale_connections:
            try:
                table.delete_item(Key={"connectionId": cid})
            except Exception:
                pass

    except Exception:
        # Telemetry broadcast is best-effort — never break the pipeline
        pass

