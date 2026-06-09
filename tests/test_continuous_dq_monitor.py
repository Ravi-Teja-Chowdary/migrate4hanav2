"""
Unit tests for WS4 pillar 1 -- Continuous DQ Monitor.

Decouples the F4 TransformationEngine + DQ gates from the migration state
machine. This SaaS pivot runs post-cutover on a schedule (or via webhook)
against live S/4 records, reusing the same DQ ruleset the customer's
business users edit through the WS1 visual authoring API.
"""
from __future__ import annotations
import sys, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
sys.path.insert(0, str(REPO_ROOT / "lambda" / "continuous-dq-monitor"))


# Mock the AWS clients BEFORE importing the handler
class FakeDDB:
    def __init__(self):
        self.items = []
        self.queries = []
    def put_item(self, **kwargs):
        self.items.append(kwargs["Item"])
        return {}
    def query(self, **kwargs):
        self.queries.append(kwargs)
        # Return an empty Items list -- "no prior block" fresh-tenant case
        return {"Items": []}


class FakeSecretsManager:
    def get_secret_value(self, SecretId):
        return {"SecretString": json.dumps({
            "ashost": "fake.example.com", "sysnr": "00",
            "client": "100", "user": "ADMIN", "passwd": "x"
        })}


class FakeConn:
    """Stand-in for a pyrfc Connection that returns scripted MARA / BUT000 / etc.
    rows for the scan."""
    def __init__(self, scripts: dict):
        self.scripts = scripts
        self.calls = []
    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            return self.scripts.get(kwargs.get("QUERY_TABLE"), {"DATA": []})
        return {}
    def close(self): pass


import handler as dq  # noqa
_fake_ddb = FakeDDB()
_fake_sm  = FakeSecretsManager()
dq.DDB = _fake_ddb
dq.SECRETS = _fake_sm


# Inject our fake S/4 connection into the open_rfc helper
def _patched_open_rfc(secret_id):
    return _patched_open_rfc.conn
dq._open_rfc = _patched_open_rfc


RULESET = {
    "version": "1",
    "object_rules": {
        "Material": {
            "transforms": [],
            "dq_rules": [
                {"type": "MANDATORY", "field": "MEINS"},
                {"type": "MANDATORY", "field": "MTART"},
            ],
        },
        "BusinessPartner": {
            "transforms": [],
            "dq_rules": [
                {"type": "MANDATORY", "field": "NAME_ORG1"},
            ],
        },
    }
}


