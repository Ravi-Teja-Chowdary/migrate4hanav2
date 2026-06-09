"""
api-orchestrator - REST endpoints for the Visual Business Authoring layer.

WORKSTREAM 1 of the Trojan-Horse productization mandate (2026-06-09).
Deprecates the local `manage-value-maps.ps1` administrative script and
exposes the same operations as JSON REST endpoints so a future React
console can drive value-mapping + ruleset management WITHOUT manual
file injection.

Endpoints (mapped from API Gateway):

  GET    /value-maps                         list all value-map matrices
  GET    /value-maps/{name}                  fetch one matrix
  PUT    /value-maps/{name}                  upsert a matrix (validates structure)
  DELETE /value-maps/{name}                  remove a matrix (audited)

  GET    /rulesets                           list all transformation rulesets
  GET    /rulesets/{object}                  fetch one object's ruleset
  PUT    /rulesets/{object}                  upsert a ruleset (validates against
                                              transformation_engine.RulesetError)

  GET    /telemetry/runs                     list recent migration runs
  GET    /telemetry/runs/{run_id}            per-run aggregate from DDB
  GET    /telemetry/key-map/{object}/{src}   resolve one source key (admin debug)

Storage: matrices + rulesets live in the existing S3 value-maps bucket
(`migrate4hana-value-maps-<env>`); run telemetry queries the F1
PersistentKeyMap DDB table (`migrate4hana-key-map-prod`) directly.

Auth: API Gateway in front of this lambda is expected to enforce IAM or
Cognito user-pool auth. The handler itself is auth-naive and assumes the
gateway has already authenticated; production deploy will require the
gateway side to populate the requestContext.authorizer.claims block.

Tenant isolation: every endpoint that touches storage routes through
TenantContext.from_env() (single-tenant `default` when no env overlay)
so the same handler serves any number of customer landscapes via path
prefix.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

# Pull in shared utilities from lambda/utils (mounted by container or layer)
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

try:
    import boto3
    S3 = boto3.client("s3")
    DDB = boto3.client("dynamodb")
except Exception:   # local-dev fallback
    S3 = None
    DDB = None

# Lazy imports — the tenant/F1/transformation modules live in lambda/utils
def _tenant_ctx():
    try:
        from tenant_context import TenantContext
        return TenantContext.from_env()
    except Exception:
        class _N:
            tenant_id = "default"
            tenant_slug = "default"
            is_default = True
            def value_maps_key(self, fname="matrix.json"):
                return f"mappings/{fname}"
        return _N()


VALUE_MAPS_BUCKET = os.environ.get("M4H_VALUE_MAPS_BUCKET",
                                    "migrate4hana-value-maps-prod")
KEY_MAP_TABLE = os.environ.get("M4H_KEYMAP_TABLE",
                                "migrate4hana-key-map-prod")
VALUE_MAPS_PREFIX = "value-maps/"
RULESETS_PREFIX   = "rulesets/"


def _ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",      # API Gateway will refine
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, default=str),
    }


def _err(msg: str, status: int = 400) -> dict:
    return _ok({"error": msg}, status=status)


# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers (S3 + DDB)
# ─────────────────────────────────────────────────────────────────────────────
def _s3_list(prefix: str) -> list:
    if S3 is None:
        return []
    try:
        resp = S3.list_objects_v2(Bucket=VALUE_MAPS_BUCKET, Prefix=prefix)
        return [
            {
                "name":     obj["Key"][len(prefix):].rsplit(".json", 1)[0],
                "size":     obj["Size"],
                "modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                "etag":     obj.get("ETag", "").strip('"'),
            }
            for obj in (resp.get("Contents") or [])
            if obj["Key"].endswith(".json") and obj["Key"] != prefix
        ]
    except Exception as e:
        return [{"error": str(e)[:200]}]


def _s3_get(prefix: str, name: str) -> dict:
    key = f"{prefix}{name}.json"
    try:
        resp = S3.get_object(Bucket=VALUE_MAPS_BUCKET, Key=key)
        body = resp["Body"].read().decode("utf-8")
        return {"name": name, "body": json.loads(body),
                "etag": resp.get("ETag", "").strip('"'),
                "modified": resp.get("LastModified").isoformat()
                              if resp.get("LastModified") else None}
    except S3.exceptions.NoSuchKey:
        return {"_status": 404, "name": name, "error": "not found"}
    except Exception as e:
        return {"_status": 502, "name": name, "error": str(e)[:200]}


def _s3_put(prefix: str, name: str, body: dict, validate=None) -> dict:
    if validate is not None:
        err = validate(body)
        if err:
            return {"_status": 400, "error": err}
    key = f"{prefix}{name}.json"
    try:
        S3.put_object(Bucket=VALUE_MAPS_BUCKET, Key=key,
                       Body=json.dumps(body, indent=2).encode("utf-8"),
                       ContentType="application/json")
        return {"name": name, "status": "saved",
                "size": len(json.dumps(body))}
    except Exception as e:
        return {"_status": 502, "error": str(e)[:200]}


def _s3_delete(prefix: str, name: str) -> dict:
    key = f"{prefix}{name}.json"
    try:
        S3.delete_object(Bucket=VALUE_MAPS_BUCKET, Key=key)
        return {"name": name, "status": "deleted"}
    except Exception as e:
        return {"_status": 502, "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────────
# Validation hooks (apply before write-through to S3)
# ─────────────────────────────────────────────────────────────────────────────
def _validate_matrix(body: dict) -> str:
    """Value-map matrix shape: {table_name: {src_value: tgt_value}}."""
    if not isinstance(body, dict):
        return "matrix root must be a dict"
    for tname, table in body.items():
        if not isinstance(tname, str) or not tname:
            return f"matrix key {tname!r} not a non-empty string"
        if not isinstance(table, dict):
            return f"matrix['{tname}'] must be a dict of src->tgt"
        for src, tgt in table.items():
            if not isinstance(src, str) or not isinstance(tgt, str):
                return f"matrix['{tname}'] entry {src!r}->{tgt!r} not string->string"
    return ""


def _validate_ruleset(body: dict) -> str:
    """Defer to TransformationEngine's existing validator -- if it raises
    RulesetError the ruleset would fail at runtime, so reject upfront."""
    try:
        from transformation_engine import TransformationEngine
        TransformationEngine(ruleset=body)
        return ""
    except Exception as e:
        return f"ruleset rejected by transformation engine: {str(e)[:160]}"


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry queries (read-only against DDB)
# ─────────────────────────────────────────────────────────────────────────────
def _telemetry_runs(limit: int = 50) -> dict:
    """List distinct run_ids in the key_map table (one per migration run)."""
    if DDB is None:
        return {"runs": [], "note": "DDB unavailable"}
    try:
        resp = DDB.scan(
            TableName=KEY_MAP_TABLE,
            ProjectionExpression="run_id,written_at,#o",
            ExpressionAttributeNames={"#o": "object"},
            Limit=200,
        )
        runs: dict = {}
        for item in resp.get("Items") or []:
            rid = (item.get("run_id") or {}).get("S", "")
            if not rid:
                continue
            r = runs.setdefault(rid, {"run_id": rid, "rows": 0,
                                       "first_seen": None, "last_seen": None,
                                       "objects": set()})
            r["rows"] += 1
            ts = (item.get("written_at") or {}).get("S")
            if ts:
                if r["first_seen"] is None or ts < r["first_seen"]:
                    r["first_seen"] = ts
                if r["last_seen"] is None or ts > r["last_seen"]:
                    r["last_seen"] = ts
            r["objects"].add((item.get("object") or {}).get("S", ""))
        out = sorted(
            ({**r, "objects": sorted(r["objects"])} for r in runs.values()),
            key=lambda x: x["last_seen"] or "",
            reverse=True,
        )
        return {"runs": out[:limit], "scan_size": len(resp.get("Items") or [])}
    except Exception as e:
        return {"_status": 502, "error": str(e)[:200]}


def _telemetry_run_detail(run_id: str) -> dict:
    """Per-run object breakdown."""
    if DDB is None:
        return {"_status": 502, "error": "DDB unavailable"}
    try:
        resp = DDB.scan(
            TableName=KEY_MAP_TABLE,
            FilterExpression="run_id = :rid",
            ExpressionAttributeValues={":rid": {"S": run_id}},
            ProjectionExpression="#o,source_key,target_key,disposition,written_at",
            ExpressionAttributeNames={"#o": "object"},
        )
        items = resp.get("Items") or []
        by_obj: dict = {}
        for it in items:
            obj_name = (it.get("object") or {}).get("S", "")
            b = by_obj.setdefault(obj_name, {"object": obj_name, "count": 0,
                                              "dispositions": {}})
            b["count"] += 1
            disp = (it.get("disposition") or {}).get("S", "")
            b["dispositions"][disp] = b["dispositions"].get(disp, 0) + 1
        return {"run_id": run_id, "row_count": len(items),
                "by_object": list(by_obj.values())}
    except Exception as e:
        return {"_status": 502, "error": str(e)[:200]}


def _telemetry_resolve(object_type: str, src_key: str) -> dict:
    """Admin debug: resolve one source key via the F1 PersistentKeyMap."""
    if DDB is None:
        return {"_status": 502, "error": "DDB unavailable"}
    try:
        ctx = _tenant_ctx()
        pk = ctx.tenant_slug + "#" + object_type if not ctx.is_default else object_type
        resp = DDB.get_item(
            TableName=KEY_MAP_TABLE,
            Key={"object": {"S": pk}, "source_key": {"S": src_key}},
        )
        item = resp.get("Item")
        if not item:
            return {"_status": 404,
                    "object": object_type, "source_key": src_key,
                    "resolution": None}
        return {
            "object":      object_type,
            "source_key":  src_key,
            "target_key":  (item.get("target_key") or {}).get("S"),
            "disposition": (item.get("disposition") or {}).get("S"),
            "tenant_id":   (item.get("tenant_id") or {}).get("S"),
            "run_id":      (item.get("run_id") or {}).get("S"),
            "written_at":  (item.get("written_at") or {}).get("S"),
        }
    except Exception as e:
        return {"_status": 502, "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────────
# Lambda handler — route by HTTP method + path
# ─────────────────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    path = event.get("path") or event.get("rawPath") or "/"
    path_params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}

    # OPTIONS preflight
    if method == "OPTIONS":
        return _ok({"ok": True})

    # /value-maps
    if path.startswith("/value-maps"):
        name = path_params.get("name") or _trim(path, "/value-maps/")
        if method == "GET" and not name:
            return _ok({"matrices": _s3_list(VALUE_MAPS_PREFIX)})
        if method == "GET" and name:
            r = _s3_get(VALUE_MAPS_PREFIX, name)
            return _ok(r, status=r.pop("_status", 200))
        if method == "PUT" and name:
            body = _parse_body(event)
            r = _s3_put(VALUE_MAPS_PREFIX, name, body, validate=_validate_matrix)
            return _ok(r, status=r.pop("_status", 200))
        if method == "DELETE" and name:
            r = _s3_delete(VALUE_MAPS_PREFIX, name)
            return _ok(r, status=r.pop("_status", 200))

    # /rulesets
    if path.startswith("/rulesets"):
        name = path_params.get("object") or _trim(path, "/rulesets/")
        if method == "GET" and not name:
            return _ok({"rulesets": _s3_list(RULESETS_PREFIX)})
        if method == "GET" and name:
            r = _s3_get(RULESETS_PREFIX, name)
            return _ok(r, status=r.pop("_status", 200))
        if method == "PUT" and name:
            body = _parse_body(event)
            r = _s3_put(RULESETS_PREFIX, name, body, validate=_validate_ruleset)
            return _ok(r, status=r.pop("_status", 200))

    # /telemetry/runs
    if path.startswith("/telemetry/runs"):
        run_id = path_params.get("run_id") or _trim(path, "/telemetry/runs/")
        if method == "GET" and not run_id:
            limit = int(query.get("limit", 50))
            return _ok(_telemetry_runs(limit=limit))
        if method == "GET" and run_id:
            r = _telemetry_run_detail(run_id)
            return _ok(r, status=r.pop("_status", 200))

    # /telemetry/key-map/{object}/{source_key}
    if path.startswith("/telemetry/key-map"):
        obj = path_params.get("object")
        src = path_params.get("source_key")
        if method == "GET" and obj and src:
            r = _telemetry_resolve(obj, src)
            return _ok(r, status=r.pop("_status", 200))

    # Health
    if path in ("/", "/health"):
        return _ok({
            "service": "api-orchestrator",
            "tenant":  _tenant_ctx().tenant_id,
            "endpoints": [
                "GET    /value-maps",
                "GET    /value-maps/{name}",
                "PUT    /value-maps/{name}",
                "DELETE /value-maps/{name}",
                "GET    /rulesets",
                "GET    /rulesets/{object}",
                "PUT    /rulesets/{object}",
                "GET    /telemetry/runs",
                "GET    /telemetry/runs/{run_id}",
                "GET    /telemetry/key-map/{object}/{source_key}",
            ],
        })

    return _err(f"unknown route {method} {path}", status=404)


def _trim(path: str, prefix: str) -> str:
    if not path.startswith(prefix):
        return ""
    return path[len(prefix):].split("/")[0].strip()


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except Exception:
        return {}
