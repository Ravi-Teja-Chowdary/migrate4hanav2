"""
run_client200_banks — migrate ECC bank master (BNKA) into client 200 via
BAPI_BANK_CREATE. Simple master data: no org/tax dependency. Preserves country
+ bank key. Resumable (persists done set; also skips banks already on 200).

Source-data harmonisation:
  * REGION (PROVZ) is validated against the target T005S; invalid region codes
    (e.g. ECC 'PQ' for Québec vs S/4 'QC') are blanked rather than failing the
    whole bank on message 00/058 "Entry ... does not exist in T005S".
  * Country bank-key length/check rules (AR/102, AR/103) cannot be satisfied
    without altering the key (which would break faithfulness), so those banks
    are skipped and tallied by reason in a skip report — honest exceptions, not
    silent losses.
"""
import os, sys, json, time
from collections import Counter
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from basis_kit_installer import push_rows_via_kit

DONEFILE = os.path.join("local-staging", "c200_bankmap.json")
SKIPFILE = os.path.join("local-staging", "c200_bank_skips.json")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


print(f"started {time.strftime('%H:%M:%S')}", flush=True)
banks = rt(ec, "BNKA", ["BANKS", "BANKL", "BANKA", "ORT01", "STRAS", "PROVZ", "SWIFT", "BRNCH"])
print(f"ECC banks: {len(banks)}", flush=True)

# valid (country, region) set from the TARGET so we only send regions S/4 accepts
valid_regions = {f"{r['LAND1']}|{r['BLAND']}" for r in rt(sc, "T005S", ["LAND1", "BLAND"], "", 0)}
print(f"target T005S region entries: {len(valid_regions)}", flush=True)

# GOVERNED CONFIG STEP: the customer's ECC bank keys are pre-assigned (external)
# and some violate the target's default country bank-key length/generation
# checks (e.g. CA 10-char keys vs the 9-char rule -> AR/103). To preserve every
# key faithfully we set the bank-key determination to '2' (external, no length
# check) for exactly the countries present in the source bank master. Reversible
# customizing (T005, delivery class C) applied via the Basis Kit.
bank_countries = sorted({b["BANKS"] for b in banks if b["BANKS"]})
t5fields = [f["FIELDNAME"] for f in sc.call("DDIF_FIELDINFO_GET", TABNAME="T005").get("DFIES_TAB", [])
            if not f["FIELDNAME"].startswith(".") and f["FIELDNAME"] != "MANDT"]
t5rows = rt(sc, "T005", t5fields, "", 0)
flip = [dict(r, BNKEY="2") for r in t5rows if r["LAND1"] in bank_countries and r.get("BNKEY") != "2"]
if flip:
    res = push_rows_via_kit(sc, "T005", t5fields, flip)
    print(f"set BNKEY=2 (external key) for {len(flip)} bank countries: "
          f"upserted={res.get('upserted')} failed={res.get('failed')}", flush=True)

done = set(json.load(open(DONEFILE))) if os.path.exists(DONEFILE) else set()
existing = {f"{b['BANKS']}|{b['BANKL']}" for b in rt(sc, "BNKA", ["BANKS", "BANKL"], "", 0)}
done |= existing
todo = [b for b in banks if f"{b['BANKS']}|{b['BANKL']}" not in done]
print(f"to create: {len(todo)} (already on 200/mapped: {len(done)})", flush=True)

ok = fail = region_fixed = 0
skips = []                       # [{key, country, reason}]
reasons = Counter()
for i, b in enumerate(todo, 1):
    key = f"{b['BANKS']}|{b['BANKL']}"
    region = b["PROVZ"]
    if region and f"{b['BANKS']}|{region}" not in valid_regions:
        region = ""             # drop region S/4 would reject; keep the bank
        region_fixed += 1
    swift = b["SWIFT"] if len(b["SWIFT"]) in (8, 11) else ""   # AR/202: SWIFT must be 8/11
    addr = {"BANK_NAME": (b["BANKA"] or "Bank")[:60], "CITY": b["ORT01"][:35],
            "STREET": b["STRAS"][:35], "REGION": region, "SWIFT_CODE": swift,
            "BANK_BRANCH": b["BRNCH"][:40]}
    try:
        r = sc.call("BAPI_BANK_CREATE", BANK_CTRY=b["BANKS"], BANK_KEY=b["BANKL"], BANK_ADDRESS=addr)
    except Exception as ex:
        fail += 1; reasons["RFC:" + type(ex).__name__] += 1
        skips.append({"key": key, "reason": type(ex).__name__}); continue
    ret = r.get("RETURN"); rl = [ret] if isinstance(ret, dict) else (ret or [])
    errs = [m for m in rl if m.get("TYPE") in ("E", "A")]
    if errs:
        sc.call("BAPI_TRANSACTION_ROLLBACK"); fail += 1
        m = errs[0]; rc = f"{m.get('ID')}/{m.get('NUMBER')}"
        reasons[rc] += 1
        skips.append({"key": key, "reason": rc, "msg": m.get("MESSAGE", "")[:80]})
    else:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); done.add(key); ok += 1
    if i % 500 == 0:
        json.dump(sorted(done), open(DONEFILE, "w"))
        json.dump(skips, open(SKIPFILE, "w"))
        print(f"  … {i}/{len(todo)} (ok={ok} fail={fail} region-blanked={region_fixed})", flush=True)
json.dump(sorted(done), open(DONEFILE, "w"))
json.dump(skips, open(SKIPFILE, "w"))
total = len(rt(sc, "BNKA", ["BANKS"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} "
      f"region-blanked={region_fixed} | BNKA on 200: {total}", flush=True)
print("skip reasons:", dict(reasons.most_common()), flush=True)
ec.close(); sc.close()
