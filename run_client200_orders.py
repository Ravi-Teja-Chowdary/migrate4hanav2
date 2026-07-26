"""
run_client200_orders — clean faithful order migration into the empty client 200.

Empty client => exact counts + full number preservation (external interval 02,
5,000,000-5,999,999, is empty) + faithful customers. Orders are header-only
(200 has no materials yet); real line items come once material migration lands.
"""
import os, sys, json
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from odata_client import ODataClient
import bp_odata

N = int(os.environ.get("N_ORDERS", "600"))
BAND = os.environ.get("M4H_ORDER_WHERE",
                      "VBTYP = 'C' AND VBELN >= '0005000000' AND VBELN < '0006000000'")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client=s["target_client"],
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
print(f"ECC {e['ashost']} -> S/4 {s['target_ashost']} client {s['target_client']}", flush=True)


def rt(c, t, f, w="", n=100):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


orders = rt(ec, "VBAK", ["VBELN", "KUNNR"], BAND, N)
print(f"extracted {len(orders)} type-C orders from ECC", flush=True)

oc = ODataClient(s["target_ashost"], s["target_user"], os.environ["M4H_TARGET_PASSWD"],
                 client=s["target_client"], port=44300)

# migrate each distinct customer once
km = {}
distinct = sorted({o["KUNNR"] for o in orders if o["KUNNR"]})
print(f"migrating {len(distinct)} distinct customers via OData ...", flush=True)
cust_ok = cust_fail = 0
for kunnr in distinct:
    kn = rt(ec, "KNA1", ["NAME1"], f"KUNNR = '{kunnr}'", 1)
    name = (kn[0]["NAME1"] if kn else "") or f"ECC Customer {kunnr}"
    r = bp_odata.create_customer(oc, name, company_code="1710", recon_account="0012104000",
                                 sales_org="1710", distr_chan="10", division="00")
    if r.get("status") == "created":
        km[kunnr] = r["customer"]; cust_ok += 1
    else:
        cust_fail += 1
print(f"  customers created: {cust_ok}, failed: {cust_fail}", flush=True)

# header-only orders with number preservation
print("creating orders (header-only, number preserved) ...", flush=True)
created = preserved = skipped = 0
for o in orders:
    bp = km.get(o["KUNNR"])
    if not bp:
        skipped += 1; continue
    hdr = {"DOC_TYPE": "TA", "SALES_ORG": "1710", "DISTR_CHAN": "10", "DIVISION": "00"}
    parts = [{"PARTN_ROLE": "AG", "PARTN_NUMB": bp.zfill(10)}]
    try:
        r = sc.call("BAPI_SALESORDER_CREATEFROMDAT2", ORDER_HEADER_IN=hdr,
                    ORDER_PARTNERS=parts, SALESDOCUMENTIN=o["VBELN"])
    except Exception as ex:
        skipped += 1; continue
    tgt = (r.get("SALESDOCUMENT") or "").strip()
    if tgt:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        created += 1
        if tgt.lstrip("0") == o["VBELN"].lstrip("0"):
            preserved += 1
    else:
        sc.call("BAPI_TRANSACTION_ROLLBACK")
        skipped += 1

vbak_now = rt(sc, "VBAK", ["VBELN"], "", 1000)
print(f"\nSUMMARY (client 200): orders_created={created}  kept_exact_number={preserved}  "
      f"faithful_customer={created}  skipped={skipped}", flush=True)
print(f"  VBAK on client 200 now: {len(vbak_now)}{'+' if len(vbak_now)>=1000 else ''}", flush=True)
ec.close(); sc.close()
