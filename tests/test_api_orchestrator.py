"""
Unit tests for WS1 api-orchestrator handler.

Tests the route table + validation hooks without any AWS dependency by
mocking S3 + DDB clients at module level. Covers:

  - Health route (/) returns service metadata + endpoint catalog
  - Value-map list / get / put / delete routing
  - Ruleset put runs through TransformationEngine validation
  - Value-map structural validator rejects malformed matrices
  - Telemetry routes wire to the DDB scan/get helpers
  - 404 on unknown routes
  - OPTIONS preflight returns CORS headers
"""
from __future__ import annotations
import sys, os, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
sys.path.insert(0, str(REPO_ROOT / "lambda" / "api-orchestrator"))


# ─────────────────────────────────────────────────────────────────────────────
# Mock S3 + DDB BEFORE importing the handler
# ─────────────────────────────────────────────────────────────────────────────
class FakeS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.store: dict = {}        # key -> {body, last_modified, etag}
        self.calls: list = []

    def list_objects_v2(self, Bucket, Prefix):
        self.calls.append(("list", Bucket, Prefix))
        out = []
        for k, v in self.store.items():
            if k.startswith(Prefix) and k != Prefix and k.endswith(".json"):
                out.append({"Key": k, "Size": len(v["body"]),
                             "LastModified": _fake_dt(),
                             "ETag": f'"{v["etag"]}"'})
        return {"Contents": out}

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        v = self.store.get(Key)
        if v is None:
            raise FakeS3.exceptions.NoSuchKey()
        from io import BytesIO
        return {"Body": BytesIO(v["body"]),
                "ETag": f'"{v["etag"]}"',
                "LastModified": _fake_dt()}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.calls.append(("put", Bucket, Key))
        body_bytes = Body if isinstance(Body, bytes) else Body.encode("utf-8")
        self.store[Key] = {"body": body_bytes, "etag": "abc123"}
        return {"ETag": "abc123"}

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Bucket, Key))
        self.store.pop(Key, None)
        return {}


class FakeDDB:
    def __init__(self):
        self.items: list = []
        self.calls: list = []

    def scan(self, TableName, **kwargs):
        self.calls.append(("scan", TableName, kwargs))
        # Apply simple FilterExpression filtering for run_id matches
        f = kwargs.get("FilterExpression", "")
        v = kwargs.get("ExpressionAttributeValues", {})
        items = self.items
        if "run_id = :rid" in f:
            rid = (v.get(":rid") or {}).get("S")
            items = [it for it in items
                      if (it.get("run_id") or {}).get("S") == rid]
        return {"Items": items[: kwargs.get("Limit", 200)]}

    def get_item(self, TableName, Key):
        self.calls.append(("get_item", TableName, Key))
        for it in self.items:
            if ((it.get("object") or {}).get("S") == Key["object"]["S"]
                    and (it.get("source_key") or {}).get("S") == Key["source_key"]["S"]):
                return {"Item": it}
        return {}


def _fake_dt():
    class _D:
        def isoformat(self):
            return "2026-06-09T00:00:00+00:00"
    return _D()


# ─────────────────────────────────────────────────────────────────────────────
# Patch the handler module before tests so it uses the fakes
# ─────────────────────────────────────────────────────────────────────────────
import handler as api_handler   # noqa: E402

_fake_s3  = FakeS3()
_fake_ddb = FakeDDB()
api_handler.S3 = _fake_s3
api_handler.DDB = _fake_ddb


# ─────────────────────────────────────────────────────────────────────────────
def _call(method, path, body=None, path_params=None, query=None):
    event = {
        "httpMethod": method,
        "path":       path,
        "pathParameters": path_params or {},
        "queryStringParameters": query or {},
    }
    if body is not None:
        event["body"] = json.dumps(body)
    resp = api_handler.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


# ─────────────────────────────────────────────────────────────────────────────
def test_health_route_returns_endpoint_catalog():
    code, body = _call("GET", "/health")
    assert code == 200
    assert body["service"] == "api-orchestrator"
    assert any("/value-maps" in ep for ep in body["endpoints"])
    print("  [OK] GET /health returns service metadata + endpoint catalog")


def test_options_preflight_returns_cors():
    resp = api_handler.lambda_handler({"httpMethod": "OPTIONS", "path": "/value-maps"}, None)
    assert resp["statusCode"] == 200
    # CORS headers present on every response
    assert resp["headers"]["Access-Control-Allow-Methods"] == "GET,POST,PUT,DELETE,OPTIONS"
    print("  [OK] OPTIONS preflight returns CORS headers")


def test_value_maps_put_get_list_delete_roundtrip():
    matrix = {"company_code_map": {"1000": "1710", "3000": "1710"}}
    code, body = _call("PUT", "/value-maps/co-codes",
                        body=matrix,
                        path_params={"name": "co-codes"})
    assert code == 200, body
    assert body["status"] == "saved"

    code, body = _call("GET", "/value-maps", path_params={})
    assert code == 200
    assert any(m["name"] == "co-codes" for m in body["matrices"])

    code, body = _call("GET", "/value-maps/co-codes",
                        path_params={"name": "co-codes"})
    assert code == 200
    assert body["body"]["company_code_map"]["1000"] == "1710"

    code, body = _call("DELETE", "/value-maps/co-codes",
                        path_params={"name": "co-codes"})
    assert code == 200
    assert body["status"] == "deleted"

    code, body = _call("GET", "/value-maps/co-codes",
                        path_params={"name": "co-codes"})
    assert code == 404
    print("  [OK] /value-maps PUT->GET->LIST->DELETE roundtrip works")


