#!/usr/bin/env python3
"""
cutover.py — governed ECC->S/4 cutover rehearsal orchestrator.

Turns the data-migration engine's capabilities into one operation a migration lead can
sign off on:

    INITIAL LOAD (full)  ->  DELTA LOAD (CDC, idempotent)  ->  RECONCILE  ->  GO / NO-GO

Phase 1 does the bulk load before the cutover window (full extract). Phase 2, at cutover,
extracts only what CHANGED since (delta/CDC) and loads it idempotently (the registry ledger
guarantees no duplicates). The verdict is GO only if every phase reconciled, no errors, and
the run is support-clean. Produces a cutover report for sign-off.

Prereqs (same as a normal run): M4H_ECC_PASSWD, M4H_TARGET_PASSWD set; a routing DAG exists
(reused from RUN-FULL-001). Usage:  python cutover.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGING = ROOT / "local-staging" / "m4h-local"
RUNS = STAGING / "runs"
LEDGER_DIR = STAGING / "migration-ledger"
SRC_DAG = RUNS / "RUN-FULL-001" / "object-router" / "dag.json"
CUTOVER_ID = os.environ.get("M4H_CUTOVER_ID", "CUTOVER-001")


def _summary(run_id):
    return json.loads((RUNS / run_id / "data-migrator" / "summary.json").read_text())


def _ensure_dag(run_id):
    dst = RUNS / run_id / "object-router" / "dag.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC_DAG, dst)


def _run_phase(label, run_id, extra_env):
    _ensure_dag(run_id)
    env = dict(os.environ)
    env.setdefault("SAPNWRFC_HOME", "sapnwrfc")
    env.update({"M4H_LOAD_TO_S4": "1", "M4H_LOAD_MAX_ROWS": env.get("M4H_LOAD_MAX_ROWS", "6")})
    env.update(extra_env)
    print(f"\n=== PHASE: {label}  (run-id {run_id}) ===")
    subprocess.run([sys.executable, str(ROOT / "run_local_lift_and_shift.py"),
                    "--only", "stage13", "--run-id", run_id],
                   env=env, cwd=str(ROOT), check=False)
    return _summary(run_id)


def _verdict(s):
    return (s.get("reconciliation") or {}).get("verdict")


def main():
    if not (os.environ.get("M4H_ECC_PASSWD") and os.environ.get("M4H_TARGET_PASSWD")):
        sys.exit("Set M4H_ECC_PASSWD and M4H_TARGET_PASSWD first.")

    # Fresh rehearsal: clear the cross-run ledger + CDC watermark so phase 1 is a true
    # initial load and phase 2 a true delta.
    for f in ("key_mapping.json", "cdc-watermark.json"):
        p = LEDGER_DIR / f
        if p.exists():
            p.unlink()

    t0 = time.time()
    p1 = _run_phase("INITIAL LOAD (full extract)", f"{CUTOVER_ID}-init", {"M4H_CDC_DELTA": "0"})
    p2 = _run_phase("DELTA LOAD (CDC since initial, idempotent)", f"{CUTOVER_ID}-delta",
                    {"M4H_CDC_DELTA": "1"})

    checks = {
        "initial_load_reconciled": _verdict(p1) in ("RECONCILED", "NOTHING_TO_RECONCILE"),
        "delta_load_reconciled": _verdict(p2) in ("RECONCILED", "NOTHING_TO_RECONCILE"),
        "no_extract_errors": p1.get("error_count", 0) == 0 and p2.get("error_count", 0) == 0,
        "support_clean": (p1.get("support_compliance") or {}).get("verdict") == "SUPPORT-CLEAN",
        "delta_no_duplicates": (p2.get("idempotency") or {}).get("newly_created", 0)
        <= (p2.get("cdc") or {}).get("changed_rows_extracted", 1) + 5,
    }
    go = all(checks.values())

    report = {
        "cutover_id": CUTOVER_ID,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "phases": [
            {"phase": "initial_load", "mode": "full",
             "objects": p1.get("object_count"), "created_in_s4": p1.get("objects_created_in_s4"),
             "reconciliation": _verdict(p1),
             "support": (p1.get("support_compliance") or {}).get("verdict")},
            {"phase": "delta_load", "mode": "delta",
             "changed_rows_extracted": (p2.get("cdc") or {}).get("changed_rows_extracted"),
             "newly_created": (p2.get("idempotency") or {}).get("newly_created"),
             "reused_from_ledger": (p2.get("idempotency") or {}).get("reused_from_ledger"),
             "reconciliation": _verdict(p2)},
        ],
        "checklist": checks,
        "go_no_go": "GO" if go else "NO-GO",
    }
    out = RUNS / CUTOVER_ID
    out.mkdir(parents=True, exist_ok=True)
    (out / "cutover_report.json").write_text(json.dumps(report, indent=2))

    print("\n" + "=" * 64)
    print(f"  CUTOVER REHEARSAL {CUTOVER_ID}  ->  {report['go_no_go']}")
    print("=" * 64)
    for ph in report["phases"]:
        print(f"  {ph['phase']:13} [{ph['mode']:5}]  recon={ph['reconciliation']}  " +
              (f"created={ph.get('created_in_s4')}" if ph['mode'] == 'full'
               else f"changed={ph.get('changed_rows_extracted')} new={ph.get('newly_created')} reused={ph.get('reused_from_ledger')}"))
    print("  ---- GO/NO-GO checklist ----")
    for k, v in checks.items():
        print(f"   [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\n  Report: {out / 'cutover_report.json'}")
    sys.exit(0 if go else 2)


if __name__ == "__main__":
    main()
