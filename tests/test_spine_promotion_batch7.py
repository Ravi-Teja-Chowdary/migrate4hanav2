"""
Unit tests for object-promotion grind batch 7:
  WorkCenter / InfoRecord / Quotation / OutboundDelivery.

First batch BEYOND live-25 -- expanding to PP, deeper MM, and SD docs.
Tricky shapes covered:
  - WorkCenter: WERKS-gated idempotency probe + capacity category default
  - InfoRecord: dual F1 resolution (Material + Vendor) before BAPI
  - Quotation: SO-shape mirror with QUOTATION_HEADER_IN + DOC_TYPE=AG
  - OutboundDelivery: F1-resolves the referenced sales order before
    create-from-SO BAPI

Run:  python tests\test_spine_promotion_batch7.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    get_spine, DISP_CREATED, DISP_MATCHED_EXISTING,
    DISP_DEAD_LETTER, DEAD_LETTER_DQ, DEAD_LETTER_BAPI,
)
import work_center_spine             # noqa: F401
import info_record_spine             # noqa: F401
import quotation_spine               # noqa: F401
import outbound_delivery_spine       # noqa: F401
from work_center_spine        import WorkCenterSpineOrchestrator         # noqa
from info_record_spine        import InfoRecordSpineOrchestrator         # noqa
from quotation_spine          import QuotationSpineOrchestrator          # noqa
from outbound_delivery_spine  import OutboundDeliverySpineOrchestrator   # noqa


# ─────────────────────────────────────────────────────────────────────────────
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
        self.adds = []

    def resolve(self, obj, src):
        return self.store.get((obj, src))

    def add(self, obj, src, tgt, disp):
        self.store[(obj, src)] = tgt
        self.adds.append((obj, src, tgt, disp))


# ─────────────────────────────────────────────────────────────────────────────
def test_all_4_batch7_objects_register():
    for obj, cls in (
        ("WorkCenter", WorkCenterSpineOrchestrator),
        ("InfoRecord", InfoRecordSpineOrchestrator),
        ("Quotation",  QuotationSpineOrchestrator),
        ("OutboundDelivery", OutboundDeliverySpineOrchestrator),
    ):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-7 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# WorkCenter
# ─────────────────────────────────────────────────────────────────────────────
def test_wc_happy_path_creates_and_emits_verify_key():
    rfc = FakeRfc()
    rfc.script("BAPI_WORKCENTER_CREATE", {"RETURN": [{"TYPE": "S"}]})
    orch = WorkCenterSpineOrchestrator(rfc, cc_org={"PLANT": "1710"})
    res = orch.load_one({"ARBPL": "WC001", "KTEXT": "Test work center"})
    assert res.status == DISP_CREATED
    assert res.target_key == "WC001"
    assert res.verify_key and res.verify_key["table"] == "CRHD"
    assert res.verify_key["key"]["WERKS"] == "1710"
    print("  [OK] WorkCenter happy path + verify_key CRHD/WERKS+ARBPL")


def test_wc_already_exists_returns_matched_existing():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "WC001"}]})   # exists
    orch = WorkCenterSpineOrchestrator(rfc, cc_org={"PLANT": "1710"})
    res = orch.load_one({"ARBPL": "WC001"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_WORKCENTER_CREATE" for c in rfc.calls)
    print("  [OK] WorkCenter pre-existing -> matched_existing (skip BAPI)")


def test_wc_missing_plant_dead_letters_dq():
    orch = WorkCenterSpineOrchestrator(FakeRfc(), cc_org={})
    res = orch.load_one({"ARBPL": "X"})
    assert res.status == DISP_DEAD_LETTER and res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] WorkCenter missing PLANT -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# InfoRecord
# ─────────────────────────────────────────────────────────────────────────────
def test_info_record_resolves_both_material_and_vendor():
    rfc = FakeRfc()
    rfc.script("BAPI_INFORECORD_CREATE",
                {"RETURN": [{"TYPE": "S"}], "INFO_RECORD": "5300000001"})
    km = FakeKeyMap({
        ("Material", "MAT_SRC"): "MAT_TGT",
        ("Vendor",   "VND_SRC"): "100001",
    })
    orch = InfoRecordSpineOrchestrator(rfc, cc_org={"PURCH_ORG": "1710"},
                                         key_map=km)
    res = orch.load_one({"INFNR": "SRC_IR_1", "MATNR": "mat_src",
                          "LIFNR": "VND_SRC", "EKORG": "1710",
                          "NETPR": "100"})
    assert res.status == DISP_CREATED
    assert res.target_key == "5300000001"
    create = next(c for c in rfc.calls if c[0] == "BAPI_INFORECORD_CREATE")
    # F1-resolved material + vendor on the wire
    assert create[1]["GENERAL_DATA"]["MATERIAL"] == "MAT_TGT"
    assert create[1]["GENERAL_DATA"]["VENDOR"].lstrip("0") == "100001"
    assert any("F1" in m for m in res.messages)
    print("  [OK] InfoRecord dual F1 resolution (Material + Vendor) on wire")


def test_info_record_unresolved_falls_through_to_source_keys():
    rfc = FakeRfc()
    rfc.script("BAPI_INFORECORD_CREATE",
                {"RETURN": [{"TYPE": "S"}], "INFO_RECORD": "5300000002"})
    orch = InfoRecordSpineOrchestrator(rfc, cc_org={"PURCH_ORG": "1710"},
                                         key_map=FakeKeyMap())
    res = orch.load_one({"INFNR": "X", "MATNR": "M", "LIFNR": "V", "EKORG": "1710"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_INFORECORD_CREATE")
    assert create[1]["GENERAL_DATA"]["MATERIAL"] == "M"
    print("  [OK] InfoRecord unresolved -> source keys forwarded (BAPI judges)")


def test_info_record_missing_matnr_dead_letters():
    orch = InfoRecordSpineOrchestrator(FakeRfc(), cc_org={"PURCH_ORG": "1710"})
    res = orch.load_one({"INFNR": "X", "LIFNR": "V", "EKORG": "1710"})
    assert res.status == DISP_DEAD_LETTER
    print("  [OK] InfoRecord missing MATNR -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Quotation
# ─────────────────────────────────────────────────────────────────────────────
def test_quotation_happy_path_with_doc_type_AG():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_QUOTATION_CREATEFROMDATA":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "2000001"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = QuotationSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_Q_1", "KUNNR": "C"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_QUOTATION_CREATEFROMDATA")
    assert create[1]["QUOTATION_HEADER_IN"]["DOC_TYPE"] == "AG"
    print("  [OK] Quotation happy path (sales-area discovery + DOC_TYPE=AG)")


def test_quotation_multi_item_uses_row_items_list():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_QUOTATION_CREATEFROMDATA":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "2000002"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "C"): "0010000001",
                      ("Material", "M1"): "MAT_T_1"})
    orch = QuotationSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "Q", "KUNNR": "C",
                          "items": [{"MATNR": "M1", "MENGE": "5"},
                                     {"MATNR": "M2", "MENGE": "10"}]})
    create = next(c for c in rfc.calls if c[0] == "BAPI_QUOTATION_CREATEFROMDATA")
    items = create[1]["QUOTATION_ITEMS_IN"]
    assert len(items) == 2
    assert items[0]["MATERIAL"] == "MAT_T_1"   # F1-resolved
    assert items[1]["MATERIAL"] == "MAT"        # harmonized to sample
    print("  [OK] Quotation multi-item w/ F1 resolution + harmonize fallback")


# ─────────────────────────────────────────────────────────────────────────────
# OutboundDelivery
# ─────────────────────────────────────────────────────────────────────────────
def test_obd_resolves_referenced_sales_order():
    rfc = FakeRfc()
    rfc.script("BAPI_OUTB_DELIVERY_CREATESLS",
                {"RETURN": [{"TYPE": "S"}], "DELIVERY": "8000001"})
    km = FakeKeyMap({("SalesOrder", "SRC_SO_1"): "0000006789"})
    orch = OutboundDeliverySpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_DLV_1", "VBELN_VL": "SRC_SO_1",
                          "POSNR": "10", "LFIMG": "5"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_OUTB_DELIVERY_CREATESLS")
    item = create[1]["SALES_ORDER_ITEMS"][0]
    assert item["REF_DOC"] == "0000006789"   # F1-resolved SO
    assert item["DLV_QTY"] == "5"
    print("  [OK] OutboundDelivery F1-resolves referenced SO before BAPI")


def test_obd_missing_referenced_so_dead_letters():
    orch = OutboundDeliverySpineOrchestrator(FakeRfc(), key_map=FakeKeyMap())
    res = orch.load_one({"VBELN": "X"})
    assert res.status == DISP_DEAD_LETTER and res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] OutboundDelivery missing VBELN_VL -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch7():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
            return {"DATA": []}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    cases = (
        (WorkCenterSpineOrchestrator,
            {"ARBPL": "DRY"}, {"cc_org": {"PLANT": "1710"}}),
        (InfoRecordSpineOrchestrator,
            {"INFNR": "DRY", "MATNR": "M", "LIFNR": "V", "EKORG": "1710"},
            {"cc_org": {"PURCH_ORG": "1710"}, "key_map": FakeKeyMap()}),
        (QuotationSpineOrchestrator,
            {"VBELN": "DRY", "KUNNR": "C"}, {}),
        (OutboundDeliverySpineOrchestrator,
            {"VBELN": "DRY", "VBELN_VL": "SO"}, {}),
    )
    write_bapis = []
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run")
    # No write BAPI fired
    assert not [c[0] for c in rfc.calls if c[0] in (
        "BAPI_WORKCENTER_CREATE", "BAPI_INFORECORD_CREATE",
        "BAPI_QUOTATION_CREATEFROMDATA", "BAPI_OUTB_DELIVERY_CREATESLS")]
    print("  [OK] dry-run mode skips writes for all 4 batch-7 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 7 - WorkCenter / InfoRecord / Quotation / OutboundDelivery")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-7 spine promotion tests passed.")
