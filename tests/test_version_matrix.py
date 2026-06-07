"""
Unit tests for version_matrix - source/target catalogue, routing rules,
RFC-detection helpers.

Run:  python tests\test_version_matrix.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from version_matrix import (   # noqa
    SOURCE_ECC_VERSIONS, TARGET_S4_RELEASES,
    SOURCE_BY_CODE, TARGET_BY_CODE,
    routing_for_pair, supported_pairs, matrix_payload,
    detect_source_ecc_version, detect_target_s4_release,
    VersionIncompatibilityError,
)


# ──────────────────────────────────────────────────────────────────────────────
# Catalogue shape
# ──────────────────────────────────────────────────────────────────────────────
def test_source_catalogue_covers_EHP0_through_EHP8():
    """Spec: source SAP ECC 6.0 EHP0..EHP8. All 9 entries present."""
    ehps = sorted(v.ehp for v in SOURCE_ECC_VERSIONS)
    assert ehps == list(range(0, 9)), f"missing EHP coverage; got {ehps}"
    print("  [OK] Source catalogue covers all EHP0..EHP8")


def test_target_catalogue_covers_1909_through_2025():
    """Spec: target S/4HANA 1909..2025. All releases represented."""
    years = sorted(r.release_year for r in TARGET_S4_RELEASES)
    assert 1909 in years and 2020 in years and 2025 in years
    assert all(1909 <= y <= 2025 for y in years)
    print("  [OK] Target catalogue covers 1909..2025")


# ──────────────────────────────────────────────────────────────────────────────
# Routing rules
# ──────────────────────────────────────────────────────────────────────────────
def test_modern_pair_with_hana_override_routes_to_modern_bulk():
    """EHP8 on HANA + 2023 -> modern path (HANA DB override unlocks the fast extract)."""
    plan = routing_for_pair("ECC60_EHP8", "S4HANA_2023", source_db="HANA")
    assert plan.extract_strategy == "MODERN_BULK"
    assert plan.package_size >= 25_000
    assert plan.template_format == "FIORI_MC_CSV"
    assert plan.use_open_sql_optimizations is True
    assert plan.fargate_fan_out == "HIGH"
    assert plan.cluster_read_safety == "RELAXED"
    assert plan.odata_ltmc_supported is True
    print("  [OK] EHP8 on HANA + 2023: modern extract, Fiori CSV, high fan-out")


def test_same_pair_without_hana_override_stays_legacy():
    """EHP8 on a traditional RDBMS + 2023 - conservative defaults keep us safe."""
    plan = routing_for_pair("ECC60_EHP8", "S4HANA_2023")    # no source_db
    assert plan.extract_strategy == "LEGACY_CHUNKED"
    assert plan.cluster_read_safety == "STRICT"
    assert plan.fargate_fan_out == "LOW"
    # template stays Fiori CSV regardless - that's a TARGET property
    assert plan.template_format == "FIORI_MC_CSV"
    print("  [OK] EHP8 (no DB hint) + 2023: legacy chunked, conservative defaults")


def test_legacy_pair_routes_to_chunked_and_low_fanout():
    """EHP3 + 1909 -> legacy path (low Fargate fan-out, small package, strict cluster, LSMW XML)."""
    plan = routing_for_pair("ECC60_EHP3", "S4HANA_1909")
    assert plan.extract_strategy == "LEGACY_CHUNKED"
    assert plan.package_size <= 5_000
    assert plan.template_format == "LEGACY_LSMW_XML"
    assert plan.use_open_sql_optimizations is False
    assert plan.fargate_fan_out == "LOW"
    assert plan.cluster_read_safety == "STRICT"
    assert plan.odata_ltmc_supported is False        # 1909 has no MC OData
    print("  [OK] EHP3 -> 1909: legacy chunked, LSMW XML, low fan-out, strict cluster reads")


def test_unknown_source_raises():
    try:
        routing_for_pair("ECC50_EHP9", "S4HANA_2023")
    except VersionIncompatibilityError as e:
        assert "ECC50_EHP9" in str(e)
        print("  [OK] Unknown source rejected with helpful message")
        return
    assert False, "expected VersionIncompatibilityError"


def test_unknown_target_raises():
    try:
        routing_for_pair("ECC60_EHP8", "S4HANA_3000")
    except VersionIncompatibilityError as e:
        assert "S4HANA_3000" in str(e)
        print("  [OK] Unknown target rejected with helpful message")
        return
    assert False, "expected VersionIncompatibilityError"


def test_impossible_jump_is_rejected():
    """EHP0 -> 2023 is a 12+ year jump we haven't proved out; refuse."""
    try:
        routing_for_pair("ECC60_EHP0", "S4HANA_2024")
    except VersionIncompatibilityError as e:
        assert "EHP" in str(e) or "12" in str(e)
        print("  [OK] EHP0 -> 2024 (12-year jump) refused with explanation")
        return
    assert False, "expected VersionIncompatibilityError"


