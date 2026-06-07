"""
version_matrix — Migrate4HANA supported (source ECC, target S/4HANA) pair
catalogue + routing rules.

This module is the **single source of truth** for which version combinations
the tool supports and how its runtime behaves for each one. It is consumed by:

  * the FastAPI backend (``api_server.py``) for the
    ``/api/versions/supported|detected|selected`` endpoints
  * the data-migrator Lambda handler for extract-path / package-size / template
    decisions
  * the frontend `VersionMatrix.jsx` page (via the API) to drive the selector

Two product decisions baked in (per Gemini's Phase 1 prompt):

  * **Source scope:** SAP ECC 6.0 EHP0 through EHP8. ECC 5.0 and older are
    out of scope (no Unicode kernel + non-NetWeaver ABAP rules out modern RFC).
  * **Target scope:** SAP S/4HANA 1909 through 2025. 1809 and earlier are out
    of scope (no SAP Migration Cockpit standard layer).

Anything outside this matrix MUST halt the run with a clear
``VersionIncompatibilityError``. The matrix is also designed to be extensible:
new releases are added by inserting one entry into ``TARGET_S4_RELEASES`` (or
the source list); the routing logic adapts via the ``routing_for_pair`` helper.

The module is stdlib-only. No boto3, no SAP imports. Trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Source ECC catalogue
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EccVersion:
    """A supported source ECC version + the runtime traits that matter."""
    code: str          # e.g. "ECC60_EHP8"   (machine ID, used in JSON)
    label: str         # e.g. "ECC 6.0 EHP8" (display)
    ehp: int           # 0..8
    db_default: str    # default DB family for routing ("ANY_DB" or "HANA")
    extract_strategy: str   # "LEGACY_CHUNKED" | "MODERN_BULK"
    default_package_size: int   # rows per RFC_READ_TABLE pull
    can_use_open_sql_optimizations: bool


SOURCE_ECC_VERSIONS: tuple[EccVersion, ...] = (
    EccVersion("ECC60_EHP0", "ECC 6.0 (no EHP)",  0, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP1", "ECC 6.0 EHP1",      1, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP2", "ECC 6.0 EHP2",      2, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP3", "ECC 6.0 EHP3",      3, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP4", "ECC 6.0 EHP4",      4, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP5", "ECC 6.0 EHP5",      5, "ANY_DB", "LEGACY_CHUNKED",  5_000, False),
    EccVersion("ECC60_EHP6", "ECC 6.0 EHP6",      6, "ANY_DB", "LEGACY_CHUNKED", 10_000, False),
    # EHP7/8 default to AnyDB because many installs (Oracle/MSSQL/DB2) are still
    # on traditional RDBMS. The RFC detector promotes to HANA when RFCDBSYS=HDB.
    EccVersion("ECC60_EHP7", "ECC 6.0 EHP7",      7, "ANY_DB", "LEGACY_CHUNKED", 10_000, False),
    EccVersion("ECC60_EHP8", "ECC 6.0 EHP8",      8, "ANY_DB", "LEGACY_CHUNKED", 10_000, False),
)
SOURCE_BY_CODE = {v.code: v for v in SOURCE_ECC_VERSIONS}


# ─────────────────────────────────────────────────────────────────────────────
# Target S/4HANA catalogue
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class S4Release:
    code: str          # e.g. "S4HANA_2023"
    label: str         # e.g. "S/4HANA 2023"
    release_year: int  # 1909, 2020, 2021, ..., 2025
    template_format: str       # "LEGACY_LSMW_XML" (<2020) | "FIORI_MC_CSV" (>=2020)
    bp_external_numbering: bool   # CVI mandates BP-led numbering (all >=1909)
    odata_ltmc_supported: bool    # MC OData service available
    notes: str = ""


TARGET_S4_RELEASES: tuple[S4Release, ...] = (
    S4Release("S4HANA_1909", "S/4HANA 1909", 1909,
              "LEGACY_LSMW_XML", True,  False,
              "Last release using LSMW XML migration objects; MC OData not exposed."),
    S4Release("S4HANA_2020", "S/4HANA 2020", 2020,
              "FIORI_MC_CSV", True, True),
    S4Release("S4HANA_2021", "S/4HANA 2021", 2021,
              "FIORI_MC_CSV", True, True),
    S4Release("S4HANA_2022", "S/4HANA 2022", 2022,
              "FIORI_MC_CSV", True, True),
    S4Release("S4HANA_2023", "S/4HANA 2023", 2023,
              "FIORI_MC_CSV", True, True),
    S4Release("S4HANA_2024", "S/4HANA 2024", 2024,
              "FIORI_MC_CSV", True, True),
    S4Release("S4HANA_2025", "S/4HANA 2025", 2025,
              "FIORI_MC_CSV", True, True,
              "Latest supported; transformation engine + dynamic schema tested here first."),
)
TARGET_BY_CODE = {r.code: r for r in TARGET_S4_RELEASES}


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility + routing
# ─────────────────────────────────────────────────────────────────────────────
class VersionIncompatibilityError(ValueError):
    """Raised when a configured (source, target) pair is not in the supported matrix."""


@dataclass(frozen=True)
class RoutingPlan:
    """The effective runtime configuration derived from a (source, target) pair."""
    source: EccVersion
    target: S4Release
    extract_strategy: str       # carried from source
    package_size: int           # carried from source
    template_format: str        # carried from target
    use_open_sql_optimizations: bool
    bp_external_numbering: bool
    odata_ltmc_supported: bool
    fargate_fan_out: str        # "LOW" | "HIGH"
    cluster_read_safety: str    # "STRICT" | "RELAXED"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = asdict(self.source)
        d["target"] = asdict(self.target)
        return d


def routing_for_pair(source_code: str, target_code: str,
                     source_db: Optional[str] = None) -> RoutingPlan:
    """Resolve a (source ECC code, target S/4 code) pair into a RoutingPlan.

    :param source_code: catalogue code of the source ECC version (EccVersion.code)
    :param target_code: catalogue code of the target S/4HANA release
    :param source_db:   optional DB family override ("HANA" or "ANY_DB"). The
                        EccVersion catalogue carries conservative defaults
                        (ANY_DB) because most ECC installs are still on
                        traditional RDBMS. When the detector or UI knows the
                        source is on HANA, pass "HANA" here to promote the
                        extract strategy to MODERN_BULK.

    Raises VersionIncompatibilityError if either code is unknown or the pair
    is forbidden (e.g. EHP0 paired with 2024 - no realistic path, hasn't been
    field-tested, so we refuse to claim support).
    """
    src = SOURCE_BY_CODE.get(source_code)
    tgt = TARGET_BY_CODE.get(target_code)
    if src is None:
        raise VersionIncompatibilityError(
            f"Unknown source version {source_code!r}. "
            f"Supported: {sorted(SOURCE_BY_CODE)}"
        )
    if tgt is None:
        raise VersionIncompatibilityError(
            f"Unknown target version {target_code!r}. "
            f"Supported: {sorted(TARGET_BY_CODE)}"
        )

    # Per-pair rules: prevent insane combinations we can't field-validate.
    # EHP0-3 -> 2023+ is theoretically possible but practically a 12-year jump
    # we haven't proved out. Force the customer to upgrade their ECC to EHP4+
    # first OR accept landing on 1909/2020/2021.
    if src.ehp <= 3 and tgt.release_year >= 2023:
        raise VersionIncompatibilityError(
            f"{src.label} -> {tgt.label} not supported: 12+ year jump from "
            f"non-Unicode-stable EHP onto a modern release. Either upgrade "
            f"the source to EHP4+ or target 1909/2020/2021."
        )

    # Apply DB override: if the caller knows the source is on HANA AND the EHP
    # is recent enough (EHP6+) to actually benefit from open-SQL optimisations,
    # promote the routing to modern bulk.
    effective_db = (source_db or src.db_default).upper()
    if effective_db == "HANA" and src.ehp >= 6:
        extract_strategy = "MODERN_BULK"
        package_size = max(src.default_package_size, 25_000)
        open_sql_ok = True
    else:
        extract_strategy = src.extract_strategy
        package_size = src.default_package_size
        open_sql_ok = src.can_use_open_sql_optimizations

    # Derive composite routing tags.
    fargate_fan_out = "HIGH" if extract_strategy == "MODERN_BULK" else "LOW"
    cluster_read_safety = "RELAXED" if open_sql_ok else "STRICT"

    return RoutingPlan(
        source=src,
        target=tgt,
        extract_strategy=extract_strategy,
        package_size=package_size,
        template_format=tgt.template_format,
        use_open_sql_optimizations=open_sql_ok,
        bp_external_numbering=tgt.bp_external_numbering,
        odata_ltmc_supported=tgt.odata_ltmc_supported,
        fargate_fan_out=fargate_fan_out,
        cluster_read_safety=cluster_read_safety,
    )


def supported_pairs() -> list[dict]:
    """Return all valid (source, target) pairs, suitable for serving to the UI."""
    pairs: list[dict] = []
    for src in SOURCE_ECC_VERSIONS:
        for tgt in TARGET_S4_RELEASES:
            try:
                plan = routing_for_pair(src.code, tgt.code)
            except VersionIncompatibilityError:
                continue
            pairs.append({
                "source_code": src.code,
                "source_label": src.label,
                "target_code": tgt.code,
                "target_label": tgt.label,
                "extract_strategy": plan.extract_strategy,
                "template_format": plan.template_format,
                "fargate_fan_out": plan.fargate_fan_out,
            })
    return pairs


def matrix_payload() -> dict:
    """The full catalogue, ready to serve as JSON to the frontend."""
    return {
        "sources": [asdict(s) for s in SOURCE_ECC_VERSIONS],
        "targets": [asdict(t) for t in TARGET_S4_RELEASES],
        "valid_pairs": supported_pairs(),
        "doc_url": "https://migrate4hana.dev/version-matrix",
    }


# ─────────────────────────────────────────────────────────────────────────────
# RFC-detection helpers (called from api_server.py)
# ─────────────────────────────────────────────────────────────────────────────
def detect_source_ecc_version(rfc_system_info: dict) -> Optional[EccVersion]:
    """Map a raw RFC_SYSTEM_INFO response to our EccVersion catalogue.

    Expected keys on the input dict (typed by NW RFC):
       RFCSI_EXPORT.RFCSAPRL   e.g. "740" (Kernel/SAP_BASIS release)
       RFCSI_EXPORT.RFCSI_RESV  reserved; sometimes carries EHP hint
       RFCSI_EXPORT.RFCDBSYS    DB family - "HDB" if HANA

    Returns None when we can't confidently map (caller surfaces "unknown" to UI).
    """
    if not rfc_system_info:
        return None
    export = (rfc_system_info.get("RFCSI_EXPORT") or rfc_system_info)
    saprl = str(export.get("RFCSAPRL") or "").strip()
    dbsys = str(export.get("RFCDBSYS") or "").strip().upper()
    # SAP_BASIS release -> EHP mapping (kernel release table; well-known)
    #   700/701/702 -> EHP0/EHP1/EHP2     (ECC 6.0 base + first EHPs)
    #   730/731     -> EHP6 / EHP6 SP
    #   740/741/742 -> EHP7
    #   750/751/752/753 -> EHP8
    rel_to_ehp = {
        "700": 0, "701": 1, "702": 2, "703": 3, "710": 3, "711": 4,
        "720": 4, "730": 6, "731": 6,
        "740": 7, "741": 7, "742": 7,
        "750": 8, "751": 8, "752": 8, "753": 8,
    }
    ehp = rel_to_ehp.get(saprl)
    if ehp is None:
        return None
    for v in SOURCE_ECC_VERSIONS:
        if v.ehp == ehp:
            # Override DB hint if RFC clearly says HANA
            if dbsys == "HDB" and v.db_default != "HANA":
                # synthesize an in-place override; doesn't pollute the catalogue
                return EccVersion(v.code, v.label, v.ehp, "HANA",
                                  "MODERN_BULK",
                                  max(v.default_package_size, 25_000), True)
            return v
    return None


def detect_target_s4_release(cvers_rows: list[dict]) -> Optional[S4Release]:
    """Map CVERS rows (component release info) to our S4Release catalogue.

    CVERS holds per-component release data. We look at the S4CORE row whose
    RELEASE looks like "100" -> 1909, "101" -> 2020, "102" -> 2021, ..., "108" -> 2025.
    """
    if not cvers_rows:
        return None
    s4core_rel = None
    for row in cvers_rows:
        name = (row.get("COMPONENT") or row.get("COMP_ID") or "").upper()
        if name == "S4CORE":
            s4core_rel = str(row.get("RELEASE") or "").strip()
            break
    if not s4core_rel:
        return None
    rel_to_year = {
        "100": 1909, "101": 2020, "102": 2021, "103": 2022,
        "104": 2022, "105": 2023, "106": 2023, "107": 2024,
        "108": 2025,
    }
    year = rel_to_year.get(s4core_rel)
    if year is None:
        return None
    for r in TARGET_S4_RELEASES:
        if r.release_year == year:
            return r
    return None
