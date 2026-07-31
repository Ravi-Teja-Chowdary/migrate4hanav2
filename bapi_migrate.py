"""
bapi_migrate — the DIRECT-API migration lane: headless, support-safe object load.

The migration RUN with zero GUI and without voiding SAP support. It writes to S/4
ONLY through SAP's official released BAPIs (which run SAP's own validation and keep
the DB consistent) — never by modifying SAP standard or writing tables behind the
app layer, and never through the GUI/cockpit. This is SAP's sanctioned integration
path, so support is preserved.

Design mirrors grind.py: a registry maps each object to its ECC source, its BAPI,
a key, an existence check (net-new only — existing target records are never touched,
enforced twice: a pre-read skip-set AND the BAPI's own no-overwrite flag), and a
builder that maps source fields to BAPI parameters (incl. migrate-time hygiene).

    py -3.7 bapi_migrate.py Bank              # dry-run
    py -3.7 bapi_migrate.py Bank --commit     # migrate net-new + reconcile

Proven (2026-07-31): Bank — ECC BNKA -> BAPI_BANK_CREATE -> commit -> reconciled on
target (first migrated+reconciled object via this lane). Extend by adding a registry
entry; no new engine code.
"""
import os, sys, argparse
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine


def _valid_swift(s):
    s = (s or "").strip()
    return s if (len(s) >= 4 and s[:4].isalpha()) else ""   # drop invalid/test SWIFT


def _build_bank(r):
    """BNKA row -> (import kwargs for BAPI_BANK_CREATE)."""
    addr = {"BANK_NAME": r["BANKA"].strip()[:60], "REGION": r["PROVZ"].strip(),
            "STREET": r["STRAS"].strip()[:35], "CITY": r["ORT01"].strip()[:35],
            "SWIFT_CODE": _valid_swift(r["SWIFT"]), "BANK_BRANCH": r["BRNCH"].strip()[:40],
            "BANK_NO": r["BNKLZ"].strip()}
    return {"BANK_CTRY": r["BANKS"].strip(), "BANK_KEY": r["BANKL"].strip(),
            "BANK_ADDRESS": addr, "I_NO_OVERWRITE": "X"}


# object registry: source table/fields, key, BAPI, param builder, created-key extractor
OBJECTS = {
    "Bank": {
        "src_table": "BNKA",
        "src_fields": ["BANKS", "BANKL", "BANKA", "PROVZ", "STRAS", "ORT01", "SWIFT", "BRNCH", "BNKLZ"],
        "src_where": "LOEVM = ''",
        "key": ("BANKS", "BANKL"),
        "tgt_table": "BNKA",
        "tgt_key": ["BANKS", "BANKL"],
        "bapi": "BAPI_BANK_CREATE",
        "build": _build_bank,
    },
}


def migrate(eng, obj, limit, commit):
    spec = OBJECTS[obj]
    ecc, tgt = eng.ecc, eng.tgt
    src = eng.read_table(ecc, spec["src_table"], spec["src_fields"], spec.get("src_where", ""))
    tgt_keys = {tuple(r[k].strip() for k in spec["tgt_key"])
                for r in eng.read_table(tgt, spec["tgt_table"], spec["tgt_key"])}
    kf = spec["key"]
    netnew = [r for r in src if all(r[k].strip() for k in kf)
              and tuple(r[k].strip() for k in kf) not in tgt_keys]
    print(f"{obj}: source={len(src)} on-target={len(tgt_keys)} net-new={len(netnew)} "
          f"(up to {limit})" + ("" if commit else "  [DRY-RUN]"))

    ok = fail = 0; errors = []
    for r in netnew[:limit]:
        kv = "/".join(r[k].strip() for k in kf)
        if not commit:
            print(f"  DRY {kv}")
            continue
        res = tgt.call(spec["bapi"], **spec["build"](r))
        ret = res.get("RETURN", {})
        if ret.get("TYPE") in ("E", "A"):
            fail += 1; errors.append(f"{kv}: {ret.get('MESSAGE','')[:70]}")
            tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
            print(f"  OK  {kv}")
    if commit:
        print(f"=== {obj}: created={ok} failed={fail} ===")
        for e in errors[:10]:
            print("   ERR", e)
        after = {tuple(x[k].strip() for k in spec["tgt_key"])
                 for x in eng.read_table(tgt, spec["tgt_table"], spec["tgt_key"])}
        landed = sum(1 for r in netnew[:limit] if tuple(r[k].strip() for k in kf) in after)
        print(f"RECONCILE: {landed}/{min(limit, len(netnew))} intended {obj} records now on target")


