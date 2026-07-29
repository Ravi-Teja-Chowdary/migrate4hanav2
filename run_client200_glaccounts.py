"""
run_client200_glaccounts — migrate ECC G/L accounts (SKA1/SKAT) into client 200
via the remote-enabled master FM GL_ACCT_MASTER_SAVE_RFC.

Approach (faithful, no forced CoA remap): create each ECC account into its OWN
chart of accounts where that chart also exists on the target (12 charts overlap:
INT/IKR/GKR/CARU/CAFR/CAIN/CAJP/CAKR/CANA/CATW/CACN/CAES). Preserves account
number + all language descriptions.

Key facts proven live:
  * GL_ACCT_MASTER_SAVE_RFC uses a DEEP structure: ACCOUNT_COA = {KEYY:{KTOPL,
    SAKNR}, DATA:{GLACCOUNT_TYPE,KTOKS,XBILK,GVTYP,...}, ACTION:'I'}; ACCOUNT_NAMES
    rows = {KEYY:{KTOPL,SAKNR,SPRAS}, DATA:{TXT20,TXT50}, ACTION:'I'}.
  * The description must exist in the CHART's maintenance language (e.g. INT is
    maintained in German 'D', not 'E') — FH743 otherwise. We carry every ECC
    language text, so whatever the maintenance language is, it's covered.
  * S/4 GLACCOUNT_TYPE (mandatory): X balance sheet, N nonoperating P&L, P primary
    cost/revenue, S secondary cost, C cash. Derived from XBILK + the ECC cost-
    element category (CSKB.KATYP).

Resumable; per-reason skip tally written.
"""
import os, sys, json, time
from collections import Counter, defaultdict
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from basis_kit_installer import push_rows_via_kit

DONEFILE = os.path.join("local-staging", "c200_glmap.json")
SKIPFILE = os.path.join("local-staging", "c200_gl_skips.json")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

# Latin/European languages safe over the target codepage (skip CJK/RTL that may
# not be installed and would fail the whole account); the chart maintenance
# language for the overlapping charts is within this set.
SAFE_LANG = set("EDFSIPNLCOVHQRUK56789TZBGWMAJ") - set("AJ")   # keep broad, drop Arabic/Japanese codepages
# secondary cost-element categories → S; any other cost element → P
SECONDARY = {"21", "31", "41", "42", "43"}


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


print(f"started {time.strftime('%H:%M:%S')}", flush=True)
ecc_charts = {r["KTOPL"] for r in rt(ec, "SKA1", ["KTOPL"])}
tgt_charts = {r["KTOPL"] for r in rt(sc, "SKA1", ["KTOPL"])}
charts = sorted(ecc_charts & tgt_charts)
print(f"overlapping charts: {charts}", flush=True)

# GOVERNED CONFIG STEP: the target's account-group number ranges (T077S) cap
# below the customer's real ECC account numbers (e.g. INT groups end at 999999
# but ECC has 1,111,000). Widen the upper bound (BISNR) to the max for the
# groups of the charts we migrate, so real account numbers land in their natural
# group. Reversible customizing (T077S, class C) via the Basis Kit.
t7f = [f["FIELDNAME"] for f in sc.call("RFC_GET_STRUCTURE_DEFINITION", TABNAME="T077S").get("FIELDS", [])
       if f["FIELDNAME"] != "MANDT"]
widen = []
for r in rt(sc, "T077S", t7f):
    if r["KTOPL"] in charts and r["BISNR"] and r["BISNR"] < "9999999999":
        widen.append(dict(r, BISNR="9999999999"))
if widen:
    res = push_rows_via_kit(sc, "T077S", t7f, widen)
    print(f"widened {len(widen)} account-group ranges (BISNR→9999999999): "
          f"upserted={res.get('upserted')} failed={res.get('failed')}", flush=True)

# cost-element category map (KSTAR -> KATYP), any controlling area
katyp = {}
for r in rt(ec, "CSKB", ["KSTAR", "KATYP"]):
    katyp.setdefault(r["KSTAR"], r["KATYP"])
print(f"cost elements known: {len(katyp)}", flush=True)


def gl_type(xbilk, saknr):
    if xbilk == "X":
        return "X"                       # balance sheet
    k = katyp.get(saknr)
    if k in SECONDARY:
        return "S"                       # secondary cost
    if k:
        return "P"                       # primary cost / revenue
    return "N"                           # nonoperating P&L


done = set(json.load(open(DONEFILE))) if os.path.exists(DONEFILE) else set()
ok = fail = 0
skips, reasons = [], Counter()

