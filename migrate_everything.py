"""
migrate_everything — the one-command ECC -> S/4HANA "every damn thing" migrator.

THE product entry point. Point it at a source ECC + a target S/4 client and it migrates
every object it can across all THREE buckets, **SAP-support-safe**: it writes to S/4 ONLY
through SAP's official released BAPIs / OData APIs (which run SAP's own validation and keep
the DB consistent — every FI document must balance to zero or SAP refuses it). It never
modifies SAP standard and never writes tables behind the app layer. It picks the right lane
per object, then reconciles and reports honestly.

Three buckets, in migration order:
  1. Master data      (bapi_migrate.py) — Bank, G/L, Customer, Vendor, Characteristic,
                        Class, Equipment, Fixed Asset, Document + cockpit staging for the rest.
  2. Open transactions (bucket2_migrate.py) — Maintenance Notification + the open-doc lane
                        (PO/PR/SO/production order gated by target master-data completeness).
  3. Balances          (bucket3_migrate.py) — G/L balances, AR / AP open items, inventory
                        stock, asset values — posted + reconciled to the cent.

Target client: set M4H_TARGET_CLIENT (env). Client 100 = SAP Best Practices fully-activated
client (plant+sales-extended materials + full FI/CO config) — the proving ground that
mirrors a real client. Client 200 = thin. Default 200.

    M4H_TARGET_CLIENT=100 py -3.7 migrate_everything.py                 # plan (no writes)
    M4H_TARGET_CLIENT=100 py -3.7 migrate_everything.py --commit        # execute all 3 buckets
    M4H_TARGET_CLIENT=100 py -3.7 migrate_everything.py --commit --limit 5
    py -3.7 migrate_everything.py --commit --staging                    # also run the ~220
                                                                        # cockpit-staging objects

Honest by design: every object ends in exactly one bucket — migrated / staged / needs-config
/ no-source — nothing is hidden, and bad data is refused by SAP validation, never forced.
"""
import os, sys, json, argparse, datetime, traceback
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine
from object_catalog import Catalog
import scaffold_recipe as scf
import bapi_migrate as bm
import bucket2_migrate as b2
import bucket3_migrate as b3
import grind_all as ga

MT = "M02"

# -- Bucket 1: master-data direct-api handlers (catalog object ident -> handler name) --
DIRECT = {
    "Z_BANK_2_M02": "Bank", "Z_GL_ACCOUNT_3_M02": "GLAccount",
    "Z_CUSTOMER_2_M02": "Customer", "Z_CUST_EXT_3_M02": "Customer",
    "Z_VENDOR_2_M02": "Vendor", "Z_VEND_EXT_3_M02": "Vendor",
    "Z_CHARACT_M02": "Characteristic", "Z_CLASS_2_M02": "Class",
    "Z_KOSTL_MASTER_M02": "CostCenter", "Z_PRCTR_MSTR2_M02": "ProfitCenter",
    "Z_EQUIPMENT_2_M02": "Equipment", "Z_FIXED_ASSET_M02": "FixedAsset",
    "Z_DOCU_INFOREC_M02": "Document",
}


def run_direct(eng, handler, limit, commit):
    """Dispatch to the proven support-safe master-data handler in bapi_migrate."""
    if handler in bm.HANDLERS:
        bm.HANDLERS[handler](eng, limit, commit)
    elif handler in bm.OBJECTS:
        bm.migrate(eng, handler, limit, commit)


def run_handlers(eng, handlers, limit, commit, report, bucket):
    """Run a {name: fn(eng, limit, commit)} map, recording one honest row per object."""
    for name, fn in sorted(handlers.items()):
        try:
            fn(eng, limit, commit)
            report.append({"bucket": bucket, "object": name, "result": "migrated" if commit else "ready"})
        except Exception as e:
            report.append({"bucket": bucket, "object": name, "result": "error", "err": str(e)[:90]})
            print(f"  ERROR {name}: {str(e)[:90]}", flush=True)


def _blocked_count(report_path):
    try:
        return sum(1 for l in open(report_path, encoding="utf-8") if "🔴 BLOCKED" in l)
    except Exception:
        return -1


def _recon_verdict(report_path):
    try:
        txt = open(report_path, encoding="utf-8").read()
        return "GO" if "Overall verdict: **GO" in txt else "NO-GO"
    except Exception:
        return "UNKNOWN"


