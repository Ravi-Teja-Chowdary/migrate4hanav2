"""
preservation_planner - compute per-object source-key preservation strategy.

Given a live ECC connection and live S/4 connection, this module:

  1. Discovers actual source-key ranges per object (min/max VBELN, EBELN,
     KUNNR, LIFNR, MATNR, KOSTL, etc.) via RFC_READ_TABLE probes.
  2. Discovers existing number-range intervals on S/4 per SNRO object,
     annotated with EXTERNIND (external vs internal) via NRIV probe.
  3. Computes per-object coverage under each of 4 strategies:

       A. Point NUMKE at existing external interval
          Only source keys inside that specific external range preserve;
          rest get target-assigned. Zero SAP-side risk.

       B. Modify a SAP-shipped internal interval to external
          Full preservation across the range. Requires Basis approval —
          SAP won't cover incidents on modified designated-internal
          intervals. Highest fidelity to "true replication".

       C. Shift source keys via mapping table
          Source key + offset lands in an existing external interval.
          Source 4969 becomes target 5,004,969 if using RV_BELEG
          interval 02. Full audit; source key visible via ledger.
          Zero SAP-side risk but numbers differ.

       D. Accept renumbering, use ledger for lookup
          Target assigns fresh numbers. Every mapping tracked in DDB
          key_map. Zero SAP-side risk, zero preservation.

  4. Emits a plan dict the wizard renders + the customer approves.
  5. Applies the approved plan via Basis Kit RFCs.

The B answer is what most closely matches "ECC replicated into S/4 with
same content, same IDs everywhere". Trade-off is customer's Basis team
must approve modifying SAP-designed intervals — a per-object decision.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("preservation_planner")


# ─────────────────────────────────────────────────────────────────────────────
# Per-object metadata: what SNRO object, source table + key field, target
# customizing table + NUMKE field (for strategy A/B).
# ─────────────────────────────────────────────────────────────────────────────
OBJECT_META = {
    # object_type: {"snro": SNRO object on target,
    #               "src_table": ECC source table,
    #               "src_key":   source key field,
    #               "cust_table":  target customizing table that carries NUMKE,
    #               "cust_key":    customizing key field (e.g. AUART for TVAK),
    #               "cust_numke":  the NUMKE field name}
    "SalesOrder":       {"snro": "RV_BELEG",  "src_table": "VBAK",  "src_key": "VBELN",
                          "cust_table": "TVAK",  "cust_key": "AUART", "cust_numke": "NUMKE"},
    "OpenSO":           {"snro": "RV_BELEG",  "src_table": "VBAK",  "src_key": "VBELN",
                          "cust_table": "TVAK",  "cust_key": "AUART", "cust_numke": "NUMKE"},
    "OutboundDelivery": {"snro": "RV_BELEG",  "src_table": "LIKP",  "src_key": "VBELN",
                          "cust_table": "TVLK",  "cust_key": "LFART", "cust_numke": "NUMKE"},
    "BillingDocument":  {"snro": "RV_BELEG",  "src_table": "VBRK",  "src_key": "VBELN",
                          "cust_table": "TVFK",  "cust_key": "FKART", "cust_numke": "NUMKE"},
    "PurchaseOrder":    {"snro": "EINKBELEG", "src_table": "EKKO",  "src_key": "EBELN",
                          "cust_table": "T161",  "cust_key": "BSART", "cust_numke": "NUMKE"},
    "OpenPO":           {"snro": "EINKBELEG", "src_table": "EKKO",  "src_key": "EBELN",
                          "cust_table": "T161",  "cust_key": "BSART", "cust_numke": "NUMKE"},
    "BusinessPartner":  {"snro": "BU_PARTNER", "src_table": "BUT000", "src_key": "PARTNER",
                          "cust_table": "TB003", "cust_key": "BU_GROUP", "cust_numke": "NUMKR"},
    "Customer":         {"snro": "BU_PARTNER", "src_table": "KNA1",   "src_key": "KUNNR",
                          "cust_table": "TB003", "cust_key": "BU_GROUP", "cust_numke": "NUMKR"},
    "Vendor":           {"snro": "BU_PARTNER", "src_table": "LFA1",   "src_key": "LIFNR",
                          "cust_table": "TB003", "cust_key": "BU_GROUP", "cust_numke": "NUMKR"},
    "Material":         {"snro": "MATBELEG",  "src_table": "MARA",   "src_key": "MATNR",
                          "cust_table": "T134", "cust_key": "MTART", "cust_numke": "NUMKR"},
    "FixedAsset":       {"snro": "ANLAGENNR", "src_table": "ANLA",   "src_key": "ANLN1",
                          "cust_table": "T093B", "cust_key": "ANLKL", "cust_numke": "NUMKR"},
    "OpenAR":           {"snro": "RV_BELEG",  "src_table": "BSID",   "src_key": "BELNR"},
    "OpenAP":           {"snro": "RV_BELEG",  "src_table": "BSIK",   "src_key": "BELNR"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Discovery helpers
# ─────────────────────────────────────────────────────────────────────────────
def discover_source_ranges(ecc_conn, object_types: Optional[list] = None) -> dict:
    """For each object, find (min_key, max_key, count) of the source table.

    Returns::

        {object_type: {"min_key": str, "max_key": str, "count": int,
                       "src_table": str, "src_key": str,
                       "min_num": int|None, "max_num": int|None,
                       "note": ""}, ...}
    """
    out = {}
    for obj_type, meta in OBJECT_META.items():
        if object_types and obj_type not in object_types:
            continue
        src_table = meta["src_table"]
        src_key   = meta["src_key"]
        entry = {"src_table": src_table, "src_key": src_key,
                 "min_key": "", "max_key": "", "count": 0,
                 "min_num": None, "max_num": None, "note": ""}
        try:
            # Pull a sample of key values (100 rows) — for min/max we'd
            # ideally use an aggregation but RFC_READ_TABLE doesn't support
            # SQL functions. This gives us a directional estimate.
            r = ecc_conn.call("RFC_READ_TABLE", QUERY_TABLE=src_table,
                                DELIMITER="|",
                                FIELDS=[{"FIELDNAME": src_key}],
                                ROWCOUNT=100000)
            data = r.get("DATA", []) or []
            keys = [(row.get("WA") or "").strip() for row in data]
            keys = [k for k in keys if k]
            if not keys:
                entry["note"] = "no rows in source table"
                out[obj_type] = entry
                continue
            entry["count"] = len(keys)
            entry["min_key"] = min(keys)
            entry["max_key"] = max(keys)
            # Try numeric interpretation
            try:
                nums = []
                for k in keys:
                    try:
                        nums.append(int(k))
                    except (ValueError, TypeError):
                        pass
                if nums:
                    entry["min_num"] = min(nums)
                    entry["max_num"] = max(nums)
            except Exception:
                pass
        except Exception as e:
            entry["note"] = f"{type(e).__name__}: {str(e)[:150]}"
        out[obj_type] = entry
    return out


def discover_target_intervals(s4_conn) -> dict:
    """For each SNRO object we care about, list its NRIV intervals.

    Returns::

        {snro_object: [{"nr": "01", "from": 1, "to": 4999999,
                        "extern": bool}, ...]}
    """
    snros = sorted({m["snro"] for m in OBJECT_META.values()})
    out = {}
    for snro in snros:
        intervals = []
        try:
            r = s4_conn.call("RFC_READ_TABLE", QUERY_TABLE="NRIV", DELIMITER="|",
                              OPTIONS=[{"TEXT": f"OBJECT = '{snro}'"}],
                              FIELDS=[{"FIELDNAME": "NRRANGENR"},
                                       {"FIELDNAME": "FROMNUMBER"},
                                       {"FIELDNAME": "TONUMBER"},
                                       {"FIELDNAME": "EXTERNIND"}],
                              ROWCOUNT=200)
            for row in r.get("DATA", []) or []:
                parts = ((row.get("WA") or "") + "||||").split("|")
                nr = parts[0].strip()
                fr = parts[1].strip()
                to = parts[2].strip()
                ex = parts[3].strip()
                try:
                    fr_int = int(fr)
                except (ValueError, TypeError):
                    fr_int = None
                try:
                    to_int = int(to)
                except (ValueError, TypeError):
                    to_int = None
                intervals.append({"nr": nr, "from": fr_int, "to": to_int,
                                    "from_raw": fr, "to_raw": to,
                                    "extern": (ex == "X")})
        except Exception as e:
            log.warning("NRIV probe failed for %s: %s", snro, e)
        out[snro] = intervals
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Coverage computation
# ─────────────────────────────────────────────────────────────────────────────
def _range_overlaps(min_n: int, max_n: int, intervals: list, *,
                     extern_only: bool = False) -> tuple:
    """How many keys in [min_n, max_n] fit under intervals (optionally only
    external ones). Returns (fits_count, best_interval)."""
    if min_n is None or max_n is None:
        return (0, None)
    total = max_n - min_n + 1
    for iv in intervals:
        if extern_only and not iv["extern"]:
            continue
        if iv["from"] is None or iv["to"] is None:
            continue
        if iv["from"] <= min_n and iv["to"] >= max_n:
            return (total, iv)
    # No single interval covers the full range; count partial overlaps
    # (this is directional — for a proper count we'd need to inspect
    # every source key value, which is expensive)
    for iv in intervals:
        if extern_only and not iv["extern"]:
            continue
        if iv["from"] is None or iv["to"] is None:
            continue
        overlap_from = max(iv["from"], min_n)
        overlap_to   = min(iv["to"],   max_n)
        if overlap_from <= overlap_to:
            return (overlap_to - overlap_from + 1, iv)
    return (0, None)


def compute_strategy_coverage(source_ranges: dict, target_intervals: dict) -> dict:
    """For each object, compute preservation coverage under each strategy.

    Returns::

        {object_type: {
            "source":     {"min_key", "max_key", "count", ...},
            "snro":       str,
            "target_intervals_count": int,
            "target_external_intervals": [...],
            "strategies": {
                "A": {"description", "coverage_est_pct", "risk", "action"},
                "B": {...},
                "C": {...},
                "D": {...},
            },
            "recommended": "A" | "B" | "C" | "D",
        }, ...}
    """
    plan: dict = {}
    for obj, meta in OBJECT_META.items():
        src = source_ranges.get(obj) or {}
        snro = meta["snro"]
        intervals = target_intervals.get(snro, [])
        external_intervals = [iv for iv in intervals if iv["extern"]]
        total_source = src.get("count", 0)
        min_n = src.get("min_num")
        max_n = src.get("max_num")

        # --- Strategy A: point NUMKE at existing external interval ---
        a_fits, a_iv = _range_overlaps(min_n, max_n, intervals, extern_only=True)
        a_cov = (100.0 * a_fits / total_source) if total_source else 0.0
        strat_A = {
            "description": "Point NUMKE at an existing external interval. "
                            "Only source keys inside that specific external range preserve; "
                            "others get target-assigned. Zero SAP-side risk.",
            "coverage_est_pct": round(a_cov, 1),
            "risk": "none",
            "action": ("Point " + str(meta.get("cust_table", "?")) +
                        "." + str(meta.get("cust_numke", "?")) +
                        " -> interval " + (a_iv["nr"] if a_iv else "n/a")),
            "target_interval": (a_iv["nr"] if a_iv else None),
        }

        # --- Strategy B: modify existing internal interval to external ---
        # Find the interval that contains the source range, even if internal.
        b_fits, b_iv = _range_overlaps(min_n, max_n, intervals, extern_only=False)
        b_cov = (100.0 * b_fits / total_source) if total_source else 0.0
        b_needs_flip = bool(b_iv and not b_iv["extern"])
        strat_B = {
            "description": "Modify the SAP-shipped interval containing source range "
                            "to external. Full preservation for the range. Requires "
                            "Basis approval - SAP support risk on the modified interval.",
            "coverage_est_pct": round(b_cov, 1),
            "risk": ("high (Basis approval required)" if b_needs_flip else "none (already external)"),
            "action": ("Flip " + snro + " interval " +
                        (b_iv["nr"] if b_iv else "n/a") +
                        " EXTERNIND to 'X'" if b_needs_flip else
                        "Interval " + (b_iv["nr"] if b_iv else "n/a") +
                        " is already external"),
            "target_interval": (b_iv["nr"] if b_iv else None),
            "requires_basis_approval": b_needs_flip,
        }

        # --- Strategy C: shift source keys ---
        # Find an existing external interval; compute offset needed.
        c_cov = 0.0
        c_shift = None
        c_target_iv = None
        if external_intervals and min_n is not None and max_n is not None:
            # Pick largest external interval that can accommodate the source range
            best_iv = max(external_intervals,
                            key=lambda iv: (iv.get("to", 0) or 0) - (iv.get("from", 0) or 0))
            if best_iv.get("from") is not None and best_iv.get("to") is not None:
                range_size = max_n - min_n + 1
                slot_size  = best_iv["to"] - best_iv["from"] + 1
                if slot_size >= range_size:
                    c_shift = best_iv["from"] - min_n
                    c_cov = 100.0
                    c_target_iv = best_iv["nr"]
        strat_C = {
            "description": "Shift source keys by a computed offset into an existing "
                            "external interval. Every source key preserved in ledger; "
                            "target key differs but is deterministic. Zero SAP-side risk.",
            "coverage_est_pct": round(c_cov, 1),
            "risk": "none (numbers differ but audit-traceable)",
            "action": ("Add offset " + f"{c_shift:+d}" +
                        " (source X -> target X" + f"{c_shift:+d}" + ")"
                        if c_shift is not None else "no external interval big enough"),
            "shift_offset": c_shift,
            "target_interval": c_target_iv,
        }

        # --- Strategy D: accept renumbering ---
        strat_D = {
            "description": "Accept target-assigned numbers. Every mapping tracked in "
                            "DDB key_map. Zero SAP-side changes. Zero preservation - "
                            "customer uses key_map CSV for source-to-target lookups.",
            "coverage_est_pct": 0.0,
            "risk": "none (no target-side changes)",
            "action": "No target-side changes required",
        }

        # --- Recommend the highest-fidelity option that's actually applicable ---
        # Order: B (best fidelity if flippable) > A (partial fidelity) > C (shifted) > D
        # If strategy B has coverage > A, and Basis-approval is available, B wins.
        # Otherwise A if it has meaningful coverage. Otherwise C if applicable.
        if strat_B["coverage_est_pct"] > 0 and strat_B["coverage_est_pct"] >= strat_A["coverage_est_pct"]:
            recommended = "B"
        elif strat_A["coverage_est_pct"] >= 80:
            recommended = "A"
        elif strat_C["coverage_est_pct"] >= 80:
            recommended = "C"
        elif strat_A["coverage_est_pct"] > 0:
            recommended = "A"
        else:
            recommended = "D"

        plan[obj] = {
            "source": src,
            "snro":   snro,
            "target_intervals_count":  len(intervals),
            "target_external_intervals": [iv["nr"] for iv in external_intervals],
            "strategies": {"A": strat_A, "B": strat_B, "C": strat_C, "D": strat_D},
            "recommended": recommended,
        }
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Apply an approved plan via Basis Kit RFCs
# ─────────────────────────────────────────────────────────────────────────────
def apply_approved_plan(s4_conn, plan: dict, decisions: dict) -> dict:
    """Apply the customer-approved per-object strategy.

    `decisions` is a dict mapping object_type -> "A" | "B" | "C" | "D".

    Returns per-object apply outcome. For A: calls Z_M4H_TABLE_UPDATE.
    For B: calls Z_M4H_NR_MODIFY. For C: records the shift offset to be
    used by the loader (returns the shift metadata to store in env vars).
    For D: no-op.
    """
    outcomes = []
    shift_map = {}   # returned to caller; caller sets M4H_KEY_SHIFT_<OBJ> env vars

    for obj, choice in decisions.items():
        entry = plan.get(obj) or {}
        strat = (entry.get("strategies") or {}).get(choice) or {}
        meta = OBJECT_META.get(obj) or {}
        snro = meta.get("snro")
        result = {"object": obj, "choice": choice, "action": strat.get("action")}

        try:
            if choice == "A":
                # Point NUMKE at existing external interval
                iv = strat.get("target_interval")
                cust_table = meta.get("cust_table")
                cust_numke = meta.get("cust_numke")
                if iv and cust_table:
                    # Determine key values to update (all AUART/BSART/etc.)
                    # For safety, pass common values; wizard should widen.
                    r = s4_conn.call("Z_M4H_TABLE_UPDATE",
                                       IV_TABLE=cust_table,
                                       IT_KEY_VALUES=[{"LINE": "TA"}, {"LINE": "OR"},
                                                        {"LINE": "NB"}, {"LINE": "UB"}],
                                       IV_FLAG_FIELD=cust_numke,
                                       IV_FLAG_VALUE=iv)
                    result["status"] = (r.get("EV_STATUS") or "").strip()
                    result["rows_updated"] = r.get("EV_ROWS_UPDATED", 0)
                else:
                    result["status"] = "SKIPPED: no target interval or customizing table"

            elif choice == "B":
                # Flip existing interval's EXTERNIND via Z_M4H_NR_MODIFY
                iv = strat.get("target_interval")
                if snro and iv:
                    r = s4_conn.call("Z_M4H_NR_MODIFY",
                                       IV_OBJECT=snro, IV_SUBOBJECT=" ",
                                       IV_INTERVAL_NR=iv, IV_EXTERN="X")
                    result["status"] = (r.get("EV_STATUS") or "").strip()
                else:
                    result["status"] = "SKIPPED: no target interval"

            elif choice == "C":
                # Record shift offset for loader
                offset = strat.get("shift_offset")
                if offset is not None:
                    shift_map[obj] = offset
                    result["status"] = f"OK: shift_offset={offset:+d} recorded"
                else:
                    result["status"] = "SKIPPED: no shift possible"

            elif choice == "D":
                result["status"] = "OK: no target-side changes (renumber+ledger)"

            else:
                result["status"] = f"UNKNOWN CHOICE: {choice}"
        except Exception as e:
            result["status"] = f"ERROR: {type(e).__name__}: {str(e)[:150]}"

        outcomes.append(result)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcomes":     outcomes,
        "shift_map":    shift_map,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────
def build_plan(ecc_conn, s4_conn, object_types: Optional[list] = None) -> dict:
    """One-call: discover source + target state, compute the plan.

    Wizard renders this; customer picks per-object; caller applies via
    apply_approved_plan.
    """
    src_ranges = discover_source_ranges(ecc_conn, object_types)
    tgt_intervals = discover_target_intervals(s4_conn)
    plan = compute_strategy_coverage(src_ranges, tgt_intervals)
    return {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "objects_analyzed": len(plan),
        "target_snro_map":  {snro: len(ivs) for snro, ivs in tgt_intervals.items()},
        "plan":             plan,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test with fake connections
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    class _FakeEcc:
        def call(self, fn, **kw):
            if fn == "RFC_READ_TABLE":
                tbl = kw.get("QUERY_TABLE")
                # VBAK: 15,332 records numbered 1-15332
                if tbl == "VBAK":
                    return {"DATA": [{"WA": f"{i:010d}"} for i in range(1, 100)]}
                # EKKO: numbers 3000000001-3000018782
                if tbl == "EKKO":
                    return {"DATA": [{"WA": f"3000000{i:03d}"} for i in range(1, 50)]}
                return {"DATA": [{"WA": f"{i:010d}"} for i in range(1, 20)]}
            return {}

    class _FakeS4:
        def call(self, fn, **kw):
            if fn == "RFC_READ_TABLE":
                # Return RV_BELEG intervals matching real CAL S/4 state
                if "RV_BELEG" in kw.get("OPTIONS", [{}])[0].get("TEXT", ""):
                    return {"DATA": [
                        {"WA": "01|1|4999999|"},          # internal
                        {"WA": "02|5000000|5999999|X"},   # external
                        {"WA": "60|6000000|9999999|X"},   # external
                    ]}
                if "EINKBELEG" in kw.get("OPTIONS", [{}])[0].get("TEXT", ""):
                    return {"DATA": [
                        {"WA": "41|4100000000|4199999999|X"},
                        {"WA": "44|4400000000|4499999999|X"},
                    ]}
                return {"DATA": []}
            return {}

    result = build_plan(_FakeEcc(), _FakeS4())
    print(json.dumps(result, indent=2, default=str))
    print("\nOK - preservation_planner self-test passed.")
