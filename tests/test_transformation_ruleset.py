"""
Unit tests for the F4 value-mapping ruleset.

Validates that value-maps\matrix.json + value-maps\ruleset.json work
end-to-end through the TransformationEngine: a raw ECC-shaped record goes
in, the right value-mapped + cleansed record comes out, and DQ gates
reject what they should.

These run with NO live AWS - matrix is loaded from the local file via
the ``value_maps=`` inline param (which has same semantics as the S3
loader but is testable without network).

Run:  python tests\test_transformation_ruleset.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from transformation_engine import TransformationEngine, REJECTION_STATUS   # noqa


def _load(name: str) -> dict:
    return json.loads((REPO_ROOT / "value-maps" / name).read_text(encoding="utf-8"))


def _engine() -> TransformationEngine:
    ruleset = _load("ruleset.json")
    matrix  = _load("matrix.json")
    # strip _meta and _doc keys (loader ignores leading-underscore by convention,
    # but TransformationEngine treats them as ordinary tables - filter explicitly)
    matrix = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
              for k, v in matrix.items() if not k.startswith("_")}
    ruleset = {k: v for k, v in ruleset.items() if not k.startswith("_")}
    return TransformationEngine(ruleset=ruleset, value_maps=matrix)


def test_customer_value_map_full_pipeline():
    eng = _engine()
    # Legacy ECC-shaped customer record
    raw = {
        "KUNNR": "  0001000123  ",
        "NAME1": "Acme   Corp",           # double-space gets REGEX_CLEANSE'd to single
        "LAND1": "germany",                # UPPER + country_map -> "DE"
        "BUKRS": "1000",                   # company_code_map -> "US01"
        "WAERS": "DEM",                    # currency_map -> "EUR"
        "SPRAS": "D",                      # language_map -> "DE"
        "KTOKD": "Z001",                   # customer_group_map -> "BP01"
    }
    out, dq = eng.apply("Customer", raw)
    assert out["KUNNR"] == "0001000123"     # TRIM
    assert out["NAME1"] == "Acme Corp"      # REGEX_CLEANSE collapsed whitespace
    assert out["LAND1"] == "DE"             # UPPER then country_map
    assert out["BUKRS"] == "US01"
    assert out["WAERS"] == "EUR"
    assert out["SPRAS"] == "DE"
    assert out["KTOKD"] == "BP01"
    assert dq.passed, f"DQ unexpectedly failed: {dq.reasons}"
    print("  [OK] Customer end-to-end (TRIM + VALUE_MAP x5 + REGEX_CLEANSE + DQ pass)")


def test_customer_mandatory_gate_rejects_empty_kunnr():
    eng = _engine()
    raw = {"KUNNR": "", "NAME1": "X", "LAND1": "US", "BUKRS": "1000", "WAERS": "USD"}
    out, dq = eng.apply("Customer", raw)
    assert dq is not None and not dq.passed
    assert dq.to_dict()["status"] == REJECTION_STATUS
    assert any("KUNNR" in r for r in dq.reasons) or any(rj["field"] == "KUNNR" for rj in dq.rejections)
    print("  [OK] Customer MANDATORY gate rejects empty KUNNR")


def test_customer_regex_valid_gate_rejects_3char_country():
    eng = _engine()
    raw = {"KUNNR": "K1", "NAME1": "X", "LAND1": "USA", "BUKRS": "1000", "WAERS": "USD"}
    out, dq = eng.apply("Customer", raw)
    # LAND1=USA hits country_map -> US (2 chars), so DQ should pass
    assert out["LAND1"] == "US"
    assert dq.passed
    # but a country NOT in the map (e.g. "XXX") stays "XXX" and fails REGEX_VALID
    raw2 = {"KUNNR": "K2", "NAME1": "X", "LAND1": "XXX", "BUKRS": "1000", "WAERS": "USD"}
    out2, dq2 = eng.apply("Customer", raw2)
    assert not dq2.passed
    assert any(rj["field"] == "LAND1" for rj in dq2.rejections)
    print("  [OK] Customer REGEX_VALID rejects unmapped LAND1 that stays non-ISO")


def test_currency_legacy_european_currencies_collapse_to_EUR():
    eng = _engine()
    for legacy in ("DEM", "FRF", "ITL", "ESP", "BEF", "NLG"):
        out, _ = eng.apply("Customer", {"KUNNR": "K", "NAME1": "X", "LAND1": "DE",
                                         "BUKRS": "1000", "WAERS": legacy})
        assert out["WAERS"] == "EUR", f"{legacy} did not collapse to EUR"
    print("  [OK] Currency map collapses 6 legacy European currencies to EUR")


def test_vendor_value_map_path():
    eng = _engine()
    raw = {"LIFNR": "V100", "NAME1": "Beta Supplier", "LAND1": "germany",
           "BUKRS": "2000", "WAERS": "EUR", "KTOKK": "ZVEN"}
    out, dq = eng.apply("Vendor", raw)
    assert out["LAND1"] == "DE"
    assert out["BUKRS"] == "DE01"
    assert out["KTOKK"] == "BPV1"
    assert dq.passed
    print("  [OK] Vendor full transform pipeline")


def test_material_type_remap():
    eng = _engine()
    out, dq = eng.apply("Material", {"MATNR": "M1", "MTART": "ZFG"})
    assert out["MTART"] == "FERT"
    assert dq.passed
    print("  [OK] Material legacy ZFG -> FERT")


def test_material_allowed_gate_rejects_unknown_type():
    eng = _engine()
    out, dq = eng.apply("Material", {"MATNR": "M2", "MTART": "BOGUS"})
    # BOGUS isn't in material_type_map (keep semantics) so stays BOGUS,
    # then DQ ALLOWED rejects
    assert not dq.passed
    assert any(rj["field"] == "MTART" for rj in dq.rejections)
    print("  [OK] Material ALLOWED gate rejects unknown MTART")


def test_gl_account_remap():
    eng = _engine()
    out, _ = eng.apply("GLAccount", {"SAKNR": "100000"})
    assert out["SAKNR"] == "10000000"
    print("  [OK] GLAccount 100000 -> 10000000")


def test_company_code_unique_gate():
    eng = _engine()
    out1, dq1 = eng.apply("CompanyCode", {"BUKRS": "1000", "WAERS": "USD"})
    assert dq1.passed
    # second time with the SAME bukrs after mapping -> UNIQUE should reject
    out2, dq2 = eng.apply("CompanyCode", {"BUKRS": "1000", "WAERS": "USD"})
    assert out2["BUKRS"] == "US01"
    assert not dq2.passed
    assert any("UNIQUE" in r for r in dq2.reasons) or any(rj["rule"] == "UNIQUE" for rj in dq2.rejections)
    print("  [OK] CompanyCode UNIQUE gate catches the second row")


def test_no_rules_pass_through():
    eng = _engine()
    out, dq = eng.apply("UnknownObject", {"X": 1, "Y": 2})
    assert out == {"X": 1, "Y": 2}
    assert dq is None
    print("  [OK] Object with no rules passes through unchanged")


def test_engine_never_raises_on_bad_input():
    eng = _engine()
    out, dq = eng.apply("Customer", {})    # totally empty record
    # Should NOT raise; DQ gates catch missing fields cleanly
    assert dq is not None
    assert not dq.passed
    print("  [OK] Empty record produces DQ rejection, not an exception")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("F4 - transformation ruleset & value-mapping matrix tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nF4 ruleset tests: PASS")
