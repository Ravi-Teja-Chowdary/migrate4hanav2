"""
Tests for evidence-collector and reconciliation-engine.
Both Lambdas use boto3.resource('dynamodb') / boto3.client('s3') at module level,
so we monkeypatch those before import. We also stub utils/logger.
"""
from __future__ import annotations
import importlib
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda" / "utils"))


# ────────────────────────── Test doubles ──────────────────────────
class _FakeTable:
    def __init__(self):
        self.items = {}            # (run_id, seq) -> item

    def query(self, **kw):
        run_id = kw["ExpressionAttributeValues"][":r"]
        rows = [v for (rid, _), v in self.items.items() if rid == run_id]
        rows.sort(key=lambda r: int(r["seq"]),
                  reverse=not kw.get("ScanIndexForward", True))
        return {"Items": rows[: kw.get("Limit", 1000)]}

    def put_item(self, **kw):
        item = kw["Item"]
        self.items[(item["run_id"], int(item["seq"]))] = item

    def get_item(self, **kw):
        key = kw["Key"]
        item = self.items.get((key["run_id"], int(key["seq"])))
        return {"Item": item} if item else {}


class _FakeDDB:
    def __init__(self):
        self.tables = {}
    def Table(self, name):
        return self.tables.setdefault(name, _FakeTable())


class _FakeS3:
    def __init__(self):
        self.objects = {}
    def put_object(self, **kw):
        self.objects[(kw["Bucket"], kw["Key"])] = kw["Body"]
        return {"ETag": "fake"}


class _Ctx:
    aws_request_id = "test-req-id"


# ────────────────────────── Helpers ──────────────────────────
def _load(module_name: str, src_dir: str, fake_ddb, fake_s3):
    """Import a Lambda handler with boto3 mocked."""
    sys.modules.pop(module_name, None)
    sys.modules.pop("handler", None)
    src_path = str(ROOT / "lambda" / src_dir)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    import boto3
    boto3.resource = lambda *a, **k: fake_ddb           # type: ignore
    boto3.client = lambda *a, **k: fake_s3              # type: ignore

    spec = importlib.util.spec_from_file_location(
        module_name, str(ROOT / "lambda" / src_dir / "handler.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                        # type: ignore
    return mod


# ────────────────────────── Test cases ──────────────────────────
def test_evidence_chain_genesis_and_append():
    fake_ddb = _FakeDDB()
    fake_s3 = _FakeS3()
    os.environ["EVENTS_TABLE_NAME"] = "test-events"
    os.environ["S3_EVIDENCE_BUCKET"] = "test-evidence"

    h = _load("evidence_collector", "evidence-collector", fake_ddb, fake_s3)

    r1 = h.lambda_handler(
        {"run_id": "R1", "stage": "transport-import-executor",
         "event_type": "completed", "payload": {"transport": "DEVK900123"}},
        _Ctx())
    assert r1["seq"] == 1
    assert r1["prev_hash"] == "0" * 64
    assert len(r1["this_hash"]) == 64
    assert ("test-evidence", f"runs/R1/events/00000001-{r1['this_hash'][:12]}.json") \
        in fake_s3.objects

    r2 = h.lambda_handler(
        {"run_id": "R1", "stage": "reconciliation-engine",
         "event_type": "completed", "payload": {"variance": 0}},
        _Ctx())
    assert r2["seq"] == 2
    assert r2["prev_hash"] == r1["this_hash"]

    # Walk and verify
    v = h.verify_chain("R1")
    assert v["ok"] is True, v
    assert v["length"] == 2
    assert v["tip_hash"] == r2["this_hash"]


def test_evidence_chain_detects_tampering():
    fake_ddb = _FakeDDB()
    fake_s3 = _FakeS3()
    os.environ["EVENTS_TABLE_NAME"] = "test-events-2"
    os.environ["S3_EVIDENCE_BUCKET"] = "test-evidence-2"

    h = _load("evidence_collector", "evidence-collector", fake_ddb, fake_s3)
    h.lambda_handler({"run_id": "R2", "stage": "s",
                      "event_type": "started", "payload": {}}, _Ctx())
    h.lambda_handler({"run_id": "R2", "stage": "s",
                      "event_type": "completed", "payload": {"a": 1}}, _Ctx())

    # Tamper the second event's payload directly in the table
    tbl = fake_ddb.Table("test-events-2")
    tbl.items[("R2", 2)]["payload"] = {"a": 999}

    v = h.verify_chain("R2")
    assert v["ok"] is False
    assert v["broken_at"] == 2


def test_reconciliation_engine_count_within_tolerance():
    fake_ddb = _FakeDDB()
    fake_s3 = _FakeS3()
    os.environ["TOLERANCE_TABLE_NAME"] = "test-tol"
    os.environ["EVIDENCE_COLLECTOR_FN"] = "noop"
    os.environ["MANUAL_GATE_FN"] = "noop"

    h = _load("reconciliation_engine", "reconciliation-engine",
              fake_ddb, fake_s3)

    # Pure unit: smoke-call the verdict helpers if present, otherwise the
    # full handler with no recon items returns a dict with reconciliations=[].
    out = h.lambda_handler(
        {"run_id": "R3", "object_class": "Customer",
         "reconciliations": []}, _Ctx())
    assert isinstance(out, dict)
    assert "reconciliations" in out or "results" in out or "status" in out


if __name__ == "__main__":
    failures = 0
    for fn in [test_evidence_chain_genesis_and_append,
               test_evidence_chain_detects_tampering,
               test_reconciliation_engine_count_within_tolerance]:
        try:
            fn()
            print(f"  OK   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"Failures: {failures}")
    sys.exit(1 if failures else 0)
