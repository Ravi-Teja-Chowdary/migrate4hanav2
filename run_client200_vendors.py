"""
run_client200_vendors — migrate all ECC vendors into empty client 200 as
Business-Partner suppliers (FLVN01) via the OData API_BUSINESS_PARTNER path.
Same proven mechanism as customers. Resumable: persists the vendor key-map.
"""
import os, sys, json, time
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from odata_client import ODataClient
import bp_odata

VENDMAP = os.path.join("local-staging", "c200_vendmap.json")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
oc = ODataClient(s["target_ashost"], s["target_user"], os.environ["M4H_TARGET_PASSWD"],
                 client="200", port=44300)


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


# a valid vendor reconciliation account on the target
recons = rt(sc, "SKB1", ["SAKNR"], "BUKRS = '1710' AND MITKZ = 'K'", 5)
RECON = recons[0]["SAKNR"] if recons else "0021311000"
print(f"vendor recon={RECON}; started {time.strftime('%H:%M:%S')}", flush=True)

vendors = rt(ec, "LFA1", ["LIFNR", "NAME1"], "LIFNR <> ''")
print(f"ECC vendors: {len(vendors)}", flush=True)

km = json.load(open(VENDMAP)) if os.path.exists(VENDMAP) else {}
todo = [v for v in vendors if v["LIFNR"] and v["LIFNR"] not in km]
print(f"to migrate: {len(todo)} (already mapped: {len(km)})", flush=True)

ok = fail = 0
for i, v in enumerate(todo, 1):
    name = v["NAME1"] or f"ECC Vendor {v['LIFNR']}"
    r = bp_odata.create_supplier(oc, name, company_code="1710", recon_account=RECON,
                                 purch_org="1710")
    if r.get("status") == "created":
        km[v["LIFNR"]] = r["supplier"]; ok += 1
    else:
        fail += 1
    if i % 100 == 0:
        json.dump(km, open(VENDMAP, "w"))
        print(f"  … {i}/{len(todo)} (created={ok} failed={fail})", flush=True)
json.dump(km, open(VENDMAP, "w"))

# count supplier BPs on target (LFA1 grows as BPs get the supplier role)
total = len(rt(sc, "LFA1", ["LIFNR"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | suppliers created={ok} failed={fail} "
      f"| LFA1 on client 200 now: {total}", flush=True)
ec.close(); sc.close()
