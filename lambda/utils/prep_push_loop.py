"""
prep_push_loop — self-healing customizing loop (Basis Kit v1.1 required).

Live-proven pattern (2026-07-16, S/4 2020 CAL): a load run's dead-letter
records NAME the customizing rows the target is missing ("The value 002 is
not allowed for MARA-MATKL", "rate type 001 not defined in target (TCURV)",
"From currency UNI does not exist", "material type XLMT does not exist").
Instead of handing those to a human, this module:

  1. detect_tables(dead_records)         — map error signatures -> scan tables
  2. push_missing(ecc, s4, tables)       — scan ECC, diff against target keys,
                                           push ONLY the missing rows over RFC
                                           via Z_M4HTABLE_UPSERT (kit v1.1)
  3. (caller)                            — re-run the load stage; dead letters
                                           retry idempotently against the now-
                                           complete customizing

Two manual rounds of exactly this took LOCAL-E2E-FULL-002 from 15.8% ->
8.4% -> 7.4% dead-letter (Material +176, ExchangeRates +612 records).
The pipeline stage `_inline_prep_push_retry` runs the same loop unattended.

Safety: pushes are delta-only (existing target rows never touched), MODIFY
semantics (idempotent), and the kit FM refuses any table whose delivery
class isn't customizing. If the kit isn't installed the loop degrades to a
no-op with a clear reason — it can never fail a pipeline run.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Error-message signature (case-insensitive substring) -> ECC scan tables.
# Only signatures we've SEEN live; extend as new customizing classes appear.
DETECTION_RULES = [
    (("mara-matkl", "matl_group"),              ("T023", "T023T")),
    (("material type",),                        ("T134", "T134T")),
    (("tcurv",),                                ("TCURV",)),
    (("tcurf",),                                ("TCURF", "TCURV")),
    (("from currency", "to currency"),          ("TCURC",)),
]

MAX_ROUNDS_DEFAULT = 2


def _record_text(rec: dict) -> str:
    msg = rec.get("reason") or rec.get("messages") or rec.get("code") or ""
    if isinstance(msg, list):
        msg = "; ".join(str(x) for x in msg)
    return str(msg).lower()


def detect_tables(dead_records: list) -> list:
    """Return the sorted set of ECC scan tables whose absence explains one or
    more dead-letter records."""
    tables: set = set()
    for rec in dead_records or []:
        text = _record_text(rec)
        for signatures, tbls in DETECTION_RULES:
            if any(sig in text for sig in signatures):
                tables.update(tbls)
    return sorted(tables)


def _target_keys(s4_conn, table: str, key_fields: list, where: str = "") -> set:
    """All key tuples currently on target (paged; S/4's hardened RFC_READ_TABLE
    needs GET_SORTED with ROWSKIPS)."""
    out: set = set()
    skip, page = 0, 5000
    while True:
        kw = dict(QUERY_TABLE=table, DELIMITER="|", ROWCOUNT=page,
                  FIELDS=[{"FIELDNAME": f} for f in key_fields])
        if where:
            kw["OPTIONS"] = [{"TEXT": where}]
        if skip:
            kw["ROWSKIPS"] = skip
            kw["GET_SORTED"] = "X"
        r = s4_conn.call("RFC_READ_TABLE", **kw)
        rows = r.get("DATA") or []
        for x in rows:
            out.add(tuple(p.strip() for p in x["WA"].split("|")))
        skip += len(rows)
        if len(rows) < page:
            return out


def push_missing(ecc_conn, s4_conn, tables: list) -> dict:
    """Scan ECC for ``tables``, diff against target keys, push the delta via
    the kit upsert FM. Returns per-table results + totals; never raises."""
    from abap_generator import scan_ecc, SCAN_SPEC
    from basis_kit_installer import push_rows_via_kit

    spec = {t: SCAN_SPEC[t] for t in tables if t in SCAN_SPEC}
    missing_spec = [t for t in tables if t not in SCAN_SPEC]
    out = {"tables": [], "total_pushed": 0, "total_failed": 0,
           "no_scan_spec": missing_spec}
    if not spec:
        return out
    try:
        scan = scan_ecc(ecc_conn, spec=spec)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"ECC scan failed: {type(e).__name__}: {str(e)[:140]}"
        return out

    for table, tinfo in scan.items():
        rows = tinfo.get("rows") or []
        cols = tinfo.get("columns") or []
        keys = tinfo.get("key_fields") or spec[table].get("key_fields") or []
        where = spec[table].get("where", "")
        if not rows or not cols or not keys:
            out["tables"].append({"table": table, "delta": 0,
                                   "note": "no scannable rows"})
            continue
        try:
            existing = _target_keys(s4_conn, table, keys, where)
        except Exception as e:  # noqa: BLE001
            out["tables"].append({"table": table, "delta": 0,
                                   "note": f"target read failed: {str(e)[:100]}"})
            continue
        delta = [r for r in rows
                 if tuple(str(r.get(k, "")).strip() for k in keys) not in existing]
        if not delta:
            out["tables"].append({"table": table, "delta": 0,
                                   "note": "target already complete"})
            continue
        res = push_rows_via_kit(s4_conn, table, cols, delta)
        out["tables"].append({"table": table, "delta": len(delta),
                               "pushed": res["upserted"], "failed": res["failed"],
                               "status": (res["chunk_statuses"] or [""])[0][:120]})
        out["total_pushed"] += res["upserted"]
        out["total_failed"] += res["failed"]
    return out


def kit_upsert_available(s4_conn) -> bool:
    """True when a kit v1.1 upsert FM exists on the target (either name)."""
    for cand in ("Z_M4HTABLE_UPSERT", "Z_M4H_TABLE_UPSERT"):
        try:
            r = s4_conn.call("RFC_READ_TABLE", QUERY_TABLE="TFDIR", DELIMITER="|",
                             OPTIONS=[{"TEXT": f"FUNCNAME = '{cand}'"}],
                             FIELDS=[{"FIELDNAME": "FUNCNAME"}], ROWCOUNT=1)
            if r.get("DATA"):
                return True
        except Exception:  # noqa: BLE001
            return False
    return False
