"""
Unit tests for object-promotion grind batch 5:
  OpenAR / OpenAP / Batch / InventoryBalance.

Tricky shapes covered:
  - OpenAR:  KNB1 recon-readiness probe + customer harmonization + BSID verify
  - OpenAP:  LFB1 recon-readiness probe + vendor harmonization + BSIK verify
  - Batch:   batch-managed (MARC.XCHPF='X') material harmonization + CHARG
              collision-safe (max 10 chars, 999-attempt cap)
  - InventoryBalance: material/plant/sloc discovery (MARD) + MM-period
              self-heal (parses "period YYYY/MM" from BAPI message and
              retries on the 15th of that period)

Run:  python tests\test_spine_promotion_batch5.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    get_spine, DISP_CREATED, DISP_MATCHED_EXISTING, DISP_REMAPPED,
    DISP_DEAD_LETTER, DEAD_LETTER_DQ, DEAD_LETTER_BAPI,
)
import open_ar_spine             # noqa: F401
import open_ap_spine             # noqa: F401
import batch_spine               # noqa: F401
import inventory_balance_spine   # noqa: F401
from open_ar_spine            import OpenARSpineOrchestrator               # noqa
from open_ap_spine            import OpenAPSpineOrchestrator               # noqa
from batch_spine              import BatchSpineOrchestrator                # noqa
from inventory_balance_spine  import InventoryBalanceSpineOrchestrator     # noqa


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
def test_all_4_batch5_objects_register():
    for obj, cls in (
        ("OpenAR", OpenARSpineOrchestrator),
        ("OpenAP", OpenAPSpineOrchestrator),
        ("Batch", BatchSpineOrchestrator),
        ("InventoryBalance", InventoryBalanceSpineOrchestrator),
    ):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-5 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAR
# ─────────────────────────────────────────────────────────────────────────────
AR_ORG = {"COMP_CODE": "1710", "CLEARING_GL": "0000199990",
          "PROFIT_CTR": "YB600", "USERNAME": "MIGRATE_ADMI"}


def test_open_ar_happy_with_registry_customer():
    rfc = FakeRfc()
    # KNB1 returns 2 recon-ready customers; registry resolves to one of them
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0010000001"}, {"WA": "0010000002"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9000000123" + "1710" + "2026"})
    km = FakeKeyMap({("Customer", "SRC_AR_C1"): "0010000001"})
    orch = OpenARSpineOrchestrator(rfc, cc_org=AR_ORG, key_map=km)
    res = orch.load_one({"BELNR": "SRC_AR_1", "KUNNR": "SRC_AR_C1",
                          "DMBTR": "1234.56", "SHKZG": "S", "WAERS": "USD"})
    assert res.status == DISP_CREATED, res.messages
    assert res.target_key == "9000000123"   # BELNR(10) sliced from OBJ_KEY
    create = next(c for c in rfc.calls if c[0] == "BAPI_ACC_DOCUMENT_POST")
    assert create[1]["ACCOUNTRECEIVABLE"][0]["CUSTOMER"] == "0010000001"
    # GL offset balanced
    cur = create[1]["CURRENCYAMOUNT"]
    assert float(cur[0]["AMT_DOCCUR"]) + float(cur[1]["AMT_DOCCUR"]) == 0
    print("  [OK] OpenAR registry customer + balanced FI posting + BSID-keyed")


def test_open_ar_harmonizes_when_registry_customer_not_recon_ready():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0010000001"}, {"WA": "0010000002"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9000000124" + "1710" + "2026"})
    km = FakeKeyMap({("Customer", "SRC_AR_X"): "9999999999"})   # not in KNB1 pool
    orch = OpenARSpineOrchestrator(rfc, cc_org=AR_ORG, key_map=km)
    res = orch.load_one({"BELNR": "SRC_AR_2", "KUNNR": "SRC_AR_X",
                          "DMBTR": "500.00", "SHKZG": "S"})
    assert res.status == DISP_CREATED
    assert any("harmonized" in m for m in res.messages)
    assert any(a[0] == "Customer" and a[3] == "harmonized" for a in km.adds)
    print("  [OK] OpenAR harmonizes when registry customer not recon-ready")


def test_open_ar_no_recon_pool_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})   # empty KNB1
    orch = OpenARSpineOrchestrator(rfc, cc_org=AR_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"BELNR": "X", "KUNNR": "C", "DMBTR": "100"})
    assert res.status == DISP_DEAD_LETTER
    assert any("no recon-ready" in m for m in res.messages)
    print("  [OK] OpenAR no recon-ready customer pool -> dead-letter")


def test_open_ar_zero_amount_dq_rejects():
    orch = OpenARSpineOrchestrator(FakeRfc(), cc_org=AR_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"BELNR": "X", "KUNNR": "C", "DMBTR": "0"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] OpenAR zero open amount -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAP
# ─────────────────────────────────────────────────────────────────────────────
AP_ORG = {"COMP_CODE": "1710", "CLEARING_GL": "0000199991",
          "PROFIT_CTR": "YB600", "USERNAME": "MIGRATE_ADMI"}


def test_open_ap_happy_uses_vendor_payable_table():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0000100001"}, {"WA": "0000100002"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "S"}], "OBJ_KEY": "9100000200" + "1710" + "2026"})
    km = FakeKeyMap({("Vendor", "SRC_AP_V1"): "0000100001"})
    orch = OpenAPSpineOrchestrator(rfc, cc_org=AP_ORG, key_map=km)
    res = orch.load_one({"BELNR": "SRC_AP_1", "LIFNR": "SRC_AP_V1",
                          "DMBTR": "2500.00", "SHKZG": "H", "WAERS": "USD"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_ACC_DOCUMENT_POST")
    # AP uses ACCOUNTPAYABLE / VENDOR_NO, NOT ACCOUNTRECEIVABLE / CUSTOMER
    assert "ACCOUNTPAYABLE" in create[1]
    assert "ACCOUNTRECEIVABLE" not in create[1]
    assert create[1]["ACCOUNTPAYABLE"][0]["VENDOR_NO"] == "0000100001"
    assert create[1]["DOCUMENTHEADER"]["DOC_TYPE"] == "KR"
    print("  [OK] OpenAP uses ACCOUNTPAYABLE + DOC_TYPE=KR (not AR's DR)")


def test_open_ap_missing_lifnr_dq_rejects():
    orch = OpenAPSpineOrchestrator(FakeRfc(), cc_org=AP_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"BELNR": "X", "DMBTR": "100"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] OpenAP missing LIFNR -> DQ dead-letter")


def test_open_ap_bapi_error_rolls_back():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0000100001"}]})
    rfc.script("BAPI_ACC_DOCUMENT_POST",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "vendor blocked"}], "OBJ_KEY": "$"})
    orch = OpenAPSpineOrchestrator(rfc, cc_org=AP_ORG, key_map=FakeKeyMap())
    res = orch.load_one({"BELNR": "X", "LIFNR": "V", "DMBTR": "100", "SHKZG": "H"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_BAPI
    assert any(c[0] == "BAPI_TRANSACTION_ROLLBACK" for c in rfc.calls)
    print("  [OK] OpenAP BAPI error -> rollback + BAPI_FAILURE dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Batch
# ─────────────────────────────────────────────────────────────────────────────
def test_batch_happy_path_preserves_charg_when_free():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "MARC":
                return {"DATA": [{"WA": "TGT_MAT|1710"}]}
            if qt == "MCH1":
                return {"DATA": []}   # no collision
        if fn == "BAPI_BATCH_CREATE":
            return {"RETURN": [{"TYPE": "S"}], "BATCH": "B001"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = BatchSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "SRC_MAT", "CHARG": "B001"})
    # tgt_mat differs from src_mat -> REMAPPED
    assert res.status == DISP_REMAPPED
    assert res.target_key == "B001"
    assert any("harmonized" in m for m in res.messages)
    print("  [OK] Batch preserves CHARG when free + records material harmonization")


def test_batch_collision_safe_suffix():
    rfc = FakeRfc()
    collisions = {"B001"}
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "MARC":
                return {"DATA": [{"WA": "TGT_MAT|1710"}]}
            if qt == "MCH1":
                opt = (kwargs.get("OPTIONS") or [{}])[0].get("TEXT", "")
                charg = None
                if "CHARG = '" in opt:
                    charg = opt.split("CHARG = '")[1].split("'")[0]
                return {"DATA": [{"WA": "x"}] if charg in collisions else []}
        if fn == "BAPI_BATCH_CREATE":
            return {"RETURN": [{"TYPE": "S"}], "BATCH": kwargs.get("BATCH")}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = BatchSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "SRC_MAT", "CHARG": "B001"})
    assert res.status == DISP_REMAPPED
    assert res.target_key == "B001_1"   # collision -> suffix
    assert any("collided" in m for m in res.messages)
    print("  [OK] Batch collision-safe suffix when source CHARG taken")


def test_batch_no_target_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})   # no batch-managed material
    orch = BatchSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "X", "CHARG": "B"})
    assert res.status == DISP_DEAD_LETTER
    assert any("target batch-managed" in m for m in res.messages)
    print("  [OK] Batch no target batch-managed material -> dead-letter")


def test_batch_missing_charg_dq_rejects():
    orch = BatchSpineOrchestrator(FakeRfc())
    res = orch.load_one({"MATNR": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Batch missing CHARG -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# InventoryBalance
# ─────────────────────────────────────────────────────────────────────────────
def test_inventory_balance_happy_path_with_harmonization():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            return {"DATA": [{"WA": "TGT_MAT|1710|0001"}]}
        if fn == "BAPI_GOODSMVT_CREATE":
            return {"RETURN": [{"TYPE": "S"}],
                    "MATERIALDOCUMENT": "5000099999", "MATDOCUMENTYEAR": "2026"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = InventoryBalanceSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "SRC_MAT", "LABST": "50.000", "MEINS": "EA"})
    assert res.status == DISP_REMAPPED   # material harmonized
    assert res.target_key == "TGT_MAT@5000099999/2026"
    assert any("harmonized" in m for m in res.messages)
    create = next(c for c in rfc.calls if c[0] == "BAPI_GOODSMVT_CREATE")
    assert create[1]["GOODSMVT_ITEM"][0]["MOVE_TYPE"] == "561"
    assert create[1]["GOODSMVT_CODE"]["GM_CODE"] == "05"
    print("  [OK] InventoryBalance happy path + material harmonization + mvt 561")


def test_inventory_balance_mm_period_self_heal():
    rfc = FakeRfc()
    posts = {"n": 0}
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            return {"DATA": [{"WA": "TGT_MAT|1710|0001"}]}
        if fn == "BAPI_GOODSMVT_CREATE":
            posts["n"] += 1
            # First post: period closed error; second: success
            if posts["n"] == 1:
                return {"RETURN": [{"TYPE": "E",
                                     "MESSAGE": "Posting period 2025/03 is not open"}]}
            return {"RETURN": [{"TYPE": "S"}],
                    "MATERIALDOCUMENT": "5000099998", "MATDOCUMENTYEAR": "2025"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = InventoryBalanceSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "TGT_MAT", "LABST": "10", "MEINS": "EA"})
    assert res.status == DISP_CREATED
    assert posts["n"] == 2   # initial attempt + retry on the parsed period
    # The retry should have used pdate=20250315 (15th of YYYY/MM)
    retry_call = [c for c in rfc.calls if c[0] == "BAPI_GOODSMVT_CREATE"][1]
    assert retry_call[1]["GOODSMVT_HEADER"]["PSTNG_DATE"] == "20250315"
    # And the cache should now be set
    assert getattr(orch, "_mm_pdate", "") == "20250315"
    print("  [OK] InventoryBalance MM-period self-heal: parses YYYY/MM + retries on 15th")


def test_inventory_balance_no_target_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})
    orch = InventoryBalanceSpineOrchestrator(rfc)
    res = orch.load_one({"MATNR": "X", "LABST": "1"})
    assert res.status == DISP_DEAD_LETTER
    assert any("material/plant" in m for m in res.messages)
    print("  [OK] InventoryBalance no target material/plant/sloc -> dead-letter")


def test_inventory_balance_zero_qty_dq_rejects():
    orch = InventoryBalanceSpineOrchestrator(FakeRfc())
    res = orch.load_one({"MATNR": "X", "LABST": "0"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] InventoryBalance zero/negative LABST -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting dry-run
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch5():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt in ("KNB1", "LFB1"): return {"DATA": [{"WA": "0010000001"}]}
            if qt == "MARC":           return {"DATA": [{"WA": "TGT|1710"}]}
            if qt == "MARD":           return {"DATA": [{"WA": "TGT|1710|0001"}]}
            if qt == "MCH1":           return {"DATA": []}
            return {"DATA": []}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    cases = (
        (OpenARSpineOrchestrator,
            {"BELNR": "DRY", "KUNNR": "C", "DMBTR": "100"},
            {"cc_org": AR_ORG, "key_map": FakeKeyMap()}),
        (OpenAPSpineOrchestrator,
            {"BELNR": "DRY", "LIFNR": "V", "DMBTR": "100"},
            {"cc_org": AP_ORG, "key_map": FakeKeyMap()}),
        (BatchSpineOrchestrator,
            {"MATNR": "M", "CHARG": "B"}, {}),
        (InventoryBalanceSpineOrchestrator,
            {"MATNR": "M", "LABST": "10"}, {}),
    )
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run"), f"{cls.__name__} got {res.disposition}"
    # No write-BAPI fired
    write_bapis = [c[0] for c in rfc.calls if c[0] in (
        "BAPI_ACC_DOCUMENT_POST", "BAPI_BATCH_CREATE", "BAPI_GOODSMVT_CREATE",
    )]
    assert not write_bapis, f"dry-run should skip writes; got {write_bapis}"
    print("  [OK] dry-run mode skips writes for all 4 batch-5 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 5 - OpenAR / OpenAP / Batch / InventoryBalance")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-5 spine promotion tests passed.")
