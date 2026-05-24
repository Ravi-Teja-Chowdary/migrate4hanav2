"""
Probe Business Partner creation via BAPI (sidestepping the DEBMAS/MDG IDoc wall).
Reads valid BP groupings, then attempts BAPI_BUPA_CREATE_FROM_DATA for a minimal
organization BP. Reads RETURN (BAPIs give clean errors). Rolls back (discovery).
"""
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


def read(tbl, fields, where="", n=10):
    try:
        r = c.call("RFC_READ_TABLE", QUERY_TABLE=tbl, DELIMITER="|",
                   OPTIONS=[{"TEXT": where}] if where else [],
                   FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=n)
        return [[p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])]
    except Exception as e:
        return [["<err>", getattr(e, "key", type(e).__name__)]]


print("=== BP groupings (TB001 / number-range groupings) ===")
for tbl in ("TB001", "TBD001"):
    rows = read(tbl, ["GROUP", "TXTMI"]) if tbl == "TB001" else read(tbl, ["GROUP"])
    print(f"  {tbl}: {rows[:8]}")

print("\n=== attempt BAPI_BUPA_CREATE_FROM_DATA (org BP) ===")
for grp in ["", "0001", "BP01", "0003"]:
    try:
        kwargs = dict(PARTNERCATEGORY="2",
                      CENTRALDATAORGANIZATION={"NAME1": "Migrate4HANA Test BP"},
                      CENTRALDATA={"PARTNERLANGUAGE": "E"})
        if grp:
            kwargs["PARTNERGROUP"] = grp
        res = c.call("BAPI_BUPA_CREATE_FROM_DATA", **kwargs)
        bp = res.get("BUSINESSPARTNER", "")
        ret = res.get("RETURN", [])
        ret = ret if isinstance(ret, list) else [ret]
        errs = [m for m in ret if m.get("TYPE") in ("E", "A")]
        print(f"  grouping={grp or '(blank)'}: BP={bp or '-'}  "
              f"{'OK' if not errs else 'ERR'}")
        for m in ret[:4]:
            print(f"      {m.get('TYPE')} {m.get('ID')}{m.get('NUMBER')}: {m.get('MESSAGE')}")
        c.call("BAPI_TRANSACTION_ROLLBACK")
        if bp and not errs:
            print(f"  >>> grouping {grp or '(blank)'} WORKS (rolled back).")
            break
    except Exception as e:
        print(f"  grouping={grp or '(blank)'}: EXCEPTION {getattr(e,'key',type(e).__name__)}: {str(e)[:120]}")
c.close()
