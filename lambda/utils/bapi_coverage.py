"""
bapi_coverage.py - field-coverage analysis + LTMC staging fallback.

Background
----------
Released BAPIs are support-compliant but field-incomplete. Three classic gaps:

  1. Extension fields (CI_*) added by customers - no BAPI parameter, must go
     via BADI BAPI_ADDREXTEND or be loaded via LTMC.
  2. Complex tax fields (J_1B*, India GST overlays) - rarely surfaced in
     generic BAPIs.
  3. Newer S/4 fields that the BAPI was never extended to carry.

A naive loader silently drops these fields, then reconciliation flags missing
data after the fact, after thousands of records have already been loaded.

This module does the analysis BEFORE load:

  - FieldCoverageReport: which source fields the chosen BAPI cannot carry
  - LtmcStagingEmitter: write the carve-out as an LTMC-shaped CSV/JSON so the
    Migration Cockpit can pick them up; one file per (object, batch) with a
    matching control file naming the source-field gap
  - decide_load_path(): returns BAPI | BAPI_PLUS_LTMC_DELTA | LTMC_ONLY

The interface is dependency-free (no pyrfc) so it can be exercised from any
stage handler. The actual list of BAPI-supported fields per BAPI is supplied
by the caller (the dispatcher already knows which BAPI it picked); this module
just compares it against the source record's keys.

Self-test below proves a customer record with a custom CI field is routed to
BAPI_PLUS_LTMC_DELTA, that the LTMC staging file is written with the missing
fields, and that an extension-field-free record goes straight to BAPI.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger("bapi_coverage")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
#  Coverage analysis
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FieldCoverageReport:
    object_type: str
    bapi_name: str
    record_count: int
    supported_fields: List[str]
    unsupported_fields: List[str]           # source fields the BAPI cannot carry
    extension_fields_detected: List[str]    # subset that look like CI_*/ZZ*
    tax_fields_detected: List[str]          # subset that look like J_1B*, etc.

    def to_dict(self) -> dict:
        return asdict(self)


# Field-name patterns that strongly indicate "this won't fit a generic BAPI".
_EXTENSION_PREFIXES = ("CI_", "ZZ", "ZX", "YY")
_TAX_FIELD_PATTERNS = ("J_1B", "J_1A", "J_1G", "J_1I", "J_3R", "TXJCD")


def _is_extension(field_name: str) -> bool:
    f = field_name.upper()
    return any(f.startswith(p) for p in _EXTENSION_PREFIXES)


def _is_tax(field_name: str) -> bool:
    f = field_name.upper()
    return any(f.startswith(p) for p in _TAX_FIELD_PATTERNS)


def analyze_coverage(records: Iterable[dict],
                     object_type: str,
                     bapi_name: str,
                     bapi_supported_fields: Set[str]) -> FieldCoverageReport:
    """Inspect a batch of source records; report which fields the chosen BAPI
    cannot carry. The set passed in is authoritative (typically built from the
    BAPI's interface metadata via DD_BAPI_PARAMETER_GET or hand-maintained
    catalog)."""
    seen: Set[str] = set()
    for r in records:
        for k, v in r.items():
            if v is None or v == "" or v == 0:
                continue   # field is empty → no risk if BAPI omits it
            seen.add(k.upper())

    supported_upper = {f.upper() for f in bapi_supported_fields}
    unsupported = sorted(seen - supported_upper)
    extension = [f for f in unsupported if _is_extension(f)]
    tax = [f for f in unsupported if _is_tax(f)]

    count = sum(1 for _ in records) if isinstance(records, list) else 0
    if not isinstance(records, list):
        # iterable already consumed; recover count from seen via a second pass
        # is impossible; caller may pass a list to get an accurate record_count.
        count = -1

    report = FieldCoverageReport(
        object_type=object_type, bapi_name=bapi_name,
        record_count=count if count >= 0 else 0,
        supported_fields=sorted(supported_upper & seen),
        unsupported_fields=unsupported,
        extension_fields_detected=extension,
        tax_fields_detected=tax,
    )
    if unsupported:
        logger.warning("BAPI coverage gap for %s via %s: %d fields not in interface "
                       "(extension=%d, tax=%d, sample=%s)",
                       object_type, bapi_name, len(unsupported),
                       len(extension), len(tax), unsupported[:5])
    return report


# ─────────────────────────────────────────────────────────────────────────────
#  Decision: BAPI vs BAPI+LTMC vs LTMC-only
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LoadDecision:
    path: str           # "BAPI" | "BAPI_PLUS_LTMC_DELTA" | "LTMC_ONLY"
    reason: str
    coverage: FieldCoverageReport
    ltmc_delta_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {**asdict(self), "coverage": self.coverage.to_dict()}


# A field is "load-blocking" if the BAPI dropping it would corrupt the record.
# Extension fields are load-blocking if the customer marked them in the rule
# pack; tax fields are always load-blocking for country-specific objects.
_ALWAYS_BLOCKING = set()  # populated per-object by the caller via decide_load_path


def decide_load_path(coverage: FieldCoverageReport,
                     blocking_fields: Optional[Set[str]] = None) -> LoadDecision:
    """Decide whether to load via BAPI, BAPI + LTMC delta, or LTMC only.

    Rules:
      - No unsupported fields                              -> BAPI
      - Unsupported but none are in blocking_fields        -> BAPI (warn only)
      - Unsupported AND some are blocking                  -> BAPI_PLUS_LTMC_DELTA
      - More than half of populated fields are unsupported -> LTMC_ONLY (BAPI is
        the wrong tool for this object/customer)
    """
    blocking = {f.upper() for f in (blocking_fields or set())}
    auto_blocking = set(coverage.tax_fields_detected) | set(coverage.extension_fields_detected)
    effectively_blocking = (set(coverage.unsupported_fields) & blocking) | auto_blocking

    total_populated = len(coverage.supported_fields) + len(coverage.unsupported_fields)
    if total_populated and len(coverage.unsupported_fields) / total_populated > 0.5:
        return LoadDecision(
            path="LTMC_ONLY",
            reason=f"{len(coverage.unsupported_fields)}/{total_populated} populated "
                   f"source fields are not carried by {coverage.bapi_name} - LTMC is the correct lane",
            coverage=coverage,
            ltmc_delta_fields=coverage.unsupported_fields)

    if not coverage.unsupported_fields:
        return LoadDecision(path="BAPI",
                            reason="all populated source fields supported by BAPI",
                            coverage=coverage)

    if effectively_blocking:
        return LoadDecision(
            path="BAPI_PLUS_LTMC_DELTA",
            reason=f"{len(effectively_blocking)} blocking field(s) cannot ride the BAPI "
                   f"(extension={len(coverage.extension_fields_detected)}, "
                   f"tax={len(coverage.tax_fields_detected)}); "
                   f"emit the delta to LTMC after BAPI load",
            coverage=coverage,
            ltmc_delta_fields=sorted(effectively_blocking))

    return LoadDecision(
        path="BAPI",
        reason=f"{len(coverage.unsupported_fields)} non-blocking fields will be dropped "
               f"(safe per ruleset)",
        coverage=coverage)


# ─────────────────────────────────────────────────────────────────────────────
#  LTMC staging emit (CSV + control JSON, picked up by Migration Cockpit)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LtmcStagingHandoff:
    object_type: str
    csv_path: str
    control_path: str
    records: int
    delta_fields: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


class LtmcStagingEmitter:
    """Write the LTMC-shaped staging file + a control JSON describing the gap.

    Output layout under `out_dir`:
        ltmc-staging/<object_type>/<batch_id>.csv
        ltmc-staging/<object_type>/<batch_id>.control.json
    """

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)

    def emit(self, records: List[dict],
             object_type: str,
             batch_id: str,
             delta_fields: List[str],
             bapi_name: str,
             reason: str) -> LtmcStagingHandoff:
        target = self.out_dir / "ltmc-staging" / object_type
        target.mkdir(parents=True, exist_ok=True)
        csv_path = target / f"{batch_id}.csv"
        ctl_path = target / f"{batch_id}.control.json"

        # CSV header = union of supported BAPI key fields (so MC can join back)
        # plus the delta fields the BAPI cannot carry. Caller usually passes the
        # full record so we just dump every field present.
        all_fields: List[str] = []
        seen_set: Set[str] = set()
        for r in records:
            for k in r.keys():
                if k not in seen_set:
                    all_fields.append(k)
                    seen_set.add(k)

        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r)

        ctl_path.write_text(json.dumps({
            "object_type": object_type,
            "batch_id": batch_id,
            "record_count": len(records),
            "delta_fields_for_ltmc": delta_fields,
            "bapi_attempted": bapi_name,
            "reason": reason,
            "ltmc_load_mode": "Staging tables (Direct Transfer)",
            "ltmc_object_recommendation": _ltmc_object_for(object_type),
        }, indent=2), encoding="utf-8")

        return LtmcStagingHandoff(
            object_type=object_type,
            csv_path=str(csv_path),
            control_path=str(ctl_path),
            records=len(records),
            delta_fields=delta_fields)


def _ltmc_object_for(object_type: str) -> str:
    """Map our internal object type to the standard LTMC migration-object name."""
    return {
        "BusinessPartner": "Business Partner (Customer & Vendor)",
        "Customer":        "Business Partner (Customer)",
        "Vendor":          "Business Partner (Supplier)",
        "Material":        "Material",
        "FixedAsset":      "Fixed Asset",
        "GLAccount":       "G/L Account",
        "OpenAR":          "Customer open items",
        "OpenAP":          "Supplier open items",
        "OpenPO":          "Open purchase orders",
        "Bank":            "Bank",
    }.get(object_type, object_type)


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    print("=" * 78)
    print("bapi_coverage - self-test")
    print("=" * 78)

    # Hand-shaped BAPI catalog for the test - real code reads from
    # DD_BAPI_PARAMETER_GET or a static catalog file.
    BAPI_CUSTOMER_FIELDS = {
        "KUNNR", "NAME1", "STRAS", "ORT01", "PSTLZ", "LAND1", "SPRAS",
        "STCEG", "STCD1", "TELF1",
    }

    # Case 1: clean record, BAPI handles everything
    clean = [{"KUNNR": "100001", "NAME1": "Beta Inc", "LAND1": "US",
              "ORT01": "Boston", "STCEG": "12-3456789"}]
    cov = analyze_coverage(clean, "Customer", "BAPI_CUSTOMER_CREATEFROMDATA",
                           BAPI_CUSTOMER_FIELDS)
    decision = decide_load_path(cov)
    assert decision.path == "BAPI", f"expected BAPI, got {decision.path}"
    print(f"  clean record: path={decision.path} ({decision.reason}) OK")

    # Case 2: record carries a CI_ extension field + a J_1B tax field
    dirty = [{"KUNNR": "100002", "NAME1": "ACME Brasil", "LAND1": "BR",
              "ORT01": "Sao Paulo", "STCD1": "12.345.678/0001-90",
              "CI_LOYALTY_TIER": "GOLD",
              "J_1BNFTYPE": "T01"}]
    cov2 = analyze_coverage(dirty, "Customer", "BAPI_CUSTOMER_CREATEFROMDATA",
                            BAPI_CUSTOMER_FIELDS)
    assert "CI_LOYALTY_TIER" in cov2.extension_fields_detected
    assert "J_1BNFTYPE" in cov2.tax_fields_detected
    decision2 = decide_load_path(cov2)
    assert decision2.path == "BAPI_PLUS_LTMC_DELTA", \
        f"expected BAPI_PLUS_LTMC_DELTA, got {decision2.path}"
    print(f"  CI+tax record: path={decision2.path} (delta={decision2.ltmc_delta_fields}) OK")

    # Case 3: > 50% unsupported → route entirely via LTMC
    heavy_extension = [{"KUNNR": "100003", "NAME1": "Zeta Co",
                        "CI_F1": "x", "CI_F2": "y", "CI_F3": "z",
                        "ZZ_F1": "a", "ZZ_F2": "b"}]
    cov3 = analyze_coverage(heavy_extension, "Customer", "BAPI_CUSTOMER_CREATEFROMDATA",
                            BAPI_CUSTOMER_FIELDS)
    decision3 = decide_load_path(cov3)
    assert decision3.path == "LTMC_ONLY", f"expected LTMC_ONLY, got {decision3.path}"
    print(f"  extension-heavy record: path={decision3.path} ({decision3.reason}) OK")

    # Case 4: write the LTMC staging file
    with tempfile.TemporaryDirectory() as td:
        emitter = LtmcStagingEmitter(td)
        handoff = emitter.emit(dirty, "Customer", "batch_0001",
                               decision2.ltmc_delta_fields,
                               "BAPI_CUSTOMER_CREATEFROMDATA",
                               decision2.reason)
        assert Path(handoff.csv_path).exists()
        assert Path(handoff.control_path).exists()
        ctl = json.loads(Path(handoff.control_path).read_text())
        assert "Business Partner (Customer)" in ctl["ltmc_object_recommendation"]
        assert ctl["delta_fields_for_ltmc"] == sorted(decision2.ltmc_delta_fields)
        print(f"  LTMC staging emit: csv+ctl written, "
              f"recommended object='{ctl['ltmc_object_recommendation']}' OK")

    print("\nOK - BAPI coverage analysis routes records correctly and emits LTMC staging files.")
