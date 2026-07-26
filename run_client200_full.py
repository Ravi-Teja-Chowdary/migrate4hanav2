"""
run_client200_full — full band-aware order migration into empty client 200.

Migrates all ECC type-C sales orders with number preservation. A sales doc type
has ONE external interval (TA.NUMKE), so we band-cycle: group orders by the
target's RV_BELEG intervals, repoint TA's external range per band (headless via
the kit), and create each order with SALESDOCUMENTIN. Orders whose band interval
is internal are created without preservation (renumbered) so the count is still
complete. Resumable: persists the customer key-map and skips orders already on 200.
"""
import os, sys, json, time
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from odata_client import ODataClient
import bp_odata

CUSTMAP = os.path.join("local-staging", "c200_custmap.json")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
oc = ODataClient(s["target_ashost"], s["target_user"], os.environ["M4H_TARGET_PASSWD"],
                 client="200", port=44300)
print(f"ECC {e['ashost']} -> S/4 200; started {time.strftime('%H:%M:%S')}", flush=True)


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


# ---- source orders + target state ----
orders = rt(ec, "VBAK", ["VBELN", "KUNNR"], "VBTYP = 'C'")
print(f"ECC type-C orders: {len(orders)}", flush=True)
existing = {o["VBELN"] for o in rt(sc, "VBAK", ["VBELN"], "", 0)}
print(f"already on 200 (skip): {len(existing)}", flush=True)

# RV_BELEG intervals (blank subobject) + external flag
ivs = rt(sc, "NRIV", ["NRRANGENR", "FROMNUMBER", "TONUMBER", "EXTERNIND"],
         "OBJECT = 'RV_BELEG' AND SUBOBJECT = ''")
intervals = []
for i in ivs:
    try:
        intervals.append((i["NRRANGENR"], int(i["FROMNUMBER"]), int(i["TONUMBER"]),
                          i["EXTERNIND"] == "X"))
    except (ValueError, KeyError):
        continue  # skip alphanumeric/reference intervals
print("numeric intervals:", [(nr, ext) for nr, lo, hi, ext in intervals], flush=True)

def interval_of(vbeln):
    n = int(vbeln)
    for nr, lo, hi, ext in intervals:
        if lo <= n <= hi:
            return nr, ext
    return None, False


# ---- customers (resumable key-map) ----
km = json.load(open(CUSTMAP)) if os.path.exists(CUSTMAP) else {}
todo = sorted({o["KUNNR"] for o in orders if o["KUNNR"] and o["KUNNR"] not in km})
print(f"customers to migrate: {len(todo)} (already mapped: {len(km)})", flush=True)
for i, kunnr in enumerate(todo, 1):
    nm = rt(ec, "KNA1", ["NAME1"], f"KUNNR = '{kunnr}'", 1)
    name = (nm[0]["NAME1"] if nm else "") or f"ECC Customer {kunnr}"
    r = bp_odata.create_customer(oc, name, company_code="1710", recon_account="0012104000",
                                 sales_org="1710", distr_chan="10", division="00")
    if r.get("status") == "created":
        km[kunnr] = r["customer"]
    if i % 50 == 0:
        json.dump(km, open(CUSTMAP, "w")); print(f"  customers {i}/{len(todo)}", flush=True)
json.dump(km, open(CUSTMAP, "w"))
print(f"customers mapped: {len(km)}", flush=True)


# ---- orders grouped by interval, external bands first ----
groups = {}
for o in orders:
    if o["VBELN"] in existing:
        continue
    nr, ext = interval_of(o["VBELN"])
    groups.setdefault((nr, ext), []).append(o)

created = preserved = renum = skipped = 0
# external bands first (so preservation happens), internal last (renumber)
for (nr, ext) in sorted(groups, key=lambda k: (not k[1], k[0] or "zz")):
    grp = groups[(nr, ext)]
    if ext and nr:
        sc.call("Z_M4H_TABLE_UPDATE", IV_TABLE="TVAK", IT_KEY_VALUES=[{"LINE": "TA"}],
                IV_FLAG_FIELD="NUMKE", IV_FLAG_VALUE=nr)
        try: sc.call("IUUC_RESET_NUMBER_RANGE_BUFFER")
        except Exception: pass
    print(f"band interval={nr} external={ext}: {len(grp)} orders", flush=True)
    for j, o in enumerate(grp, 1):
        bp = km.get(o["KUNNR"])
        if not bp:
            skipped += 1; continue
        hdr = {"DOC_TYPE": "TA", "SALES_ORG": "1710", "DISTR_CHAN": "10", "DIVISION": "00"}
        parts = [{"PARTN_ROLE": "AG", "PARTN_NUMB": bp.zfill(10)}]
        kw = dict(ORDER_HEADER_IN=hdr, ORDER_PARTNERS=parts)
        if ext:
            kw["SALESDOCUMENTIN"] = o["VBELN"]
        try:
            r = sc.call("BAPI_SALESORDER_CREATEFROMDAT2", **kw)
        except Exception:
            skipped += 1; continue
        tgt = (r.get("SALESDOCUMENT") or "").strip()
        if tgt:
            sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
            created += 1
            if tgt.lstrip("0") == o["VBELN"].lstrip("0"):
                preserved += 1
            else:
                renum += 1
        else:
            sc.call("BAPI_TRANSACTION_ROLLBACK"); skipped += 1
        if j % 500 == 0:
            print(f"  … {j}/{len(grp)} (created={created} preserved={preserved})", flush=True)

total = len(rt(sc, "VBAK", ["VBELN"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={created} preserved={preserved} "
      f"renumbered={renum} skipped={skipped}", flush=True)
print(f"VBAK on client 200 now: {total}", flush=True)
ec.close(); sc.close()
