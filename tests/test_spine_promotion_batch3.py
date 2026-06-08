"""
Unit tests for object-promotion grind batch 3:
  Characteristic / Class / CostElementGroup / ProfitCenterGroup.

Each covers the specific tricky shape:
  - Characteristic: global-key preservation + data-type fallback to CHAR
  - Class: customizing prerequisite (KLART must be in TCLA) + composite key
  - CostElementGroup: 12-char SETNAME limit + chart-of-accounts discovery
  - ProfitCenterGroup: 12-char SETNAME limit + CO_AREA from cc_org

Run:  python tests\test_spine_promotion_batch3.py
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
import characteristic_spine        # noqa: F401
import class_spine                  # noqa: F401
import cost_element_group_spine    # noqa: F401
import profit_center_group_spine   # noqa: F401
from characteristic_spine       import CharacteristicSpineOrchestrator       # noqa
from class_spine                 import ClassSpineOrchestrator                # noqa
from cost_element_group_spine   import CostElementGroupSpineOrchestrator    # noqa
from profit_center_group_spine  import ProfitCenterGroupSpineOrchestrator   # noqa


# ─────────────────────────────────────────────────────────────────────────────
class FakeRfc:
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.fail_next: dict = {}
        self.scripts["BAPI_TRANSACTION_COMMIT"] = {}
        self.scripts["BAPI_TRANSACTION_ROLLBACK"] = {}
        self.scripts["RFC_READ_TABLE"] = {"DATA": []}

    def script(self, fn, resp):
        self.scripts[fn] = resp
        return self

    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        if fn in self.fail_next:
            raise RuntimeError(self.fail_next.pop(fn))
        return self.scripts.get(fn, {})


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
def test_all_4_batch3_objects_register():
    for obj, cls in (("Characteristic", CharacteristicSpineOrchestrator),
                      ("Class", ClassSpineOrchestrator),
                      ("CostElementGroup", CostElementGroupSpineOrchestrator),
                      ("ProfitCenterGroup", ProfitCenterGroupSpineOrchestrator)):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-3 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# Characteristic
# ─────────────────────────────────────────────────────────────────────────────
def test_characteristic_happy_path_preserves_name():
    rfc = FakeRfc()
    rfc.script("BAPI_CHARACT_CREATE", {"RETURN": [{"TYPE": "S"}]})
    orch = CharacteristicSpineOrchestrator(rfc)
    res = orch.load_one({"ATNAM": "color", "ATFOR": "CHAR",
                          "ANZST": "10", "ATBEZ": "Color characteristic"})
    assert res.status == DISP_CREATED
    assert res.source_key == "color"     # source preserved as-given
    assert res.target_key == "COLOR"     # but uppercased on the wire
    print("  [OK] Characteristic happy path preserves uppercased name")


def test_characteristic_unknown_dtype_falls_back_to_char():
    rfc = FakeRfc()
    rfc.script("BAPI_CHARACT_CREATE", {"RETURN": [{"TYPE": "S"}]})
    orch = CharacteristicSpineOrchestrator(rfc)
    res = orch.load_one({"ATNAM": "MYCHAR", "ATFOR": "XYZ"})
    assert res.status == DISP_CREATED
    assert any("XYZ" in m and "used CHAR" in m for m in res.messages)
    # Confirm payload was CHAR
    create_call = next(c for c in rfc.calls if c[0] == "BAPI_CHARACT_CREATE")
    assert create_call[1]["CHARACTDETAIL"]["DATA_TYPE"] == "CHAR"
    print("  [OK] Characteristic unknown ATFOR -> falls back to CHAR + audit msg")


def test_characteristic_pre_existing_matched():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "0001"}]})   # CABN probe returns row
    orch = CharacteristicSpineOrchestrator(rfc)
    res = orch.load_one({"ATNAM": "EXISTS"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_CHARACT_CREATE" for c in rfc.calls)
    print("  [OK] Characteristic pre-existing ATNAM -> matched_existing")


def test_characteristic_missing_name_dead_letters():
    orch = CharacteristicSpineOrchestrator(FakeRfc())
    res = orch.load_one({"ATFOR": "CHAR"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Characteristic missing ATNAM -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Class
# ─────────────────────────────────────────────────────────────────────────────
def test_class_happy_path_with_configured_type():
    rfc = FakeRfc()
    # TCLA probe returns class types; KLAH probe returns no row (not pre-existing)
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCLA":
                return {"DATA": [{"WA": "001"}, {"WA": "023"}, {"WA": "300"}]}
            if qt == "KLAH":
                return {"DATA": []}
        if fn == "BAPI_CLASS_CREATE":
            return {"RETURN": [{"TYPE": "S"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ClassSpineOrchestrator(rfc)
    res = orch.load_one({"CLASS": "MY_CLASS", "KLART": "001", "KSCHL": "My class"})
    assert res.status == DISP_CREATED
    assert res.target_key == "MY_CLASS"
    print("  [OK] Class with target-configured KLART -> created")


def test_class_unknown_class_type_dead_letters_customizing():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCLA":
                return {"DATA": [{"WA": "001"}, {"WA": "023"}]}   # 300 NOT configured
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ClassSpineOrchestrator(rfc)
    res = orch.load_one({"CLASS": "MY_PMCAT", "KLART": "300"})
    assert res.status == DISP_DEAD_LETTER
    # Confirm BAPI_CLASS_CREATE was NEVER called (customizing prerequisite)
    assert all(c[0] != "BAPI_CLASS_CREATE" for c in rfc.calls)
    assert any("300" in m and "TCLA" in m for m in res.messages)
    print("  [OK] Class unknown KLART -> customizing-prerequisite dead-letter")


def test_class_missing_klart_dead_letters_dq():
    orch = ClassSpineOrchestrator(FakeRfc())
    res = orch.load_one({"CLASS": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Class missing KLART -> DQ dead-letter")


def test_class_pre_existing_matched():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCLA":
                return {"DATA": [{"WA": "001"}]}
            if qt == "KLAH":
                return {"DATA": [{"WA": "0000123"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ClassSpineOrchestrator(rfc)
    res = orch.load_one({"CLASS": "MY_CLS", "KLART": "001"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_CLASS_CREATE" for c in rfc.calls)
    print("  [OK] Class pre-existing (CLASS, KLART) -> matched_existing")


# ─────────────────────────────────────────────────────────────────────────────
# CostElementGroup
# ─────────────────────────────────────────────────────────────────────────────
def test_cost_element_group_happy_path_with_discovered_chart():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "T001":
                return {"DATA": [{"WA": "YCOA"}, {"WA": "YCOA"}, {"WA": "INT"}]}
            if qt == "SETHEADER":
                return {"DATA": []}
        if fn == "BAPI_COSTELEMENTGRP_CREATE":
            return {"RETURN": [{"TYPE": "S"}], "GROUPNAME": "MYCOST"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = CostElementGroupSpineOrchestrator(rfc)
    res = orch.load_one({"SETNAME": "MYCOST", "DESCRIPT": "My cost group"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_COSTELEMENTGRP_CREATE")
    assert create[1]["CHARTOFACCOUNTSIMP"] == "YCOA"   # most-common from T001
    assert create[1].get("TOPNODEONLY") == "X"          # no VALUES given
    print("  [OK] CostElementGroup auto-discovers chart YCOA + top-node only")


def test_cost_element_group_name_too_long_dead_letters():
    rfc = FakeRfc()
    orch = CostElementGroupSpineOrchestrator(rfc)
    res = orch.load_one({"SETNAME": "WAYTOOLONGNAME"})
    assert res.status == DISP_DEAD_LETTER
    assert any("12-char" in m for m in res.messages)
    assert all(c[0] != "BAPI_COSTELEMENTGRP_CREATE" for c in rfc.calls)
    print("  [OK] CostElementGroup name > 12 chars -> dead-letter (manual rename)")


def test_cost_element_group_with_values_uses_hierarchyvalues():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "T001":
                return {"DATA": [{"WA": "YCOA"}]}
            if qt == "SETHEADER":
                return {"DATA": []}
        if fn == "BAPI_COSTELEMENTGRP_CREATE":
            return {"RETURN": [{"TYPE": "S"}], "GROUPNAME": "MYCOST"}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = CostElementGroupSpineOrchestrator(rfc)
    res = orch.load_one({"SETNAME": "MYCOST",
                          "VALUES": [["400000", "499999"], ["600000", "609999"]]})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_COSTELEMENTGRP_CREATE")
    assert "HIERARCHYVALUES" in create[1]
    assert len(create[1]["HIERARCHYVALUES"]) == 2
    assert "TOPNODEONLY" not in create[1]
    print("  [OK] CostElementGroup with VALUES emits HIERARCHYVALUES (not top-node)")


def test_cost_element_group_no_chart_discovered_dead_letters():
    rfc = FakeRfc()
    # T001 empty -> no chart
    orch = CostElementGroupSpineOrchestrator(rfc)
    res = orch.load_one({"SETNAME": "MYCOST"})
    assert res.status == DISP_DEAD_LETTER
    assert any("chart" in m.lower() for m in res.messages)
    print("  [OK] CostElementGroup no chart discovered -> dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# ProfitCenterGroup
# ─────────────────────────────────────────────────────────────────────────────
def test_profit_center_group_happy_path():
    rfc = FakeRfc()
    rfc.script("BAPI_PROFITCENTERGRP_CREATE",
                {"RETURN": [{"TYPE": "S"}], "GROUPNAME": "PCGROUP"})
    orch = ProfitCenterGroupSpineOrchestrator(rfc, cc_org={"CO_AREA": "1710"})
    res = orch.load_one({"SETNAME": "PCGROUP", "DESCRIPT": "PC hierarchy"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_PROFITCENTERGRP_CREATE")
    assert create[1]["CONTROLLINGAREAIMP"] == "1710"
    assert create[1].get("TOPNODEONLY") == "X"
    print("  [OK] ProfitCenterGroup happy path with CO_AREA from cc_org")


def test_profit_center_group_missing_co_area_dead_letters():
    orch = ProfitCenterGroupSpineOrchestrator(FakeRfc(), cc_org={})
    res = orch.load_one({"SETNAME": "PCGROUP"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] ProfitCenterGroup missing CO_AREA -> DQ dead-letter")


def test_profit_center_group_pre_existing_matched():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "PCGROUP"}]})
    orch = ProfitCenterGroupSpineOrchestrator(rfc, cc_org={"CO_AREA": "1710"})
    res = orch.load_one({"SETNAME": "PCGROUP"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_PROFITCENTERGRP_CREATE" for c in rfc.calls)
    print("  [OK] ProfitCenterGroup pre-existing SETNAME -> matched_existing")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: dry-run
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch3():
    rfc = FakeRfc()
    # Seed the customizing/discovery probes so the dry-run path can build payload
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCLA":   return {"DATA": [{"WA": "001"}]}
            if qt == "T001":   return {"DATA": [{"WA": "YCOA"}]}
            return {"DATA": []}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    cases = (
        (CharacteristicSpineOrchestrator,       {"ATNAM": "DRY"},                          {}),
        (ClassSpineOrchestrator,                {"CLASS": "DRY", "KLART": "001"},          {}),
        (CostElementGroupSpineOrchestrator,    {"SETNAME": "DRY"},                        {}),
        (ProfitCenterGroupSpineOrchestrator,   {"SETNAME": "DRY"},                        {"cc_org": {"CO_AREA": "1710"}}),
    )
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run"), f"{cls.__name__} got {res.disposition}"
    # No write BAPI should have been called
    write_bapis = [c[0] for c in rfc.calls if c[0] in (
        "BAPI_CHARACT_CREATE", "BAPI_CLASS_CREATE",
        "BAPI_COSTELEMENTGRP_CREATE", "BAPI_PROFITCENTERGRP_CREATE",
    )]
    assert not write_bapis, f"dry-run should skip writes; got {write_bapis}"
    print("  [OK] dry-run mode skips writes for all 4 batch-3 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 3 - Characteristic / Class / CostElementGroup / ProfitCenterGroup")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-3 spine promotion tests passed.")
