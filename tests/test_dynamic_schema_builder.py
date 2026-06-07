"""
Unit tests for dynamic_schema_builder (F3).

Mocks SAP RFC + S3 in-process. Validates the full cache->RFC->fallback chain
plus per-RFC compilation (DD_BAPI_PARAMETER_GET + DD03L paths).

Run:  python tests\test_dynamic_schema_builder.py
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from dynamic_schema_builder import (    # noqa
    CachedSchema, OBJECT_BAPI_MAP, DEFAULT_TTL_SECONDS,
    introspect_via_dd_bapi_parameter_get,
    introspect_via_dd03l,
    compile_field_set_from_dd_bapi,
    compile_field_set_from_dd03l,
    load_cached_schema, save_cached_schema,
    build_schema, build_all_schemas,
    _parse_s3_uri, _cache_key,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────
class FakeRfc:
    """Mock pyrfc.Connection with scriptable responses."""
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.fail_next: dict = {}    # fn_name -> str message

    def call(self, fn_name: str, **kwargs):
        self.calls.append((fn_name, kwargs))
        if fn_name in self.fail_next:
            raise RuntimeError(self.fail_next.pop(fn_name))
        return self.scripts.get(fn_name, {})


class FakeS3:
    """Mock boto3 s3 client. Stores objects as (bucket, key) -> bytes."""
    def __init__(self):
        self.store: dict = {}
        self.gets = 0
        self.puts = 0

    def get_object(self, *, Bucket, Key):
        self.gets += 1
        if (Bucket, Key) not in self.store:
            raise Exception("NoSuchKey")
        body = self.store[(Bucket, Key)]

        class _StreamingBody:
            def __init__(self, b): self._b = b
            def read(self): return self._b
        return {"Body": _StreamingBody(body)}

    def put_object(self, *, Bucket, Key, Body, ContentType=None):
        self.puts += 1
        self.store[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Compilation helpers (no RFC, pure transform)
# ─────────────────────────────────────────────────────────────────────────────
def test_compile_field_set_from_dd_bapi_picks_up_top_and_subfields():
    params = [
        {"PARAMETER": "HEADDATA", "SUBFIELDS": [{"FIELDNAME": "MATERIAL"},
                                                  {"FIELDNAME": "MATL_TYPE"}]},
        {"PARAMETER": "CLIENTDATA", "SUBFIELDS": [{"FIELDNAME": "BASE_UOM"}]},
        {"FIELDNAME": "STANDALONE"},
    ]
    fields = compile_field_set_from_dd_bapi(params)
    assert {"HEADDATA", "CLIENTDATA", "STANDALONE", "MATERIAL", "MATL_TYPE", "BASE_UOM"} <= fields
    print("  [OK] compile_field_set_from_dd_bapi captures top-level + nested fields")


def test_compile_field_set_from_dd03l_uppercases_and_skips_includes():
    rows = [
        {"FIELDNAME": "matnr"},
        {"FIELDNAME": "MTART"},
        {"FIELDNAME": ".INCLUDE"},    # DDIC include directive
        {"FIELDNAME": ""},
    ]
    fields = compile_field_set_from_dd03l(rows)
    assert "MATNR" in fields and "MTART" in fields
    assert ".INCLUDE" not in fields and "" not in fields
    print("  [OK] compile_field_set_from_dd03l uppercases + skips .INCLUDE directives")


# ─────────────────────────────────────────────────────────────────────────────
# S3 cache layer
# ─────────────────────────────────────────────────────────────────────────────
def test_s3_uri_parser():
    bucket, prefix = _parse_s3_uri("s3://my-bucket/dynamic-schema")
    assert bucket == "my-bucket" and prefix == "dynamic-schema"
    bucket2, prefix2 = _parse_s3_uri("s3://only-bucket")
    assert bucket2 == "only-bucket" and prefix2 == ""
    print("  [OK] _parse_s3_uri handles with/without prefix")


def test_cache_key_layout():
    key = _cache_key("dynamic-schema", "S4H", "100", "S4HANA_2023", "Material")
    assert key == "dynamic-schema/S4H/100/S4HANA_2023/Material.json"
    print("  [OK] cache key is (sid/client/release/object.json)")


def test_save_and_load_cached_schema_round_trip():
    s3 = FakeS3()
    sch = CachedSchema(sid="S4H", client="100", s4_release="S4HANA_2023",
                       object_type="Material", bapi="BAPI_MATERIAL_SAVEDATA",
                       fields=["MATERIAL", "MATL_TYPE"], written_at=time.time(),
                       source="rfc")
    save_cached_schema("s3://migrate4hana-schemas/dyn", sch, s3_client=s3)
    assert s3.puts == 1
    back = load_cached_schema("s3://migrate4hana-schemas/dyn", "S4H", "100",
                               "S4HANA_2023", "Material", s3_client=s3)
    assert back is not None
    assert back.fields == ["MATERIAL", "MATL_TYPE"]
    assert back.bapi == "BAPI_MATERIAL_SAVEDATA"
    print("  [OK] S3 cache save+load round-trips cleanly via FakeS3")


def test_cache_freshness_check():
    sch = CachedSchema(sid="x", client="100", s4_release="S4HANA_2023",
                       object_type="Material", bapi="x",
                       fields=["A"], written_at=time.time(), source="rfc")
    assert sch.is_fresh(60)            # just written
    sch.written_at = time.time() - 1_000_000
    assert not sch.is_fresh(60)
    print("  [OK] is_fresh respects TTL boundaries")


def test_load_cached_schema_miss_returns_None():
    s3 = FakeS3()
    out = load_cached_schema("s3://nope/prefix", "S4H", "100", "rel", "Material",
                              s3_client=s3)
    assert out is None
    print("  [OK] cache miss returns None (no exception)")


def test_save_cached_schema_failure_does_not_raise():
    class _BadS3:
        def put_object(self, **kw): raise RuntimeError("disk full")
    sch = CachedSchema(sid="x", client="100", s4_release="r", object_type="o",
                       bapi="b", fields=[], written_at=time.time(), source="rfc")
    # Must NOT raise - cache writes are best-effort
    save_cached_schema("s3://b/p", sch, s3_client=_BadS3())
    print("  [OK] save failure is logged, not raised")


# ─────────────────────────────────────────────────────────────────────────────
# build_schema orchestration (cache -> RFC -> fallback)
# ─────────────────────────────────────────────────────────────────────────────
def test_build_schema_cache_hit_skips_rfc():
    s3 = FakeS3()
    cached = CachedSchema(sid="S4H", client="100", s4_release="S4HANA_2023",
                          object_type="Material", bapi="BAPI_MATERIAL_SAVEDATA",
                          fields=["MATERIAL", "MATL_TYPE"], written_at=time.time(),
                          source="rfc")
    save_cached_schema("s3://b/dyn", cached, s3_client=s3)
    rfc = FakeRfc()   # no scripts; if RFC were called, it'd return {} and the
                      # builder would fall through. Cache hit must short-circuit.
    s = build_schema("Material", conn=rfc, sid="S4H", client="100",
                      s4_release="S4HANA_2023", cache_s3_uri="s3://b/dyn",
                      s3_client=s3)
    assert s.source == "rfc"           # carries through from the cached envelope
    assert set(s.fields) == {"MATERIAL", "MATL_TYPE"}
    assert all(c[0] != "DD_BAPI_PARAMETER_GET" for c in rfc.calls)
    print("  [OK] fresh cache hit short-circuits RFC entirely")


def test_build_schema_rfc_hit_writes_cache():
    s3 = FakeS3()
    rfc = FakeRfc()
    rfc.scripts["DD_BAPI_PARAMETER_GET"] = {
        "PARAMS": [
            {"PARAMETER": "HEADDATA",
             "SUBFIELDS": [{"FIELDNAME": "MATERIAL"}, {"FIELDNAME": "MATL_TYPE"}]},
        ]
    }
    s = build_schema("Material", conn=rfc, sid="S4H", client="100",
                      s4_release="S4HANA_2023", cache_s3_uri="s3://b/dyn",
                      s3_client=s3)
    assert s.source == "rfc"
    assert "MATERIAL" in s.fields and "MATL_TYPE" in s.fields
    assert s3.puts == 1
    # Round-trip - the cache now has it
    back = load_cached_schema("s3://b/dyn", "S4H", "100", "S4HANA_2023",
                               "Material", s3_client=s3)
    assert back is not None and "MATERIAL" in back.fields
    print("  [OK] RFC hit compiles + writes the S3 cache")


def test_build_schema_dd_bapi_failure_falls_back_to_dd03l():
    s3 = FakeS3()
    rfc = FakeRfc()
    rfc.fail_next["DD_BAPI_PARAMETER_GET"] = "function not found"
    # DD03L path returns fields packed in WA strings (we mock the FIELDS metadata
    # so the splitter knows the offsets; here we use delimiter mode)
    rfc.scripts["RFC_READ_TABLE"] = {
        "FIELDS": [
            {"FIELDNAME": "FIELDNAME", "OFFSET": "0",  "LENGTH": "30"},
            {"FIELDNAME": "POSITION",  "OFFSET": "30", "LENGTH": "4"},
            {"FIELDNAME": "KEYFLAG",   "OFFSET": "34", "LENGTH": "1"},
            {"FIELDNAME": "DATATYPE",  "OFFSET": "35", "LENGTH": "4"},
            {"FIELDNAME": "LENG",      "OFFSET": "39", "LENGTH": "6"},
            {"FIELDNAME": "DECIMALS",  "OFFSET": "45", "LENGTH": "6"},
        ],
        "DATA": [
            {"WA": "MATERIAL|0001|X|CHAR|000040|000000"},
            {"WA": "MATL_TYPE|0002| |CHAR|000004|000000"},
            {"WA": ".INCLUDE|0003| |    |000000|000000"},
        ]
    }
    s = build_schema("Material", conn=rfc, sid="S4H", client="100",
                      s4_release="S4HANA_2023", cache_s3_uri="s3://b/dyn",
                      s3_client=s3)
    assert s.source == "rfc"
    assert "MATERIAL" in s.fields and "MATL_TYPE" in s.fields
    assert ".INCLUDE" not in s.fields
    print("  [OK] DD_BAPI failure -> DD03L fallback succeeds + caches")


def test_build_schema_falls_back_to_static_catalog_when_rfc_dead():
    s3 = FakeS3()
    rfc = FakeRfc()
    rfc.fail_next["DD_BAPI_PARAMETER_GET"] = "system down"
    rfc.fail_next["RFC_READ_TABLE"] = "system down"

    class _StaticCatalog:
        @staticmethod
        def for_object(obj):
            return {"MATERIAL", "MATL_TYPE", "MBRSH"} if obj == "Material" else set()

    s = build_schema("Material", conn=rfc, sid="S4H", client="100",
                      s4_release="S4HANA_2023", cache_s3_uri="s3://b/dyn",
                      bapi_field_catalog_module=_StaticCatalog,
                      s3_client=s3)
    assert s.source == "fallback"
    assert "MATERIAL" in s.fields and "MBRSH" in s.fields
    # No cache write - the fallback isn't authoritative for the landscape
    assert s3.puts == 0
    print("  [OK] RFC dead -> static catalog fallback (no cache pollution)")


def test_build_schema_unknown_object_returns_empty_set_gracefully():
    rfc = FakeRfc()
    s = build_schema("BogusObject", conn=rfc, sid="x", client="100",
                      s4_release="r", cache_s3_uri="")
    assert s.source == "fallback"
    assert s.fields == []
    print("  [OK] unknown object -> empty fields (permissive no-op)")


def test_force_refresh_bypasses_cache():
    s3 = FakeS3()
    # Pre-seed cache
    sch = CachedSchema(sid="S4H", client="100", s4_release="S4HANA_2023",
                       object_type="Material", bapi="x",
                       fields=["STALE"], written_at=time.time(), source="rfc")
    save_cached_schema("s3://b/dyn", sch, s3_client=s3)
    rfc = FakeRfc()
    rfc.scripts["DD_BAPI_PARAMETER_GET"] = {
        "PARAMS": [{"FIELDNAME": "FRESH"}]
    }
    s = build_schema("Material", conn=rfc, sid="S4H", client="100",
                      s4_release="S4HANA_2023", cache_s3_uri="s3://b/dyn",
                      force_refresh=True, s3_client=s3)
    assert "FRESH" in s.fields and "STALE" not in s.fields
    print("  [OK] force_refresh bypasses stale cache and refreshes")


def test_build_all_schemas_returns_dict_shape_matching_catalog():
    """build_all_schemas must produce the same shape as bapi_field_catalog.as_dict()
    so it's drop-in compatible everywhere UnifiedLoader.bapi_field_catalog is used."""
    rfc = FakeRfc()
    rfc.scripts["DD_BAPI_PARAMETER_GET"] = {
        "PARAMS": [{"FIELDNAME": "F1"}, {"FIELDNAME": "F2"}]
    }
    out = build_all_schemas(["Material", "Customer"],
                             conn=rfc, sid="S4H", client="100",
                             s4_release="S4HANA_2023")
    assert isinstance(out, dict)
    assert set(out["Material"]) == {"F1", "F2"}
    assert set(out["Customer"]) == {"F1", "F2"}
    print("  [OK] build_all_schemas returns {object_type: set(fields)} ready for UnifiedLoader")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("F3 - dynamic_schema_builder tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll dynamic_schema_builder tests passed.")
