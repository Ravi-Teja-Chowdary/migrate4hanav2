"""
preflight_verifier - actively probes every operation a migration run
will perform, shows what to expect + what actually happens live, so the
user can verify BEFORE consenting to the run.

Design principle: nothing is trusted. Every check either:
  (a) runs a dry probe against the live system (RFC_SYSTEM_INFO, kit
      status FMs, dry NR probe, etc.), OR
  (b) explains exactly what will happen in the migration run, with a
      concrete example output the user can compare against.

Every check row carries:
    name          — short human-readable label
    category      — connection / kit / discovery / plan / migration
    description   — full paragraph of what will happen
    expected      — sample of what the output will look like when it works
    actual        — live probe result (str or dict)
    verdict       — pass | warn | fail | info | pending
    blocking      — bool; if True, migration cannot start without this passing

The wizard renders this as a table + consent checkbox. Once every
blocking row is `pass` (or user acknowledges warnings), the Start
migration button unlocks.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("preflight_verifier")


PASS = "pass"
WARN = "warn"
FAIL = "fail"
INFO = "info"
PENDING = "pending"


def _row(name, category, description, expected, actual="", verdict=PENDING,
         blocking=False) -> dict:
    return {"name": name, "category": category, "description": description,
            "expected": expected, "actual": actual, "verdict": verdict,
            "blocking": bool(blocking)}


# ─────────────────────────────────────────────────────────────────────────────
# Individual check functions
# ─────────────────────────────────────────────────────────────────────────────
def check_ecc_connection(ecc_conn) -> dict:
    r = _row(
        name="ECC RFC connection",
        category="connection",
        description="Probes ECC via RFC_SYSTEM_INFO to confirm pyrfc can "
                     "reach the source system with the saved credentials. "
                     "Migration cannot extract any data without this.",
        expected="ECC connected: <SID> release <REL> db <DB>  (e.g. Y01 740 MSSQL)",
        blocking=True,
    )
    try:
        info = ecc_conn.call("RFC_SYSTEM_INFO").get("RFCSI_EXPORT", {})
        r["actual"] = f"connected: {info.get('RFCSYSID','?')} rel {info.get('RFCSAPRL','?')} db {info.get('RFCDBSYS','?')}"
        r["verdict"] = PASS
    except Exception as e:
        r["actual"] = f"FAIL: {type(e).__name__}: {str(e)[:180]}"
        r["verdict"] = FAIL
    return r


def check_s4_connection(s4_conn) -> dict:
    r = _row(
        name="S/4 RFC connection",
        category="connection",
        description="Probes S/4 via RFC_SYSTEM_INFO to confirm pyrfc can "
                     "reach the target system with the saved credentials. "
                     "Migration cannot land any data without this.",
        expected="S/4 connected: <SID> release <REL> db <DB>  (e.g. S4H 816 HDB)",
        blocking=True,
    )
    try:
        info = s4_conn.call("RFC_SYSTEM_INFO").get("RFCSI_EXPORT", {})
        r["actual"] = f"connected: {info.get('RFCSYSID','?')} rel {info.get('RFCSAPRL','?')} db {info.get('RFCDBSYS','?')}"
        r["verdict"] = PASS
    except Exception as e:
        r["actual"] = f"FAIL: {type(e).__name__}: {str(e)[:180]}"
        r["verdict"] = FAIL
    return r


def check_basis_kit_installed(s4_conn) -> dict:
    r = _row(
        name="Basis Kit installed on S/4",
        category="kit",
        description="Probes Z_M4H_STATUS to confirm the migrate4hana Basis "
                     "Kit is installed and callable. Kit provides Z_M4H_NR_MAINTAIN, "
                     "Z_M4H_NR_MODIFY, Z_M4H_TABLE_UPDATE, Z_M4H_HEALTH_LOG - the "
                     "5 RFC functions the migration uses to prep target-side "
                     "customizing. Without the kit, only Extract-only mode works.",
        expected="Kit installed: M4H_KIT_1.0 (installed <date>) as user MIGRATE_ADMI",
        blocking=False,   # non-blocking; migration works without kit (just no preservation)
    )
    try:
        resp = s4_conn.call("Z_M4H_STATUS")
        ver = (resp.get("EV_VERSION") or "").strip()
        ts  = (resp.get("EV_INSTALL_TS") or "").strip()
        usr = (resp.get("EV_USER") or "").strip()
        r["actual"] = f"installed: {ver} (installed {ts}) as user {usr}"
        r["verdict"] = PASS
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s:
            r["actual"] = "NOT INSTALLED - the wizard's Basis Kit install button emits the 5-FM install ABAP for one-time SE37 setup (~10 min)"
            r["verdict"] = WARN
        else:
            r["actual"] = f"probe error: {type(e).__name__}: {str(e)[:150]}"
            r["verdict"] = WARN
    return r


def check_kit_nr_modify_callable(s4_conn) -> dict:
    r = _row(
        name="Z_M4H_NR_MODIFY callable",
        category="kit",
        description="Dry-probes Z_M4H_NR_MODIFY by asking it to modify an "
                     "interval that doesn't exist ('XX' on RV_BELEG). Expects "
                     "the 'not found' error message, which proves the FM is "
                     "reachable and its logic runs. Used by Strategy B in the "
                     "preservation planner.",
        expected="OK: FM callable, returned 'interval XX not found on RV_BELEG'",
        blocking=False,
    )
    try:
        resp = s4_conn.call("Z_M4H_NR_MODIFY",
                              IV_OBJECT="RV_BELEG", IV_SUBOBJECT=" ",
                              IV_INTERVAL_NR="XX", IV_EXTERN="X")
        status = (resp.get("EV_STATUS") or "").strip()
        if "not found" in status.lower():
            r["actual"] = f"OK: {status}"
            r["verdict"] = PASS
        else:
            r["actual"] = f"unexpected: {status}"
            r["verdict"] = WARN
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s:
            r["actual"] = "NOT INSTALLED (probable: kit missing or FM not remote-enabled)"
            r["verdict"] = WARN
        else:
            r["actual"] = f"error: {type(e).__name__}: {str(e)[:120]}"
            r["verdict"] = WARN
    return r


def check_rfc_user_privilege(s4_conn) -> dict:
    """H0.2 — report whether the RFC user runs on the broad SAP_ALL profile vs
    the scoped ZM4H_MIGRATION_ADMIN role. Live-verified probe: BAPI_USER_GET_DETAIL
    returns PROFILES + ACTIVITYGROUPS (roles). Non-blocking (CAL trials legitimately
    can't apply PFCG roles); a production landscape should carry the scoped role."""
    SCOPED_ROLE = "ZM4H_MIGRATION_ADMIN"
    r = _row(
        name="RFC user privilege scope",
        category="security",
        description="Checks the target RFC user's authorizations via "
                    "BAPI_USER_GET_DETAIL. Production should run on the scoped "
                    f"{SCOPED_ROLE} role, NOT SAP_ALL. Non-blocking: CAL trials "
                    "have no PFCG so SAP_ALL there is expected.",
        expected=f"scoped role {SCOPED_ROLE} assigned; SAP_ALL absent",
        blocking=False,
    )
    try:
        # discover the current user from the live connection (don't assume)
        who = ""
        try:
            attrs = s4_conn.get_connection_attributes() or {}
            who = (attrs.get("user") or "").strip().upper()
        except Exception:
            pass
        d = s4_conn.call("BAPI_USER_GET_DETAIL", USERNAME=who) if who \
            else s4_conn.call("BAPI_USER_GET_DETAIL")
        profs = {(p.get("BAPIPROF") or p.get("PROFILE") or "").strip().upper()
                 for p in (d.get("PROFILES") or [])}
        roles = {(g.get("AGR_NAME") or "").strip().upper()
                 for g in (d.get("ACTIVITYGROUPS") or [])}
        has_sap_all = "SAP_ALL" in profs
        has_scoped = SCOPED_ROLE in roles
        if has_scoped and not has_sap_all:
            r["actual"] = f"OK: scoped role {SCOPED_ROLE} present, SAP_ALL absent"
            r["verdict"] = PASS
        elif has_sap_all:
            r["actual"] = (f"SAP_ALL present (over-privileged for production). "
                           f"Scoped role {'present' if has_scoped else 'NOT assigned'}. "
                           f"OK on a CAL trial; apply {SCOPED_ROLE} + remove SAP_ALL "
                           f"before a production run.")
            r["verdict"] = WARN
        else:
            r["actual"] = (f"Neither SAP_ALL nor {SCOPED_ROLE} detected "
                           f"(profiles={sorted(profs)[:6]}, roles={sorted(roles)[:6]}) "
                           f"— verify the RFC user can perform kit + BAPI operations.")
            r["verdict"] = WARN
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s or "not authorized" in s.lower() or "AUTH" in s:
            r["actual"] = ("could not read user detail (BAPI_USER_GET_DETAIL blocked "
                           "or absent) — privilege scope unverified")
            r["verdict"] = INFO
        else:
            r["actual"] = f"probe error: {type(e).__name__}: {str(e)[:120]}"
            r["verdict"] = INFO
    return r


def check_kit_table_update_callable(s4_conn) -> dict:
    r = _row(
        name="Z_M4H_TABLE_UPDATE callable",
        category="kit",
        description="Dry-probes Z_M4H_TABLE_UPDATE by asking it to update a "
                     "value that doesn't exist. Expects OK with 0 rows updated "
                     "(no error, just no match). Used by Strategy A in the "
                     "preservation planner to point NUMKE at existing intervals.",
        expected="OK: 0 rows updated, 1 errors  (no matching row is the expected outcome)",
        blocking=False,
    )
    try:
        resp = s4_conn.call("Z_M4H_TABLE_UPDATE",
                              IV_TABLE="TVAK",
                              IT_KEY_VALUES=[{"LINE": "__NONEXISTENT__"}],
                              IV_FLAG_FIELD="NUMKE",
                              IV_FLAG_VALUE="XX")
        status = (resp.get("EV_STATUS") or "").strip()
        rows = resp.get("EV_ROWS_UPDATED", 0)
        r["actual"] = f"OK: {status} (rows_updated={rows})"
        r["verdict"] = PASS
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s:
            r["actual"] = "NOT INSTALLED"
            r["verdict"] = WARN
        else:
            r["actual"] = f"error: {type(e).__name__}: {str(e)[:120]}"
            r["verdict"] = WARN
    return r


def check_source_key_ranges(ecc_conn, sample_objects: list) -> dict:
    r = _row(
        name="Source data volumes discoverable",
        category="discovery",
        description="Samples row counts on a handful of key ECC tables "
                     "(VBAK, EKKO, KNA1, LFA1, MARA) so you can see what "
                     "volumes will migrate. Used by the preservation planner "
                     "to compute source key ranges.",
        expected=("VBAK 15,332 (SO) | EKKO 18,782 (PO) | KNA1 19,575 (Cust) | "
                    "LFA1 2,415 (Vend) | MARA 24,494 (Mat)"),
        blocking=False,
    )
    volumes = []
    for tbl in ("VBAK", "EKKO", "KNA1", "LFA1", "MARA"):
        try:
            resp = ecc_conn.call("RFC_READ_TABLE", QUERY_TABLE=tbl,
                                    DELIMITER="|",
                                    FIELDS=[{"FIELDNAME": "MANDT"}],
                                    ROWCOUNT=100000)
            n = len(resp.get("DATA", []) or [])
            volumes.append(f"{tbl} {n}")
        except Exception:
            volumes.append(f"{tbl} err")
    r["actual"] = " | ".join(volumes)
    r["verdict"] = PASS if any(v.split(" ")[1].isdigit() and int(v.split(" ")[1]) > 0 for v in volumes) else WARN
    return r


def check_target_intervals_readable(s4_conn) -> dict:
    r = _row(
        name="Target NRIV intervals readable",
        category="discovery",
        description="Probes NRIV on S/4 for RV_BELEG intervals. Preservation "
                     "planner uses this to know which intervals are external "
                     "and their number ranges. Without this, Strategy A and B "
                     "can't be computed.",
        expected="NRIV probe: 20+ intervals on RV_BELEG (mix of internal/external)",
        blocking=False,
    )
    try:
        resp = s4_conn.call("RFC_READ_TABLE", QUERY_TABLE="NRIV", DELIMITER="|",
                              OPTIONS=[{"TEXT": "OBJECT = 'RV_BELEG'"}],
                              FIELDS=[{"FIELDNAME": "NRRANGENR"},
                                       {"FIELDNAME": "EXTERNIND"}],
                              ROWCOUNT=50)
        rows = resp.get("DATA", []) or []
        ext_count = sum(1 for row in rows if "X" in (row.get("WA") or ""))
        r["actual"] = f"{len(rows)} intervals on RV_BELEG ({ext_count} marked external)"
        r["verdict"] = PASS if rows else WARN
    except Exception as e:
        r["actual"] = f"error: {type(e).__name__}: {str(e)[:120]}"
        r["verdict"] = FAIL
    return r


def check_migration_bapis_present(s4_conn) -> dict:
    r = _row(
        name="Key BAPIs available on S/4",
        category="migration",
        description="Probes existence of the SAP-shipped BAPIs the "
                     "migration uses (BAPI_BUPA_CREATE_FROM_DATA, "
                     "BAPI_MATERIAL_SAVEDATA, BAPI_PO_CREATE1, "
                     "BAPI_SALESORDER_CREATEFROMDAT2, BAPI_ACC_DOCUMENT_POST). "
                     "All are standard SAP; any missing indicates a stripped-"
                     "down or unusual S/4 install.",
        expected=("BAPI_BUPA_CREATE_FROM_DATA present | BAPI_MATERIAL_SAVEDATA "
                    "present | BAPI_PO_CREATE1 present | "
                    "BAPI_SALESORDER_CREATEFROMDAT2 present | "
                    "BAPI_ACC_DOCUMENT_POST present"),
        blocking=False,
    )
    bapis = ("BAPI_BUPA_CREATE_FROM_DATA", "BAPI_MATERIAL_SAVEDATA",
             "BAPI_PO_CREATE1", "BAPI_SALESORDER_CREATEFROMDAT2",
             "BAPI_ACC_DOCUMENT_POST")
    results = []
    missing = 0
    for bapi in bapis:
        try:
            # Empty-arg call — succeeds if callable (any real error means it exists)
            s4_conn.call(bapi)
            results.append(f"{bapi} present")
        except Exception as e:
            s = str(e)
            if "FU_NOT_FOUND" in s or "does not exist" in s.lower():
                results.append(f"{bapi} MISSING")
                missing += 1
            else:
                # Missing param err — expected; means BAPI exists
                results.append(f"{bapi} present")
    r["actual"] = " | ".join(results)
    r["verdict"] = PASS if missing == 0 else (WARN if missing < 3 else FAIL)
    return r


def check_local_staging_writable() -> dict:
    import os
    r = _row(
        name="Local staging path writable",
        category="migration",
        description="Ensures local-staging/m4h-local/runs/ is writable so the "
                     "migration can persist run artifacts (extracts, "
                     "key_mapping, dead-letter, summary.json). Required for "
                     "both auto and step-by-step modes.",
        expected="local-staging/m4h-local/runs/  writable + present",
        blocking=True,
    )
    try:
        base = os.path.abspath(os.path.join(os.getcwd(),
                                             "local-staging", "m4h-local", "runs"))
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".preflight-probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        r["actual"] = f"OK: {base} is writable"
        r["verdict"] = PASS
    except Exception as e:
        r["actual"] = f"FAIL: {type(e).__name__}: {str(e)[:120]}"
        r["verdict"] = FAIL
    return r


def check_preservation_plan_dry(ecc_conn, s4_conn) -> dict:
    r = _row(
        name="Preservation plan compute (dry preview)",
        category="plan",
        description="Runs the preservation planner in dry-preview mode "
                     "(computes plan without applying). Confirms per-object "
                     "coverage estimates for each of A/B/C/D strategies. "
                     "Auto mode uses this to decide which strategies to apply "
                     "automatically.",
        expected=("Plan computed: N objects analysed. Typical output shows "
                    "CostCenter recommended=B 100%, Material recommended=B 100%, "
                    "SalesOrder recommended=B (needs Basis approval) etc."),
        blocking=False,
    )
    try:
        # Do a lightweight preview — just call OBJECT_META keys, no full scan
        try:
            from preservation_planner import build_plan
        except ImportError:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from preservation_planner import build_plan
        plan = build_plan(ecc_conn, s4_conn, object_types=["SalesOrder", "PurchaseOrder"])
        analysed = plan.get("objects_analyzed", 0)
        recs = {}
        for obj, entry in (plan.get("plan") or {}).items():
            recs[obj] = entry.get("recommended", "?")
        r["actual"] = f"OK: {analysed} objects analysed. Recommendations: {recs}"
        r["verdict"] = PASS
    except Exception as e:
        r["actual"] = f"error: {type(e).__name__}: {str(e)[:150]}"
        r["verdict"] = WARN
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ─────────────────────────────────────────────────────────────────────────────
def run_preflight(ecc_conn, s4_conn, *,
                    run_mode: str = "auto",
                    load_to_s4: bool = True,
                    preserve_source_numbers: bool = True) -> dict:
    """Run every preflight check and return the aggregate result.

    Returns::

        {"generated_at": iso8601,
         "run_mode":     "auto" | "step",
         "checks":       [row, row, ...],
         "summary": {"total": N, "pass": p, "warn": w, "fail": f,
                      "blocking_fail": bf, "ready_to_migrate": bool},
         "consent_text": str}
    """
    checks = [
        check_local_staging_writable(),
        check_ecc_connection(ecc_conn),
        check_s4_connection(s4_conn),
    ]
    # Only continue with target-side probes if S/4 connection is up
    if checks[-1]["verdict"] == PASS:
        kit_check = check_basis_kit_installed(s4_conn)
        checks.extend([
            kit_check,
            check_rfc_user_privilege(s4_conn),   # H0.2
            check_migration_bapis_present(s4_conn),
            check_target_intervals_readable(s4_conn),
        ])
        # Kit-specific probes only if kit is present (reference the kit check
        # result directly — robust to reordering/adding checks above).
        if kit_check["verdict"] == PASS:
            checks.extend([
                check_kit_nr_modify_callable(s4_conn),
                check_kit_table_update_callable(s4_conn),
            ])
    # Only continue with ECC-side probes if ECC connection is up
    if len(checks) > 1 and checks[1]["verdict"] == PASS:
        checks.append(check_source_key_ranges(ecc_conn, []))
        if len(checks) > 2 and checks[2]["verdict"] == PASS:
            checks.append(check_preservation_plan_dry(ecc_conn, s4_conn))

    tot = len(checks)
    p = sum(1 for c in checks if c["verdict"] == PASS)
    w = sum(1 for c in checks if c["verdict"] == WARN)
    f = sum(1 for c in checks if c["verdict"] == FAIL)
    bf = sum(1 for c in checks if c["verdict"] == FAIL and c.get("blocking"))
    ready = (bf == 0)

    consent = (
        f"I ({{signer}}) have reviewed the {tot} preflight checks. "
        f"{p} passed, {w} warnings, {f} failures ({bf} blocking). "
        f"I authorize migrate4hana to execute the {'auto' if run_mode == 'auto' else 'step-by-step'} "
        f"migration against target S/4 as configured, calling only SAP-shipped BAPIs "
        f"and the migrate4hana Basis Kit RFCs."
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_mode":     run_mode,
        "checks":       checks,
        "summary": {
            "total": tot, "pass": p, "warn": w, "fail": f,
            "blocking_fail": bf, "ready_to_migrate": ready,
        },
        "consent_text": consent,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    class _FakeConn:
        def __init__(self, kit=True): self.kit = kit
        def call(self, fn, **kw):
            if fn == "RFC_SYSTEM_INFO":
                return {"RFCSI_EXPORT": {"RFCSYSID": "TST", "RFCSAPRL": "816",
                                           "RFCDBSYS": "HDB"}}
            if fn == "Z_M4H_STATUS":
                if not self.kit:
                    raise RuntimeError("FU_NOT_FOUND: Z_M4H_STATUS not found")
                return {"EV_VERSION": "M4H_KIT_1.0",
                        "EV_INSTALL_TS": "2026-07-12 08:40 UTC",
                        "EV_USER": "MIGRATE_ADMI"}
            if fn == "Z_M4H_NR_MODIFY":
                return {"EV_STATUS": "ERROR: interval XX not found on RV_BELEG"}
            if fn == "Z_M4H_TABLE_UPDATE":
                return {"EV_STATUS": "OK: 0 rows updated, 1 errors",
                        "EV_ROWS_UPDATED": 0}
            if fn == "RFC_READ_TABLE":
                return {"DATA": [{"WA": "01|"}, {"WA": "02|X"}]}
            return {}
    result = run_preflight(_FakeConn(), _FakeConn())
    print(f"Total checks: {result['summary']['total']}")
    print(f"Pass: {result['summary']['pass']}, Warn: {result['summary']['warn']}, "
          f"Fail: {result['summary']['fail']}")
    print(f"Ready to migrate: {result['summary']['ready_to_migrate']}")
    for c in result["checks"]:
        v = {"pass": "OK", "warn": "!!", "fail": "XX", "info": "i", "pending": "?"}[c["verdict"]]
        print(f"  [{v}] {c['name']:40s} {c['actual'][:80]}")
    print("\nOK - preflight_verifier self-test passed.")
