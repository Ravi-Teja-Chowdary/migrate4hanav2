"""
Unit tests for the MC file exporter framework.

The exporter is a single module that registers 20 pseudo-spine subclasses
covering the non-BAPI catalog lane. Each subclass:
  - validates source rows against the MC template's mandatory columns
  - projects rows onto the template's column set
  - accumulates rows in a per-class buffer
  - exposes a flush_to_s3 classmethod that uploads as CSV + a Z-sidecar JSON

UnifiedLoader sees these the same as any other spine -- mechanism='spine/...'.
"""
from __future__ import annotations
import sys, csv, json
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import get_spine, DISP_CREATED, DISP_DEAD_LETTER, DEAD_LETTER_DQ   # noqa
import mc_file_exporter as mc   # noqa


class FakeS3:
    def __init__(self):
        self.objects: dict = {}
        self.calls: list = []

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.calls.append(("put", Bucket, Key, ContentType))
        body_bytes = Body if isinstance(Body, bytes) else Body.encode("utf-8")
        self.objects[Key] = body_bytes
        return {"ETag": "abc"}


class FakeRfc:
    def __init__(self):
        self.calls: list = []
    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        return {}


def _orch_for(obj: str):
    """Build a clean orchestrator for the given object_type. Clears the
    per-class buffer so tests are independent."""
    cls = get_spine(obj)
    assert cls is not None, f"{obj} not registered"
    cls._row_buffer = []
    return cls(FakeRfc())


# ─────────────────────────────────────────────────────────────────────────────
def test_all_20_mc_objects_registered():
    expected = [
        "Routing", "ActivityType", "StatisticalKeyFigure", "CommitmentItem",
        "GLAccount", "TaskList", "InspPlan", "InspMethod", "ServiceMaster",
        "SourceList", "HouseBank", "HouseBankAccount", "ConditionRecord",
        "CustomerHierarchy", "BOMItem", "Network", "WBSElement", "OrgUnit",
        "Position", "EmployeeAction",
    ]
    registered = mc.registered_objects()
    assert sorted(registered) == sorted(expected)
    # All accessible via get_spine
    for obj in expected:
        assert get_spine(obj) is not None
    print(f"  [OK] all {len(expected)} MC file objects registered + accessible")


def test_routing_validates_mandatory_columns():
    orch = _orch_for("Routing")
    res = orch.load_one({"PLNNR": "12345"})       # missing WERKS + MATNR + ARBPL
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    assert "mandatory" in res.messages[0].lower()
    print("  [OK] Routing rejects rows missing mandatory MC columns")


def test_routing_accepts_full_row_and_queues_to_buffer():
    orch = _orch_for("Routing")
    res = orch.load_one({"PLNNR": "12345", "PLNAL": "01",
                          "WERKS": "1710", "MATNR": "M001",
                          "OBJEKT": "K", "ARBPL": "WC1"})
    assert res.status == DISP_CREATED
    assert res.verify_key["table"] == "PLKO"
    # Buffer should have the row
    cls = get_spine("Routing")
    assert len(cls._row_buffer) == 1
    assert cls._row_buffer[0]["record"]["MATNR"] == "M001"
    print("  [OK] Routing queues row to flush buffer + verify_key on PLKO")


def test_z_columns_routed_to_customs_sidecar():
    orch = _orch_for("CustomerHierarchy")
    orch.load_one({"HITYP": "A", "KUNNR": "C1", "HKUNNR": "C2",
                    "ZZ_CUSTOMER_GROUP": "TIER1",
                    "ZZ_LEGACY_REGION":  "EMEA"})
    cls = get_spine("CustomerHierarchy")
    buffered = cls._row_buffer[0]
    assert buffered["record"]["KUNNR"] == "C1"
    assert buffered["customs"]["ZZ_CUSTOMER_GROUP"] == "TIER1"
    assert buffered["customs"]["ZZ_LEGACY_REGION"] == "EMEA"
    print("  [OK] Z* columns separated into sidecar customs blob")