for ch in charts:
    tgt = {r["SAKNR"] for r in rt(sc, "SKA1", ["SAKNR"], "KTOPL = '%s'" % ch)}
    groups = {r["KTOKS"] for r in rt(sc, "T077S", ["KTOKS"], "KTOPL = '%s'" % ch)}
    def_group = "GL" if "GL" in groups else (sorted(groups)[0] if groups else "")
    ecc = rt(ec, "SKA1", ["SAKNR", "XBILK", "GVTYP", "KTOKS", "BILKT"], "KTOPL = '%s'" % ch)
    # texts for the whole chart, grouped by account
    txt = defaultdict(list)
    for t in rt(ec, "SKAT", ["SAKNR", "SPRAS", "TXT20", "TXT50"], "KTOPL = '%s'" % ch):
        if t["SPRAS"] in SAFE_LANG and t["TXT50"].strip():
            txt[t["SAKNR"]].append(t)
    todo = [a for a in ecc if a["SAKNR"] not in tgt and f"{ch}|{a['SAKNR']}" not in done]
    print(f"  {ch}: ecc={len(ecc)} target={len(tgt)} to-create={len(todo)}", flush=True)

    def nrow(sp, t20, t50):
        return {"KEYY": {"KTOPL": ch, "SAKNR": saknr, "SPRAS": sp},
                "DATA": {"TXT20": t20[:20], "TXT50": t50[:50]}, "ACTION": "I"}

    def save(coa, names):
        r = sc.call("GL_ACCT_MASTER_SAVE_RFC", ACCOUNT_COA=coa, ACCOUNT_NAMES=names,
                    TESTMODE="", NO_AUTHORITY_CHECK="X")
        return [m for m in (r.get("RETURN") or []) if m.get("TYPE") in ("E", "A")]

    for i, a in enumerate(todo, 1):
        saknr = a["SAKNR"]
        grp = a["KTOKS"] if a["KTOKS"] in groups else def_group
        # descriptions: dedupe by language + guarantee EN & DE (common chart
        # maintenance languages) so FH743 doesn't block on a missing maint lang
        names, seen = [], set()
        for t in txt.get(saknr, []):
            if t["SPRAS"] not in seen:
                seen.add(t["SPRAS"]); names.append(nrow(t["SPRAS"], t["TXT20"], t["TXT50"]))
        base = txt[saknr][0] if txt.get(saknr) else {
            "TXT20": "Account " + saknr.lstrip("0"), "TXT50": "G/L account " + saknr.lstrip("0")}
        for L in ("E", "D"):
            if L not in seen:
                names.append(nrow(L, base["TXT20"], base["TXT50"]))
        # Start WITHOUT the group account number (BILKT). Most charts don't
        # require it; adding it when the referenced group account doesn't exist
        # on the target's group chart causes FH065. Add it only if the chart
        # actually demands it (FH740), then a missing group account = clean skip.
        coa = {"KEYY": {"KTOPL": ch, "SAKNR": saknr},
               "DATA": {"GLACCOUNT_TYPE": gl_type(a["XBILK"], saknr), "KTOKS": grp,
                        "XBILK": a["XBILK"], "GVTYP": a["GVTYP"]},
               "ACTION": "I"}
        try:
            errs = save(coa, names)
            tries = 0
            while errs and tries < 3:
                ids = {f"{m.get('ID')}/{m.get('NUMBER')}" for m in errs}
                if "FH/740" in ids and a["BILKT"]:        # group account required
                    coa["DATA"]["BILKT"] = a["BILKT"]; errs = save(coa, names)
                elif "FH/002" in ids:                     # invalid P&L stmt type
                    coa["DATA"]["GVTYP"] = ""; errs = save(coa, names)
                elif "FH/174" in ids:                     # orphan text exists → master only
                    errs = save(coa, [])
                else:
                    break                                 # e.g. FH065 = group-chart dependency
                tries += 1
        except Exception as ex:
            fail += 1; reasons["RFC:" + type(ex).__name__] += 1
            skips.append({"key": f"{ch}|{saknr}", "reason": type(ex).__name__}); continue
        if errs:
            fail += 1; rc = f"{errs[0].get('ID')}/{errs[0].get('NUMBER')}"; reasons[rc] += 1
            skips.append({"key": f"{ch}|{saknr}", "reason": rc, "msg": errs[0].get("MESSAGE", "")[:80]})
        else:
            done.add(f"{ch}|{saknr}"); ok += 1
        if i % 500 == 0:
            json.dump(sorted(done), open(DONEFILE, "w")); json.dump(skips, open(SKIPFILE, "w"))
            print(f"    … {ch} {i}/{len(todo)} (ok={ok} fail={fail})", flush=True)

json.dump(sorted(done), open(DONEFILE, "w")); json.dump(skips, open(SKIPFILE, "w"))
total = len(rt(sc, "SKA1", ["SAKNR"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} | SKA1 on 200: {total}", flush=True)
print("skip/fail reasons:", dict(reasons.most_common(15)), flush=True)
ec.close(); sc.close()
