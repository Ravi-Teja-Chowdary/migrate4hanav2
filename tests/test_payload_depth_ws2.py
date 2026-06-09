"""
Unit tests for WS2 payload-depth expansion across SalesOrder + PurchaseOrder.

Verifies the spine subclasses now accept and correctly route:
  - Multi-line items (row["items"])
  - Multi-role partner functions (row["partners"]) via F1 resolution
  - Pricing conditions (row["conditions"])
  - Long texts (row["texts"]) for post-create BAPI_LONGTEXT_SAVE

The base shape (single item, sold-to-only / vendor-only, no conditions,
no texts) must still work unchanged so existing batch-4 tests stay green
(verified separately by running test_spine_promotion_batch4.py).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import DISP_CREATED   # noqa
import sales_order_spine             # noqa: F401
import purchase_order_spine          # noqa: F401
from sales_order_spine    import SalesOrderSpineOrchestrator   # noqa
from purchase_order_spine import PurchaseOrderSpineOrchestrator   # noqa


class FakeRfc:
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.scripts["BAPI_TRANSACTION_COMMIT"] = {}
        self.scripts["BAPI_TRANSACTION_ROLLBACK"] = {}
        self.scripts["RFC_READ_TABLE"] = {"DATA": []}

    def script(self, fn, resp):
        self.scripts[fn] = resp
        return self

    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        return self.scripts.get(fn, {})


class FakeKeyMap:
    def __init__(self, seed=None):
        self.store = dict(seed or {})
        self.adds: list = []

    def resolve(self, obj, src):
        return self.store.get((obj, src))

    def add(self, obj, src, tgt, disp):
        self.store[(obj, src)] = tgt
        self.adds.append((obj, src, tgt, disp))


PO_ORG = {"PURCH_ORG": "1710", "PUR_GROUP": "001", "PLANT": "1710",
          "PO_UNIT": "EA", "MATL_GROUP": "L001", "GL_ACCOUNT": "0000400000",
          "COSTCENTER": "1710001", "COMP_CODE": "1710", "DOC_TYPE": "NB",
          "CURRENCY": "USD"}


# ─────────────────────────────────────────────────────────────────────────────
# SalesOrder depth
# ─────────────────────────────────────────────────────────────────────────────
def test_so_multi_item_uses_row_items_list():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT1710A|1710|10"}]}
            if qt == "VBAK": return {"DATA": [{"WA": "TA"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000001"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "SRC_C_1"): "0010000001",
                      ("Material", "M1"): "MAT_TGT_1",
                      ("Material", "M2"): "MAT_TGT_2"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    row = {"VBELN": "SRC_SO_1", "KUNNR": "SRC_C_1",
           "items": [
               {"MATNR": "M1", "MENGE": "5", "MEINS": "PC"},
               {"MATNR": "M2", "MENGE": "10", "MEINS": "KG"},
               {"MATNR": "UNRESOLVED_M", "MENGE": "1", "MEINS": "EA"},
           ]}
    res = orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    items = create[1]["ORDER_ITEMS_IN"]
    assert len(items) == 3
    assert items[0]["MATERIAL"] == "MAT_TGT_1"   # resolved through F1
    assert items[0]["TARGET_QTY"] == "5"
    assert items[1]["MATERIAL"] == "MAT_TGT_2"
    assert items[2]["MATERIAL"] == "MAT1710A"    # harmonized -> sample saleable
    sched = create[1]["ORDER_SCHEDULES_IN"]
    assert len(sched) == 3 and sched[0]["ITM_NUMBER"] == "000010"
    print("  [OK] SalesOrder multi-item from row['items'] with F1 resolution + harmonize")


def test_so_partners_extends_with_extra_roles():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000002"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "SRC_C_1"): "0010000001",
                      ("Customer", "RE_PAYER"): "0010000099",
                      ("Customer", "WE_SHIP"):  "0010000077"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    row = {"VBELN": "SO", "KUNNR": "SRC_C_1",
           "partners": [
               {"PARVW": "RE", "KUNNR": "RE_PAYER"},
               {"PARVW": "WE", "KUNNR": "WE_SHIP"},
               {"PARVW": "AG", "KUNNR": "SRC_C_1"},   # explicit AG — must NOT duplicate
           ]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    parts = create[1]["ORDER_PARTNERS"]
    roles = [p["PARTN_ROLE"] for p in parts]
    assert roles.count("AG") == 1   # NOT doubled
    assert "RE" in roles and "WE" in roles
    re_part = next(p for p in parts if p["PARTN_ROLE"] == "RE")
    assert re_part["PARTN_NUMB"].lstrip("0") == "10000099"   # F1-resolved
    print("  [OK] SalesOrder partners: extra roles routed through F1, AG not doubled")


def test_so_conditions_emit_order_conditions_in():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000003"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    row = {"VBELN": "SO", "KUNNR": "C",
           "conditions": [
               {"ITEM": 10, "KSCHL": "PR00", "KBETR": "100.00", "WAERS": "USD"},
               {"ITEM": 20, "KSCHL": "K007", "KBETR": "5.00",   "WAERS": "USD"},
           ]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    conds = create[1].get("ORDER_CONDITIONS_IN") or []
    assert len(conds) == 2
    assert conds[0]["COND_TYPE"] == "PR00" and conds[0]["ITM_NUMBER"] == "000010"
    assert conds[1]["COND_TYPE"] == "K007" and conds[1]["ITM_NUMBER"] == "000020"
    print("  [OK] SalesOrder conditions -> ORDER_CONDITIONS_IN with per-item ITM_NUMBER")


def test_so_texts_emit_longtexts_for_post_create():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000004"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    row = {"VBELN": "SO", "KUNNR": "C",
           "texts": [
               {"TDOBJECT": "VBBK", "TDID": "0001", "TDLINE": "Header note 1"},
               {"TDOBJECT": "VBBK", "TDID": "0001", "TDLINE": "Header note 2"},
               {"TDOBJECT": "VBBP", "TDID": "0002", "TDLINE": ""},   # empty -> filtered
           ]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    texts = create[1].get("LONGTEXTS") or []
    assert len(texts) == 2   # empty filtered
    assert texts[0]["TDLINE"] == "Header note 1"
    print("  [OK] SalesOrder texts -> LONGTEXTS (empty TDLINE filtered)")


def test_so_base_shape_still_works_without_arrays():
    """Backward-compat: row with no items/partners/conditions/texts still
    produces a valid single-item / sold-to-only SO."""
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000005"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SO_BASE", "KUNNR": "C"})
    assert res.target_key == "5000005"
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    assert len(create[1]["ORDER_ITEMS_IN"]) == 1
    assert "ORDER_CONDITIONS_IN" not in create[1]
    assert "LONGTEXTS" not in create[1]
    print("  [OK] SalesOrder base shape (no arrays) still works -- backward-compat")


# ─────────────────────────────────────────────────────────────────────────────
# PurchaseOrder depth
# ─────────────────────────────────────────────────────────────────────────────
def test_po_partners_routed_via_f1_to_pa_buspartno():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE",
                {"DATA": [{"WA": "100001"}, {"WA": "100002"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500001"})
    km = FakeKeyMap({("Vendor", "V"):     "100001",
                      ("Vendor", "GS_V"):  "100002",
                      ("Vendor", "RS_V"):  "100003"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    row = {"EBELN": "PO", "LIFNR": "V",
           "items": [{"MATNR": "M", "MENGE": "1"}],
           "partners": [
               {"PARVW": "GS", "LIFNR": "GS_V"},   # goods supplier
               {"PARVW": "RS", "LIFNR": "RS_V"},   # invoicing party (unresolved)
           ]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    pa = create[1].get("POPARTNER") or []
    assert len(pa) == 2
    descs = [p["PARTNERDESC"] for p in pa]
    assert "GS" in descs and "RS" in descs
    gs = next(p for p in pa if p["PARTNERDESC"] == "GS")
    assert gs["BUSPARTNO"].lstrip("0") == "100002"
    print("  [OK] PurchaseOrder partners -> POPARTNER routed through F1")


def test_po_conditions_emit_pocond_per_item():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE",
                {"DATA": [{"WA": "100001"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500002"})
    km = FakeKeyMap({("Vendor", "V"): "100001"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    row = {"EBELN": "PO", "LIFNR": "V",
           "items": [{"MATNR": "M", "MENGE": "1"}],
           "conditions": [
               {"ITEM": 10, "KSCHL": "PB00", "KBETR": "50.00", "WAERS": "USD"},
               {"ITEM": 20, "KSCHL": "RA00", "KBETR": "2.50",  "WAERS": "USD"},
           ]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    conds = create[1].get("POCOND") or []
    assert len(conds) == 2
    assert conds[0]["COND_TYPE"] == "PB00"
    assert conds[1]["ITM_NUMBER"] == "000020"
    print("  [OK] PurchaseOrder conditions -> POCOND with per-item ITM_NUMBER")


def test_po_texts_emit_longtexts():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE",
                {"DATA": [{"WA": "100001"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500003"})
    km = FakeKeyMap({("Vendor", "V"): "100001"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    row = {"EBELN": "PO", "LIFNR": "V",
           "items": [{"MATNR": "M", "MENGE": "1"}],
           "texts": [{"TDOBJECT": "EKKO", "TDID": "F01", "TDLINE": "Header note"}]}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    texts = create[1].get("LONGTEXTS") or []
    assert len(texts) == 1
    print("  [OK] PurchaseOrder texts -> LONGTEXTS for BAPI_LONGTEXT_SAVE follow-up")


def test_po_base_shape_still_works_without_arrays():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "100001"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500004"})
    km = FakeKeyMap({("Vendor", "V"): "100001"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    res = orch.load_one({"EBELN": "PO_BASE", "LIFNR": "V",
                          "items": [{"MATNR": "M", "MENGE": "1"}]})
    assert res.target_key == "4500004"
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    # No optional WS2 sections when arrays absent
    assert "POPARTNER" not in create[1]
    assert "POCOND" not in create[1]
    assert "LONGTEXTS" not in create[1]
    print("  [OK] PurchaseOrder base shape (items only) still works")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: EXTENSIONIN routing for ZZ* custom fields
# ─────────────────────────────────────────────────────────────────────────────
def test_zz_field_routed_through_extensionin():
    """The base orchestrator's collect_custom_fields auto-detects ZZ*/YY*/
    CI_* prefixes and packs them as EXTENSIONIN entries. The SO spine then
    builds the parallel EXTENSIONINX activation array. Proves the
    auto-detection works without the subclass having to enumerate Z fields.
    """
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000006"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    row = {"VBELN": "SO_Z", "KUNNR": "C",
           # Custom Z and Y fields the source extracted from VBAK append
           "ZZ_CUSTOMER_TIER":  "GOLD",
           "ZZ_LEGACY_SAP_ID":  "ECC_VBELN_12345",
           "YY_RISK_FLAG":      "LOW",
           "CI_PARTNER_SCORE":  "87",
           # A field that is NOT a custom prefix -- should be ignored by EXTENSIONIN
           "ORDINARY_FIELD":    "should not be packed"}
    orch.load_one(row)
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    ext_in  = create[1].get("EXTENSIONIN") or []
    ext_inx = create[1].get("EXTENSIONINX") or []
    assert len(ext_in)  == 4   # ZZ_CUSTOMER_TIER, ZZ_LEGACY_SAP_ID, YY_RISK_FLAG, CI_PARTNER_SCORE
    assert len(ext_inx) == 4   # parallel X-mask
    # Every EXTENSIONIN row carries the configured struct name
    assert all(r["STRUCTURE"] == "BAPI_TE_VBAK" for r in ext_in)
    # ORDINARY_FIELD didn't sneak in
    names = [r["VALUEPART1"][:30].strip() for r in ext_in]
    assert "ORDINARY_FIELD" not in names
    print("  [OK] ZZ*/YY*/CI_* custom fields auto-routed through EXTENSIONIN (+ X-mask)")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS2 payload-depth tests (SalesOrder + PurchaseOrder + EXTENSIONIN)")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll WS2 payload-depth tests passed.")
