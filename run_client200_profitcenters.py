"""
run_client200_profitcenters — migrate ECC profit centers (CEPC) into empty
client 200 controlling area A000 via BAPI_PROFITCENTER_CREATE. Preserves the
profit-center IDs; harmonises the hierarchy node to an existing target group.
Resumable (persists the PC key set).
"""
import os, sys, json, time
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from pyrfc import Connection

PCMAP = os.path.join("local-staging", "c200_pcmap.json")
COAREA, HIER_GRP, CCODE = "A000", "YBH110", "1710"
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
# distinct ECC profit centers + their English short text
pcs = sorted({r["PRCTR"] for r in rt(ec, "CEPC", ["PRCTR"], "PRCTR <> ''") if r["PRCTR"]})
names = {}
for r in rt(ec, "CEPCT", ["PRCTR", "KTEXT"], "SPRAS = 'E'"):
    names[r["PRCTR"]] = r["KTEXT"]
print(f"ECC distinct profit centers: {len(pcs)}", flush=True)

done = set(json.load(open(PCMAP))) if os.path.exists(PCMAP) else set()
todo = [p for p in pcs if p not in done]
print(f"to create: {len(todo)} (already: {len(done)})", flush=True)

ok = fail = 0
for i, p in enumerate(todo, 1):
    nm = (names.get(p) or f"PC {p}")[:40]
    r = sc.call("BAPI_PROFITCENTER_CREATE",
                PROFITCENTERID={"CO_AREA": COAREA, "PROFIT_CTR": p},
                BASICDATA={"PRCTR_NAME": nm, "LONG_TEXT": nm, "IN_CHARGE": "M4H",
                           "PRCTR_HIER_GRP": HIER_GRP},
                VALIDFROM="20200101", VALIDTO="99991231",
                COMPANYCODES=[{"COMP_CODE": CCODE, "ASSIGN_TO_PRCTR": "X"}])
    ret = r.get("RETURN"); rl = [ret] if isinstance(ret, dict) else (ret or [])
    if any(m.get("TYPE") in ("E", "A") for m in rl):
        sc.call("BAPI_TRANSACTION_ROLLBACK"); fail += 1
    else:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); done.add(p); ok += 1
    if i % 100 == 0:
        json.dump(sorted(done), open(PCMAP, "w"))
        print(f"  … {i}/{len(todo)} (ok={ok} fail={fail})", flush=True)
json.dump(sorted(done), open(PCMAP, "w"))
total = len(rt(sc, "CEPC", ["PRCTR"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} | CEPC on 200: {total}", flush=True)
ec.close(); sc.close()