def test_flush_to_s3_writes_csv_with_template_columns():
    cls = get_spine("ActivityType")
    cls._row_buffer = []
    orch = cls(FakeRfc())
    for i in range(3):
        orch.load_one({"KOKRS": "1710", "LSTAR": f"LSTAR_{i:03d}",
                        "ATYP": "1", "TXT": f"Activity {i}",
                        "OUTPUT_UNIT": "H"})
    s3 = FakeS3()
    r = cls.flush_to_s3(s3, "test-bucket", "run-001", "acme")
    assert r["rows"] == 3
    assert r["uri"] == "s3://test-bucket/tenants/acme/runs/run-001/mc_file/ActivityType.csv"
    assert r["template"] == "MC_CO_ACTIVITY_TYPE_V1"
    # Read back the CSV
    key = "tenants/acme/runs/run-001/mc_file/ActivityType.csv"
    body = s3.objects[key].decode("utf-8")
    reader = csv.DictReader(StringIO(body))
    rows = list(reader)
    assert len(rows) == 3
    assert reader.fieldnames == ["KOKRS", "LSTAR", "TXT", "ATYP", "OUTPUT_UNIT"]
    # Buffer should be cleared after flush
    assert cls._row_buffer == []
    print("  [OK] flush_to_s3 writes CSV with template-defined columns + clears buffer")


def test_flush_to_s3_writes_customs_sidecar_when_present():
    cls = get_spine("GLAccount")
    cls._row_buffer = []
    orch = cls(FakeRfc())
    orch.load_one({"KTOPL": "INT", "SAKNR": "0000400000", "TXT": "Wages",
                    "ZZ_TAX_DEDUCTIBLE": "Y"})
    orch.load_one({"KTOPL": "INT", "SAKNR": "0000400001", "TXT": "Bonuses"})
    s3 = FakeS3()
    r = cls.flush_to_s3(s3, "test-bucket", "run-002", "acme")
    assert r["customs_uri"] is not None   # at least one row had customs
    customs_key = "tenants/acme/runs/run-002/mc_file/GLAccount.customs.json"
    sidecar = json.loads(s3.objects[customs_key].decode("utf-8"))
    assert len(sidecar) == 1   # only the row with Z columns
    assert sidecar[0]["customs"]["ZZ_TAX_DEDUCTIBLE"] == "Y"
    print("  [OK] flush_to_s3 writes Z-customs sidecar JSON when any row has them")


def test_flush_to_s3_no_customs_sidecar_when_absent():
    cls = get_spine("Position")
    cls._row_buffer = []
    orch = cls(FakeRfc())
    orch.load_one({"PLANS": "10000001"})
    s3 = FakeS3()
    r = cls.flush_to_s3(s3, "test-bucket", "run-003")
    assert r["customs_uri"] is None
    customs_key = "runs/run-003/mc_file/Position.customs.json"
    assert customs_key not in s3.objects
    print("  [OK] flush_to_s3 omits customs sidecar when no Z columns present")


def test_flush_all_iterates_every_registered_object():
    # Pre-clear all buffers
    for obj in mc.registered_objects():
        get_spine(obj)._row_buffer = []
    # Queue rows for 3 different objects
    for obj in ("Routing", "ActivityType", "InspMethod"):
        cls = get_spine(obj)
        spec = mc.MC_TEMPLATES[obj]
        # Mandatory row -- one per object
        row = {c: f"VAL_{c}" for c in spec["mandatory"]}
        cls(FakeRfc()).load_one(row)
    s3 = FakeS3()
    results = mc.flush_all(s3, "test-bucket", "run-004")
    objs_flushed = {r["object"] for r in results}
    assert objs_flushed == {"Routing", "ActivityType", "InspMethod"}
    # Each got a CSV file in S3
    assert sum(1 for r in results if r["rows"] > 0) == 3
    print("  [OK] flush_all visits every MC object with buffered rows")


def test_unified_loader_dispatches_mc_objects_via_spine_path():
    """Sanity: get_spine() returns the MC class for any registered object_type
    so UnifiedLoader's spine-first routing works for the MC lane too."""
    from unified_loader import UnifiedLoader   # noqa
    # We don't construct a real loader (boto3-heavy); just confirm the
    # spine registry resolves the MC objects.
    for obj in ("Routing", "GLAccount", "OrgUnit"):
        cls = get_spine(obj)
        assert cls is not None
        assert cls.object_type == obj
    print("  [OK] UnifiedLoader's get_spine() resolves MC pseudo-spines")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("MC file exporter tests -- 20 file-lane objects under one framework")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll MC file exporter tests passed.")
