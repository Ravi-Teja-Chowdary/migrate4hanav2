"""
run_client200_costcenters — migrate ECC cost centers (CSKS) into empty client
200 controlling area A000 via BAPI_COSTCENTER_CREATEMULTIPLE. References the
migrated profit centers (falls back to a valid one). Preserves cost-center IDs.
Run AFTER run_client200_profitcenters.py. Resumable.
"""
import os, sys, json, time
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from pyrfc import Connection

CCMAP = os.path.join("local-staging", "c200_ccmap.json")
PCMAP = os.path.join("local-staging", "c200_pcmap.json")
COAREA, HIER_GRP, CCODE, CURR, CAT = "A000", "0001", "1710", "USD", "G"
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
pc_ok = set(json.load(open(PCMAP))) if os.path.exists(PCMAP) else set()
fallback_pc = sorted(pc_ok)[0] if pc_ok else "M4HPC_110"
print(f"migrated profit centers available: {len(pc_ok)} (fallback {fallback_pc})", flush=True)

# distinct ECC cost centers (first occurrence's profit center), + English text
rows = rt(ec, "CSKS", ["KOSTL", "PRCTR"], "KOSTL <> ''")
cc = {}
for r in rows:
    cc.setdefault(r["KOSTL"], r["PRCTR"])
names = {r["KOSTL"]: r["KTEXT"] for r in rt(ec, "CSKT", ["KOSTL", "KTEXT"], "SPRAS = 'E'")}
print(f"ECC distinct cost centers: {len(cc)}", flush=True)

done = set(json.load(open(CCMAP))) if os.path.exists(CCMAP) else set()
todo = [k for k in sorted(cc) if k not in done]
print(f"to create: {len(todo)} (already: {len(done)})", flush=True)

ok = fail = 0
for i, kostl in enumerate(todo, 1):
    prctr = cc[kostl] if cc[kostl] in pc_ok else fallback_pc
    nm = (names.get(kostl) or f"CC {kostl}")[:20]
    row = {"COSTCENTER": kostl, "COSTCENTER_TYPE": CAT, "VALID_FROM": "20200101",
           "VALID_TO": "99991231", "PERSON_IN_CHARGE": "M4H", "COSTCTR_HIER_GRP": HIER_GRP,
           "COMP_CODE": CCODE, "CURRENCY": CURR, "PROFIT_CTR": prctr,
           "NAME": nm, "DESCRIPT": nm}
    r = sc.call("BAPI_COSTCENTER_CREATEMULTIPLE", CONTROLLINGAREA=COAREA, COSTCENTERLIST=[row])
    ret = r.get("RETURN") or []
    if isinstance(ret, dict):
        ret = [ret]
    if any(m.get("TYPE") in ("E", "A") for m in ret):
        sc.call("BAPI_TRANSACTION_ROLLBACK"); fail += 1
    else:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); done.add(kostl); ok += 1
    if i % 100 == 0:
        json.dump(sorted(done), open(CCMAP, "w"))
        print(f"  … {i}/{len(todo)} (ok={ok} fail={fail})", flush=True)
json.dump(sorted(done), open(CCMAP, "w"))
total = len(rt(sc, "CSKS", ["KOSTL"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} | CSKS on 200: {total}", flush=True)
ec.close(); sc.close()
