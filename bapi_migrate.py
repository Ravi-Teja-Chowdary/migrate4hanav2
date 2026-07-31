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


def migrate_costcenter(eng, limit, commit, src_ca="1000", tgt_ca="A000",
                       hier="0001", comp="1010", cur="EUR"):
    """Cost centers via SAP official BAPI_COSTCENTER_CREATEMULTIPLE (support-safe).
    Org-maps ECC controlling area -> target (default 1000->A000) and lands each on the
    target's existing hierarchy node / company code / a valid profit center. Every
    record is TESTRUN-validated before write. Net-new only.
    NOTE: on an IDES<->IDES pair cost-center numbers fully overlap (net-new=0); on a
    real client whose fresh S/4 lacks the cost centers this creates + reconciles them."""
    ecc, tgt = eng.ecc, eng.tgt
    tgt_cc = {r["KOSTL"].strip() for r in eng.read_table(tgt, "CSKS", ["KOSTL"], "KOKRS = '%s'" % tgt_ca)}
    a000_pc = {r["PRCTR"].strip() for r in eng.read_table(tgt, "CEPC", ["PRCTR"], "KOKRS = '%s'" % tgt_ca)}
    def_pc = sorted(a000_pc)[0] if a000_pc else ""
    src = eng.read_table(ecc, "CSKS", ["KOSTL", "DATAB", "DATBI", "VERAK", "KOSAR", "PRCTR"],
                         "KOKRS = '%s'" % src_ca)
    nm = {r["KOSTL"].strip(): r for r in eng.read_table(ecc, "CSKT", ["KOSTL", "KTEXT", "LTEXT"],
          "KOKRS = '%s' AND SPRAS = 'E'" % src_ca)}
    netnew = [r for r in src if r["KOSTL"].strip() not in tgt_cc][:limit]
    print(f"CostCenter {src_ca}->{tgt_ca}: source={len(src)} on-target={len(tgt_cc)} "
          f"net-new={len(netnew)}" + ("" if commit else "  [DRY/TESTRUN]"))
    if not netnew:
        print("  net-new=0 (full overlap on this system) — nothing to create."); return
    rows = []
    for r in netnew:
        k = r["KOSTL"].strip(); t = nm.get(k, {})
        pc = r["PRCTR"].strip() if r["PRCTR"].strip() in a000_pc else def_pc
        rows.append({"COSTCENTER": k, "VALID_FROM": r["DATAB"].strip() or "20200101",
                     "VALID_TO": r["DATBI"].strip() or "99991231",
                     "PERSON_IN_CHARGE": r["VERAK"].strip()[:20],
                     "COSTCENTER_TYPE": r["KOSAR"].strip() or "G", "COSTCTR_HIER_GRP": hier,
                     "COMP_CODE": comp, "CURRENCY": cur, "PROFIT_CTR": pc,
                     "NAME": (t.get("KTEXT", "").strip() or ("CC " + k))[:20],
                     "DESCRIPT": (t.get("LTEXT", "").strip() or t.get("KTEXT", "").strip() or ("Cost center " + k))[:40]})
    ret = tgt.call("BAPI_COSTCENTER_CREATEMULTIPLE", CONTROLLINGAREA=tgt_ca,
                   COSTCENTERLIST=rows, TESTRUN="X").get("RETURN", [])
    errs = [x for x in ret if x["TYPE"] in ("E", "A")]
    print(f"  TESTRUN: {len(errs)} errors")
    for x in errs[:8]:
        print(f"     ERR row {x.get('ROW','')}: {x['MESSAGE'][:75]}")
    if commit and not errs:
        tgt.call("BAPI_COSTCENTER_CREATEMULTIPLE", CONTROLLINGAREA=tgt_ca, COSTCENTERLIST=rows, TESTRUN="")
        tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        after = {r["KOSTL"].strip() for r in eng.read_table(tgt, "CSKS", ["KOSTL"], "KOKRS = '%s'" % tgt_ca)}
        landed = sum(1 for r in netnew if r["KOSTL"].strip() in after)
        print(f"=== CostCenter RECONCILE: {landed}/{len(netnew)} now in {tgt_ca} ===")


