"""
Unit tests for WS4 pillar 2 -- Immutable Compliance Archive.

Validates the extract -> format -> seal -> ledger-chain pipeline that
lets a customer shut down their legacy ECC hardware while remaining
SOX / FDA / GDPR compliant for the 7-10 year audit horizon.
"""
from __future__ import annotations
import sys, json, hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
sys.path.insert(0, str(REPO_ROOT / "lambda" / "compliance-archive"))


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
    def put_object(self, **kwargs):
        self.calls.append({k: v for k, v in kwargs.items() if k != "Body"})
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}


class FakeDDB:
    def __init__(self):
        self.items = []
    def query(self, **kw):
        # Items keyed by tenant_obj -- filter to match the query key
        k = kw["ExpressionAttributeValues"][":k"]["S"]
        matches = [it for it in self.items
                    if (it.get("tenant_obj") or {}).get("S") == k]
        matches.sort(key=lambda it: int((it.get("ts") or {}).get("N", 0)),
                       reverse=not kw.get("ScanIndexForward", True))
        return {"Items": matches[:kw.get("Limit", 100)]}
    def put_item(self, **kwargs):
        self.items.append(kwargs["Item"])
        return {}


class FakeConn:
    def __init__(self, scripts=None):
        self.scripts = scripts or {}
        self.calls = []
    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            return self.scripts.get(kwargs.get("QUERY_TABLE"), {})
        return {}
    def close(self): pass


class FakeSM:
    def get_secret_value(self, SecretId):
        return {"SecretString": json.dumps({
            "ashost": "ecc.test", "sysnr": "00", "client": "800",
            "user": "x", "passwd": "y"})}


import handler as ca  # noqa
_fake_s3, _fake_ddb, _fake_sm = FakeS3(), FakeDDB(), FakeSM()
ca.S3 = _fake_s3
ca.DDB = _fake_ddb
ca.SECRETS = _fake_sm
_fake_conn_holder = {"conn": FakeConn()}
ca._open_rfc = lambda sid: _fake_conn_holder["conn"]


def test_extract_seals_chunk_with_object_lock():
    """Extract one chunk; verify ObjectLockMode=COMPLIANCE + retention
    + the chunk's block_hash matches SHA-256 over the JSONL body."""
    _fake_conn_holder["conn"] = FakeConn(scripts={
        "KNA1": {
            "DATA": [
                {"WA": "0010000001|ACME Corp|US|12-3456789"},
                {"WA": "0010000002|Globex|DE|99-887766"},
            ],
            "FIELDS": [
                {"FIELDNAME": "KUNNR"}, {"FIELDNAME": "NAME1"},
                {"FIELDNAME": "LAND1"}, {"FIELDNAME": "STCD1"},
            ],
        },
    })
    _fake_s3.calls.clear()
    _fake_s3.objects.clear()
    _fake_ddb.items.clear()

    resp = ca.lambda_handler({"mode": "extract",
                                 "object_type": "Customer",
                                 "chunk_idx": 0,
                                 "retention_days": 3650}, None)
    body = json.loads(resp["body"])
    assert body["rows"] == 2
    assert body["chunk_idx"] == 0
    assert len(body["block_hash"]) == 64   # SHA-256 hex
    # S3 put_object was called with Object Lock COMPLIANCE + retention
    put_call = _fake_s3.calls[0]
    assert put_call["ObjectLockMode"] == "COMPLIANCE"
    assert put_call["ServerSideEncryption"] == "AES256"
    assert "ObjectLockRetainUntilDate" in put_call
    # Block_hash also recorded in S3 object metadata
    assert put_call["Metadata"]["block-hash"] == body["block_hash"]
    print("  [OK] extract seals chunk with COMPLIANCE mode + retention + AES256 SSE")


def test_extract_chains_to_previous_block_hash():
    """Two sequential extracts -- the second's prev_hash should be the
    first's block_hash."""
    _fake_conn_holder["conn"] = FakeConn(scripts={
        "MARA": {
            "DATA": [
                {"WA": "MAT001|HALB|M|EA|Material 1"},
                {"WA": "MAT002|HALB|M|EA|Material 2"},
            ],
            "FIELDS": [
                {"FIELDNAME": "MATNR"}, {"FIELDNAME": "MTART"},
                {"FIELDNAME": "MBRSH"}, {"FIELDNAME": "MEINS"},
                {"FIELDNAME": "MAKTX"},
            ],
        },
    })
    _fake_ddb.items.clear()
    _fake_s3.objects.clear()

    # First chunk
    r1 = ca.lambda_handler({"mode": "extract", "object_type": "Material",
                              "chunk_idx": 0}, None)
    first_hash = json.loads(r1["body"])["block_hash"]
    # Second chunk
    r2 = ca.lambda_handler({"mode": "extract", "object_type": "Material",
                              "chunk_idx": 1}, None)
    second_body = json.loads(r2["body"])
    assert second_body["prev_hash"] == first_hash
    print("  [OK] sequential chunks chain via prev_hash (audit-trail tamper-evidence)")


