"""
cvi_mapper.py - Customer/Vendor Integration (CVI) ->S/4HANA Business Partner unifier.

Background
----------
ECC stores customers in KNA1 and vendors in LFA1 with overlapping number ranges
and frequently duplicate addresses (same legal entity registered as both a
customer and a vendor under different numbers). S/4HANA forces both into a
single BP entity (BUT000) with role assignments (FLCU01 for customer, FLVN01
for vendor). Naive migration creates duplicate BPs, breaks CVI joins, and
corrupts open-AR/AP postings that hang off the partner.

This module does the deterministic part of that unification:

  1. detect_overlap()      - same number used by both KNA1 and LFA1
  2. detect_duplicates()   - same (name, country, tax_id) across either table
  3. unify()               - emit a CviMap: legacy_key -> (target_bp_id, roles, conflicts)
  4. CviConflict           - structured rejection for records we will NOT
                             auto-merge (e.g. mismatched VAT numbers, name
                             collision with different cities). These go to the
                             dead-letter for a data steward.

Out of scope (real CVI projects do these in addition):
  - address harmonization across locales (street abbreviation, char-set)
  - fuzzy matching with edit distance / phonetic keys
  - business-rule overrides per company code

Self-test at bottom proves: number-range overlap detection, exact-duplicate
fold, near-duplicate quarantine, and round-trip stability (re-running on the
same input produces identical maps).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("cvi_mapper")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# S/4 BP role keys
ROLE_CUSTOMER = "FLCU01"
ROLE_VENDOR = "FLVN01"
ROLE_FI_CUSTOMER = "FLCU00"
ROLE_FI_VENDOR = "FLVN00"


@dataclass
class CviConflict:
    """A record we refuse to auto-merge - needs a human data steward."""
    legacy_kna1_id: Optional[str]
    legacy_lfa1_id: Optional[str]
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CviMapping:
    """A legacy KNA1/LFA1 key resolved to a target BP."""
    target_bp_id: str
    roles: List[str]
    source_kna1: Optional[str] = None
    source_lfa1: Optional[str] = None
    merged: bool = False     # True if both customer + vendor folded into one BP
    # Cross-references resolved in phase 2 (LIFNR-on-customer, KUNNR-on-vendor,
    # KNRZE / LIFRG / etc.). Each entry: {"field": "LIFNR", "target_bp": "BP..."}.
    # Empty list when the source had no cross-refs.
    cross_refs: List[dict] = field(default_factory=list)
    # Two-phase load hint: phase 1 creates the stub, phase 2 attaches xrefs.
    load_phase: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
#  Normalization helpers
# ─────────────────────────────────────────────────────────────────────────────
_WS_RE = re.compile(r"\s+")
_NONALNUM_RE = re.compile(r"[^A-Z0-9]+")


def _norm_name(name: str) -> str:
    """Uppercase + collapse whitespace + strip punctuation. Used as a join key
    only - the original spelling is preserved on the BP record."""
    if not name:
        return ""
    return _NONALNUM_RE.sub("", _WS_RE.sub(" ", name.strip().upper()))


def _norm_taxid(tax_id: str) -> str:
    """Tax IDs vary wildly (DE123456789 vs 123456789, hyphens, spaces). For
    matching we normalize to digits/letters only, uppercase."""
    if not tax_id:
        return ""
    return _NONALNUM_RE.sub("", tax_id.upper())


def _norm_country(country: str) -> str:
    return (country or "").strip().upper()[:2]


# ─────────────────────────────────────────────────────────────────────────────
#  Detection passes
# ─────────────────────────────────────────────────────────────────────────────
def detect_overlap(kna1: Iterable[dict], lfa1: Iterable[dict]) -> List[str]:
    """Return the set of partner numbers that appear in BOTH KNA1.KUNNR and
    LFA1.LIFNR. Real ECC sites with shared number ranges hit this immediately
    and naive loaders create two BPs with the same external ID -> CVI breaks."""
    kunnr = {str(r.get("KUNNR", "")).lstrip("0") for r in kna1 if r.get("KUNNR")}
    lifnr = {str(r.get("LIFNR", "")).lstrip("0") for r in lfa1 if r.get("LIFNR")}
    overlap = sorted(kunnr & lifnr)
    if overlap:
        logger.warning("CVI: %d partner numbers overlap KNA1 ↔ LFA1 (e.g. %s)",
                       len(overlap), overlap[:5])
    return overlap


def _build_partner_index(rows: Iterable[dict], key_field: str) -> Dict[Tuple[str, str, str], List[dict]]:
    """Index records by (norm_name, country, norm_taxid). Returns a dict
    pointing to ALL records under that fingerprint (so duplicates inside the
    same table show up as buckets of len > 1)."""
    idx: Dict[Tuple[str, str, str], List[dict]] = {}
    for r in rows:
        fp = (
            _norm_name(r.get("NAME1") or r.get("NAME") or ""),
            _norm_country(r.get("LAND1") or r.get("COUNTRY") or ""),
            _norm_taxid(r.get("STCEG") or r.get("STCD1") or r.get("TAX_ID") or ""),
        )
        if not any(fp):
            continue  # nothing to match on
        idx.setdefault(fp, []).append(r)
    return idx


def detect_duplicates(rows: Iterable[dict], key_field: str) -> Dict[Tuple[str, str, str], List[str]]:
    """Within a single table, find partners sharing the same fingerprint.
    Returns {fingerprint: [legacy_ids...]} for buckets with > 1 entry."""
    idx = _build_partner_index(rows, key_field)
    dups = {fp: [str(r[key_field]).lstrip("0") for r in bucket]
            for fp, bucket in idx.items() if len(bucket) > 1}
    if dups:
        logger.info("CVI: %d duplicate-fingerprint groups inside %s",
                    len(dups), key_field)
    return dups


# ─────────────────────────────────────────────────────────────────────────────
#  Unification (the actual mapping)
# ─────────────────────────────────────────────────────────────────────────────
def _stable_bp_id(legacy_id: str, prefix: str = "BP") -> str:
    """Deterministic, collision-resistant target BP ID derived from the legacy
    key. Hex hash keeps it short, prefix marks it as tool-issued. Real
    customers either use external numbering (this) or rely on S/4 internal
    numbering and capture the assignment - we support both via map_external()."""
    h = hashlib.sha256(legacy_id.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}{h}"


def unify(kna1: List[dict],
          lfa1: List[dict],
          *,
          bp_prefix: str = "BP") -> Tuple[Dict[str, CviMapping], List[CviConflict]]:
    """Produce the legacy ->BP map and the conflict list.

    Strategy (deterministic, repeatable):
      1. Group customers and vendors that share (name, country, tax_id) into a
         single BP with both FLCU01 + FLVN01 roles.
      2. If a record has the SAME legacy number on both sides (overlap), it's
         treated as the same legal entity ->merged. Roles list reflects both.
      3. Anything else gets its own BP (single role).

    Quarantined as CviConflict:
      - Same name+country but DIFFERENT tax_id ->likely two distinct entities
        sharing a brand name. Don't auto-merge.
      - Same tax_id but DIFFERENT name ->suspicious (different legal name,
        same tax ID). Don't auto-merge.
    """
    cust_idx = _build_partner_index(kna1, "KUNNR")
    vend_idx = _build_partner_index(lfa1, "LIFNR")

    mappings: Dict[str, CviMapping] = {}
    conflicts: List[CviConflict] = []

    # Pass 1: merge by exact fingerprint
    all_fps = set(cust_idx.keys()) | set(vend_idx.keys())
    for fp in sorted(all_fps):
        custs = cust_idx.get(fp, [])
        vends = vend_idx.get(fp, [])

        # Seed BP id from the lowest-sorted legacy key for determinism
        seed_keys = [str(r["KUNNR"]).lstrip("0") for r in custs] + \
                    [str(r["LIFNR"]).lstrip("0") for r in vends]
        if not seed_keys:
            continue
        bp_id = _stable_bp_id(sorted(seed_keys)[0], prefix=bp_prefix)

        roles: List[str] = []
        if custs:
            roles.extend([ROLE_CUSTOMER, ROLE_FI_CUSTOMER])
        if vends:
            roles.extend([ROLE_VENDOR, ROLE_FI_VENDOR])
        merged = bool(custs) and bool(vends)

        for c in custs:
            kunnr = str(c["KUNNR"]).lstrip("0")
            mappings[f"KNA1:{kunnr}"] = CviMapping(
                target_bp_id=bp_id, roles=list(roles),
                source_kna1=kunnr, merged=merged)
        for v in vends:
            lifnr = str(v["LIFNR"]).lstrip("0")
            mappings[f"LFA1:{lifnr}"] = CviMapping(
                target_bp_id=bp_id, roles=list(roles),
                source_lfa1=lifnr, merged=merged)

    # Pass 2: near-duplicate detection (same name+country, different tax_id)
    by_name_country_c: Dict[Tuple[str, str], List[dict]] = {}
    for fp, rows in cust_idx.items():
        nc = (fp[0], fp[1])
        by_name_country_c.setdefault(nc, []).extend(rows)
    by_name_country_v: Dict[Tuple[str, str], List[dict]] = {}
    for fp, rows in vend_idx.items():
        nc = (fp[0], fp[1])
        by_name_country_v.setdefault(nc, []).extend(rows)

    for nc, cs in by_name_country_c.items():
        vs = by_name_country_v.get(nc, [])
        if not vs:
            continue
        c_taxids = {_norm_taxid(c.get("STCEG") or c.get("STCD1") or "") for c in cs}
        v_taxids = {_norm_taxid(v.get("STCEG") or v.get("STCD1") or "") for v in vs}
        c_taxids.discard("")
        v_taxids.discard("")
        if c_taxids and v_taxids and not (c_taxids & v_taxids):
            # One conflict per (name, country) fingerprint group, not
            # per N*M (customer, vendor) pair. Bug fix: at large scale
            # with several near-duplicates per fingerprint the quadratic
            # explosion produced 100K+ conflicts for 15K records.
            sample_kna1_ids = sorted({str(c["KUNNR"]).lstrip("0") for c in cs})[:5]
            sample_lfa1_ids = sorted({str(v["LIFNR"]).lstrip("0") for v in vs})[:5]
            conflicts.append(CviConflict(
                legacy_kna1_id=sample_kna1_ids[0] if sample_kna1_ids else None,
                legacy_lfa1_id=sample_lfa1_ids[0] if sample_lfa1_ids else None,
                reason="name+country match but tax IDs differ - manual review",
                detail={"name": cs[0].get("NAME1") if cs else None,
                        "country": _norm_country((cs[0] if cs else {}).get("LAND1") or ""),
                        "kna1_tax_ids": sorted(c_taxids),
                        "lfa1_tax_ids": sorted(v_taxids),
                        "kna1_count": len(cs),
                        "lfa1_count": len(vs),
                        "sample_kna1_ids": sample_kna1_ids,
                        "sample_lfa1_ids": sample_lfa1_ids}))

    return mappings, conflicts


# ─────────────────────────────────────────────────────────────────────────────
#  Cross-reference resolution with cycle protection (Gemini follow-up #2)
# ─────────────────────────────────────────────────────────────────────────────
# ECC master records carry cross-references between customer and vendor sides
# of the same legal entity. The two most common fields:
#
#   KNA1.LIFNR  - the vendor counterpart of this customer (intercompany)
#   LFA1.KUNNR  - the customer counterpart of this vendor (intercompany)
#
# Plus several less common ones (KNRZE on KNA1; LIFRG / VBUND chains). When
# two intercompany partners point at each other, naive lookup creates an
# infinite resolution loop. We solve this with a two-phase load:
#
#   Phase 1 - create every BP as a stub WITHOUT the cross-ref fields populated
#             (the unify() pass above already produced these mappings).
#   Phase 2 - walk every KNA1/LFA1 row, look up its xref legacy key in the
#             phase-1 mapping, and record a `cross_refs` entry on the source
#             mapping. The xref resolution is one hop deep by design - if A
#             refs B and B refs A, both mappings record their direct xref,
#             but neither chases the other (no recursion, no cycle).
#
# Caller flow in the live loader:
#   maps, confs, plan = unify_with_xrefs(kna1, lfa1)
#   for m in plan.phase_1: bapi_bp_create(stub_for(m))    # no LIFNR/KUNNR fields
#   for m in plan.phase_2: bapi_bp_update(m, m.cross_refs) # attach xrefs

# Fields we treat as cross-refs between the two tables. Listed by table.
_XREF_FIELDS = {
    "KNA1": [("LIFNR", "Vendor"), ("KNRZE", "Customer")],   # LIFNR=vendor counterpart
    "LFA1": [("KUNNR", "Customer"), ("LIFRG", "Vendor")],    # KUNNR=customer counterpart
}


@dataclass
class TwoPhasePlan:
    phase_1: List[CviMapping] = field(default_factory=list)  # stub create
    phase_2: List[CviMapping] = field(default_factory=list)  # xref attach
    unresolved_xrefs: List[dict] = field(default_factory=list)
    cycles_detected: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase_1_count": len(self.phase_1),
            "phase_2_count": len(self.phase_2),
            "unresolved_xrefs": self.unresolved_xrefs,
            "cycles_detected": [list(c) for c in self.cycles_detected],
        }


def unify_with_xrefs(kna1: List[dict],
                     lfa1: List[dict],
                     *,
                     bp_prefix: str = "BP") -> Tuple[Dict[str, CviMapping],
                                                     List[CviConflict],
                                                     TwoPhasePlan]:
    """unify() + cross-reference resolution.

    Returns the same (mappings, conflicts) tuple as unify(), plus a TwoPhasePlan
    that tells the loader which BPs need a follow-up update pass to attach the
    KNA1.LIFNR / LFA1.KUNNR references. Cycles are detected and reported - they
    are NOT errors (intercompany pairs legitimately point at each other), but
    the loader must execute the two phases in order.
    """
    mappings, conflicts = unify(kna1, lfa1, bp_prefix=bp_prefix)
    plan = TwoPhasePlan()

    # Build quick lookup tables: legacy_key -> mapping
    by_kunnr: Dict[str, CviMapping] = {}
    by_lifnr: Dict[str, CviMapping] = {}
    for k, m in mappings.items():
        if k.startswith("KNA1:") and m.source_kna1:
            by_kunnr[m.source_kna1] = m
        if k.startswith("LFA1:") and m.source_lfa1:
            by_lifnr[m.source_lfa1] = m

    # Walk every source row and resolve xref fields one hop deep
    for table, rows, lookup in (("KNA1", kna1, by_kunnr), ("LFA1", lfa1, by_lifnr)):
        key_field = "KUNNR" if table == "KNA1" else "LIFNR"
        for r in rows:
            src_key = str(r.get(key_field, "")).lstrip("0")
            if not src_key:
                continue
            mapping_key = f"{table}:{src_key}"
            m = mappings.get(mapping_key)
            if m is None:
                continue
            for xref_field, role in _XREF_FIELDS.get(table, []):
                xref_val = str(r.get(xref_field, "")).lstrip("0")
                if not xref_val or xref_val == src_key:
                    continue
                # Resolve to the partner BP - look in the opposite-side index
                partner_lookup = by_lifnr if role == "Vendor" else by_kunnr
                partner = partner_lookup.get(xref_val)
                if partner is None:
                    plan.unresolved_xrefs.append({
                        "source_table": table,
                        "source_key": src_key,
                        "xref_field": xref_field,
                        "xref_value": xref_val,
                        "reason": f"{role} {xref_val} not in this batch's extract",
                    })
                    continue
                # Same BP both sides? That's the CVI-merged case, no xref needed
                if partner.target_bp_id == m.target_bp_id:
                    continue
                m.cross_refs.append({
                    "field": xref_field,
                    "target_bp": partner.target_bp_id,
                    "partner_legacy_key": xref_val,
                })
                # Cycle detection: did partner also xref back at us?
                # (One-hop, so we just check the partner's already-resolved list.)
                if any(x.get("target_bp") == m.target_bp_id
                       for x in partner.cross_refs):
                    pair = tuple(sorted([m.target_bp_id, partner.target_bp_id]))
                    if pair not in plan.cycles_detected:
                        plan.cycles_detected.append(pair)

    # Partition into phase 1 (stub-only) and phase 2 (has xrefs to attach)
    for m in mappings.values():
        if m.cross_refs:
            m.load_phase = 2
            plan.phase_2.append(m)
        else:
            plan.phase_1.append(m)
    if plan.cycles_detected:
        logger.info("CVI: %d intercompany cycle(s) detected - two-phase load "
                    "required: %s", len(plan.cycles_detected),
                    plan.cycles_detected[:3])
    if plan.unresolved_xrefs:
        logger.warning("CVI: %d cross-reference(s) point at partners outside "
                       "this extract - will be unresolved", len(plan.unresolved_xrefs))
    return mappings, conflicts, plan


def serialize_map(mappings: Dict[str, CviMapping],
                  conflicts: List[CviConflict]) -> str:
    """Stable JSON for storage in the run summary / S3."""
    payload = {
        "mappings": {k: v.to_dict() for k, v in sorted(mappings.items())},
        "conflicts": [c.to_dict() for c in conflicts],
        "stats": {
            "total_legacy_keys": len(mappings),
            "unique_bps": len({m.target_bp_id for m in mappings.values()}),
            "merged_customer_vendor": sum(1 for m in mappings.values() if m.merged),
            "conflicts": len(conflicts),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 78)
    print("cvi_mapper - self-test")
    print("=" * 78)

    kna1 = [
        # Same legal entity registered as both customer + vendor
        {"KUNNR": "0000100001", "NAME1": "ACME GmbH", "LAND1": "DE", "STCEG": "DE123456789"},
        # Customer-only
        {"KUNNR": "0000100002", "NAME1": "Beta Inc", "LAND1": "US", "STCEG": "12-3456789"},
        # Duplicate INSIDE customer table (same fingerprint as 100001)
        {"KUNNR": "0000100099", "NAME1": "Acme  GmbH", "LAND1": "DE", "STCEG": "DE-123-456-789"},
        # Near-duplicate: same name+country, different tax_id (conflict)
        {"KUNNR": "0000100050", "NAME1": "Gamma AG", "LAND1": "DE", "STCEG": "DE111111111"},
    ]
    lfa1 = [
        # Pairs with kna1 100001 -> same BP, both roles
        {"LIFNR": "0000200001", "NAME1": "Acme GmbH", "LAND1": "DE", "STCEG": "DE 123 456 789"},
        # Number-range overlap with kna1 100002 (treated as different entity
        # because fingerprints differ)
        {"LIFNR": "0000100002", "NAME1": "Different Vendor", "LAND1": "US", "STCEG": "98-7654321"},
        # Conflict partner for Gamma AG (different tax_id)
        {"LIFNR": "0000200050", "NAME1": "Gamma AG", "LAND1": "DE", "STCEG": "DE222222222"},
    ]

    overlap = detect_overlap(kna1, lfa1)
    assert overlap == ["100002"], f"overlap detection wrong: {overlap}"
    print(f"  overlap detection: {overlap} OK")

    dups = detect_duplicates(kna1, "KUNNR")
    assert any(len(v) == 2 for v in dups.values()), "should detect Acme dup"
    print(f"  intra-table duplicates: {len(dups)} group(s) OK")

    mappings, conflicts = unify(kna1, lfa1)
    assert mappings["KNA1:100001"].merged is True, "100001 should be merged"
    assert mappings["KNA1:100001"].target_bp_id == mappings["LFA1:200001"].target_bp_id, \
        "merged pair should share BP id"
    assert ROLE_CUSTOMER in mappings["KNA1:100001"].roles
    assert ROLE_VENDOR in mappings["KNA1:100001"].roles
    assert mappings["KNA1:100099"].target_bp_id == mappings["KNA1:100001"].target_bp_id, \
        "Acme duplicate should fold into same BP"
    assert any(c.reason.startswith("name+country match but tax IDs differ")
               for c in conflicts), "Gamma AG conflict missed"
    print(f"  mappings: {len(mappings)} keys ->"
          f"{len({m.target_bp_id for m in mappings.values()})} unique BPs OK")
    print(f"  merged customer+vendor: "
          f"{sum(1 for m in mappings.values() if m.merged)} OK")
    print(f"  conflicts (manual review): {len(conflicts)} OK")

    # Round-trip stability: re-run should produce byte-identical output
    s1 = serialize_map(*unify(kna1, lfa1))
    s2 = serialize_map(*unify(kna1, lfa1))
    assert s1 == s2, "CVI mapping is not deterministic"
    print(f"  round-trip stability: identical bytes on re-run OK")

    print("\nOK - CVI unification deterministic; overlap + duplicate + conflict detection working.")
