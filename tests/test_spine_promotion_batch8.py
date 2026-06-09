"""
Unit tests for object-promotion grind batch 8:
  Inquiry / BillingDocument / PlannedOrder / ProductionBOM.

Covers tricky shapes:
  - Inquiry: SO-shape mirror, DOC_TYPE='AF'
  - BillingDoc: ref-doc resolution via SalesOrder OR OutboundDelivery registry
                based on REF_TYPE field
  - PlannedOrder: MATNR resolution + PLNUM target capture
  - ProductionBOM: dual-resolve (parent + every child) with unresolved-count metric

Run:  python tests\test_spine_promotion_batch8.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    get_spine, DISP_CREATED, DISP_DEAD_LETTER, DEAD_LETTER_DQ, DEAD_LETTER_BAPI,
)
import inquiry_spine                 # noqa: F401
import billing_document_spine        # noqa: F401
import planned_order_spine           # noqa: F401
import production_bom_spine          # noqa: F401
from inquiry_spine             import InquirySpineOrchestrator             # noqa
from billing_document_spine    import BillingDocumentSpineOrchestrator     # noqa
from planned_order_spine       import PlannedOrderSpineOrchestrator        # noqa
from production_bom_spine      import ProductionBOMSpineOrchestrator       # noqa


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

    def resolve(self, obj, src):
        return self.store.get((obj, src))

    def add(self, obj, src, tgt, disp):
        self.store[(obj, src)] = tgt
        self.adds.append((obj, src, tgt, disp))


def test_all_4_batch8_register():
    for obj, cls in (
        ("Inquiry", InquirySpineOrchestrator),
        ("BillingDocument", BillingDocumentSpineOrchestrator),
        ("PlannedOrder", PlannedOrderSpineOrchestrator),
        ("ProductionBOM", ProductionBOMSpineOrchestrator),
    ):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-8 spine subclasses registered")


def test_inquiry_uses_doc_type_af():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
        if fn == "BAPI_INQUIRY_CREATEFROMDATA":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "1000001"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched
    km = FakeKeyMap({("Customer", "C"): "0010000001"})
    orch = InquirySpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_INQ_1", "KUNNR": "C"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_INQUIRY_CREATEFROMDATA")
    assert create[1]["INQUIRY_HEADER_IN"]["DOC_TYPE"] == "AF"
    print("  [OK] Inquiry uses DOC_TYPE='AF' on the wire")


def test_billing_doc_resolves_via_so_registry_for_REF_TYPE_SO():
    rfc = FakeRfc()
    rfc.script("BAPI_BILLINGDOC_CREATEMULTIPLE",
                {"RETURN": [{"TYPE": "S"}],
                 "SUCCESS": [{"BILL_DOC": "9000000123"}]})
    km = FakeKeyMap({("SalesOrder", "SRC_SO"): "TGT_SO_001"})
    orch = BillingDocumentSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_BIL", "REF_VBELN": "SRC_SO",
                          "REF_TYPE": "SO", "FKART": "F2"})
    assert res.status == DISP_CREATED
    assert res.target_key == "9000000123"
    create = next(c for c in rfc.calls if c[0] == "BAPI_BILLINGDOC_CREATEMULTIPLE")
    assert create[1]["BILLINGDATAIN"][0]["REF_DOC"] == "TGT_SO_001"
    assert create[1]["BILLINGDATAIN"][0]["REF_DOC_CA"] == "C"   # order ref
    print("  [OK] BillingDocument REF_TYPE=SO routes to SalesOrder registry + CA=C")


def test_billing_doc_resolves_via_delivery_registry_for_REF_TYPE_DLV():
    rfc = FakeRfc()
    rfc.script("BAPI_BILLINGDOC_CREATEMULTIPLE",
                {"RETURN": [{"TYPE": "S"}],
                 "SUCCESS": [{"BILL_DOC": "9000000124"}]})
    km = FakeKeyMap({("OutboundDelivery", "SRC_DLV"): "TGT_DLV_001"})
    orch = BillingDocumentSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_BIL2", "REF_VBELN": "SRC_DLV",
                          "REF_TYPE": "DLV"})
    create = next(c for c in rfc.calls if c[0] == "BAPI_BILLINGDOC_CREATEMULTIPLE")
    assert create[1]["BILLINGDATAIN"][0]["REF_DOC"] == "TGT_DLV_001"
    assert create[1]["BILLINGDATAIN"][0]["REF_DOC_CA"] == "M"   # delivery ref
    print("  [OK] BillingDocument REF_TYPE=DLV routes to OutboundDelivery registry + CA=M")


def test_billing_doc_missing_ref_dq_rejects():
    orch = BillingDocumentSpineOrchestrator(FakeRfc(), key_map=FakeKeyMap())
    res = orch.load_one({"VBELN": "X"})
    assert res.status == DISP_DEAD_LETTER and res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] BillingDocument missing REF_VBELN -> DQ dead-letter")


def test_planned_order_captures_target_plnum():
    rfc = FakeRfc()
    rfc.script("BAPI_PLANNEDORDER_CREATE",
                {"RETURN": [{"TYPE": "S"}], "PLANNEDORDER": "0010000001"})
    km = FakeKeyMap({("Material", "MAT_SRC"): "MAT_TGT"})
    orch = PlannedOrderSpineOrchestrator(rfc, cc_org={"PLANT": "1710"},
                                          key_map=km)
    res = orch.load_one({"PLNUM": "X", "MATNR": "MAT_SRC", "GSMNG": "100"})
    assert res.status == DISP_CREATED
    assert res.target_key == "0010000001"
    create = next(c for c in rfc.calls if c[0] == "BAPI_PLANNEDORDER_CREATE")
    assert create[1]["PLAF_DATA"]["MATERIAL"] == "MAT_TGT"
    assert create[1]["PLAF_DATA"]["ORDER_QTY"] == "100"
    print("  [OK] PlannedOrder captures SAP-assigned PLNUM + F1-resolves MATNR")


def test_production_bom_resolves_parent_and_each_child():
    rfc = FakeRfc()
    rfc.script("CSAP_MAT_BOM_CREATE",
                {"RETURN": [{"TYPE": "S"}], "BOM_NO": "00000000123"})
    km = FakeKeyMap({
        ("Material", "PARENT_SRC"): "PARENT_TGT",
        ("Material", "CHILD_A"):    "CHILD_A_TGT",
        # CHILD_B intentionally unresolved
        ("Material", "CHILD_C"):    "CHILD_C_TGT",
    })
    orch = ProductionBOMSpineOrchestrator(rfc, cc_org={"PLANT": "1710"},
                                            key_map=km)
    res = orch.load_one({"MATNR": "PARENT_SRC", "STLAN": "1", "STLAL": "01",
                          "components": [
                              {"IDNRK": "CHILD_A", "MENGE": "2"},
                              {"IDNRK": "CHILD_B", "MENGE": "5"},
                              {"IDNRK": "CHILD_C", "MENGE": "1"},
                          ]})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "CSAP_MAT_BOM_CREATE")
    assert create[1]["MATERIAL"] == "PARENT_TGT"
    items = create[1]["ITEMS"]
    assert items[0]["COMPONENT"] == "CHILD_A_TGT"   # resolved
    assert items[1]["COMPONENT"] == "CHILD_B"        # unresolved -> forwarded
    assert items[2]["COMPONENT"] == "CHILD_C_TGT"   # resolved
    assert any("1 BOM component" in m for m in res.messages)
    print("  [OK] ProductionBOM resolves parent + each child + reports unresolved")


def test_production_bom_empty_components_dq_rejects():
    orch = ProductionBOMSpineOrchestrator(FakeRfc(), cc_org={"PLANT": "1710"})
    res = orch.load_one({"MATNR": "P", "components": []})
    assert res.status == DISP_DEAD_LETTER
    print("  [OK] ProductionBOM empty components -> DQ dead-letter")


def test_dry_run_across_batch8():
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
        (InquirySpineOrchestrator,         {"VBELN": "DRY", "KUNNR": "C"}, {}),
        (BillingDocumentSpineOrchestrator, {"VBELN": "DRY", "REF_VBELN": "SO"},
            {"key_map": FakeKeyMap()}),
        (PlannedOrderSpineOrchestrator,    {"PLNUM": "DRY", "MATNR": "M", "GSMNG": "1"},
            {"cc_org": {"PLANT": "1710"}, "key_map": FakeKeyMap()}),
        (ProductionBOMSpineOrchestrator,   {"MATNR": "P",
                                             "components": [{"IDNRK": "C", "MENGE": "1"}]},
            {"cc_org": {"PLANT": "1710"}}),
    )
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run")
    write_bapis = [c[0] for c in rfc.calls if c[0] in (
        "BAPI_INQUIRY_CREATEFROMDATA", "BAPI_BILLINGDOC_CREATEMULTIPLE",
        "BAPI_PLANNEDORDER_CREATE", "CSAP_MAT_BOM_CREATE")]
    assert not write_bapis
    print("  [OK] dry-run mode skips writes for all 4 batch-8 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 8 - Inquiry / BillingDoc / PlannedOrder / ProductionBOM")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-8 spine promotion tests passed.")
