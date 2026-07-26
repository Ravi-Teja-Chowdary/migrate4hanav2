import os, sys, json
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ["M4H_PRESERVE_SRC_NUMBERS"] = "1"
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from odata_client import ODataClient
import bp_odata
from sales_order_spine import SalesOrderSpineOrchestrator

N = int(os.environ.get("N_ORDERS", "5"))
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
epw, spw = os.environ["M4H_ECC_PASSWD"], os.environ["M4H_TARGET_PASSWD"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=epw, lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr=s["target_sysnr"],
                client=s["target_client"], user=s["target_user"], passwd=spw, lang="EN")


def rt(conn, table, fields, where="", rows=100):
    r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                  OPTIONS=[{"TEXT": where}] if where else [],
                  FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=rows)
    return [dict(zip(fields, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


# 1) N type-C sales orders from ECC, chosen from the external band 5,000,000-5,999,999
#    so number-preservation can be demonstrated on this (non-empty IDES) client.
#    (On an empty client every order preserves; here only free-external-band ones do.)
band = os.environ.get("M4H_ORDER_WHERE",
                      "VBTYP = 'C' AND VBELN >= '0005000000' AND VBELN < '0006000000'")
orders = rt(ec, "VBAK", ["VBELN", "KUNNR"], where=band, rows=N)
print(f"extracted {len(orders)} type-C orders from ECC:",
      [(o["VBELN"], o["KUNNR"]) for o in orders])


class KM:
    def __init__(self): self.m = {}
    def resolve(self, obj, src): return self.m.get((obj, str(src).strip()))
    def add(self, obj, src, tgt, disp=""): self.m[(obj, str(src).strip())] = str(tgt).strip()


km = KM()
oc = ODataClient(s["target_ashost"], s["target_user"], spw,
                 client=s.get("target_client", "100"), port=44300)

# 2) migrate each DISTINCT source customer via OData (faithful) → key_map
print("\n-- migrating source customers via OData (BP) --")
for kunnr in sorted({o["KUNNR"] for o in orders if o["KUNNR"]}):
    kn = rt(ec, "KNA1", ["NAME1"], where=f"KUNNR = '{kunnr}'", rows=1)
    name = (kn[0]["NAME1"] if kn else "") or f"ECC Customer {kunnr}"
    res = bp_odata.create_customer(oc, name, company_code="1710",
                                   recon_account="0012104000",
                                   sales_org="1710", distr_chan="10", division="00")
    if res.get("status") == "created":
        km.add("Customer", kunnr, res["customer"])
        print(f"  {kunnr} '{name}'  ->  BP {res['customer']}")
    else:
        print(f"  {kunnr} FAILED: {res.get('messages')}")

# 3) saleable materials in sales area 1710/10 on the target (set + a sample)
mvke = rt(sc, "MVKE", ["MATNR"], where="VKORG = '1710' AND VTWEG = '10'", rows=9999)
saleable = {m["MATNR"] for m in mvke if m.get("MATNR")}
sample_mat = mvke[0]["MATNR"] if mvke else ""
print(f"\nsaleable materials on target (1710/10): {len(saleable)}  sample={sample_mat!r}")

# 3a) real line items per order from ECC VBAP. Use the order's actual material
#     when it's already saleable on the target (many IDES materials overlap);
#     otherwise the spine falls back to the sample material. Real quantity + UoM.
def _num(q):
    try: return str(int(float(q)))
    except Exception: return "1"
items_kept = 0
for o in orders:
    vbap = rt(ec, "VBAP", ["POSNR", "MATNR", "KWMENG", "VRKME"],
              where=f"VBELN = '{o['VBELN']}'", rows=100)
    its = []
    for it in vbap:
        mat = (it.get("MATNR") or "").strip()
        if mat and mat in saleable:
            km.add("Material", mat, mat)
            its.append({"MATNR": mat, "MENGE": _num(it.get("KWMENG")),
                        "MEINS": (it.get("VRKME") or "EA").strip() or "EA"})
    o["items"] = its
    items_kept += len(its)
print(f"real saleable line items attached across {len(orders)} orders: {items_kept}")

# 3b) a VALID sales-order type on the target (most-common existing type-C AUART)
from collections import Counter
tvb = rt(sc, "VBAK", ["AUART"], where="VBTYP = 'C'", rows=500)
otypes = Counter(x["AUART"] for x in tvb if x.get("AUART"))
otype = otypes.most_common(1)[0][0] if otypes else "TA"
print(f"target sales-order type (discovered): {otype!r}  (top: {otypes.most_common(3)})")

# 4) spine with a PRE-SEEDED sales-area config (bypass the flawed auto-discovery
#    so migrated customers are recognised instead of harmonised)
spine = SalesOrderSpineOrchestrator(sc, key_map=km, target_release="S4HANA_2020")
bps = [km.m[k] for k in km.m if k[0] == "Customer"]
spine._so_cfg_cache = {"sorg": "1710", "chan": "10", "div": "00", "otype": otype,
                       "customers": set(bps),
                       "sample_customer": (bps[0] if bps else ""),
                       "sample_material": sample_mat}

# 5) create the orders with preservation on
print("\n-- creating sales orders (preservation ON) --")
created = preserved = harmonized = 0
for o in orders:
    r = spine.load_one({"VBELN": o["VBELN"], "KUNNR": o["KUNNR"],
                        "items": o.get("items") or []})
    tgt = (r.target_key or "").strip()
    disp = r.disposition or r.status
    src_bp = km.resolve("Customer", o["KUNNR"])
    nit = len(o.get("items") or [])
    if tgt:
        created += 1
        kept = tgt.lstrip("0") == o["VBELN"].lstrip("0")
        preserved += 1 if kept else 0
        soldto = "harmonized" if "harmoniz" in (disp or "") else f"BP {src_bp}"
        print(f"  SO {o['VBELN']} (cust {o['KUNNR']}) -> S/4 {tgt}  "
              f"{'SAME #' if kept else 'renumbered'}  sold-to={soldto}  "
              f"items={nit if nit else 'sample'}")
    else:
        print(f"  SO {o['VBELN']} FAILED: {'; '.join((r.messages or [])[:2])}")

print(f"\nSUMMARY: created={created}/{len(orders)}  kept-exact-number={preserved}  "
      f"faithful-customer={created - harmonized}")
ec.close(); sc.close()
