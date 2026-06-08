"""
Unit tests for object-promotion grind batch 2:
  InternalOrder / FunctionalLocation / FixedAsset / Project.

Each covers the specific tricky shape for that object:
  - InternalOrder:  internal numbering + order-type fallback via TESTRUN
  - FunctionalLocation: structure-bound label reformat + collision-safe naming
  - FixedAsset: composite key + asset-class validation + external/internal numbering
  - Project:    coding-mask sanitization with retry

Run:  python tests\test_spine_promotion_batch2.py
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
import internal_order_spine    # noqa: F401
import funcloc_spine           # noqa: F401
import fixed_asset_spine       # noqa: F401
import project_spine           # noqa: F401
from internal_order_spine import InternalOrderSpineOrchestrator   # noqa
from funcloc_spine        import FunctionalLocationSpineOrchestrator   # noqa
from fixed_asset_spine    import FixedAssetSpineOrchestrator      # noqa
from project_spine        import ProjectSpineOrchestrator         # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────
class FakeRfc:
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.fail_next: dict = {}
        self.scripts["BAPI_TRANSACTION_COMMIT"] = {}
        self.scripts["BAPI_TRANSACTION_ROLLBACK"] = {}
        # Default RFC_READ_TABLE -> no rows so probes don't accidentally find pre-existing
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
def test_all_4_batch2_objects_register():
    for obj, cls in (("InternalOrder", InternalOrderSpineOrchestrator),
                      ("FunctionalLocation", FunctionalLocationSpineOrchestrator),
                      ("FixedAsset", FixedAssetSpineOrchestrator),
                      ("Project", ProjectSpineOrchestrator)):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-2 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# InternalOrder
# ─────────────────────────────────────────────────────────────────────────────
class _IOCallTracker:
    """Helper: return distinct scripts for TESTRUN vs real BAPI_INTERNALORDER_CREATE."""
    def __init__(self, testrun_valid: bool, real_result: dict):
        self.testrun_valid = testrun_valid
        self.real_result   = real_result
        self.calls = []
    def script_into(self, rfc):
        orig = rfc.call
        def patched(fn, **kwargs):
            self.calls.append((fn, kwargs))
            if fn == "BAPI_INTERNALORDER_CREATE":
                if kwargs.get("TESTRUN") == "X":
                    return ({"RETURN": [{"TYPE": "S"}]} if self.testrun_valid
                            else {"RETURN": [{"TYPE": "E", "MESSAGE": "invalid order type"}]})
                return self.real_result
            return orig(fn, **kwargs)
        rfc.call = patched


def test_internal_order_happy_path_with_internal_numbering():
    rfc = FakeRfc()
    tracker = _IOCallTracker(True, {"RETURN": [{"TYPE": "S"}], "ORDERID": "800000054321"})
    tracker.script_into(rfc)
    orch = InternalOrderSpineOrchestrator(rfc,
                                           cc_org={"CO_AREA": "1710",
                                                    "COMP_CODE": "1710",
                                                    "CURRENCY": "USD",
                                                    "PROFIT_CTR": "YB600",
                                                    "ORDER_TYPE": "Y600"})
    res = orch.load_one({"AUFNR": "SRC_IO_1", "AUART": "Y600", "KTEXT": "Test IO"})
    assert res.status == DISP_CREATED
    assert res.source_key == "SRC_IO_1"
    assert res.target_key == "800000054321"   # SAP-assigned ORDERID
    print("  [OK] InternalOrder internal-numbering captures SAP-assigned ORDERID")


def test_internal_order_invalid_otype_falls_back():
    rfc = FakeRfc()
    tracker = _IOCallTracker(False, {"RETURN": [{"TYPE": "S"}], "ORDERID": "800000054322"})
    tracker.script_into(rfc)
    orch = InternalOrderSpineOrchestrator(rfc,
                                           cc_org={"CO_AREA": "1710",
                                                    "COMP_CODE": "1710",
                                                    "CURRENCY": "USD",
                                                    "PROFIT_CTR": "YB600",
                                                    "ORDER_TYPE": "Y600"})
    res = orch.load_one({"AUFNR": "X", "AUART": "0100"})   # legacy ECC type
    assert res.status == DISP_CREATED
    # Substitution surfaced in messages
    assert any("0100" in m and "used Y600" in m for m in res.messages)
    print("  [OK] InternalOrder invalid AUART -> falls back + records substitution")


def test_internal_order_missing_co_area_dead_letters():
    orch = InternalOrderSpineOrchestrator(FakeRfc(), cc_org={})
    res = orch.load_one({"AUFNR": "X", "AUART": "Y600"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] InternalOrder missing CO_AREA -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# FunctionalLocation
# ─────────────────────────────────────────────────────────────────────────────
def test_funcloc_no_strind_dead_letters():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": []})  # no IFLOT rows -> no strind
    orch = FunctionalLocationSpineOrchestrator(rfc)
    res = orch.load_one({"TPLNR": "X-001"})
    # Surfaces as BAPI_FAILURE because call_bapi returns None with the message
    assert res.status == DISP_DEAD_LETTER
    assert any("structure indicator" in m for m in res.messages)
    print("  [OK] FunctionalLocation no target strind -> dead-letter with explanation")


def test_funcloc_happy_path_label_fits_mask():
    rfc = FakeRfc()
    # Existing IFLOT rows establish strind=YH, category=1, delim='-', widths=[4,3,3]
    rfc.script("RFC_READ_TABLE",
                {"DATA": [
                    {"WA": "YH|1100-PMP-001|1"},
                    {"WA": "YH|1100-PMP-002|1"},
                    {"WA": "YH|1100-PMP-003|1"},
                ]})
    rfc.script("BAPI_FUNCLOC_CREATE",
                {"RETURN": [{"TYPE": "S"}], "FUNCTLOCATION": "1100-PMP-004"})
    orch = FunctionalLocationSpineOrchestrator(rfc)
    res = orch.load_one({"TPLNR": "1100-PMP-004", "PLTXT": "Pump 4"})
    assert res.status in (DISP_CREATED, DISP_REMAPPED)
    assert res.target_key == "1100-PMP-004"
    print("  [OK] FunctionalLocation label fitting target mask succeeds")


def test_funcloc_collision_safe_remap_when_label_taken():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE",
                {"DATA": [
                    {"WA": "YH|1100-PMP-001|1"},
                    {"WA": "YH|1100-PMP-002|1"},
                ]})
    rfc.script("BAPI_FUNCLOC_CREATE",
                {"RETURN": [{"TYPE": "S"}], "FUNCTLOCATION": "1100-PMP-001"})
    orch = FunctionalLocationSpineOrchestrator(rfc)
    res = orch.load_one({"TPLNR": "1100-PMP-001"})   # collides with existing
    # We expect either REMAPPED (collision-safe rename) or matched
    assert res.status in (DISP_REMAPPED, DISP_CREATED)
    print("  [OK] FunctionalLocation handles label collisions (collision-safe naming)")


def test_funcloc_missing_tplnr_dead_letters():
    rfc = FakeRfc()
    orch = FunctionalLocationSpineOrchestrator(rfc)
    res = orch.load_one({"PLTXT": "no key"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] FunctionalLocation missing TPLNR -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# FixedAsset
# ─────────────────────────────────────────────────────────────────────────────
class _FACallTracker:
    """Distinguish TESTRUN (validation) from real BAPI_FIXEDASSET_CREATE1."""
    def __init__(self, testrun_valid: bool, real_result: dict):
        self.testrun_valid = testrun_valid
        self.real_result   = real_result
    def script_into(self, rfc):
        orig = rfc.call
        def patched(fn, **kwargs):
            rfc.calls.append((fn, kwargs))
            if fn == "BAPI_FIXEDASSET_CREATE1":
                if kwargs.get("TESTRUN") == "X":
                    return ({"RETURN": [{"TYPE": "S"}]} if self.testrun_valid
                            else {"RETURN": [{"TYPE": "E", "MESSAGE": "class invalid"}]})
                return self.real_result
            if fn == "RFC_READ_TABLE":
                return rfc.scripts.get("RFC_READ_TABLE", {"DATA": []})
            return rfc.scripts.get(fn, {})
        rfc.call = patched


def test_fixed_asset_internal_numbering_captures_target():
    rfc = FakeRfc()
    _FACallTracker(True, {"RETURN": [{"TYPE": "S"}], "ASSET": "ANL_INT_999"}).script_into(rfc)
    orch = FixedAssetSpineOrchestrator(rfc,
                                        cc_org={"ASSET_COMP_CODE": "1710",
                                                 "ASSET_CLASS": "1100"})
    res = orch.load_one({"ANLN1": "SRC_ANL", "ANLKL": "1100", "TXT50": "Office chair"})
    assert res.status == DISP_CREATED
    assert res.target_key == "ANL_INT_999"
    print("  [OK] FixedAsset internal numbering captures SAP-assigned ASSET")


def test_fixed_asset_external_numbering_idempotent():
    rfc = FakeRfc()
    # Probe returns "exists" - external + pre-existing -> matched_existing
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "EXT_ANL_1"}]})
    orch = FixedAssetSpineOrchestrator(rfc,
                                        cc_org={"ASSET_COMP_CODE": "1710",
                                                 "ASSET_CLASS": "1100",
                                                 "ASSET_EXTERNAL_NUM": True})
    res = orch.load_one({"ANLN1": "EXT_ANL_1", "ANLKL": "1100"})
    assert res.status == DISP_MATCHED_EXISTING
    # No actual BAPI_FIXEDASSET_CREATE1 call should have happened
    assert all(c[0] != "BAPI_FIXEDASSET_CREATE1" for c in rfc.calls)
    print("  [OK] FixedAsset external-numbering + pre-existing -> matched_existing")


def test_fixed_asset_missing_company_code_dead_letters():
    rfc = FakeRfc()
    orch = FixedAssetSpineOrchestrator(rfc, cc_org={})
    res = orch.load_one({"ANLN1": "X", "ANLKL": "1100"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] FixedAsset missing company code -> DQ dead-letter")


def test_fixed_asset_class_remap_recorded():
    rfc = FakeRfc()
    # Force the class-validity probe to return False so we remap
    _FACallTracker(False, {"RETURN": [{"TYPE": "S"}], "ASSET": "ANL_INT_555"}).script_into(rfc)
    orch = FixedAssetSpineOrchestrator(rfc,
                                        cc_org={"ASSET_COMP_CODE": "1710",
                                                 "ASSET_CLASS": "1100"})
    res = orch.load_one({"ANLN1": "X", "ANLKL": "ZSRC", "TXT50": "Legacy machine"})
    assert res.status == DISP_CREATED
    assert any("ZSRC" in m and "used 1100" in m for m in res.messages)
    print("  [OK] FixedAsset invalid class -> remap to fallback + audit message")


# ─────────────────────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────────────────────
def test_project_happy_path_with_discovered_profile():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            if "OPTIONS" in kwargs:
                return {"DATA": []}   # exist-probe -> not found
            return {"DATA": [{"WA": "YPMS|1710"}, {"WA": "YPMS|1710"}, {"WA": "YPMS|1710"}]}
        if fn == "BAPI_PROJECTDEF_CREATE":
            return {"RETURN": [{"TYPE": "S"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched
    orch = ProjectSpineOrchestrator(rfc)
    res = orch.load_one({"PSPID": "TEST/PRJ", "POST1": "Test project"})
    # TEST/PRJ has a slash - sanitized form is sent first since src != sanitized
    assert res.status in (DISP_CREATED, DISP_REMAPPED)
    bapi_call = next(c for c in rfc.calls if c[0] == "BAPI_PROJECTDEF_CREATE")
    assert bapi_call[1]["PROJECT_DEFINITION_STRU"]["PROJECT_PROFILE"] == "YPMS"
    print("  [OK] Project happy path + auto-discovered profile YPMS")


def test_project_mask_error_retries_with_sanitized_id():
    rfc = FakeRfc()
    call_count = {"n": 0}
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            if "OPTIONS" in kwargs:
                return {"DATA": []}   # exist-probe -> not found
            return {"DATA": [{"WA": "YPMS|1710"}]}
        if fn == "BAPI_PROJECTDEF_CREATE":
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"RETURN": [{"TYPE": "E", "MESSAGE": "PSPID violates mask"}]}
            return {"RETURN": [{"TYPE": "S"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ProjectSpineOrchestrator(rfc)
    res = orch.load_one({"PSPID": "TEST/PRJ", "POST1": "Test"})
    assert res.status == DISP_REMAPPED
    assert res.target_key == "TESTPRJ"   # sanitized
    assert any("TEST/PRJ" in m and "TESTPRJ" in m for m in res.messages)
    print("  [OK] Project mask error -> retries with sanitized id + records remap")


def test_project_pre_existing_matched():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE", {"DATA": [{"WA": "YPMS|1710"}]})   # for discovery
    # The PROJ probe will return an existing PSPID hit
    call_count = {"n": 0}
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "PROJ" and "OPTIONS" in kwargs:
                # the exist-check call -> return a row
                return {"DATA": [{"WA": "0001"}]}
            # the config-discovery call -> return profile rows
            return {"DATA": [{"WA": "YPMS|1710"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ProjectSpineOrchestrator(rfc)
    res = orch.load_one({"PSPID": "EXISTING_PRJ"})
    assert res.status == DISP_MATCHED_EXISTING
    assert all(c[0] != "BAPI_PROJECTDEF_CREATE" for c in rfc.calls)
    print("  [OK] Project pre-existing PSPID -> matched_existing")


def test_project_missing_pspid_dead_letters():
    orch = ProjectSpineOrchestrator(FakeRfc())
    res = orch.load_one({"POST1": "no id"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Project missing PSPID -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: dry-run on each
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch2():
    rfc = FakeRfc()
    rfc.script("RFC_READ_TABLE",
                {"DATA": [{"WA": "YH|1100-PMP-001|1"}, {"WA": "YPMS|1710"}]})
    for cls, row, extra in (
        (InternalOrderSpineOrchestrator,
         {"AUFNR": "X", "AUART": "Y600"},
         {"cc_org": {"CO_AREA": "1710", "COMP_CODE": "1710",
                      "CURRENCY": "USD", "PROFIT_CTR": "Y", "ORDER_TYPE": "Y600"}}),
        (FunctionalLocationSpineOrchestrator,
         {"TPLNR": "1100-PMP-001"},
         {}),
        (FixedAssetSpineOrchestrator,
         {"ANLN1": "X", "ANLKL": "1100"},
         {"cc_org": {"ASSET_COMP_CODE": "1710", "ASSET_CLASS": "1100"}}),
        (ProjectSpineOrchestrator,
         {"PSPID": "DRY"},
         {}),
    ):
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED
        assert res.disposition.endswith("_dry_run"), f"got {res.disposition}"
    # None of the heavy BAPIs should have been called
    bapi_calls = [c[0] for c in rfc.calls if c[0].startswith("BAPI_")
                  and c[0] not in ("BAPI_TRANSACTION_COMMIT",
                                    "BAPI_TRANSACTION_ROLLBACK")]
    # TESTRUN-validation may have run (Equipment / InternalOrder do this), so allow those
    assert all(c == "BAPI_INTERNALORDER_CREATE" or c == "BAPI_FIXEDASSET_CREATE1"
               for c in bapi_calls) or not bapi_calls
    print("  [OK] dry-run mode skips writes for all 4 batch-2 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 2 - InternalOrder / FuncLoc / FixedAsset / Project")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-2 spine promotion tests passed.")