def test_scheduled_scan_empty_target_returns_clean():
    _patched_open_rfc.conn = FakeConn(scripts={})
    _fake_ddb.items.clear()
    resp = dq.lambda_handler({"mode": "scan",
                                "objects": ["Material", "BusinessPartner"],
                                "ruleset": RULESET}, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["scanned"] == 0
    assert body["violations"] == 0
    # Even an empty scan seals a ledger block (continuous monitoring proof)
    assert len(body["ledger_block_hash"]) == 64
    assert len(_fake_ddb.items) == 1
    print("  [OK] empty-target scan still seals a ledger block -- proof of continuity")


def test_scheduled_scan_finds_mandatory_violations():
    """Scripted MARA returns rows missing MEINS -> rule MANDATORY:MEINS fires."""
    _patched_open_rfc.conn = FakeConn(scripts={
        "MARA": {"DATA": [
            {"WA": "MAT001|HALB|M||Test material missing UoM"},
            {"WA": "MAT002|HALB|M|EA|Compliant material"},
            {"WA": "MAT003||M|EA|Missing MTART"},
        ]},
    })
    _fake_ddb.items.clear()
    resp = dq.lambda_handler({"mode": "scan",
                                "objects": ["Material"],
                                "ruleset": RULESET}, None)
    body = json.loads(resp["body"])
    assert body["scanned"] == 3
    assert body["violations"] == 2   # MAT001 (no MEINS) + MAT003 (no MTART)
    by_rule = body["summary"]["by_rule"]
    assert by_rule.get("MANDATORY:MEINS") == 1
    assert by_rule.get("MANDATORY:MTART") == 1
    assert body["by_object"]["Material"]["violations"] == 2
    print("  [OK] scheduled scan detects MANDATORY violations + classifies by rule")


def test_webhook_scan_single_record():
    """Webhook receives ONE row; runs the DQ ruleset and returns the verdict."""
    _fake_ddb.items.clear()
    resp = dq.lambda_handler({
        "mode": "webhook",
        "object": "Material",
        "row": {"MATNR": "M_BAD", "MTART": "HALB", "MBRSH": "M",
                "MEINS": "", "MAKTX": "Missing UoM"},
        "ruleset": RULESET,
    }, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["object"] == "Material"
    assert body["violations"] == 1
    assert body["findings"][0]["rule"] == "MANDATORY:MEINS"
    print("  [OK] webhook scan single record -> DQ verdict + ledger block")


def test_webhook_returns_400_on_missing_payload():
    resp = dq.lambda_handler({"mode": "webhook"}, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "object + row required" in body["error"]
    print("  [OK] webhook missing object/row -> 400")


def test_ledger_block_chains_to_previous():
    """Sealing N findings -> N blocks; each row.prev_hash references the
    last block's block_hash. Forms a tamper-evident audit chain."""
    _patched_open_rfc.conn = FakeConn(scripts={})
    _fake_ddb.items.clear()

    # First scan -- no prior block
    dq.lambda_handler({"mode": "scan", "objects": ["Material"],
                        "ruleset": RULESET}, None)
    # Mock the second-block prev-hash lookup -- return the first block's hash
    first_block_hash = _fake_ddb.items[0]["block_hash"]["S"]
    class _DDBChained(FakeDDB):
        def query(self, **kw):
            return {"Items": [{"block_hash": {"S": first_block_hash}}]}
    chained = _DDBChained()
    chained.items.extend(_fake_ddb.items)
    dq.DDB = chained
    # Second scan -- prev_hash should reference first_block_hash
    dq.lambda_handler({"mode": "scan", "objects": ["Material"],
                        "ruleset": RULESET}, None)
    assert len(chained.items) == 2
    assert chained.items[1]["prev_hash"]["S"] == first_block_hash
    # Restore for other tests
    dq.DDB = _fake_ddb
    print("  [OK] ledger blocks chain via prev_hash -- tamper-evident audit")


def test_summary_aggregates_by_rule_and_severity():
    findings = [
        {"object": "Material", "rule": "MANDATORY:MEINS",
          "severity": "critical", "key": "M1"},
        {"object": "Material", "rule": "MANDATORY:MEINS",
          "severity": "critical", "key": "M2"},
        {"object": "BusinessPartner", "rule": "MANDATORY:LAND1",
          "severity": "warning", "key": "BP1"},
    ]
    s = dq._summarize(findings)
    assert s["by_rule"]["MANDATORY:MEINS"] == 2
    assert s["by_rule"]["MANDATORY:LAND1"] == 1
    assert s["by_severity"]["critical"] == 2
    assert s["by_severity"]["warning"] == 1
    print("  [OK] summary aggregates by rule + severity")


def test_no_ruleset_returns_empty_findings():
    """When no ruleset is configured the monitor is in pure-extract mode
    -- scan returns scanned count but zero violations."""
    _patched_open_rfc.conn = FakeConn(scripts={
        "MARA": {"DATA": [{"WA": "M|HALB|M|EA|Test"}]},
    })
    _fake_ddb.items.clear()
    resp = dq.lambda_handler({"mode": "scan", "objects": ["Material"]}, None)
    body = json.loads(resp["body"])
    assert body["scanned"] == 1
    assert body["violations"] == 0
    print("  [OK] no ruleset -> pure-extract mode (0 violations regardless of data)")


def test_unknown_mode_returns_400():
    resp = dq.lambda_handler({"mode": "bogus"}, None)
    assert resp["statusCode"] == 400
    print("  [OK] unknown mode -> 400")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS4 pillar 1 -- Continuous DQ Monitor tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll DQ Monitor tests passed.")
