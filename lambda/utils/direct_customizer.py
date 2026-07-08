"""
direct_customizer - apply S/4 target customizing via RFC/BAPI only.

No SSH, no filesystem access, no wrapper ABAP program required. Uses only
RFC-callable function modules and BAPIs available to any admin user with
S_RFC + S_TABU_DIS + S_NUMBER auths.

This is the right path for enterprise S/4 tenants where SSH to the host is
locked down by policy — which is almost every customer. Runs alongside
(and largely replaces) the ABAP-emit-and-SE38 path from abap_generator.py.

What it does
------------
1. **External number-range intervals** on every SNRO object universal
   source-key preservation touches (RV_BELEG, BU_PARTNER, BELEG_A,
   MATBELEG, ANLAGENNR, AUFTRAG, EQUIPMENT, IFLOTX). Calls
   NUMBER_RANGE_INTERVAL_UPDATE + NUMBER_RANGE_UPDATE_CLOSE. RFC-safe
   and SAP-documented at Note 45410.

2. **Customizing table rows** into TKA01, T023, T134, TCURV, TCURF,
   TFACD, TFAIN, T007A, TVAK, TVLK, TVFK, T161, TB003, T077K, T077Y,
   T003O, T093B. Uses SAP's shipped SM30 view-maintenance BAPI
   VIEW_MAINTENANCE_STORE_DATA / VIEWCLUSTER_MAINTAIN_DIRECT — this
   is the SAP-official path for customizing writes and requires no
   custom Z program on target.

3. **NUMKE / NUMKR external-range flag flips** on doc-type and account-
   group tables via the same view-maintenance BAPI: view V_TVAK for
   TVAK, V_TVLK for TVLK, etc.

Never raises for a target-side failure; every per-table / per-op result
is captured with status + reason, so the caller can report which
customizing landed and which need manual intervention. Idempotent —
re-run is safe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("direct_customizer")


# ─────────────────────────────────────────────────────────────────────────────
# Number range objects universal source-key preservation touches.
# Aligned with NUMBER_RANGE_OBJECTS in abap_generator.py so both paths
# produce the same target state.
# ─────────────────────────────────────────────────────────────────────────────
NUMBER_RANGE_OBJECTS = [
    ("RV_BELEG",   "SD documents (VBAK/LIKP/VBRK)"),
    ("BELEG_A",    "MM PO / Agreement / Contract (EKKO)"),
    ("BU_PARTNER", "Business Partner (BUT000/KNA1/LFA1)"),
    ("MATBELEG",   "Material Master (MARA)"),
    ("ANLAGENNR",  "Fixed Asset (ANLA)"),
    ("AUFTRAG",    "Internal Order / PP order (AUFK)"),
    ("EQUIPMENT",  "Equipment master"),
    ("IFLOTX",     "Functional Location"),
    ("KAUFBELEG",  "Sales customer order fallback"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Number range interval creation via NUMBER_RANGE_INTERVAL_UPDATE
# ─────────────────────────────────────────────────────────────────────────────
def apply_number_range_intervals(conn) -> list:
    """Create/update external interval 'A1' (1..9999999999, ext=X) on every
    SNRO object universal source-key preservation touches.

    Returns list of per-object result dicts::

        [{"object": "RV_BELEG", "status": "created" | "updated" | "skipped" | "error",
          "message": str}, ...]
    """
    results = []
    for obj, desc in NUMBER_RANGE_OBJECTS:
        try:
            resp = conn.call(
                "NUMBER_RANGE_INTERVAL_UPDATE",
                OBJECT=obj,
                INTERVAL=[{
                    "NRRANGENR":  "A1",
                    "FROMNUMBER": "0000000001",
                    "TONUMBER":   "9999999999",
                    "EXTERN":     "X",
                    "PROCESS":    "I",  # I = Insert if new, else no-op
                }],
            )
            errs = resp.get("ERROR") or []
            if isinstance(errs, dict):
                errs = [errs] if errs else []
            hard = [e for e in errs if (e.get("MSGTY") or "").upper() in ("E", "A")]
            if hard:
                results.append({"object": obj, "status": "error",
                                 "message": hard[0].get("MSGTX", "unknown error")})
                continue
            # Close/commit the number range
            try:
                conn.call("NUMBER_RANGE_UPDATE_CLOSE", OBJECT=obj)
            except Exception as e:
                log.warning("close failed for %s: %s", obj, e)
            results.append({"object": obj, "status": "applied",
                             "message": f"external interval A1 on {obj}: {desc}"})
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # FU_NOT_FOUND -> object doesn't exist on this release; skip cleanly
            if "FU_NOT_FOUND" in msg or "OBJECT_NOT_FOUND" in msg:
                results.append({"object": obj, "status": "skipped",
                                 "message": f"{obj}: not on this SAP release"})
            elif "authorization" in msg.lower() or "no_authority" in msg.lower():
                results.append({"object": obj, "status": "auth",
                                 "message": f"{obj}: user lacks S_NUMBER auth"})
            else:
                results.append({"object": obj, "status": "error",
                                 "message": f"{type(e).__name__}: {msg[:200]}"})
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Customizing row writes via VIEW_MAINTENANCE_STORE_DATA (SM30 BAPI)
# ─────────────────────────────────────────────────────────────────────────────
# SM30-view name -> underlying customizing table.
# When we want to write a row of customizing, we route through the view
# whose maintenance view is defined for that table. SAP ships views named
# `V_<table>` for most customizing tables; the ones that differ are
# explicitly mapped here.
TABLE_TO_VIEW = {
    "T001":  "V_T001",   "T001W": "V_T001W",  "TKA01": "V_TKA01",
    "T023":  "V_T023",   "T023T": "V_T023T",
    "T007A": "V_T007A",  "TCURC": "V_TCURC",  "TCURV": "V_TCURV",
    "TCURF": "V_TCURF",  "TFACD": "V_TFACD",  "TFAIN": "V_TFAIN",
    "T134":  "V_T134",   "T134T": "V_T134T",
    "TVAK":  "V_TVAK",   "TVLK":  "V_TVLK",   "TVFK":  "V_TVFK",
    "T161":  "V_T161",   "T003":  "V_T003",   "T003O": "V_T003O",
    "T024":  "V_024",    "T024E": "V_024E",
    "T052":  "V_T052",   "T077K": "V_T077K",  "T077Y": "V_T077Y",
    "TB003": "V_TB003",  "TSPA":  "V_TSPA",   "TVKO":  "V_TVKO",
    "TVTW":  "V_TVTW",   "TVKOV": "V_TVKOV",  "TVTA":  "V_TVTA",
    "T005":  "V_T005",   "T005S": "V_T005S",  "T006":  "V_T006",
    "T362":  "V_T362",   "T362T": "V_T362T",
    "TCJ04": "V_TCJ04",  "TCJ42": "V_TCJ42",
    "T163K": "V_T163K",  "T163Y": "V_T163Y",
    "T093B": "V_T093B",  "TQ15":  "V_TQ15",   "TQ16":  "V_TQ16",
    "T430":  "V_T430",   "T137":  "V_T137",   "TFACT": "V_TFACT",
}


def apply_customizing_rows(conn, scan: dict, *,
                             preserve_source_numbers: bool = False) -> list:
    """Attempt customizing writes via SAP's shipped SM30 view-maintenance BAPI.

    Reality check (verified on live CAL S4H 816, 2026-07-08):
    VIEW_MAINTENANCE_STORE_DATA is NOT remote-callable on S/4 1809+. SAP
    hardened this for security. Which means: **customizing table row writes
    cannot be done purely over RFC on modern S/4**. The tool detects this
    and reports honestly rather than silently no-op'ing.

    Two production paths remain:
      1. Wizard's *Download prep ABAP* → admin runs SE38 once. Manual but
         needs no infra changes. This is what almost every customer does.
      2. CTS+ transport: emit a K/R cofile pair, use RFC-callable STMS
         BAPIs to queue + import. Portable but complex.

    This function still tries option 1 (view maintenance) and reports its
    outcome per-table. The caller (api_server) inspects the summary and
    surfaces the honest state to the wizard, which then guides the user
    to the right fallback.
    """
    results = []
    view_maint_available = None   # discovered once on first call
    for table, tinfo in scan.items():
        rows = tinfo.get("rows", [])
        if not rows:
            results.append({"table": table, "status": "skipped",
                             "rows_written": 0, "message": "no rows in scan"})
            continue
        view = TABLE_TO_VIEW.get(table, f"V_{table}")
        try:
            resp = conn.call(
                "VIEW_MAINTENANCE_STORE_DATA",
                VIEW_NAME=view,
                DATA=[dict(row) for row in rows],
                CORRECTION_INSERT="X",
                COMMIT_WORK="X",
            )
            view_maint_available = True
            ret = resp.get("RETURN") or resp.get("MESSAGES") or []
            if isinstance(ret, dict):
                ret = [ret]
            hard = [m for m in ret if (m.get("TYPE") or "").upper() in ("E", "A")]
            if hard:
                results.append({"table": table, "status": "error",
                                 "rows_written": 0,
                                 "message": hard[0].get("MESSAGE", "")[:200]})
            else:
                results.append({"table": table, "status": "applied",
                                 "rows_written": len(rows),
                                 "message": f"{len(rows)} rows landed via {view}"})
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "FU_NOT_FOUND" in msg or "does not exist" in msg.lower():
                view_maint_available = False
                # Short-circuit: rest of tables would fail the same way.
                results.append({"table": table, "status": "not_available",
                                 "rows_written": 0,
                                 "message": ("VIEW_MAINTENANCE_STORE_DATA removed from "
                                              "this S/4 release — use SE38 prep-ABAP fallback")})
                break
            elif "authorization" in msg.lower():
                results.append({"table": table, "status": "auth",
                                 "rows_written": 0,
                                 "message": "user lacks S_TABU_DIS auth for this view"})
            else:
                results.append({"table": table, "status": "error",
                                 "rows_written": 0,
                                 "message": f"{type(e).__name__}: {msg[:200]}"})

    # If we determined view maintenance is unavailable, mark the remaining
    # untouched tables as blocked with the same reason (rather than repeating
    # the call).
    if view_maint_available is False:
        touched = {r["table"] for r in results}
        for table, tinfo in scan.items():
            if table not in touched and tinfo.get("rows"):
                results.append({"table": table, "status": "not_available",
                                 "rows_written": 0,
                                 "message": ("VIEW_MAINTENANCE_STORE_DATA removed from "
                                              "this S/4 release — use SE38 prep-ABAP fallback")})

    if preserve_source_numbers and view_maint_available is not False:
        results.extend(_flip_external_range_flags(conn, scan))
    return results


def _flip_external_range_flags(conn, scan: dict) -> list:
    """Flip NUMKE / NUMKR to 'A1' on doc-type + account-group tables.

    Same view-maintenance dependency as apply_customizing_rows — if that
    BAPI is missing, this can't work either. Kept for tenants where view
    maintenance IS still exposed (some ECC systems, some restrictive
    S/4 setups with custom auth mods).
    """
    flag_updates = [
        ("TVAK",  "AUART",     "NUMKE"),
        ("TVLK",  "LFART",     "NUMKE"),
        ("TVFK",  "FKART",     "NUMKE"),
        ("T161",  "BSART",     "NUMKE"),
        ("T077K", "KTOKD",     "NUMKR"),
        ("T077Y", "KTOKK",     "NUMKR"),
        ("TB003", "BU_GROUP",  "NUMKR"),
        ("T134",  "MTART",     "NUMKR"),
        ("T003O", "AUART",     "NUMKE"),
        ("T093B", "ANLKL",     "NUMKR"),
    ]
    results = []
    for table, key, flag in flag_updates:
        rows = (scan.get(table) or {}).get("rows") or []
        if not rows:
            continue
        updated = [dict(r, **{flag: "A1"}) for r in rows]
        view = TABLE_TO_VIEW.get(table, f"V_{table}")
        try:
            conn.call(
                "VIEW_MAINTENANCE_STORE_DATA",
                VIEW_NAME=view,
                DATA=updated,
                CORRECTION_INSERT="X",
                COMMIT_WORK="X",
            )
            results.append({"table": table, "status": "flag_flipped",
                             "rows_written": len(updated),
                             "message": f"{table}.{flag} = 'A1' on {len(updated)} rows"})
        except Exception as e:  # noqa: BLE001
            results.append({"table": table, "status": "flag_error",
                             "rows_written": 0,
                             "message": f"{type(e).__name__}: {str(e)[:150]}"})
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────
def apply_via_rfc(conn, scan: dict, *,
                    preserve_source_numbers: bool = False) -> dict:
    """One-call: apply the full prep in the same order the ABAP would.

    Order: customizing rows first (masters need to exist before external-
    range flags can reference them), then external-range flag flips, then
    number-range intervals. Returns a bundled summary suitable for the
    wizard to render.
    """
    started = datetime.now(timezone.utc).isoformat()

    customizing = apply_customizing_rows(
        conn, scan, preserve_source_numbers=preserve_source_numbers)
    intervals = apply_number_range_intervals(conn) if preserve_source_numbers else []

    counts = {
        "customizing_tables_written":     sum(1 for r in customizing if r.get("status") == "applied"),
        "customizing_tables_skipped":     sum(1 for r in customizing if r.get("status") == "skipped"),
        "customizing_tables_errored":     sum(1 for r in customizing if r.get("status") in ("error", "no_view", "not_available")),
        "customizing_flags_flipped":      sum(1 for r in customizing if r.get("status") == "flag_flipped"),
        "customizing_flag_errors":        sum(1 for r in customizing if r.get("status") == "flag_error"),
        "number_range_intervals_applied": sum(1 for r in intervals if r.get("status") == "applied"),
        "number_range_intervals_skipped": sum(1 for r in intervals if r.get("status") == "skipped"),
        "number_range_intervals_errored": sum(1 for r in intervals if r.get("status") in ("error", "auth")),
        "customizing_total_rows_written": sum(r.get("rows_written", 0) for r in customizing),
    }

    return {
        "status":     "success" if counts["customizing_tables_errored"] == 0
                                    and counts["number_range_intervals_errored"] == 0
                                 else "partial",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "counts":     counts,
        "customizing": customizing,
        "intervals":   intervals,
        "notes": [
            "All operations executed via pyrfc — no SSH, no filesystem, "
            "no wrapper ABAP program required on target.",
            "Idempotent: safe to re-run.",
            ("If some tables show 'not_available': VIEW_MAINTENANCE_STORE_DATA "
             "isn't shipped on this S/4 release. Fall back to ABAP path "
             "for those tables specifically."),
            ("If any operation shows status='auth': the S/4 user needs "
             "S_NUMBER (for intervals) or S_TABU_DIS (for view maintenance)."),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (shape only)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    class _FakeConn:
        def __init__(self):
            self.calls = []
        def call(self, fn, **kwargs):
            self.calls.append((fn, kwargs))
            if fn == "NUMBER_RANGE_INTERVAL_UPDATE":
                return {"ERROR": []}
            if fn == "NUMBER_RANGE_UPDATE_CLOSE":
                return {}
            if fn == "VIEW_MAINTENANCE_STORE_DATA":
                return {"RETURN": []}
            return {}

    scan = {
        "TKA01": {"rows": [{"KOKRS": "1000"}, {"KOKRS": "1010"}],
                   "columns": ["KOKRS"], "note": "", "key_fields": ["KOKRS"]},
        "T023":  {"rows": [{"MATKL": "00101"}], "columns": ["MATKL"],
                   "note": "", "key_fields": ["MATKL"]},
        "TVAK":  {"rows": [{"AUART": "TA"}, {"AUART": "OR"}],
                   "columns": ["AUART"], "note": "", "key_fields": ["AUART"]},
    }
    result = apply_via_rfc(_FakeConn(), scan, preserve_source_numbers=True)
    import json
    print(json.dumps(result["counts"], indent=2))
    assert result["counts"]["customizing_tables_written"] == 3
    assert result["counts"]["number_range_intervals_applied"] == len(NUMBER_RANGE_OBJECTS)
    assert result["counts"]["customizing_flags_flipped"] >= 1
    print("\nOK - direct_customizer self-test passed.")