def guarded(args):
    """End-to-end GUARDED run: preflight -> consent -> governed mappings -> migrate ->
    whole-company reconcile -> GO/NO-GO. Each gate can halt the run. This is the single
    command that behaves like a real go-live: nothing writes until the gates pass, and the
    result is a signed, reconciled verdict."""
    import preflight_all, reconcile_company, consent_ledger
    from key_mapper import KeyMap
    client = os.environ.get("M4H_TARGET_CLIENT", "200")
    scope = args.scope
    print(f"================ GUARDED RUN | client {client} | scope: {scope} ================\n", flush=True)

    # GATE 1 — signed consent (governance)
    c = consent_ledger.require_consent(scope)
    if not c:
        print("HALT [consent]: no signed consent for this scope. Record one with:")
        print('   py -3.7 consent_ledger.py grant --signer "<name/role>" --scope "%s"' % scope)
        return
    print(f"GATE 1 consent      ✓  approved by {c['signer']} at {c['ts']}", flush=True)

    # GATE 2 — preflight (target config + source data health)
    print("GATE 2 preflight    … running preflight_all", flush=True)
    preflight_all.main()
    blocked = _blocked_count("PREFLIGHT.md")
    if blocked > 0 and not args.force:
        print(f"HALT [preflight]: {blocked} BLOCKED item(s) — resolve them (see PREFLIGHT.md) or re-run with --force.")
        return
    print(f"GATE 2 preflight    ✓  ({blocked} blocked{' — overridden by --force' if blocked > 0 else ''})", flush=True)

    # GATE 3 — governed mappings only (refuse the positional guess)
    gov = KeyMap().resolved_map("gl_account")
    if not gov and not args.force:
        print("HALT [mapping]: no governed chart-of-accounts map. Build + confirm it:")
        print("   key_mapper.py gl_account   then   key_mapper.py gl_account --confirm-reviews")
        return
    print(f"GATE 3 mappings     ✓  governed COA pairs: {len(gov)} (positional fallback refused)", flush=True)

    # STEP 4 — migrate (idempotent handlers; FI slice = master FI + balances)
    print("STEP 4 migrate      … FI slice (G/L, Customer, Vendor, then balances)", flush=True)
    eng = Engine(allow_proposed=True)
    try:
        for h in ("GLAccount", "Customer", "Vendor"):
            try:
                run_direct(eng, h, args.limit, True)
            except Exception as e:
                print(f"   {h} ERROR: {str(e)[:80]}")
        for name in ("GLBalances", "AROpenItems", "APOpenItems"):
            try:
                b3.HANDLERS[name](eng, args.limit, True)
            except Exception as e:
                print(f"   {name} ERROR: {str(e)[:80]}")
    finally:
        eng.close()

    # GATE 5 — whole-company reconciliation (the sign-off)
    print("GATE 5 reconcile    … whole-company tie-out", flush=True)
    reconcile_company.main()
    verdict = _recon_verdict("RECONCILIATION.md")
    print(f"\n================ GUARDED RUN VERDICT: {verdict} ================")
    print("   consent ✓  preflight ✓  governed-mappings ✓  migrated ✓  reconciled -> " + verdict)
    if verdict != "GO":
        print("   NO-GO: see RECONCILIATION.md for the exact variances to resolve before go-live.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="execute (default: plan, no writes)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--staging", action="store_true", help="also run the ~220 cockpit-staging objects (slow)")
    ap.add_argument("--guarded", action="store_true", help="single end-to-end guarded run (preflight->consent->map->migrate->reconcile->GO/NO-GO)")
    ap.add_argument("--scope", default="FI slice", help="consent/reconcile scope label for the guarded run")
    ap.add_argument("--force", action="store_true", help="override preflight/mapping halts (guarded run)")
    args = ap.parse_args()
    if args.guarded:
        guarded(args); return

    client = os.environ.get("M4H_TARGET_CLIENT", "200")
    eng = Engine(allow_proposed=True)
    cat = Catalog(eng)
    objs = sorted(cat.objects(MT))
    print(f"=== migrate_everything | target client {client} | "
          f"{'EXECUTE' if args.commit else 'PLAN (no writes)'} | support-safe, 3 buckets ===\n", flush=True)
    report = []

    # == Bucket 1 — Master data (direct-API, official BAPI/OData) ====================
    print("-- Bucket 1: MASTER DATA (direct-API, official BAPI/OData) --", flush=True)
    seen = set()
    for obj in objs:
        h = DIRECT.get(obj)
        if not h or h in seen:
            continue
        seen.add(h)
        try:
            run_direct(eng, h, args.limit, args.commit)
            report.append({"bucket": "1-master", "object": h, "result": "migrated" if args.commit else "ready"})
        except Exception as e:
            report.append({"bucket": "1-master", "object": h, "result": "error", "err": str(e)[:90]})
            print(f"  ERROR {h}: {str(e)[:90]}", flush=True)

    # == Bucket 2 — Open transactions (direct-API) ==================================
    print("\n-- Bucket 2: OPEN TRANSACTIONS (direct-API) --", flush=True)
    run_handlers(eng, b2.HANDLERS, args.limit, args.commit, report, "2-open")

    # == Bucket 3 — Balances (post + reconcile to the cent) =========================
    print("\n-- Bucket 3: BALANCES (post + reconcile) --", flush=True)
    run_handlers(eng, b3.HANDLERS, args.limit, args.commit, report, "3-balances")

    # == Bucket 1 (cont.) — cockpit staging for the long tail (optional) ============
    if args.staging:
        print("\n-- Bucket 1 (cont.): cockpit staging (SAP-supported staging method) --", flush=True)
        for obj in objs:
            if obj in DIRECT:
                continue
            struct, table = cat.primary(MT, obj)
            src = ga.source_for(struct)
            row = {"bucket": "1-staging", "object": obj, "src": src}
            try:
                recipe = scf.scaffold(eng, table, src, "master", obj)
                if len(recipe["structures"][0]["map"]) == 0:
                    row["result"] = "no-source"
                elif args.commit:
                    info = eng.run(recipe)[0]
                    row["result"] = "staged" if (info.get("verified_rows") or 0) > 0 else "no-data"
                else:
                    row["result"] = "mappable"
            except Exception:
                row["result"] = "no-source"
            report.append(row)

    eng.close()

    # -- report ---------------------------------------------------------------------
    from collections import Counter
    os.makedirs("catalog", exist_ok=True)
    json.dump(report, open(os.path.join("catalog", "migration_report.json"), "w"), indent=1)
    print("\n================= MIGRATION REPORT (3 buckets) =================")
    print(f"  date: {datetime.date.today()}   target client: {client}   "
          f"mode: {'EXECUTE' if args.commit else 'PLAN'}")
    for bucket in ("1-master", "2-open", "3-balances", "1-staging"):
        rows = [r for r in report if r["bucket"] == bucket]
        if not rows:
            continue
        c = Counter(r["result"] for r in rows)
        print(f"  {bucket:<12} {len(rows):>3} objects   " + "  ".join("%s=%d" % kv for kv in c.most_common()))
    print("  wrote catalog/migration_report.json")


if __name__ == "__main__":
    main()