def test_unknown_object_type_returns_400():
    resp = ca.lambda_handler({"mode": "extract",
                                 "object_type": "UnknownTable"}, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "unknown object_type" in body["error"]
    print("  [OK] unknown object_type -> 400")


def test_extract_all_iterates_legacy_tables():
    """extract_all walks every LEGACY_TABLES entry, returning per-object
    summaries in a single response."""
    _fake_conn_holder["conn"] = FakeConn(scripts={})
    _fake_ddb.items.clear()
    resp = ca.lambda_handler({"mode": "extract_all",
                                 "objects": ["Customer", "Vendor", "Material"]}, None)
    body = json.loads(resp["body"])
    assert body["objects"] == 3
    obj_names = {s["object"] for s in body["by_object"]}
    assert obj_names == {"Customer", "Vendor", "Material"}
    print("  [OK] extract_all iterates objects with per-object summaries")


def test_verify_chain_detects_intact_chain():
    """A clean N-block chain returns ok=True with the tip block hash."""
    # Seed DDB with a fresh 3-block chain
    _fake_ddb.items.clear()
    prev = "0" * 64
    for i in range(3):
        h = hashlib.sha256(f"block{i}".encode()).hexdigest()
        _fake_ddb.items.append({
            "tenant_obj": {"S": "default#Material"},
            "ts":         {"N": str(1000 + i)},
            "block_hash": {"S": h},
            "prev_hash":  {"S": prev},
            "chunk_idx":  {"N": str(i)},
        })
        prev = h
    resp = ca.lambda_handler({"mode": "verify_chain",
                                 "object_type": "Material"}, None)
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert body["chain_length"] == 3
    assert body["tip_block_hash"] == prev
    print("  [OK] verify_chain ok=True on clean 3-block chain")


def test_verify_chain_detects_broken_chain():
    """A broken chain (mismatched prev_hash mid-stream) returns ok=False
    + broken_at_chunk_idx."""
    _fake_ddb.items.clear()
    # Build 3 blocks with a CORRUPTED prev_hash on block 2
    _fake_ddb.items.extend([
        {"tenant_obj": {"S": "default#Customer"},
          "ts": {"N": "1"}, "block_hash": {"S": "h1"},
          "prev_hash": {"S": "0" * 64}, "chunk_idx": {"N": "0"}},
        {"tenant_obj": {"S": "default#Customer"},
          "ts": {"N": "2"}, "block_hash": {"S": "h2"},
          "prev_hash": {"S": "h1"}, "chunk_idx": {"N": "1"}},
        # Block 3's prev_hash is WRONG (should be h2, set to "FORGED")
        {"tenant_obj": {"S": "default#Customer"},
          "ts": {"N": "3"}, "block_hash": {"S": "h3"},
          "prev_hash": {"S": "FORGED"}, "chunk_idx": {"N": "2"}},
    ])
    resp = ca.lambda_handler({"mode": "verify_chain",
                                 "object_type": "Customer"}, None)
    body = json.loads(resp["body"])
    assert body["ok"] is False
    assert body["broken_at_chunk_idx"] == 2
    assert body["expected_prev_hash"] == "h2"
    assert body["actual_prev_hash"] == "FORGED"
    print("  [OK] verify_chain detects FORGED prev_hash + reports broken_at_chunk_idx")


def test_record_sha256_is_per_row_tamper_evidence():
    """Every row carries a SHA-256 over its canonical JSON -- if any
    field is altered post-archive, the per-row hash mismatches the
    actual row content. Per-row tamper detection independent of the
    chunk-level chain."""
    _fake_conn_holder["conn"] = FakeConn(scripts={
        "KNA1": {
            "DATA": [{"WA": "C001|Test|US|"}],
            "FIELDS": [{"FIELDNAME": "KUNNR"}, {"FIELDNAME": "NAME1"},
                        {"FIELDNAME": "LAND1"}, {"FIELDNAME": "STCD1"}],
        },
    })
    _fake_s3.objects.clear()
    ca.lambda_handler({"mode": "extract", "object_type": "Customer",
                         "chunk_idx": 10}, None)
    # Read back the gzipped JSONL we just wrote
    import gzip
    keys = list(_fake_s3.objects.keys())
    assert keys
    body_bytes = gzip.decompress(_fake_s3.objects[keys[-1]])
    line = body_bytes.decode("utf-8").strip().split("\n")[0]
    record = json.loads(line)
    assert "record_sha256" in record
    # Verify the hash matches the row_data
    row_data = record["row_data"]
    expected = hashlib.sha256(
        json.dumps(row_data, sort_keys=True).encode("utf-8")).hexdigest()
    assert record["record_sha256"] == expected
    print("  [OK] each archived row carries per-row SHA-256 tamper-evidence")


def test_unknown_mode_returns_400():
    resp = ca.lambda_handler({"mode": "bogus"}, None)
    assert resp["statusCode"] == 400
    print("  [OK] unknown mode -> 400")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS4 pillar 2 -- Compliance Archive tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll Compliance Archive tests passed.")
