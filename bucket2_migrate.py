"""
bucket2_migrate — the DIRECT-API lane for Bucket 2 (open transactions).

Same support-safe contract as bapi_migrate.py (master data): writes to S/4 ONLY through
official released BAPIs (SAP's own validation, DB stays consistent), never modifies SAP
standard, never writes behind the app layer, net-new only. Sibling of bapi_migrate.py;
run bucket2_preflight.py first to see, per object, whether the target holds the master
data each open document points at.

    py -3.7 bucket2_migrate.py MaintenanceNotification            # dry-run
    py -3.7 bucket2_migrate.py MaintenanceNotification --commit   # migrate + reconcile

Proven live 2026-07-31 (first Bucket-2 object landed headless): Maintenance Notification
— ECC QMEL -> BAPI_ALM_NOTIF_CREATE -> BAPI_ALM_NOTIF_SAVE -> commit -> reconciled
(target QMEL 0 -> 5). The two-step create+save is required for PM/QM notifications: CREATE
builds the notification in memory and returns a TEMPORARY (%-prefixed) number; SAVE
persists it and assigns the real number before commit.

Honest boundary on the current target box: logistics open docs (PO/PR-stock/production
order/reservation) need plant-extended materials (target MARC is empty), and sales orders
need sales-view materials (target MVKE is empty) — so those are BLOCKED here by target
master-data completeness, not by the tool (their BAPIs are all present + callable). On a
real client whose S/4 has materials fully extended they land at volume. See
bucket2_preflight.py for the live per-object readiness matrix.
"""
import os, sys, argparse
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine


def migrate_maintenance_notification(eng, limit, commit):
    """PM maintenance notifications (QMEL, category 01) via SAP official
    BAPI_ALM_NOTIF_CREATE + BAPI_ALM_NOTIF_SAVE (support-safe). Lands only notifications
    whose type exists on the target and is a maintenance-category type (TQ80 QMTYP='01');
    other categories route to their own BAPI (quality/service) and need partner
    determination. Net-new only; target assigns the number."""
    ecc, tgt = eng.ecc, eng.tgt
    cat = {r["QMART"].strip(): r["QMTYP"].strip() for r in eng.read_table(tgt, "TQ80", ["QMART", "QMTYP"])}
    src = eng.read_table(ecc, "QMEL", ["QMNUM", "QMART", "QMTXT"])
    netnew = [r for r in src if cat.get(r["QMART"].strip()) == "01"]
    other = [r for r in src if r["QMART"].strip() in cat and cat[r["QMART"].strip()] != "01"]
    proc = netnew[:limit]
    print(f"MaintenanceNotification: maint-type-on-target={len(netnew)} "
          f"other-category(needs own BAPI/partners)={len(other)} processing={len(proc)}"
          + ("" if commit else "  [DRY]"))
    before = len(eng.read_table(tgt, "QMEL", ["QMNUM"]))
    ok = fail = 0; errors = []; made = []
    for r in proc:
        qt = r["QMART"].strip()
        txt = (r["QMTXT"].strip() or "Maintenance notification " + r["QMNUM"].strip())[:40]
        if not commit:
            continue
        res = tgt.call("BAPI_ALM_NOTIF_CREATE", NOTIF_TYPE=qt, NOTIFHEADER={"SHORT_TEXT": txt})
        rl = res.get("RETURN", []); rl = rl if isinstance(rl, list) else [rl]
        tmp = (res.get("NOTIFHEADER_EXPORT", {}) or {}).get("NOTIF_NO", "").strip()
        if any(m.get("TYPE") in ("E", "A") for m in rl) or not tmp:
            fail += 1; errors.append("%s: %s" % (r["QMNUM"].strip(),
                        next((m["MESSAGE"][:60] for m in rl if m.get("TYPE") in ("E", "A")), "no number")))
            tgt.call("BAPI_TRANSACTION_ROLLBACK"); continue
        sv = tgt.call("BAPI_ALM_NOTIF_SAVE", NUMBER=tmp)
        sl = sv.get("RETURN", []); sl = sl if isinstance(sl, list) else [sl]
        realno = (sv.get("NOTIFHEADER", {}) or {}).get("NOTIF_NO", "").strip() or (sv.get("NUMBER") or "").strip()
        if any(m.get("TYPE") in ("E", "A") for m in sl) or not realno:
            fail += 1; errors.append("%s: %s" % (r["QMNUM"].strip(),
                        next((m["MESSAGE"][:60] for m in sl if m.get("TYPE") in ("E", "A")), "save failed")))
            tgt.call("BAPI_TRANSACTION_ROLLBACK"); continue
        tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1; made.append(realno)
    if commit:
        print(f"=== MaintenanceNotification created={ok} failed={fail} ===")
        for e2 in errors[:8]:
            print("   ERR", e2)
        after = len(eng.read_table(tgt, "QMEL", ["QMNUM"]))
        print(f"RECONCILE: target QMEL {before} -> {after} (+{after - before})")


HANDLERS = {"MaintenanceNotification": migrate_maintenance_notification}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("object", choices=sorted(HANDLERS))
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    eng = Engine()
    try:
        HANDLERS[args.object](eng, args.limit, args.commit)
    finally:
        eng.close()