def migrate_glaccount(eng, limit, commit, coa="INT"):
    """G/L accounts via SAP's GL_ACCT_MASTER_SAVE_RFC (support-safe). Net-new only,
    restricted to accounts whose account GROUP exists on the target chart (else it's
    a customizing gap the client must close). Text supplied in the chart's maintenance
    language. TESTMODE validates each account before the real write."""
    ecc, tgt = eng.ecc, eng.tgt
    w = "KTOPL = '%s'" % coa
    tgt_grp = {r["KTOKS"].strip() for r in eng.read_table(tgt, "T077S", ["KTOKS"], w)}
    te = {r["SAKNR"].strip() for r in eng.read_table(tgt, "SKA1", ["SAKNR"], w)}
    src = {r["SAKNR"].strip(): r for r in eng.read_table(
        ecc, "SKA1", ["SAKNR", "KTOKS", "XBILK", "GVTYP"], w)}
    de = {r["SAKNR"].strip(): r for r in eng.read_table(
        ecc, "SKAT", ["SAKNR", "TXT20", "TXT50"], w + " AND SPRAS = 'D'")}
    en = {r["SAKNR"].strip(): r for r in eng.read_table(
        ecc, "SKAT", ["SAKNR", "TXT20", "TXT50"], w + " AND SPRAS = 'E'")}
    netnew = [s for s, r in src.items() if s not in te and r["KTOKS"].strip() in tgt_grp][:limit]
    gap = [s for s, r in src.items() if s not in te and r["KTOKS"].strip() not in tgt_grp]
    print(f"GLAccount chart {coa}: net-new-migratable={len(netnew)} "
          f"config-gap(account group missing on target)={len(gap)}"
          + ("" if commit else "  [DRY-RUN]"))

    def call(s, testmode):
        a = src[s]; xbilk = a["XBILK"].strip()
        prim = de.get(s) or en.get(s); et = en.get(s)
        names = []
        if prim and prim["TXT50"].strip():
            names.append({"KEYY": {"KTOPL": coa, "SAKNR": s, "SPRAS": "D"},
                          "DATA": {"TXT20": prim["TXT20"].strip(), "TXT50": prim["TXT50"].strip()}, "ACTION": "INS"})
        if et and et["TXT50"].strip():
            names.append({"KEYY": {"KTOPL": coa, "SAKNR": s, "SPRAS": "E"},
                          "DATA": {"TXT20": et["TXT20"].strip(), "TXT50": et["TXT50"].strip()}, "ACTION": "INS"})
        r = tgt.call("GL_ACCT_MASTER_SAVE_RFC",
                     ACCOUNT_COA={"KEYY": {"KTOPL": coa, "SAKNR": s},
                                  "DATA": {"GLACCOUNT_TYPE": "X" if xbilk == "X" else "N",
                                           "KTOKS": a["KTOKS"].strip(), "XBILK": xbilk,
                                           "GVTYP": a["GVTYP"].strip()}, "ACTION": "INS"},
                     ACCOUNT_NAMES=names, ACCOUNT_CCODES=[], ACCOUNT_KEYWORDS=[], RETURN=[],
                     TESTMODE=testmode, NO_SAVE_AT_WARNING="X")
        return [x for x in r.get("RETURN", []) if x["TYPE"] in ("E", "A")]

    ok = 0
    for s in netnew:
        errs = call(s, "X")
        if errs:
            print(f"  SKIP {s}: {errs[0]['MESSAGE'][:70]}"); continue
        if not commit:
            print(f"  DRY  {s}"); continue
        if not call(s, ""):
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1; print(f"  OK   {s}")
    if commit:
        after = {r["SAKNR"].strip() for r in eng.read_table(tgt, "SKA1", ["SAKNR"], w)}
        landed = sum(1 for s in netnew if s in after)
        print(f"=== GLAccount: created={ok} === RECONCILE: {landed}/{len(netnew)} on target (chart {coa})")


HANDLERS = {"GLAccount": migrate_glaccount}   # objects needing a custom (non-flat) BAPI shape


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("object", choices=sorted(set(OBJECTS) | set(HANDLERS)))
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    eng = Engine()
    try:
        if args.object in HANDLERS:
            HANDLERS[args.object](eng, args.limit, args.commit)
        else:
            migrate(eng, args.object, args.limit, args.commit)
    finally:
        eng.close()