def migrate_characteristic(eng, limit, commit):
    """Characteristics via BAPI_CHARACT_CREATE (support-safe, client-level, no org)."""
    ecc, tgt = eng.ecc, eng.tgt
    tset = {r["ATNAM"].strip() for r in eng.read_table(tgt, "CABN", ["ATNAM"])}
    src = eng.read_table(ecc, "CABN", ["ATINN", "ATNAM", "ATFOR", "ANZST", "ANZDZ"])
    desc = {r["ATINN"].strip(): r["ATBEZ"].strip()
            for r in eng.read_table(ecc, "CABNT", ["ATINN", "ATBEZ", "SPRAS"], "SPRAS = 'E'")}
    netnew = [r for r in src if r["ATNAM"].strip() and r["ATNAM"].strip() not in tset][:limit]
    print(f"Characteristic: net-new={len(netnew)}" + ("" if commit else "  [DRY]"))
    ok = fail = 0
    for r in netnew:
        nm = r["ATNAM"].strip(); fmt = r["ATFOR"].strip() or "CHAR"
        det = {"CHARACT_NAME": nm, "DATA_TYPE": fmt, "STATUS": "1"}
        if fmt in ("NUM", "CURR"):
            det["LENGTH"] = str(int(r["ANZST"] or 0) or 1); det["DECIMALS"] = str(int(r["ANZDZ"] or 0))
        elif fmt == "CHAR":
            det["LENGTH"] = str(int(r["ANZST"] or 0) or 30)
        dsc = [{"LANGUAGE_INT": "E", "LANGUAGE_ISO": "EN", "DESCRIPTION": desc.get(r["ATINN"].strip(), nm)[:30]}]
        if not commit:
            continue
        er = [x for x in [tgt.call("BAPI_CHARACT_CREATE", CHARACTDETAIL=det, CHARACTDESCR=dsc).get("RETURN", {})]
              if x.get("TYPE") in ("E", "A")]
        if er:
            fail += 1; tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
    if commit:
        after = {r["ATNAM"].strip() for r in eng.read_table(tgt, "CABN", ["ATNAM"])}
        landed = sum(1 for r in netnew if r["ATNAM"].strip() in after)
        print(f"=== Characteristic created={ok} failed={fail} | RECONCILE {landed}/{len(netnew)} ===")


def migrate_class(eng, limit, commit):
    """Classes via BAPI_CLASS_CREATE (support-safe, no org)."""
    ecc, tgt = eng.ecc, eng.tgt
    tk = {(r["CLASS"].strip(), r["KLART"].strip()) for r in eng.read_table(tgt, "KLAH", ["CLASS", "KLART"])}
    src = eng.read_table(ecc, "KLAH", ["CLASS", "KLART"])
    netnew = [r for r in src if (r["CLASS"].strip(), r["KLART"].strip()) not in tk][:limit]
    print(f"Class: net-new={len(netnew)}" + ("" if commit else "  [DRY]"))
    ok = fail = 0
    for r in netnew:
        cls, kl = r["CLASS"].strip(), r["KLART"].strip()
        if not commit:
            continue
        res = tgt.call("BAPI_CLASS_CREATE", CLASSNUMNEW=cls, CLASSTYPENEW=kl,
                       CLASSBASICDATA={"STATUS": "1"},
                       CLASSDESCRIPTIONS=[{"LANGU": "E", "LANGU_ISO": "EN", "CATCHWORD": cls[:30]}], TESTRUN="")
        if [x for x in res.get("RETURN", []) if x["TYPE"] in ("E", "A")]:
            fail += 1; tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
    if commit:
        ta = {(r["CLASS"].strip(), r["KLART"].strip()) for r in eng.read_table(tgt, "KLAH", ["CLASS", "KLART"])}
        landed = sum(1 for r in netnew if (r["CLASS"].strip(), r["KLART"].strip()) in ta)
        print(f"=== Class created={ok} failed={fail} | RECONCILE {landed}/{len(netnew)} ===")


def migrate_profitcenter(eng, limit, commit, src_ca="1000", tgt_ca="A000"):
    """Profit centers via BAPI_PROFITCENTER_CREATE (support-safe). Org-map 1000->A000.
    Net-new=0 on IDES<->IDES (full overlap); ready for real client data."""
    ecc, tgt = eng.ecc, eng.tgt
    tset = {r["PRCTR"].strip() for r in eng.read_table(tgt, "CEPC", ["PRCTR"], "KOKRS = '%s'" % tgt_ca)}
    src = {r["PRCTR"].strip(): r for r in eng.read_table(ecc, "CEPC", ["PRCTR"], "KOKRS = '%s'" % src_ca)}
    nm = {r["PRCTR"].strip(): r for r in eng.read_table(ecc, "CEPCT", ["PRCTR", "KTEXT", "LTEXT"],
          "KOKRS = '%s' AND SPRAS = 'E'" % src_ca)}
    netnew = [p for p in src if p not in tset][:limit]
    print(f"ProfitCenter {src_ca}->{tgt_ca}: net-new={len(netnew)}" + ("" if commit else "  [DRY]"))
    if not netnew:
        print("  net-new=0 (full overlap on this system) — nothing to create."); return
    ok = fail = 0
    for p in netnew:
        t = nm.get(p, {})
        basic = {"PRCTR_NAME": (t.get("KTEXT", "").strip() or p)[:20],
                 "LONG_TEXT": (t.get("LTEXT", "").strip() or p)[:40], "PRCTR_HIER_GRP": ""}
        if not commit:
            continue
        res = tgt.call("BAPI_PROFITCENTER_CREATE", PROFITCENTERID={"CO_AREA": tgt_ca, "PROFIT_CTR": p},
                       BASICDATA=basic, VALIDFROM="20200101", VALIDTO="99991231", TESTRUN="")
        r = res.get("RETURN", {})
        if (r if isinstance(r, dict) else {}).get("TYPE") in ("E", "A"):
            fail += 1
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
    if commit:
        print(f"=== ProfitCenter created={ok} failed={fail} ===")


