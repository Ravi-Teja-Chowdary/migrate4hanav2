"""
dynamic_schema_builder - replace the static bapi_field_catalog with runtime
DDIC introspection (Gemini Phase 2).

How it works
------------
For a target migration object (e.g. "Material"), the builder:

  1. Asks the S/4 system for the BAPI's interface description by calling
     ``DD_BAPI_PARAMETER_GET`` (preferred) or reading ``DD03L`` directly
     for the BAPI's structure parameters.
  2. Compiles the result into the same shape ``bapi_field_catalog.as_dict()``
     emits: ``{object_type: set(uppercased_fields)}``. So downstream callers
     (`bapi_coverage.LtmcStagingEmitter`, the spine orchestrator's
     EXTENSIONIN gate) work with either the static baseline or the dynamic
     output - drop-in compatible.
  3. Caches the compiled set in S3 keyed by ``(SID, client, S4 release,
     object)`` with a configurable TTL (default 7 days). Subsequent runs
     against the same target reuse the cache; the build cost is paid once
     per landscape.

Fallback chain (each step is short-circuit by the next on hit):

    cached in S3 (fresh) -> use it
                  (stale) -> rebuild from RFC, refresh cache
    RFC call fails       -> fall back to bapi_field_catalog.for_object()
                            (the hand-curated baseline)
    no baseline either   -> return empty set (caller's field-coverage gate
                            becomes a permissive no-op)

The module is stdlib + lazy boto3 (only imported when an S3 URI is configured).
The pyrfc call is also lazy. Both fakes inject cleanly for unit tests.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("dynamic_schema_builder")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TTL_SECONDS = int(os.environ.get("M4H_DYNAMIC_SCHEMA_TTL_SEC", 7 * 24 * 3600))
DEFAULT_CACHE_S3   = os.environ.get("M4H_DYNAMIC_SCHEMA_S3", "")
# e.g. "s3://migrate4hana-schemas-prod/dynamic-schema/"

# Migration object -> the BAPI / OData service whose interface we introspect.
# Keep this aligned with unified_loader's OBJECT_MECHANISM map.
OBJECT_BAPI_MAP: dict = {
    "Customer":         "BAPI_CUSTOMER_CREATEFROMDATA1",
    "Vendor":           "BAPI_VENDOR_CREATE",
    "Material":         "BAPI_MATERIAL_SAVEDATA",
    "BusinessPartner":  "BAPI_BUPA_CENTRAL_CREATE",
    "ExchangeRates":    "BAPI_EXCHRATE_CREATEMULTIPLE",
    "OpenPO":           "BAPI_PO_CREATE1",
    "OpenAR":           "BAPI_ACC_DOCUMENT_POST",
    "OpenAP":           "BAPI_ACC_DOCUMENT_POST",
    "CostCenter":       "BAPI_COSTCENTER_CREATEMULTIPLE",
    "ProfitCenter":     "BAPI_PROFITCENTER_CREATE",
    "FixedAsset":       "BAPI_FIXEDASSET_CREATE1",
    "Bank":             "BAPI_BANK_CREATE",
    "InternalOrder":    "BAPI_INTERNALORDER_CREATEMULTI",
    "Equipment":        "BAPI_EQUI_CREATE",
    "FunctionalLocation": "BAPI_FUNCLOC_CREATE",
    "Project":          "BAPI_BUS2001_CREATE",
    "PurchaseRequisition": "BAPI_PR_CREATE",
    "OpenSO":           "BAPI_SALESORDER_CREATEFROMDAT2",
    "PurchaseContract": "BAPI_CONTRACT_CREATE",
}


@dataclass
class CachedSchema:
    """The cache envelope. Persisted as JSON to S3."""
    sid:           str
    client:        str
    s4_release:    str        # e.g. "S4HANA_2023"
    object_type:   str
    bapi:          str
    fields:        list       # uppercased field names
    written_at:    float      # epoch seconds
    source:        str        # "rfc" | "fallback" | "manual"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CachedSchema":
        return cls(
            sid=d.get("sid", ""), client=d.get("client", ""),
            s4_release=d.get("s4_release", ""), object_type=d.get("object_type", ""),
            bapi=d.get("bapi", ""), fields=list(d.get("fields", []) or []),
            written_at=float(d.get("written_at", 0.0)),
            source=d.get("source", "manual"),
        )

    def is_fresh(self, ttl_seconds: int) -> bool:
        return (time.time() - self.written_at) < ttl_seconds


# ─────────────────────────────────────────────────────────────────────────────
# Introspection (RFC) helpers
# ─────────────────────────────────────────────────────────────────────────────
def introspect_via_dd_bapi_parameter_get(conn, bapi_name: str) -> list:
    """Call DD_BAPI_PARAMETER_GET on the target system. Returns a list of raw
    parameter rows (one dict per BAPI parameter). Raises on RFC error.

    The function returns a deeply nested structure; we flatten only what's
    needed for the field-coverage gate (field names).
    """
    resp = conn.call("DD_BAPI_PARAMETER_GET", FUNCNAME=bapi_name)
    return list(resp.get("PARAMS") or resp.get("BAPI_PARAMS") or [])


def introspect_via_dd03l(conn, structure_name: str, max_rows: int = 500) -> list:
    """Read DD03L (DDIC field-level metadata for a structure or table). This is
    the fallback when DD_BAPI_PARAMETER_GET isn't available on the release.

    Returns a list of dicts: ``{FIELDNAME, POSITION, KEYFLAG, DATATYPE, LENG, DECIMALS}``.
    """
    resp = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="DD03L",
        DELIMITER="|",
        OPTIONS=[{"TEXT": f"TABNAME = '{structure_name}'"}],
        FIELDS=[{"FIELDNAME": "FIELDNAME"},
                {"FIELDNAME": "POSITION"},
                {"FIELDNAME": "KEYFLAG"},
                {"FIELDNAME": "DATATYPE"},
                {"FIELDNAME": "LENG"},
                {"FIELDNAME": "DECIMALS"}],
        ROWCOUNT=max_rows,
    )
    fields_meta = resp.get("FIELDS") or []
    out = []
    for r in resp.get("DATA") or []:
        wa = r.get("WA") or ""
        parts = wa.split("|") if "|" in wa else _split_by_offsets(wa, fields_meta)
        if len(parts) >= 6:
            out.append({
                "FIELDNAME": parts[0].strip(),
                "POSITION":  parts[1].strip(),
                "KEYFLAG":   parts[2].strip(),
                "DATATYPE":  parts[3].strip(),
                "LENG":      parts[4].strip(),
                "DECIMALS":  parts[5].strip(),
            })
    return out


def introspect_via_dfies(conn, table_name: str) -> list:
    """Read DFIES via DDIF_FIELDINFO_GET for richer per-field metadata
    (mandatory flag, value table reference, search help, conversion exit).
    Used opportunistically for value validation, not for the basic gate.
    """
    resp = conn.call("DDIF_FIELDINFO_GET", TABNAME=table_name)
    return list(resp.get("DFIES_TAB") or [])


def _split_by_offsets(wa: str, fields_meta: list) -> list:
    """Fallback parser when RFC_READ_TABLE doesn't honour DELIMITER (some
    releases). Walk the OFFSET/LENGTH metadata to slice each column."""
    out = []
    for f in fields_meta:
        try:
            off = int(f.get("OFFSET", 0))
            ln  = int(f.get("LENGTH", 0))
            out.append(wa[off:off + ln])
        except Exception:
            out.append("")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Field-set compilation
# ─────────────────────────────────────────────────────────────────────────────
def compile_field_set_from_dd_bapi(params: list) -> set:
    """Compile the uppercased field set from a DD_BAPI_PARAMETER_GET response.

    Each row has either:
      - a primitive PARAMETER (already a single field), or
      - a STRUCTURE/TABLE reference whose constituent fields we extract.
    """
    out: set = set()
    for p in params or []:
        fname = (p.get("PARAMETER") or p.get("FIELDNAME") or "").strip()
        if fname:
            out.add(fname.upper())
        # Some DD_BAPI_PARAMETER_GET implementations also expose a SUBFIELDS
        # list per parameter; if present, fold those in too.
        for sub in (p.get("SUBFIELDS") or p.get("FIELDS") or []):
            fn = (sub.get("FIELDNAME") or sub.get("PARAMETER") or "").strip()
            if fn:
                out.add(fn.upper())
    return out


def compile_field_set_from_dd03l(rows: list) -> set:
    """Compile a flat field set from a DD03L read of a structure."""
    out: set = set()
    for r in rows or []:
        fn = (r.get("FIELDNAME") or "").strip()
        if fn and not fn.startswith("."):    # skip include directives like ".INCLUDE"
            out.add(fn.upper())
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Cache (S3) layer
# ─────────────────────────────────────────────────────────────────────────────
def _parse_s3_uri(uri: str) -> tuple:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri!r}")
    rest = uri[len("s3://"):]
    bucket, _, prefix = rest.partition("/")
    return bucket, prefix.rstrip("/")


def _cache_key(prefix: str, sid: str, client: str, s4_release: str, object_type: str) -> str:
    return f"{prefix}/{sid}/{client}/{s4_release}/{object_type}.json".lstrip("/")


def load_cached_schema(s3_uri: str, sid: str, client: str, s4_release: str,
                       object_type: str, *, s3_client=None) -> Optional[CachedSchema]:
    """Return the cached CachedSchema if present (regardless of freshness); the
    caller decides whether to trust it via ``CachedSchema.is_fresh()``.
    Returns None on cache miss or any read error."""
    if not s3_uri:
        return None
    bucket, prefix = _parse_s3_uri(s3_uri)
    key = _cache_key(prefix, sid, client, s4_release, object_type)
    try:
        if s3_client is None:
            import boto3  # type: ignore
            s3_client = boto3.client("s3")
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read() if hasattr(obj["Body"], "read") else obj["Body"]
        return CachedSchema.from_dict(json.loads(body))
    except Exception as e:
        logger.debug("dynamic_schema cache miss for %s/%s/%s/%s: %s",
                     sid, client, s4_release, object_type, e)
        return None


def save_cached_schema(s3_uri: str, schema: CachedSchema, *, s3_client=None) -> None:
    """Best-effort cache write. Failures are logged, never raised - cache is
    a performance optimization, not a correctness gate."""
    if not s3_uri:
        return
    bucket, prefix = _parse_s3_uri(s3_uri)
    key = _cache_key(prefix, schema.sid, schema.client, schema.s4_release, schema.object_type)
    try:
        if s3_client is None:
            import boto3  # type: ignore
            s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=bucket, Key=key,
            Body=json.dumps(schema.to_dict(), indent=2).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as e:
        logger.warning("dynamic_schema cache write failed for %s: %s", key, e)


# ─────────────────────────────────────────────────────────────────────────────
# The public orchestrator
# ─────────────────────────────────────────────────────────────────────────────
def build_schema(object_type: str, *,
                 conn=None, sid: str = "", client: str = "100",
                 s4_release: str = "UNKNOWN",
                 cache_s3_uri: str = "",
                 ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 bapi_field_catalog_module=None,
                 s3_client=None,
                 force_refresh: bool = False) -> CachedSchema:
    """Resolve the field set for an object via cache -> RFC -> static fallback.

    Always returns a CachedSchema (never None); ``schema.source`` says where
    the fields came from ("rfc" / "fallback" / "manual"). ``schema.fields`` is
    the uppercased field-name list ready to feed the field-coverage gate.

    :param conn: pyrfc Connection (or fake). If None, skip the RFC step.
    :param cache_s3_uri: e.g. "s3://migrate4hana-schemas-prod/dynamic-schema".
                        Empty disables caching.
    :param force_refresh: bypass the cache (always re-introspect + rewrite).
    """
    bapi_name = OBJECT_BAPI_MAP.get(object_type, "")

    # 1) Try cache
    if not force_refresh and cache_s3_uri:
        cached = load_cached_schema(cache_s3_uri, sid, client, s4_release,
                                     object_type, s3_client=s3_client)
        if cached is not None and cached.is_fresh(ttl_seconds):
            return cached

    # 2) Try RFC introspection
    if conn is not None and bapi_name:
        try:
            params = introspect_via_dd_bapi_parameter_get(conn, bapi_name)
            field_set = compile_field_set_from_dd_bapi(params)
            if field_set:
                schema = CachedSchema(
                    sid=sid, client=client, s4_release=s4_release,
                    object_type=object_type, bapi=bapi_name,
                    fields=sorted(field_set), written_at=time.time(),
                    source="rfc",
                )
                save_cached_schema(cache_s3_uri, schema, s3_client=s3_client)
                return schema
        except Exception as e:
            logger.info("DD_BAPI_PARAMETER_GET failed for %s; trying DD03L: %s",
                        bapi_name, e)
            # DD_BAPI fallback: read DD03L for one of the structures the BAPI
            # uses. We don't always know the structure name, so this only
            # catches a subset; that's OK because step 3 covers everything.
            try:
                rows = introspect_via_dd03l(conn, structure_name=bapi_name)
                field_set = compile_field_set_from_dd03l(rows)
                if field_set:
                    schema = CachedSchema(
                        sid=sid, client=client, s4_release=s4_release,
                        object_type=object_type, bapi=bapi_name,
                        fields=sorted(field_set), written_at=time.time(),
                        source="rfc",
                    )
                    save_cached_schema(cache_s3_uri, schema, s3_client=s3_client)
                    return schema
            except Exception as e2:
                logger.info("DD03L fallback also failed for %s: %s", bapi_name, e2)

    # 3) Fall back to the static bundled catalog
    static_fields: set = set()
    if bapi_field_catalog_module is None:
        try:
            import bapi_field_catalog as bapi_field_catalog_module   # type: ignore
        except Exception:
            bapi_field_catalog_module = None
    if bapi_field_catalog_module is not None:
        try:
            static_fields = bapi_field_catalog_module.for_object(object_type)
        except Exception:
            static_fields = set()
    return CachedSchema(
        sid=sid, client=client, s4_release=s4_release,
        object_type=object_type, bapi=bapi_name,
        fields=sorted({f.upper() for f in static_fields or set()}),
        written_at=time.time(),
        source="fallback",
    )


def build_all_schemas(object_types: list, *, conn=None, sid: str = "",
                      client: str = "100", s4_release: str = "UNKNOWN",
                      cache_s3_uri: str = "",
                      ttl_seconds: int = DEFAULT_TTL_SECONDS,
                      s3_client=None,
                      force_refresh: bool = False) -> dict:
    """Build schemas for many objects. Returns ``{object_type: set(fields)}``
    - same shape as ``bapi_field_catalog.as_dict()``, so it's a drop-in
    replacement when wired into UnifiedLoader.bapi_field_catalog."""
    out: dict = {}
    for obj in object_types:
        s = build_schema(obj, conn=conn, sid=sid, client=client,
                          s4_release=s4_release, cache_s3_uri=cache_s3_uri,
                          ttl_seconds=ttl_seconds, s3_client=s3_client,
                          force_refresh=force_refresh)
        out[obj] = set(s.fields)
    return out
