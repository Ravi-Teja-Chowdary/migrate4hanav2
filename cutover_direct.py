"""
cutover_direct — go-live cutover choreography for the direct-API lane (road-to-production #7).

Wires the pieces built in this project into the real go-live sequence for the direct-API
buckets (bapi_migrate / bucket2 / bucket3), so a cutover isn't a single blind shot:

    freeze  -> initial  -> delta  -> reconcile  -> (rollback if NO-GO)

  freeze     record the cutover freeze timestamp. The SOURCE system lock itself (SM02 / lock
             users) is the client Basis team's SAP-canonical step — we record the moment and
             proceed; we never manipulate work processes (that would void support).
  initial    the full guarded run (preflight->consent->map->migrate->reconcile) — the bulk load.
  delta      re-run the guarded pipeline: the migration ledger makes it idempotent, so a delta
             pass posts ONLY records that appeared since the initial load (new keys), and
             skips everything already migrated. Records CHANGED since the freeze are picked up
             by passing M4H_DELTA_SINCE=<YYYYMMDD> (source change-date filter, where available).
  reconcile  the whole-company / run-scoped tie-out decides GO / NO-GO.
  rollback   on NO-GO or an aborted cutover, reverse the FI postings in REVERSE dependency
             order (open items/transactions before balances) via rollback_postings.py (official
             reversal BAPI + FB08/F.80 worklist). Master data stays net-new (SAP doesn't delete BPs).

    M4H_TARGET_CLIENT=100 py -3.7 cutover_direct.py freeze
    M4H_TARGET_CLIENT=100 py -3.7 cutover_direct.py initial --scope "FI slice cc 1710" --force
    M4H_TARGET_CLIENT=100 py -3.7 cutover_direct.py delta   --scope "FI slice cc 1710" --force
    M4H_TARGET_CLIENT=100 py -3.7 cutover_direct.py rollback --commit
"""
import os, sys, json, time, argparse, subprocess, datetime

STATE = "cutover_state.json"


def _load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def _save(s):
    json.dump(s, open(STATE, "w"), indent=1)


def _run(cmd):
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def freeze():
    s = _load()
    s["freeze_ts"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    s["freeze_date"] = datetime.date.today().strftime("%Y%m%d")
    s["phase"] = "frozen"
    _save(s)
    print(f"FREEZE recorded at {s['freeze_ts']}.")
    print("  NOTE: lock the SOURCE system now via the SAP-canonical path (SM02 message + lock")
    print("  users / stop batch) — that is a client Basis step; this tool never manipulates work")
    print("  processes (support-safe). Then run: cutover_direct.py initial")


def _guarded(args, phase):
    s = _load(); s["phase"] = phase; _save(s)
    cmd = [sys.executable, "migrate_everything.py", "--guarded", "--scope", args.scope, "--limit", str(args.limit)]
    if args.force:
        cmd.append("--force")
    env = dict(os.environ)
    if phase == "delta" and s.get("freeze_date"):
        env["M4H_DELTA_SINCE"] = s["freeze_date"]   # source change-date filter for changed records
        print(f"DELTA pass — new records since freeze are picked up idempotently; changed-since={s['freeze_date']}")
    r = subprocess.call(cmd, env=env)
    s = _load(); s["phase"] = phase + "_done"; s["last_" + phase] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _save(s)
    return r


def rollback(args):
    """Reverse in REVERSE dependency order: open items (AR/AP) before balances (GL)."""
    print("ROLLBACK (reverse dependency order: open items -> balances)")
    for marker in ("M4H-AR-OI", "M4H-AP-OI", "M4H-GLBAL"):
        cmd = [sys.executable, "rollback_postings.py", "--marker", marker]
        if args.commit:
            cmd.append("--commit")
        _run(cmd)
    print("  (master data stays net-new — SAP doesn't delete Business Partners)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["freeze", "initial", "delta", "rollback", "status"])
    ap.add_argument("--scope", default="FI slice")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    if a.phase == "freeze":
        freeze()
    elif a.phase in ("initial", "delta"):
        _guarded(a, a.phase)
    elif a.phase == "rollback":
        rollback(a)
    else:
        print(json.dumps(_load(), indent=1))


if __name__ == "__main__":
    main()