def _odata(eng):
    import json as _j
    from odata_client import ODataClient
    t = _j.load(open("connections.json"))["lift_and_shift_target"]
    return ODataClient(host=t["target_public_ip"], user=t["target_user"],
                       passwd=os.environ["M4H_TARGET_PASSWD"], client="200", port=44300, timeout=60)


def _bp_recon(eng, table, comp):
    import collections
    a = collections.Counter(r["AKONT"].strip() for r in eng.read_table(eng.tgt, table, ["AKONT"], "BUKRS = '%s'" % comp) if r["AKONT"].strip())
    return a.most_common(1)[0][0] if a else ""


def migrate_customer(eng, limit, commit, comp="1710", sorg="1710"):
    """Customers via SAP official API_BUSINESS_PARTNER OData (BP/CVI-led, support-safe).
    NOTE: external CVI numbering assigns a new BP each run — production needs a key-map
    (ECC KUNNR -> BP) to dedupe; this migrates the first `limit` ECC customers."""
    import bp_odata
    oc = _odata(eng); recon = _bp_recon(eng, "KNB1", comp)
    src = eng.read_table(eng.ecc, "KNA1", ["KUNNR", "NAME1", "ORT01", "STRAS"])[:limit]
    print(f"Customer: creating {len(src)} (company {comp} recon {recon})" + ("" if commit else "  [DRY]"))
    ok = fail = 0; made = []
    for r in src:
        if not commit:
            continue
        res = bp_odata.create_customer(oc, name=(r["NAME1"].strip() or "Customer " + r["KUNNR"].strip()),
                company_code=comp, recon_account=recon, sales_org=sorg, distr_chan="10",
                division="00", currency="USD", country="US", city=r["ORT01"].strip()[:35] or "New York",
                postal_code="10001", street=r["STRAS"].strip()[:35] or "1 Way", language="EN")
        if res.get("status") == "created" and res.get("partner"):
            ok += 1; made.append(res["partner"])
        else:
            fail += 1
    if commit:
        landed = sum(1 for bp in made if oc.get("API_BUSINESS_PARTNER", "A_BusinessPartner('%s')" % bp, {}).status_code == 200)
        print(f"=== Customer created={ok} failed={fail} | RECONCILE {landed}/{len(made)} BPs readable ===")


def migrate_vendor(eng, limit, commit, comp="1710", porg="1710"):
    """Suppliers via SAP official API_BUSINESS_PARTNER OData (support-safe). See customer note."""
    import bp_odata
    oc = _odata(eng); recon = _bp_recon(eng, "LFB1", comp)
    src = eng.read_table(eng.ecc, "LFA1", ["LIFNR", "NAME1", "ORT01", "STRAS"])[:limit]
    print(f"Vendor: creating {len(src)} (company {comp} recon {recon})" + ("" if commit else "  [DRY]"))
    ok = fail = 0; made = []
    for r in src:
        if not commit:
            continue
        res = bp_odata.create_supplier(oc, name=(r["NAME1"].strip() or "Vendor " + r["LIFNR"].strip()),
                company_code=comp, recon_account=recon, purch_org=porg, country="US",
                city=r["ORT01"].strip()[:35] or "New York", postal_code="10001",
                street=r["STRAS"].strip()[:35] or "1 Way", language="EN")
        if res.get("status") == "created" and res.get("partner"):
            ok += 1; made.append(res["partner"])
        else:
            fail += 1
    if commit:
        landed = sum(1 for bp in made if oc.get("API_BUSINESS_PARTNER", "A_BusinessPartner('%s')" % bp, {}).status_code == 200)
        print(f"=== Vendor created={ok} failed={fail} | RECONCILE {landed}/{len(made)} BPs readable ===")


HANDLERS = {"GLAccount": migrate_glaccount, "CostCenter": migrate_costcenter,
            "Characteristic": migrate_characteristic, "Class": migrate_class,
            "ProfitCenter": migrate_profitcenter,
            "Customer": migrate_customer, "Vendor": migrate_vendor}


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
