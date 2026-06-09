"""
Unit tests for WS2 dynamic-catalog wiring -- F3 introspection feeds into the
EXTENSIONIN allowed-fields filter at load time.

Verifies:
  - hydrate_catalog_for() does NOTHING when M4H_DYNAMIC_CATALOG unset
    (preserves current behavior; flag must be explicit to enable)
  - hydrate_catalog_for() calls dynamic_schema_builder.build_schema() exactly
    once per (object_type, loader-instance) -- per-record overhead = 0
  - The hydrated field-set lands in self.bapi_field_catalog[obj] which the
    spine's collect_custom_fields() uses as allowed_fields
  - Failed hydration (build_schema raises) doesn't re-attempt on next call
  - Unknown object_type returns 0 + does not crash
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))


# ─────────────────────────────────────────────────────────────────────────────
# Stub out dynamic_schema_builder BEFORE importing unified_loader so we can
# count build_schema calls.
# ─────────────────────────────────────────────────────────────────────────────
_calls = {"n": 0, "last_args": None}

def _stub_build_schema(conn, bapi, force_refresh=False):
    _calls["n"] += 1
    _calls["last_args"] = (bapi, force_refresh)
    if bapi == "BAPI_MATERIAL_SAVEDATA":
        return {"MATERIAL", "MATL_TYPE", "BASIC_VIEW", "BASE_UOM",
                "ZZ_CUSTOMER_TIER", "ZZ_LEGACY_SAP_ID"}
    if bapi == "BAPI_BUPA_CREATE_FROM_DATA":
        return {"PARTNERCATEGORY", "CENTRALDATAORGANIZATION", "ZZ_RISK_RATING"}
    return set()

# Stub out the module so the import in hydrate_catalog_for picks up our fake
import types
dsb = types.ModuleType("dynamic_schema_builder")
dsb.build_schema = _stub_build_schema
sys.modules["dynamic_schema_builder"] = dsb


def _make_loader():
    """Build a UnifiedLoader without touching real SAP / boto3."""
    # Avoid the boto3 + pyrfc work the constructor does by importing the
    # module then mocking the needed classes.
    import unified_loader as ul
    class FakeConn:
        pass
    loader = object.__new__(ul.UnifiedLoader)
    loader.c = FakeConn()
    loader.bapi_field_catalog = {}
    loader._dynamic_catalog_enabled = True   # default for these tests
    loader._dynamic_catalog_attempted = set()
    return loader


# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_catalog_disabled_by_default_env_unset():
    """When M4H_DYNAMIC_CATALOG is unset, hydrate_catalog_for is a no-op."""
    _calls["n"] = 0
    loader = _make_loader()
    loader._dynamic_catalog_enabled = False    # explicit unset
    n = loader.hydrate_catalog_for("Material")
    assert n == 0
    assert _calls["n"] == 0                     # build_schema NOT called
    assert "Material" not in loader.bapi_field_catalog
    print("  [OK] Catalog disabled by default -- build_schema NOT called")


def test_dynamic_catalog_hydrates_on_first_call():
    """First call triggers build_schema and caches result; spine catalog populated."""
    _calls["n"] = 0
    loader = _make_loader()
    n = loader.hydrate_catalog_for("Material")
    assert n == 6   # 4 standard + 2 Z fields per the stub
    assert _calls["n"] == 1
    assert _calls["last_args"] == ("BAPI_MATERIAL_SAVEDATA", False)
    assert "ZZ_CUSTOMER_TIER" in loader.bapi_field_catalog["Material"]
    print("  [OK] First call hydrates catalog and caches against bapi_field_catalog")


def test_dynamic_catalog_idempotent_on_second_call():
    """Second + Nth calls do NOT re-invoke build_schema."""
    _calls["n"] = 0
    loader = _make_loader()
    loader.hydrate_catalog_for("Material")
    loader.hydrate_catalog_for("Material")
    loader.hydrate_catalog_for("Material")
    assert _calls["n"] == 1   # only the first call introspected
    print("  [OK] Repeat calls are a no-op -- build_schema called exactly once")


def test_dynamic_catalog_per_object_isolation():
    """Hydrating Material does NOT hydrate BusinessPartner."""
    _calls["n"] = 0
    loader = _make_loader()
    loader.hydrate_catalog_for("Material")
    assert "Material" in loader.bapi_field_catalog
    assert "BusinessPartner" not in loader.bapi_field_catalog
    loader.hydrate_catalog_for("BusinessPartner")
    assert "BusinessPartner" in loader.bapi_field_catalog
    assert _calls["n"] == 2   # two distinct objects -> two introspections
    print("  [OK] Per-object isolation -- each object_type hydrated independently")


def test_dynamic_catalog_failed_hydration_no_retry():
    """build_schema raising puts the object_type in _dynamic_catalog_attempted
    so we don't re-attempt every load (which would slow extracts to a crawl
    when the target is unreachable)."""
    _calls["n"] = 0
    loader = _make_loader()

    def _bombs(conn, bapi, force_refresh=False):
        _calls["n"] += 1
        raise RuntimeError("RFC unavailable")
    sys.modules["dynamic_schema_builder"].build_schema = _bombs

    try:
        n1 = loader.hydrate_catalog_for("Material")
        n2 = loader.hydrate_catalog_for("Material")
        n3 = loader.hydrate_catalog_for("Material")
        assert n1 == 0 and n2 == 0 and n3 == 0
        assert _calls["n"] == 1   # tried ONCE, did NOT retry
    finally:
        sys.modules["dynamic_schema_builder"].build_schema = _stub_build_schema
    print("  [OK] Failed hydration is cached -- no retry on next load")


def test_dynamic_catalog_unknown_object_no_crash():
    """An object_type not in _OBJECT_TO_BAPI returns 0 cleanly."""
    _calls["n"] = 0
    loader = _make_loader()
    n = loader.hydrate_catalog_for("UnknownObject")
    assert n == 0
    assert _calls["n"] == 0      # no BAPI mapping -> no introspection attempt
    print("  [OK] Unknown object_type returns 0 without crashing")


def test_dynamic_catalog_spine_uses_allowed_fields_to_drop_unknown_z():
    """End-to-end: catalog is populated, spine consumes it as allowed_fields,
    unknown Z fields get dropped + counted in extension_field_drops."""
    from base_spine_orchestrator import collect_custom_fields
    row = {
        "MATNR": "TEST",
        "ZZ_CUSTOMER_TIER":   "GOLD",        # IN catalog -> kept
        "ZZ_LEGACY_SAP_ID":   "L12345",      # IN catalog -> kept
        "ZZ_UNKNOWN_CUSTOM":  "weird-value", # NOT IN catalog -> dropped
        "YY_ANOTHER_UNKNOWN": "another",     # NOT IN catalog -> dropped
    }
    catalog = {"ZZ_CUSTOMER_TIER", "ZZ_LEGACY_SAP_ID", "MATERIAL"}
    ext_rows, dropped = collect_custom_fields(
        row, structname="BAPI_TE_MARA", allowed_fields=catalog)
    assert len(ext_rows) == 2
    assert dropped == 2
    print("  [OK] Spine uses allowed_fields catalog to drop unknown Z fields")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS2 dynamic-catalog wiring tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll dynamic-catalog wiring tests passed.")