def test_supported_pairs_count_is_sensible():
    pairs = supported_pairs()
    # 9 sources x 7 targets = 63 total possible, minus the EHP<=3 + year>=2023 cells
    # That's ~12 forbidden cells -> ~51 supported. Be tolerant ± a couple.
    assert 45 <= len(pairs) <= 65, f"unexpected pair count: {len(pairs)}"
    # spot-check the structure
    sample = pairs[0]
    for key in ("source_code", "source_label", "target_code", "target_label",
                "extract_strategy", "template_format", "fargate_fan_out"):
        assert key in sample
    print(f"  [OK] supported_pairs returns {len(pairs)} pairs with the expected shape")


def test_matrix_payload_is_json_clean():
    """The full matrix the API will serve - must be plain dicts/lists, no dataclasses."""
    import json
    payload = matrix_payload()
    # Must be JSON-serializable as-is
    txt = json.dumps(payload)
    assert "sources" in payload and "targets" in payload and "valid_pairs" in payload
    assert len(payload["sources"]) == 9
    assert len(payload["targets"]) == 7
    assert len(txt) > 1000   # non-trivial payload size
    print("  [OK] matrix_payload is JSON-serializable and complete")


# ──────────────────────────────────────────────────────────────────────────────
# RFC detection helpers
# ──────────────────────────────────────────────────────────────────────────────
def test_detect_source_recognises_kernel_742_as_EHP7():
    """SAP_BASIS release 742 -> EHP7."""
    raw = {"RFCSI_EXPORT": {"RFCSAPRL": "742", "RFCDBSYS": "ORACLE"}}
    v = detect_source_ecc_version(raw)
    assert v is not None
    assert v.ehp == 7
    assert v.db_default == "ANY_DB"
    print("  [OK] RFCSAPRL=742 detected as EHP7 on AnyDB")


def test_detect_source_recognises_kernel_753_as_EHP8():
    """SAP_BASIS release 753 -> EHP8."""
    raw = {"RFCSI_EXPORT": {"RFCSAPRL": "753", "RFCDBSYS": "HDB"}}
    v = detect_source_ecc_version(raw)
    assert v is not None
    assert v.ehp == 8
    assert v.db_default == "HANA"
    assert v.extract_strategy == "MODERN_BULK"
    print("  [OK] RFCSAPRL=753 + HDB detected as EHP8 on HANA -> modern bulk extract")


def test_detect_source_hana_override_promotes_legacy_ehp():
    """If a legacy EHP shows up on HANA (rare but real), promote DB hint to HANA."""
    raw = {"RFCSI_EXPORT": {"RFCSAPRL": "731", "RFCDBSYS": "HDB"}}
    v = detect_source_ecc_version(raw)
    assert v is not None
    assert v.ehp == 6
    assert v.db_default == "HANA"     # overridden from AnyDB
    assert v.extract_strategy == "MODERN_BULK"
    print("  [OK] EHP6 on HANA -> DB override + modern extract")


def test_detect_source_unknown_release_returns_None():
    raw = {"RFCSI_EXPORT": {"RFCSAPRL": "999", "RFCDBSYS": "ORACLE"}}
    assert detect_source_ecc_version(raw) is None
    print("  [OK] Unknown SAP_BASIS release -> None (caller surfaces 'unknown')")


def test_detect_target_recognises_S4CORE_101_as_2020():
    rows = [{"COMPONENT": "S4CORE", "RELEASE": "101"}]
    r = detect_target_s4_release(rows)
    assert r is not None
    assert r.release_year == 2020
    assert r.template_format == "FIORI_MC_CSV"
    print("  [OK] S4CORE 101 -> S/4HANA 2020 + Fiori CSV template")


def test_detect_target_recognises_S4CORE_100_as_1909():
    rows = [{"COMPONENT": "S4CORE", "RELEASE": "100"}]
    r = detect_target_s4_release(rows)
    assert r is not None
    assert r.release_year == 1909
    assert r.template_format == "LEGACY_LSMW_XML"
    assert r.odata_ltmc_supported is False
    print("  [OK] S4CORE 100 -> S/4HANA 1909 + legacy LSMW XML, no MC OData")


def test_detect_target_handles_other_components_in_cvers():
    """A real CVERS read includes many components; we must find S4CORE."""
    rows = [
        {"COMPONENT": "SAP_BASIS", "RELEASE": "754"},
        {"COMPONENT": "SAP_GWFND", "RELEASE": "754"},
        {"COMPONENT": "S4CORE",    "RELEASE": "108"},      # the one we care about
        {"COMPONENT": "S4COREOP",  "RELEASE": "108"},
    ]
    r = detect_target_s4_release(rows)
    assert r is not None and r.release_year == 2025
    print("  [OK] Picks S4CORE out of a multi-component CVERS read")


def test_detect_target_no_s4core_returns_None():
    rows = [{"COMPONENT": "SAP_BASIS", "RELEASE": "754"}]
    assert detect_target_s4_release(rows) is None
    print("  [OK] No S4CORE row -> None (caller surfaces 'not S/4')")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("version_matrix - unit tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll version_matrix tests passed.")