def test_value_map_validator_rejects_non_string_values():
    bad = {"company_code_map": {"1000": 1710}}   # int target, not string
    code, body = _call("PUT", "/value-maps/bad",
                        body=bad,
                        path_params={"name": "bad"})
    assert code == 400
    assert "string->string" in body.get("error", "")
    print("  [OK] /value-maps PUT rejects malformed matrices (int values)")


def test_ruleset_put_validates_via_transformation_engine():
    """A structurally-valid ruleset must round-trip through
    TransformationEngine without raising."""
    ruleset = {
        "version": "1",
        "object_rules": {
            "Customer": {
                "transforms": [{"type": "TRIM", "field": "NAME1"}],
                "dq_rules":   [{"type": "MANDATORY", "field": "LAND1"}],
            },
        },
    }
    code, body = _call("PUT", "/rulesets/Customer",
                        body=ruleset,
                        path_params={"object": "Customer"})
    assert code == 200, body
    assert body["status"] == "saved"
    print("  [OK] /rulesets PUT round-trips a valid ruleset through TE")


def test_ruleset_put_rejects_invalid_via_transformation_engine():
    """TransformationEngine.RulesetError fires on bad shape -> 400."""
    bad = {
        "version": "1",
        "object_rules": {
            "Customer": {
                "transforms": [{"type": "FIELD_MAP"}],   # missing source+target
            },
        },
    }
    code, body = _call("PUT", "/rulesets/Customer",
                        body=bad,
                        path_params={"object": "Customer"})
    assert code == 400
    assert "rejected" in body.get("error", "").lower()
    print("  [OK] /rulesets PUT rejects invalid shape via TE validator")


def test_telemetry_runs_list_aggregates_by_run_id():
    # Seed DDB with rows under two run_ids
    _fake_ddb.items = [
        {"run_id": {"S": "run-A"}, "object": {"S": "Material"},
          "source_key": {"S": "M1"}, "target_key": {"S": "T1"},
          "disposition": {"S": "created"}, "written_at": {"S": "2026-06-09T01:00"}},
        {"run_id": {"S": "run-A"}, "object": {"S": "Customer"},
          "source_key": {"S": "C1"}, "target_key": {"S": "B1"},
          "disposition": {"S": "harmonized"}, "written_at": {"S": "2026-06-09T01:01"}},
        {"run_id": {"S": "run-B"}, "object": {"S": "Material"},
          "source_key": {"S": "M2"}, "target_key": {"S": "T2"},
          "disposition": {"S": "created"}, "written_at": {"S": "2026-06-09T02:00"}},
    ]
    code, body = _call("GET", "/telemetry/runs")
    assert code == 200
    rids = {r["run_id"] for r in body["runs"]}
    assert rids == {"run-A", "run-B"}
    rA = next(r for r in body["runs"] if r["run_id"] == "run-A")
    assert rA["rows"] == 2
    assert sorted(rA["objects"]) == ["Customer", "Material"]
    print("  [OK] GET /telemetry/runs aggregates DDB rows by run_id")


def test_telemetry_run_detail_breaks_down_by_object():
    code, body = _call("GET", "/telemetry/runs/run-A",
                        path_params={"run_id": "run-A"})
    assert code == 200
    assert body["row_count"] == 2
    by_obj = {b["object"]: b for b in body["by_object"]}
    assert by_obj["Material"]["count"] == 1
    assert by_obj["Customer"]["dispositions"]["harmonized"] == 1
    print("  [OK] GET /telemetry/runs/{run_id} returns per-object breakdown")


def test_telemetry_resolve_returns_404_when_no_mapping():
    code, body = _call("GET", "/telemetry/key-map/Material/UNKNOWN",
                        path_params={"object": "Material",
                                      "source_key": "UNKNOWN"})
    assert code == 404
    assert body["resolution"] is None
    print("  [OK] GET /telemetry/key-map/{obj}/{src} returns 404 on miss")


def test_telemetry_resolve_returns_mapping():
    code, body = _call("GET", "/telemetry/key-map/Material/M1",
                        path_params={"object": "Material",
                                      "source_key": "M1"})
    assert code == 200
    assert body["target_key"] == "T1"
    assert body["disposition"] == "created"
    print("  [OK] GET /telemetry/key-map/{obj}/{src} returns the F1 mapping")


def test_unknown_route_returns_404():
    code, body = _call("GET", "/nope/wrong")
    assert code == 404
    assert "unknown route" in body["error"]
    print("  [OK] unknown route -> 404")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS1 api-orchestrator handler unit tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll api-orchestrator tests passed.")
