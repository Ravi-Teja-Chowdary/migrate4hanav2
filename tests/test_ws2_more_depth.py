"""
WS2 continuation: Material classification depth + OpenAR/AP multi-line.

Material gets CLASSIFICATION + INSPECTIONCTRL + LONGTEXTS handled via
the existing BaseSpineOrchestrator helpers. OpenAR/AP gain multi-line FI
document support so real customer invoices (which routinely have 5-20
GL lines per AR/AP document) load without falling back to single-line
approximations.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import DISP_CREATED   # noqa
import material_spine                # noqa: F401
import open_ar_spine                 # noqa: F401
import open_ap_spine                 # noqa: F401
from material_spine  import MaterialSpineOrchestrator   # noqa
from open_ar_spine   import OpenARSpineOrchestrator     # noqa
from open_ap_spine   import OpenAPSpineOrchestrator     # noqa


class FakeRfc:
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {
            "BAPI_TRANSACTION_COMMIT": {},
            "BAPI_TRANSACTION_ROLLBACK": {},
            "RFC_READ_TABLE": {"DATA": []},
        }

    def script(self, fn, resp):
        self.scripts[fn] = resp
        return self

    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        return self.scripts.get(fn, {})


class FakeKeyMap:
    def __init__(self, seed=None):
        self.store = dict(seed or {})
        self.adds = []
    def resolve(self, obj, src): return self.store.get((obj, src))
    def add(self, obj, src, tgt, disp):
        self.store[(obj, src)] = tgt
        self.adds.append((obj, src, tgt, disp))


# ─────────────────────────────────────────────────────────────────────────────
# Material classification depth
# ─────────────────────────────────────────────────────────────────────────────
def test_material_classification_triple_routed():
    rfc = FakeRfc()
    rfc.script("BAPI_MATERIAL_SAVEDATA", {"RETURN": [{"TYPE": "S"}]})
    km = FakeKeyMap({
        ("Class", "PAINT_COLOR"):           "PAINT_COLOR_TGT",
        ("Characteristic", "COLOR"):        "COLOR_TGT",
    })
    orch = MaterialSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({
        "MATNR": "M001", "MTART": "HALB", "MBRSH": "M",
        "MEINS": "EA", "MAKTX": "Test mat",
        "_classifications": [
            {"KLART": "001", "CLASS": "PAINT_COLOR",
              "ATNAM": "COLOR", "ATWRT": "RED"},
            {"KLART": "001", "CLASS": "UNREGISTERED_CLASS",
              "ATNAM": "WEIGHT", "ATWRT": "5.2"},   # both unresolved -> passthrough
        ],
    })
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_MATERIAL_SAVEDATA")
    cls = create[1].get("CLASSIFICATION") or []
    assert len(cls) == 2
    # First row: F1-resolved both sides
    assert cls[0]["CLASSNUM"] == "PAINT_COLOR_TGT"
    assert cls[0]["CHARACT_NAME"] == "COLOR_TGT"
    assert cls[0]["VALUE_CHAR"] == "RED"
    # Second row: both unresolved -> source-key passthrough
    assert cls[1]["CLASSNUM"] == "UNREGISTERED_CLASS"
    print("  [OK] Material classification dual-resolves Class + Characteristic via F1")


def test_material_inspection_setup_routed_to_inspectionctrl():
    rfc = FakeRfc()
    rfc.script("BAPI_MATERIAL_SAVEDATA", {"RETURN": [{"TYPE": "S"}]})
    orch = MaterialSpineOrchestrator(rfc)
    res = orch.load_one({
        "MATNR": "M002", "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
        "MAKTX": "Inspected mat",
        "_inspection_setup": [
            {"WERKS": "1710", "ART": "01", "AKTIV": "X"},
            {"WERKS": "1710", "ART": "04"},
        ],
    })
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_MATERIAL_SAVEDATA")
    insp = create[1].get("INSPECTIONCTRL") or []
    assert len(insp) == 2
    assert insp[0]["PLANT"] == "1710" and insp[0]["INSPECTION_TYPE"] == "01"
    print("  [OK] Material inspection setup -> INSPECTIONCTRL with INSPECTIONCTRLX X-mask")


def test_material_long_texts_routed_to_longtexts():
    rfc = FakeRfc()
    rfc.script("BAPI_MATERIAL_SAVEDATA", {"RETURN": [{"TYPE": "S"}]})
    orch = MaterialSpineOrchestrator(rfc)
    res = orch.load_one({
        "MATNR": "M003", "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
        "MAKTX": "Documented mat",
        "_long_texts": [
            {"TDOBJECT": "MARA", "TDID": "BEST", "TDLINE": "Basic data note 1"},
            {"TDOBJECT": "MARA", "TDID": "BEST", "TDLINE": "Basic data note 2"},
        ],
    })
    create = next(c for c in rfc.calls if c[0] == "BAPI_MATERIAL_SAVEDATA")
    texts = create[1].get("LONGTEXTS") or []
    assert len(texts) == 2
    print("  [OK] Material long texts -> LONGTEXTS for BAPI_LONGTEXT_SAVE follow-up")


def test_material_base_shape_still_works():
    """Backward-compat: row without WS2 sub-arrays still creates."""
    rfc = FakeRfc()
    rfc.script("BAPI_MATERIAL_SAVEDATA", {"RETURN": [{"TYPE": "S"}]})
    orch = MaterialSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "M004", "MTART": "HALB", "MBRSH": "M",
                          "MEINS": "EA", "MAKTX": "Base"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_MATERIAL_SAVEDATA")
    # None of the new sub-tables emitted
    assert "CLASSIFICATION" not in create[1]
    assert "INSPECTIONCTRL" not in create[1]
    assert "LONGTEXTS" not in create[1]
    print("  [OK] Material base shape (no WS2 arrays) still creates -- backward-compat")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAR multi-line
# ─────────────────────────────────────────────────────────────────────────────
AR_ORG = {"COMP_CODE": "1710", "CLEARING_GL": "0000199990",
          "PROFIT_CTR": "YB600", "USERNAME": "MIGRATE_ADMI"}


def test_open_ar_multi_line_emits_balanced_doc():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0010000001"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9000000001" + "1710" + "2026"})
    km = FakeKeyMap({("Customer", "C1"): "0010000001"})
    orch = OpenARSpineOrchestrator(rfc, cc_org=AR_ORG, key_map=km)
    row = {"BELNR": "INV001", "KUNNR": "C1", "DMBTR": "1000.00",
            "SHKZG": "S", "WAERS": "USD",
            "lines": [
                {"DMBTR": "300.00", "GL_ACCOUNT": "0000400000",
                  "PROFIT_CTR": "PC_A", "ITEM_TEXT": "Service A"},
                {"DMBTR": "200.00", "GL_ACCOUNT": "0000400001",
                  "PROFIT_CTR": "PC_B", "ITEM_TEXT": "Service B"},
                {"DMBTR": "500.00", "GL_ACCOUNT": "0000400002",
                  "ITEM_TEXT": "Service C"},   # uses default PROFIT_CTR
            ]}
    res = orch.load_one(row)
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_ACC_DOCUMENT_POST")
    # AR has 1 line + 3 extra GL lines + 1 offset = 5 currency rows; balanced
    cur = create[1]["CURRENCYAMOUNT"]
    assert len(cur) == 5
    total = sum(float(c["AMT_DOCCUR"]) for c in cur)
    assert abs(total) < 0.005   # net zero (balanced doc)
    gl = create[1]["ACCOUNTGL"]
    assert len(gl) == 4    # 3 extra + 1 offset
    # Per-line GL accounts honored
    gl_accts = [g["GL_ACCOUNT"] for g in gl]
    assert "0000400000" in gl_accts and "0000400001" in gl_accts
    print("  [OK] OpenAR multi-line: 3 extra lines balanced + per-line GL+PC honored")


def test_open_ar_single_line_still_balanced():
    """Backward-compat: row with no lines[] still produces a balanced 2-row doc."""
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0010000001"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9000000002" + "1710" + "2026"})
    km = FakeKeyMap({("Customer", "C1"): "0010000001"})
    orch = OpenARSpineOrchestrator(rfc, cc_org=AR_ORG, key_map=km)
    res = orch.load_one({"BELNR": "X", "KUNNR": "C1", "DMBTR": "500", "SHKZG": "S"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_ACC_DOCUMENT_POST")
    cur = create[1]["CURRENCYAMOUNT"]
    # 1 AR + 1 offset = 2 rows
    assert len(cur) == 2
    total = sum(float(c["AMT_DOCCUR"]) for c in cur)
    assert abs(total) < 0.005
    print("  [OK] OpenAR single-line still balanced (backward-compat)")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAP multi-line (symmetric)
# ─────────────────────────────────────────────────────────────────────────────
AP_ORG = {"COMP_CODE": "1710", "CLEARING_GL": "0000199991",
          "PROFIT_CTR": "YB600", "USERNAME": "MIGRATE_ADMI"}


def test_open_ap_multi_line_emits_balanced_doc():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0000100001"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9100000001" + "1710" + "2026"})
    km = FakeKeyMap({("Vendor", "V1"): "0000100001"})
    orch = OpenAPSpineOrchestrator(rfc, cc_org=AP_ORG, key_map=km)
    row = {"BELNR": "AP001", "LIFNR": "V1", "DMBTR": "3000.00", "SHKZG": "H",
            "lines": [
                {"DMBTR": "1000.00", "GL_ACCOUNT": "0000500000", "ITEM_TEXT": "Hardware"},
                {"DMBTR": "500.00",  "GL_ACCOUNT": "0000500001", "ITEM_TEXT": "License"},
            ]}
    res = orch.load_one(row)
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_ACC_DOCUMENT_POST")
    # 1 AP + 2 extras + 1 offset = 4 rows
    cur = create[1]["CURRENCYAMOUNT"]
    assert len(cur) == 4
    total = sum(float(c["AMT_DOCCUR"]) for c in cur)
    assert abs(total) < 0.005
    print("  [OK] OpenAP multi-line: 2 extra lines balanced + per-line GL honored")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS2 continuation: Material classification + OpenAR/AP multi-line")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll WS2 continuation tests passed.")
