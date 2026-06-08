"""
Unit tests for object-promotion grind batch 4:
  PurchaseRequisition / PurchaseOrder / PurchaseContract / SalesOrder.

Each covers the specific tricky shape for that transactional document:
  - PurchaseRequisition: internal numbering + ORG-context validation
  - PurchaseOrder: vendor harmonization via F1 PersistentKeyMap
  - PurchaseContract: TESTRUN-validated contract-capable vendor + caching
  - SalesOrder: coherent sales-area discovery (customer + material aligned)

Run:  python tests\test_spine_promotion_batch4.py
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
import purchase_requisition_spine    # noqa: F401
import purchase_order_spine          # noqa: F401
import purchase_contract_spine       # noqa: F401
import sales_order_spine             # noqa: F401
from purchase_requisition_spine import PurchaseRequisitionSpineOrchestrator   # noqa
from purchase_order_spine       import PurchaseOrderSpineOrchestrator         # noqa
from purchase_contract_spine    import PurchaseContractSpineOrchestrator      # noqa
from sales_order_spine          import SalesOrderSpineOrchestrator            # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
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
    """Minimal PersistentKeyMap stand-in."""
    def __init__(self, seed: Optional_dict=None):
        self.store: dict = dict(seed or {})
        self.adds: list = []

    def resolve(self, object_type: str, src_key: str):
        return self.store.get((object_type, src_key))

    def add(self, object_type: str, src_key: str, tgt_key: str, disposition: str):
        self.store[(object_type, src_key)] = tgt_key
        self.adds.append((object_type, src_key, tgt_key, disposition))


# python 3.9 has no PEP 604; alias kept simple
Optional_dict = type(None)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
def test_all_4_batch4_objects_register():
    for obj, cls in (
        ("PurchaseRequisition", PurchaseRequisitionSpineOrchestrator),
        ("PurchaseOrder", PurchaseOrderSpineOrchestrator),
        ("PurchaseContract", PurchaseContractSpineOrchestrator),
        ("SalesOrder", SalesOrderSpineOrchestrator),
    ):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-4 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# PurchaseRequisition
# ─────────────────────────────────────────────────────────────────────────────
PR_ORG = {"PUR_GROUP": "001", "PLANT": "1710", "PO_UNIT": "EA",
          "MATL_GROUP": "L001", "GL_ACCOUNT": "0000400000",
          "COSTCENTER": "1710001", "DOC_TYPE": "NB"}


def test_pr_happy_path_captures_sap_number():
    rfc = FakeRfc()
    rfc.script("BAPI_REQUISITION_CREATE",
                {"RETURN": [{"TYPE": "S"}], "NUMBER": "1000000123"})
    orch = PurchaseRequisitionSpineOrchestrator(rfc, cc_org=PR_ORG)
    res = orch.load_one({"BANFN": "SRC_PR_1", "TXZ01": "Office chairs",
                          "MENGE": "10", "PREIS": "120"})
    assert res.status == DISP_CREATED
    assert res.target_key == "1000000123"
    assert res.source_key == "SRC_PR_1"
    print("  [OK] PR happy path captures SAP-assigned NUMBER")


def test_pr_missing_org_context_dead_letters():
    rfc = FakeRfc()
    orch = PurchaseRequisitionSpineOrchestrator(rfc, cc_org={})
    res = orch.load_one({"BANFN": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    assert any("cc_org" in m for m in res.messages)
    print("  [OK] PR missing cc_org -> DQ dead-letter with reason")


def test_pr_bapi_error_rolls_back():
    rfc = FakeRfc()
    rfc.script("BAPI_REQUISITION_CREATE",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "PR creation failed"}]})
    orch = PurchaseRequisitionSpineOrchestrator(rfc, cc_org=PR_ORG)
    res = orch.load_one({"BANFN": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_BAPI
    assert any(c[0] == "BAPI_TRANSACTION_ROLLBACK" for c in rfc.calls)
    print("  [OK] PR BAPI error -> rolls back + dead-letter BAPI_FAILURE")


# ─────────────────────────────────────────────────────────────────────────────
# PurchaseOrder
# ─────────────────────────────────────────────────────────────────────────────
PO_ORG = {"PURCH_ORG": "1710", "PUR_GROUP": "001", "PLANT": "1710",
          "PO_UNIT": "EA", "MATL_GROUP": "L001", "GL_ACCOUNT": "0000400000",
          "COSTCENTER": "1710001", "COMP_CODE": "1710", "DOC_TYPE": "NB",
          "CURRENCY": "USD"}


def test_po_happy_path_with_registry_vendor():
    rfc = FakeRfc()
    # Vendor 100001 is the ready pool member and resolves via registry
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "100001"}, {"WA": "100002"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500000001"})
    km = FakeKeyMap({("Vendor", "SRC_VND_1"): "100001"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    res = orch.load_one({
        "EBELN": "SRC_PO_1", "LIFNR": "SRC_VND_1", "WAERS": "USD",
        "items": [{"MATNR": "MAT001", "MENGE": "10", "NETPR": "5"}],
    })
    assert res.status == DISP_CREATED
    assert res.target_key == "4500000001"
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    assert create[1]["POHEADER"]["VENDOR"] == "100001"   # registry win
    # No harmonization message (registry path)
    assert not any("harmonized" in m for m in res.messages)
    print("  [OK] PO registry vendor used + target PO captured")


def test_po_harmonizes_when_registry_vendor_not_ready():
    rfc = FakeRfc()
    # Ready pool returned by RFC_READ_TABLE
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "100001"}, {"WA": "100002"}, {"WA": "100003"}]})
    rfc.script("BAPI_PO_CREATE1",
                {"RETURN": [{"TYPE": "S"}], "EXPPURCHASEORDER": "4500000002"})
    # Registry resolves to a vendor NOT in the ready pool
    km = FakeKeyMap({("Vendor", "SRC_VND_9"): "999999"})
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=km)
    res = orch.load_one({
        "EBELN": "SRC_PO_9", "LIFNR": "SRC_VND_9",
        "items": [{"MATNR": "M", "MENGE": "1"}],
    })
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_PO_CREATE1")
    assert create[1]["POHEADER"]["VENDOR"] in ("100001", "100002", "100003")
    assert any("harmonized" in m for m in res.messages)
    # Registry got a new harmonized entry
    assert any(a[0] == "Vendor" and a[3] == "harmonized" for a in km.adds)
    print("  [OK] PO harmonizes when registry vendor missing from ready pool")


def test_po_no_supplier_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})   # no ready suppliers
    orch = PurchaseOrderSpineOrchestrator(rfc, cc_org=PO_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"EBELN": "X", "LIFNR": "V",
                          "items": [{"MATNR": "M"}]})
    assert res.status == DISP_DEAD_LETTER
    assert any("no purchasing-ready supplier" in m for m in res.messages)
    print("  [OK] PO no ready supplier -> dead-letter")


def test_po_no_items_dead_letters_dq():
    orch = PurchaseOrderSpineOrchestrator(FakeRfc(), cc_org=PO_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"EBELN": "X", "LIFNR": "V", "items": []})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] PO no items -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# PurchaseContract
# ─────────────────────────────────────────────────────────────────────────────
CT_ORG = {"PURCH_ORG": "1710", "PUR_GROUP": "001", "PLANT": "1710",
          "PO_UNIT": "EA", "MATL_GROUP": "L001", "COMP_CODE": "1710"}


def test_contract_happy_path_with_testrun_validated_vendor():
    rfc = FakeRfc()

    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "LFM1":
                return {"DATA": [{"WA": "100001"}, {"WA": "100002"}]}
            if qt == "T001":
                return {"DATA": [{"WA": "USD"}]}   # company-code currency
        if fn == "BAPI_CONTRACT_CREATE":
            if kwargs.get("TESTRUN") == "X":
                return {"RETURN": [{"TYPE": "S"}]}   # registry preferred vendor validates
            return {"RETURN": [{"TYPE": "S"}], "PURCHASINGDOCUMENT": "4600000001"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Vendor", "SRC_VND_1"): "100001"})
    orch = PurchaseContractSpineOrchestrator(rfc, cc_org=CT_ORG, key_map=km)
    res = orch.load_one({"EBELN": "SRC_CT_1", "LIFNR": "SRC_VND_1", "BSART": "MK"})
    assert res.status == DISP_CREATED
    assert res.target_key == "4600000001"
    # Currency was normalized to T001 USD
    create_calls = [c for c in rfc.calls if c[0] == "BAPI_CONTRACT_CREATE"
                    and c[1].get("TESTRUN") != "X"]
    assert create_calls[0][1]["HEADER"]["CURRENCY"] == "USD"
    print("  [OK] PurchaseContract happy path: registry vendor passes TESTRUN + USD currency")


def test_contract_falls_through_to_capable_vendor_when_registry_fails():
    rfc = FakeRfc()
    # 100001 is permanently blocked; 100002 is capable
    blocked = {"0000100001"}

    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "LFM1":
                return {"DATA": [{"WA": "100001"}, {"WA": "100002"}, {"WA": "100003"}]}
            if qt == "T001":
                return {"DATA": [{"WA": "EUR"}]}
        if fn == "BAPI_CONTRACT_CREATE":
            vendor = (kwargs.get("HEADER") or {}).get("VENDOR", "")
            if kwargs.get("TESTRUN") == "X":
                if vendor in blocked:
                    return {"RETURN": [{"TYPE": "E", "MESSAGE": "vendor blocked"}]}
                return {"RETURN": [{"TYPE": "S"}]}
            # Real create only fires for the capable vendor
            return {"RETURN": [{"TYPE": "S"}], "PURCHASINGDOCUMENT": "4600000002"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Vendor", "SRC_VND_X"): "100001"})
    orch = PurchaseContractSpineOrchestrator(rfc, cc_org=CT_ORG, key_map=km)
    res = orch.load_one({"EBELN": "SRC_CT_X", "LIFNR": "SRC_VND_X", "BSART": "MK"})
    assert res.status == DISP_CREATED
    real_calls = [c for c in rfc.calls if c[0] == "BAPI_CONTRACT_CREATE"
                  and c[1].get("TESTRUN") != "X"]
    assert real_calls[0][1]["HEADER"]["VENDOR"].lstrip("0") in ("100002", "100003")
    assert any("harmonized" in m for m in res.messages)
    print("  [OK] PurchaseContract falls through to capable vendor + records harmonization")


def test_contract_no_capable_vendor_dead_letters():
    rfc = FakeRfc()

    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "LFM1":
                return {"DATA": [{"WA": "100001"}, {"WA": "100002"}]}
            if qt == "T001":
                return {"DATA": [{"WA": "USD"}]}
        if fn == "BAPI_CONTRACT_CREATE":
            return {"RETURN": [{"TYPE": "E", "MESSAGE": "all vendors blocked"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = PurchaseContractSpineOrchestrator(rfc, cc_org=CT_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"EBELN": "X", "LIFNR": "V", "BSART": "MK"})
    assert res.status == DISP_DEAD_LETTER
    assert any("no contract-capable supplier" in m for m in res.messages)
    print("  [OK] PurchaseContract no capable vendor -> dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# SalesOrder
# ─────────────────────────────────────────────────────────────────────────────
def test_so_happy_path_with_discovered_sales_area():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV":
                return {"DATA": [{"WA": "0010000001|1710|10|00"},
                                  {"WA": "0010000002|1710|10|00"}]}
            if qt == "MVKE":
                return {"DATA": [{"WA": "MAT1710A|1710|10"}]}
            if qt == "VBAK":
                return {"DATA": [{"WA": "TA"}, {"WA": "TA"}, {"WA": "OR"}]}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000001234"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "SRC_C_1"): "0010000001"})
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_SO_1", "KUNNR": "SRC_C_1"})
    assert res.status == DISP_CREATED
    assert res.target_key == "5000001234"
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    assert create[1]["ORDER_HEADER_IN"]["SALES_ORG"] == "1710"
    assert create[1]["ORDER_HEADER_IN"]["DOC_TYPE"] == "TA"
    assert create[1]["ORDER_PARTNERS"][0]["PARTN_NUMB"].lstrip("0") == "10000001"
    print("  [OK] SalesOrder discovered sales area 1710/10/00 + registry customer used")


def test_so_harmonizes_when_registry_customer_not_in_sales_area():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV":
                return {"DATA": [{"WA": "0010000001|1710|10|00"},
                                  {"WA": "0010000002|1710|10|00"}]}
            if qt == "MVKE":
                return {"DATA": [{"WA": "MAT1710A|1710|10"}]}
            if qt == "VBAK":
                return {"DATA": []}
        if fn == "BAPI_SALESORDER_CREATEFROMDAT2":
            return {"RETURN": [{"TYPE": "S"}], "SALESDOCUMENT": "5000005678"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    km = FakeKeyMap({("Customer", "SRC_C_X"): "9999999999"})   # not in pool
    orch = SalesOrderSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"VBELN": "SRC_SO_X", "KUNNR": "SRC_C_X"})
    assert res.status == DISP_CREATED
    assert any("harmonized" in m for m in res.messages)
    # Registry got the harmonized entry
    assert any(a[0] == "Customer" and a[3] == "harmonized" for a in km.adds)
    # Default order type fallback
    create = next(c for c in rfc.calls if c[0] == "BAPI_SALESORDER_CREATEFROMDAT2")
    assert create[1]["ORDER_HEADER_IN"]["DOC_TYPE"] == "TA"
    print("  [OK] SalesOrder harmonizes when registry customer missing + default DOC_TYPE TA")


def test_so_no_coherent_sales_area_dead_letters():
    rfc = FakeRfc()
    # KNVV has customers in 1710/10/00 but MVKE has materials in 9999/99 — NO overlap
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "KNVV":
                return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE":
                return {"DATA": [{"WA": "MAT9999|9999|99"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = SalesOrderSpineOrchestrator(rfc)
    res = orch.load_one({"VBELN": "SRC_SO_DEAD", "KUNNR": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert any("coherent target sales area" in m for m in res.messages)
    assert all(c[0] != "BAPI_SALESORDER_CREATEFROMDAT2" for c in rfc.calls)
    print("  [OK] SalesOrder no aligned customer+material -> dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting dry-run
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch4():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "LFM1": return {"DATA": [{"WA": "100001"}]}
            if qt == "T001": return {"DATA": [{"WA": "USD"}]}
            if qt == "KNVV": return {"DATA": [{"WA": "0010000001|1710|10|00"}]}
            if qt == "MVKE": return {"DATA": [{"WA": "MAT|1710|10"}]}
            return {"DATA": []}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    cases = (
        (PurchaseRequisitionSpineOrchestrator,
            {"BANFN": "DRY"}, {"cc_org": PR_ORG}),
        (PurchaseOrderSpineOrchestrator,
            {"EBELN": "DRY", "LIFNR": "V", "items": [{"MATNR": "M"}]},
            {"cc_org": PO_ORG, "key_map": FakeKeyMap()}),
        (PurchaseContractSpineOrchestrator,
            {"EBELN": "DRY", "LIFNR": "V", "BSART": "MK"},
            {"cc_org": CT_ORG, "key_map": FakeKeyMap()}),
        (SalesOrderSpineOrchestrator,
            {"VBELN": "DRY", "KUNNR": "C"}, {}),
    )
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run"), f"{cls.__name__} got {res.disposition}"
    # No write BAPI fired
    write_bapis = [c[0] for c in rfc.calls if c[0] in (
        "BAPI_REQUISITION_CREATE", "BAPI_PO_CREATE1",
        "BAPI_SALESORDER_CREATEFROMDAT2",
    )]
    assert not write_bapis, f"dry-run should skip writes; got {write_bapis}"
    print("  [OK] dry-run mode skips writes for all 4 batch-4 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 4 - PR / PO / Contract / SalesOrder")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-4 spine promotion tests passed.")
