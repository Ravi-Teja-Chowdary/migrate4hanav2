"""
interval_coverage — close the "Document number not within defined interval" gap.

AUTO2 evidence (2026-07-14): 9,619 of 10,000 attempted OpenPOs were rejected by
BAPI_PO_CREATE1 with "E Document number <n> not within defined interval" because
the one external interval the plan pointed NUMKE at only spans a narrow band
(41515xxxxx) while the source POs live in other bands (30xxxxxxxx, ...).

This module makes interval coverage a first-class, data-driven step:

  1. scan_source_numbers(ecc)   — pull every source document number per object
  2. cluster_bands(...)         — collapse them into contiguous decimal bands
  3. propose_intervals(...)     — diff bands against target NRIV intervals and
                                  emit Z_M4H_NR_MAINTAIN creation calls for every
                                  uncovered band (flagging overlaps with existing
                                  INTERNAL intervals as conflicts — SAP forbids
                                  overlapping intervals within one SNRO object)
  4. apply_coverage_plan(s4)    — execute the proposals via the Basis Kit
                                  (idempotent: "already existed" counts as OK)

The scan half (1-2) needs only ECC; the diff/apply half (3-4) degrades
gracefully when no S/4 connection is available — proposals are then marked
``pending_overlap_check`` and must be re-diffed at apply time.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Reuse the per-object metadata + target-interval discovery from the planner
from preservation_planner import OBJECT_META, discover_target_intervals  # noqa: E402

# Interval numbers we mint for kit-created intervals, in order. CHAR2; chosen
# to be visually obvious as migrate4hana's ("M" prefix) and collision-checked
# against existing interval numbers at proposal time.
_MINT_NRS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9",
             "MA", "MB", "MC", "MD", "ME", "MF"]

# Band width per key length: fine enough that a band doesn't swallow huge
# unrelated stretches of the number space, coarse enough that a realistic
# system yields < ~20 merged bands per object.
_BAND_WIDTH = {10: 10 ** 7, 8: 10 ** 5}
_DEFAULT_BAND_DIVISOR = 1000     # fallback: key-space / 1000


def scan_source_numbers(ecc_conn, object_type: str, *,
                        max_rows: int = 200_000, where: str = "") -> dict:
    """Read all numeric source keys for ``object_type`` from ECC.

    Returns {"object", "table", "field", "total_rows", "numeric_rows",
             "non_numeric_rows", "numbers": [int, ...]}.
    """
    meta = OBJECT_META.get(object_type)
    if not meta:
        raise ValueError(f"no OBJECT_META for {object_type}")
    table, field = meta["src_table"], meta["src_key"]

    numbers, non_numeric, fetched = [], 0, 0
    page = 5000
    while fetched < max_rows:
        opts = [{"TEXT": where}] if where else []
        r = ecc_conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                          OPTIONS=opts, FIELDS=[{"FIELDNAME": field}],
                          ROWCOUNT=page, ROWSKIPS=fetched)
        rows = r.get("DATA") or []
        fetched += len(rows)
        for x in rows:
            v = x["WA"].strip()
            if v.isdigit():
                numbers.append(int(v))
            else:
                non_numeric += 1
        if len(rows) < page:
            break

    return {"object": object_type, "table": table, "field": field,
            "total_rows": fetched, "numeric_rows": len(numbers),
            "non_numeric_rows": non_numeric, "numbers": numbers,
            "key_len": len(str(meta.get("key_len") or "")) or 10}


def cluster_bands(numbers: list, *, key_len: int = 10) -> list:
    """Collapse raw numbers into merged contiguous bands.

    Returns [{"from": int, "to": int, "count": int}, ...] sorted ascending,
    where from/to are band-aligned bounds (inclusive) covering every number.
    """
    if not numbers:
        return []
    width = _BAND_WIDTH.get(key_len) or max(10 ** key_len // _DEFAULT_BAND_DIVISOR, 1)
    counts: dict = {}
    for n in numbers:
        counts[n // width] = counts.get(n // width, 0) + 1

    merged = []
    for band in sorted(counts):
        lo, hi, cnt = band * width, (band + 1) * width - 1, counts[band]
        if merged and merged[-1]["to"] + 1 == lo:
            merged[-1]["to"] = hi
            merged[-1]["count"] += cnt
        else:
            merged.append({"from": lo, "to": hi, "count": cnt})
    return merged


def _covered_by(band: dict, iv: dict) -> bool:
    return iv["from"] <= band["from"] and band["to"] <= iv["to"]


def _overlaps(a_from: int, a_to: int, b_from: int, b_to: int) -> bool:
    return a_from <= b_to and b_from <= a_to


def propose_intervals(object_type: str, bands: list,
                      target_intervals: Optional[list]) -> list:
    """Diff source bands against target NRIV intervals for the object's SNRO.

    ``target_intervals``: the planner's discover_target_intervals() rows for
    this SNRO object ([{"nr","from","to","extern"}...]), or None when no S/4
    connection was available.

    Returns one proposal per band:
      {"band": {...},
       "status": "already_covered" | "propose_create" | "conflict_internal"
                 | "pending_overlap_check",
       "interval": {"nr","from","to","extern":"X"} | None,
       "note": str}
    """
    meta = OBJECT_META[object_type]
    snro = meta["snro"]
    key_len = 10
    if target_intervals is not None:
        # NRIV rows with non-numeric bounds (alphanumeric ranges) can't be
        # compared against numeric bands — exclude from cover/overlap math.
        target_intervals = [iv for iv in target_intervals
                            if iv.get("from") is not None and iv.get("to") is not None]
    existing_nrs = {iv["nr"] for iv in (target_intervals or [])}
    mint_pool = [n for n in _MINT_NRS if n not in existing_nrs]

    proposals = []
    for band in bands:
        if target_intervals is None:
            proposals.append({"band": band, "status": "pending_overlap_check",
                              "interval": {"nr": None, "from": band["from"],
                                            "to": band["to"], "extern": "X"},
                              "note": "no S/4 connection — re-diff at apply time"})
            continue

        ext_cover = [iv for iv in target_intervals
                     if iv.get("extern") and _covered_by(band, iv)]
        if ext_cover:
            proposals.append({"band": band, "status": "already_covered",
                              "interval": None,
                              "note": f"external interval {ext_cover[0]['nr']} "
                                      f"already spans this band"})
            continue

        clash = [iv for iv in target_intervals
                 if _overlaps(band["from"], band["to"], iv["from"], iv["to"])]
        if clash:
            nrs = ",".join(iv["nr"] for iv in clash[:4])
            proposals.append({"band": band, "status": "conflict_internal",
                              "interval": None,
                              "note": f"band overlaps existing interval(s) {nrs} "
                                      f"on {snro} — SAP forbids overlapping "
                                      f"intervals; needs Strategy C shift or "
                                      f"B flip of that interval"})
            continue

        if not mint_pool:
            proposals.append({"band": band, "status": "conflict_internal",
                              "interval": None,
                              "note": "mint pool exhausted (>15 kit intervals)"})
            continue
        nr = mint_pool.pop(0)
        proposals.append({"band": band, "status": "propose_create",
                          "interval": {"nr": nr,
                                        "from": str(band["from"]).zfill(key_len),
                                        "to": str(band["to"]).zfill(key_len),
                                        "extern": "X"},
                          "note": f"create external interval {nr} on {snro}"})
    return proposals


def build_coverage_plan(ecc_conn, s4_conn=None, *, objects: Optional[list] = None,
                        max_rows: int = 200_000) -> dict:
    """Full scan → cluster → diff for each requested object (default: the
    document-number objects that failed AUTO2 on interval coverage)."""
    objects = objects or ["OpenPO", "PurchaseOrder", "OpenSO", "SalesOrder"]
    target = discover_target_intervals(s4_conn) if s4_conn is not None else None

    plan: dict = {"objects": {}, "target_probed": s4_conn is not None}
    scanned_tables: dict = {}   # (table,field) -> scan result, shared by aliases
    for obj in objects:
        meta = OBJECT_META.get(obj)
        if not meta:
            plan["objects"][obj] = {"error": "no OBJECT_META"}
            continue
        cache_key = (meta["src_table"], meta["src_key"])
        if cache_key not in scanned_tables:
            scanned_tables[cache_key] = scan_source_numbers(
                ecc_conn, obj, max_rows=max_rows)
        scan = scanned_tables[cache_key]
        bands = cluster_bands(scan["numbers"], key_len=10)
        tgt = (target or {}).get(meta["snro"]) if target is not None else None
        props = propose_intervals(obj, bands, tgt)

        covered = sum(b["count"] for p in props for b in [p["band"]]
                      if p["status"] == "already_covered")
        creatable = sum(p["band"]["count"] for p in props
                        if p["status"] in ("propose_create", "pending_overlap_check"))
        conflicted = sum(p["band"]["count"] for p in props
                         if p["status"] == "conflict_internal")
        total = scan["numeric_rows"] or 1
        plan["objects"][obj] = {
            "snro": meta["snro"], "source_table": scan["table"],
            "numeric_rows": scan["numeric_rows"],
            "bands": len(bands),
            "proposals": props,
            "coverage_now_pct": round(100.0 * covered / total, 1),
            "coverage_after_pct": round(100.0 * (covered + creatable) / total, 1),
            "conflicted_pct": round(100.0 * conflicted / total, 1),
        }
    return plan


def apply_coverage_plan(s4_conn, plan: dict) -> dict:
    """Create every proposed interval via Z_M4H_NR_MAINTAIN (idempotent).

    Proposals still in ``pending_overlap_check`` are re-diffed against the live
    target first. Returns per-object outcomes.
    """
    target = discover_target_intervals(s4_conn)
    outcomes = []
    for obj, entry in (plan.get("objects") or {}).items():
        if entry.get("error"):
            continue
        snro = entry["snro"]
        props = entry["proposals"]
        if any(p["status"] == "pending_overlap_check" for p in props):
            bands = [p["band"] for p in props]
            props = propose_intervals(obj, bands, (target or {}).get(snro) or [])
        for p in props:
            if p["status"] != "propose_create":
                continue
            iv = p["interval"]
            try:
                r = s4_conn.call("Z_M4H_NR_MAINTAIN", IV_OBJECT=snro,
                                 IV_INTERVAL_NR=iv["nr"], IV_FROM=iv["from"],
                                 IV_TO=iv["to"], IV_EXTERN="X")
                status = (r.get("EV_STATUS") or "").strip()
            except Exception as e:  # noqa: BLE001
                status = f"ERROR: {type(e).__name__}: {str(e)[:120]}"
            outcomes.append({"object": obj, "snro": snro, "interval": iv,
                             "status": status})
    return {"outcomes": outcomes}
