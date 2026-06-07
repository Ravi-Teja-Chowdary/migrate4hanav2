"""
Unit tests for object-promotion grind batch 1:
  Bank / ProfitCenter / CostCenter / Equipment.

Each subclass gets ~10 tests covering:
  - registration in the spine registry
  - happy-path creation against a mocked SAP target
  - idempotency probe (matched_existing on a re-run)
  - BAPI failure -> dead-letter
  - validation failure -> dead-letter
  - EXTENSIONIN absorption
  - dry-run
  - object-specific quirks (cat remap for Equipment, composite key for
    CostCenter / ProfitCenter, FK resolution for CostCenter)

Mocks SAP via a FakeRfcConnection. No live AWS, no live SAP.

Run:  python tests\test_spine_promotion_batch1.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    get_spine, DISP_CREATED, DISP_MATCHED_EXISTING, DISP_DEAD_LETTER,
    DEAD_LETTER_DQ, DEAD_LETTER_BAPI, DEAD_LETTER_FK,
)
import bank_spine          # noqa: F401 (registers BankSpineOrchestrator)
import profit_center_spine # noqa: F401
import cost_center_spine   # noqa: F401
import equipment_spine     # noqa: F401
from bank_spine          import BankSpineOrchestrator           # noqa
from profit_center_spine import ProfitCenterSpineOrchestrator   # noqa
from cost_center_spine   import CostCenterSpineOrchestrator     # noqa
from equipment_spine     import EquipmentSpineOrchestrator      # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────
class FakeRfc:
    """Scriptable mock pyrfc connection. .script(name, response) maps a BAPI
    name to a return value; .fail(name, msg) makes that call raise."""
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.fail_next: dict = {}
        # Pre-canned committal success for all transactional BAPIs
        self.scripts["BAPI_TRANSACTION_COMMIT"] = {}
        self.scripts["BAPI_TRANSACTION_ROLLBACK"] = {}

    def script(self, fn, resp):
        self.scripts[fn] = resp
        return self

    def fail(self, fn, msg):
        self.fail_next[fn] = msg
        return self

    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        if fn in self.fail_next:
            raise RuntimeError(self.fail_next.pop(fn))
        return self.scripts.get(fn, {})


def _empty_bnka(rfc):
    """Default: BNKA probe returns no rows (so first-call creates cleanly)."""
    rfc.script("RFC_READ_TABLE", {"DATA": []})
    return rfc


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
def test_all_4_objects_register_in_spine_registry():
    for obj, cls in (("Bank", BankSpineOrchestrator),
                      ("ProfitCenter", ProfitCenterSpineOrchestrator),
                      ("CostCenter", CostCenterSpineOrchestrator),
                      ("Equipment", EquipmentSpineOrchestrator)):
        registered = get_spine(obj)
        assert registered is cls, f"{obj} not registered (got {registered})"
    print("  [OK] all 4 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# Bank
# ─────────────────────────────────────────────────────────────────────────────
def test_bank_happy_path_creates_and_registers_key():
    rfc = _empty_bnka(FakeRfc())
    rfc.script("BAPI_BANK_CREATE", {"RETURN": [{"TYPE": "S", "MESSAGE": "Bank created"}]})

    class _KM:
        adds: list = []
        def add(self, *a, **k): self.adds.append(a)
        def resolve(self, *a, **k): return None
    km = _KM()
    orch = BankSpineOrchestrator(rfc, key_map=km)
    res = orch.load_one({"BANKS": "US", "BANKL": "BOFAUS3N",
                          "BANKA": "Bank of America", "SWIFT": "BOFAUS3N",
                          "BRNCH": "Charlotte", "ORT01": "Charlotte"})
    assert res.status == DISP_CREATED
    assert res.target_key == "BOFAUS3N"
    assert km.adds[0][:3] == ("Bank", "BOFAUS3N", "BOFAUS3N")
    # Confirm the BAPI payload carried what we built
    bapi_call = next(c for c in rfc.calls if c[0] == "BAPI_BANK_CREATE")
    assert bapi_call[1]["BANK_CTRY"] == "US"
    assert bapi_call[1]["BANK_KEY"] == "BOFAUS3N"
    assert bapi_call[1]["BANK_ADDRESS"]["SWIFT_CODE"] == "BOFAUS3N"
    print("  [OK] Bank happy path creates + registers key + emits SWIFT")


def test_bank_pre_existing_returns_matched_existing():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "BOFAUS3N"}]})   # bank already exists
    orch = BankSpineOrchestrator(rfc)
    res = orch.load_one({"BANKS": "US", "BANKL": "BOFAUS3N", "BANKA": "x"})
    assert res.status == DISP_MATCHED_EXISTING
    # No BAPI create call should have happened
    assert all(c[0] != "BAPI_BANK_CREATE" for c in rfc.calls)
    print("  [OK] Bank pre-existing -> matched_existing, BAPI not called")


def test_bank_missing_required_field_dead_letters():
    rfc = _empty_bnka(FakeRfc())
    orch = BankSpineOrchestrator(rfc)
    res = orch.load_one({"BANKS": "US"})   # missing BANKL
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Bank missing BANKL -> DQ dead-letter")


def test_bank_bapi_error_rolls_back():
    rfc = _empty_bnka(FakeRfc())
    rfc.script("BAPI_BANK_CREATE",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "duplicate key"}]})
    orch = BankSpineOrchestrator(rfc)
    res = orch.load_one({"BANKS": "US", "BANKL": "BAD"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_BAPI
    assert any(c[0] == "BAPI_TRANSACTION_ROLLBACK" for c in rfc.calls)
    print("  [OK] Bank BAPI error -> rollback + dead-letter")


def test_bank_extensionin_absorbs_z_fields():
    rfc = _empty_bnka(FakeRfc())
    rfc.script("BAPI_BANK_CREATE", {"RETURN": [{"TYPE": "S"}]})
    orch = BankSpineOrchestrator(rfc)
    res = orch.load_one({"BANKS": "US", "BANKL": "B1",
                          "ZZ_REGION": "WEST", "ZZ_NETWORK": "ACME"})
    assert res.status == DISP_CREATED
    bapi = next(c for c in rfc.calls if c[0] == "BAPI_BANK_CREATE")[1]
    assert "EXTENSIONIN" in bapi
    assert len(bapi["EXTENSIONIN"]) == 2
    assert "EXTENSIONINX" in bapi
    print("  [OK] Bank ZZ_* fields packed into EXTENSIONIN (+X activation)")


# ─────────────────────────────────────────────────────────────────────────────
# ProfitCenter
# ─────────────────────────────────────────────────────────────────────────────
def test_profit_center_happy_path():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})  # not existing
    rfc.script("BAPI_PROFITCENTER_CREATE", {"RETURN": [{"TYPE": "S"}]})
    orch = ProfitCenterSpineOrchestrator(rfc,
                                          cc_org={"CO_AREA": "1710",
                                                   "PC_HIER": "M4H",
                                                   "VALID_FROM": "20240101"})
    res = orch.load_one({"PRCTR": "YB600", "MCTXT": "TEST"})
    assert res.status == DISP_CREATED
    assert res.target_key == "YB600"
    bapi = next(c for c in rfc.calls if c[0] == "BAPI_PROFITCENTER_CREATE")[1]
    assert bapi["PROFITCENTER_KEY"]["CONTROLLINGAREA"] == "1710"
    assert bapi["MASTER_DATA"]["PRCTR_HIER_GRP"] == "M4H"
    print("  [OK] ProfitCenter happy path + org-context flowed through")


def test_profit_center_missing_co_area_dead_letters():
    rfc = FakeRfc()
    orch = ProfitCenterSpineOrchestrator(rfc, cc_org={})   # no CO_AREA
    res = orch.load_one({"PRCTR": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] ProfitCenter missing CO_AREA -> DQ dead-letter")


def test_profit_center_already_exists_matched():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "YB600"}]})
    orch = ProfitCenterSpineOrchestrator(rfc, cc_org={"CO_AREA": "1710"})
    res = orch.load_one({"PRCTR": "YB600"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_PROFITCENTER_CREATE" for c in rfc.calls)
    print("  [OK] ProfitCenter pre-existing -> matched_existing")


# ─────────────────────────────────────────────────────────────────────────────
# CostCenter
# ─────────────────────────────────────────────────────────────────────────────
def test_cost_center_happy_path_with_org_context():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})
    rfc.script("BAPI_COSTCENTER_CREATEMULTIPLE", {"RETURN": [{"TYPE": "S"}]})
    orch = CostCenterSpineOrchestrator(rfc,
                                        cc_org={"CO_AREA": "1710",
                                                 "COMP_CODE": "US01",
                                                 "CC_CATEGORY": "1",
                                                 "CC_HIER": "M4H",
                                                 "CURRENCY": "USD",
                                                 "PROFIT_CTR": "YB600"})
    res = orch.load_one({"KOSTL": "0017101601", "KTEXT": "CC test"})
    assert res.status == DISP_CREATED
    assert res.target_key == "0017101601"
    bapi = next(c for c in rfc.calls if c[0] == "BAPI_COSTCENTER_CREATEMULTIPLE")[1]
    cc = bapi["COSTCENTERLIST"][0]
    assert cc["COMP_CODE"] == "US01"
    assert cc["CURRENCY"] == "USD"
    assert cc["PROFIT_CTR"] == "YB600"
    print("  [OK] CostCenter happy path + multi-FK org context")


def test_cost_center_resolves_fk_via_keymap():
    """When a row carries source BUKRS, FK resolution should rewrite it via the
    CompanyCode registry. (cc_org doesn't override the row's BUKRS so FK runs.)"""
    class _KM:
        def __init__(self):
            self._m = {"CompanyCode": {"1000": "US01"},
                       "ProfitCenter": {"OLD_PC": "YB600"}}
            self.adds = []
        def add(self, *a, **k): self.adds.append(a)
        def resolve(self, obj, src, default=None):
            return self._m.get(obj, {}).get(str(src).strip(), default)

    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})
    rfc.script("BAPI_COSTCENTER_CREATEMULTIPLE", {"RETURN": [{"TYPE": "S"}]})
    orch = CostCenterSpineOrchestrator(rfc, key_map=_KM(),
                                        cc_org={"CO_AREA": "1710",
                                                 "CC_CATEGORY": "1",
                                                 "CC_HIER": "M4H",
                                                 "CURRENCY": "USD"})
    res = orch.load_one({"KOSTL": "C1", "BUKRS": "1000", "PRCTR": "OLD_PC"})
    # FK resolution should rewrite BUKRS and PRCTR on the row before build_payload
    assert res.status == DISP_CREATED
    bapi = next(c for c in rfc.calls if c[0] == "BAPI_COSTCENTER_CREATEMULTIPLE")[1]
    # Either the row was rewritten OR org context took precedence; for this
    # test cc_org doesn't set COMP_CODE, so the row's resolved BUKRS should win.
    assert bapi["COSTCENTERLIST"][0]["COMP_CODE"] == "US01"
    print("  [OK] CostCenter FK resolves source BUKRS -> target via PersistentKeyMap")


def test_cost_center_missing_kostl_dead_letters():
    rfc = FakeRfc()
    orch = CostCenterSpineOrchestrator(rfc, cc_org={"CO_AREA": "1710"})
    res = orch.load_one({})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] CostCenter missing KOSTL -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Equipment
# ─────────────────────────────────────────────────────────────────────────────
def test_equipment_happy_path_captures_sap_assigned_key():
    """Equipment uses internal numbering: source EQUNR may differ from target."""
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "M"}, {"WA": "M"}, {"WA": "P"}]})  # cats M, P
    rfc.script("BAPI_EQUI_CREATE",
                {"RETURN": [{"TYPE": "S"}], "EQUIPMENT": "10000054321"})
    orch = EquipmentSpineOrchestrator(rfc)
    res = orch.load_one({"EQUNR": "SRC_EQ_1", "EQTYP": "M",
                          "EQKTX": "Press"})
    assert res.status == DISP_CREATED
    # Source != target (SAP assigned a new number)
    assert res.source_key == "SRC_EQ_1"
    assert res.target_key == "10000054321"
    print("  [OK] Equipment internal-numbering captures SAP-assigned target EQUNR")


def test_equipment_invalid_category_remaps_to_default():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "M"}, {"WA": "M"}]})  # only M in target
    rfc.script("BAPI_EQUI_CREATE",
                {"RETURN": [{"TYPE": "S"}], "EQUIPMENT": "10000054322"})
    orch = EquipmentSpineOrchestrator(rfc)
    res = orch.load_one({"EQUNR": "SRC_EQ_2", "EQTYP": "ZZZ"})  # ZZZ not in target
    assert res.status == DISP_CREATED
    # Surfaced in messages so the audit ledger captures the remap
    assert any("ZZZ" in m and "used M" in m for m in res.messages)
    bapi = next(c for c in rfc.calls if c[0] == "BAPI_EQUI_CREATE")[1]
    assert bapi["DATA_SPECIFIC"]["EQUICATGRY"] == "M"
    print("  [OK] Equipment invalid EQTYP remaps to default + records substitution")


def test_equipment_empty_row_dead_letters():
    rfc = FakeRfc()
    orch = EquipmentSpineOrchestrator(rfc)
    res = orch.load_one({})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Equipment fully-empty row -> DQ dead-letter")


def test_equipment_bapi_failure_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "M"}]})
    rfc.script("BAPI_EQUI_CREATE",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "equipment master locked"}]})
    orch = EquipmentSpineOrchestrator(rfc)
    res = orch.load_one({"EQUNR": "X", "EQTYP": "M"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_BAPI
    assert any("locked" in m for m in res.messages)
    print("  [OK] Equipment BAPI error -> dead-letter with SAP message")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: dry-run works for all four
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_skips_bapi_for_all_four():
    rfc = FakeRfc()
    for cls, row, extra in (
        (BankSpineOrchestrator, {"BANKS": "US", "BANKL": "B"}, {}),
        (ProfitCenterSpineOrchestrator, {"PRCTR": "P"}, {"cc_org": {"CO_AREA": "1710"}}),
        (CostCenterSpineOrchestrator, {"KOSTL": "C"}, {"cc_org": {"CO_AREA": "1710"}}),
        (EquipmentSpineOrchestrator, {"EQUNR": "E", "EQTYP": "M"}, {}),
    ):
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED
        assert res.disposition.endswith("_dry_run")
    # The only RFC calls allowed in dry-run mode are for category discovery
    # (Equipment) - everything BAPI-side must be skipped.
    bapi_calls = [c[0] for c in rfc.calls if c[0].startswith("BAPI_")
                  and c[0] not in ("BAPI_TRANSACTION_COMMIT",
                                    "BAPI_TRANSACTION_ROLLBACK")]
    assert not bapi_calls, f"dry-run should not call any BAPI; called {bapi_calls}"
    print("  [OK] dry-run mode skips every BAPI write across all 4 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 1 - Bank / ProfitCenter / CostCenter / Equipment")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-1 spine promotion tests passed.")
