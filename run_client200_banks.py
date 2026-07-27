"""
run_client200_banks — migrate ECC bank master (BNKA) into client 200 via
BAPI_BANK_CREATE. Simple master data: no org/tax dependency. Preserves country
+ bank key. Resumable (persists done set; also skips banks already on 200).
"""
import os, sys, json, time
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from pyrfc import Connection

DONEFILE = os.path.join("local-staging", "c200_bankmap.json")
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

done = set(json.load(open(DONEFILE))) if os.path.exists(DONEFILE) else set()
existing = {f"{b['BANKS']}|{b['BANKL']}" for b in rt(sc, "BNKA", ["BANKS", "BANKL"], "", 0)}
done |= existing
todo = [b for b in banks if f"{b['BANKS']}|{b['BANKL']}" not in done]
print(f"to create: {len(todo)} (already on 200/mapped: {len(done)})", flush=True)

ok = fail = 0
for i, b in enumerate(todo, 1):
    addr = {"BANK_NAME": (b["BANKA"] or "Bank")[:60], "CITY": b["ORT01"][:35],
            "STREET": b["STRAS"][:35], "REGION": b["PROVZ"], "SWIFT_CODE": b["SWIFT"],
            "BANK_BRANCH": b["BRNCH"][:40]}
    try:
        r = sc.call("BAPI_BANK_CREATE", BANK_CTRY=b["BANKS"], BANK_KEY=b["BANKL"], BANK_ADDRESS=addr)
    except Exception:
        fail += 1; continue
    ret = r.get("RETURN"); rl = [ret] if isinstance(ret, dict) else (ret or [])
    if any(m.get("TYPE") in ("E", "A") for m in rl):
        sc.call("BAPI_TRANSACTION_ROLLBACK"); fail += 1
    else:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); done.add(f"{b['BANKS']}|{b['BANKL']}"); ok += 1
    if i % 500 == 0:
        json.dump(sorted(done), open(DONEFILE, "w"))
        print(f"  … {i}/{len(todo)} (ok={ok} fail={fail})", flush=True)
json.dump(sorted(done), open(DONEFILE, "w"))
total = len(rt(sc, "BNKA", ["BANKS"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} | BNKA on 200: {total}", flush=True)
ec.close(); sc.close()
