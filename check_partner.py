"""Show what IDoc/ALE config currently exists on S/4 (logical systems + partner profiles)."""
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
pw = os.environ["M4H_TARGET_PASSWD"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=pw, lang="EN")

def read(tbl, fields, where=""):
    opts = [{"TEXT": where}] if where else []
    try:
        r = c.call("RFC_READ_TABLE", QUERY_TABLE=tbl, DELIMITER="|", OPTIONS=opts,
                   FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=100)
        return [[p.strip() for p in row["WA"].split("|")] for row in r.get("DATA", [])]
    except Exception as e:
        return [["<err>", getattr(e, "key", type(e).__name__)]]

print("=== Logical systems defined (TBDLS) containing M4H / SEND / NPL ===")
for row in read("TBDLS", ["LOGSYS"]):
    ls = row[0]
    if any(k in ls.upper() for k in ("M4H", "SEND", "NPL", "ECC", "MIG")):
        print("  ", ls)
print("  (all logical systems count:", len(read("TBDLS", ["LOGSYS"])), ")")

print("\n=== Partner profile partners (EDPP1) ===")
rows = read("EDPP1", ["PARNUM", "PARTYP"])
if rows and rows[0][0] != "<err>":
    for r in rows[:40]:
        print("  PARNUM=%-14s PARTYP=%s" % (r[0], r[1] if len(r) > 1 else ""))
    print("  (total partners:", len(rows), ")")
else:
    print("  EDPP1:", rows)

print("\n=== Inbound parameters (EDP21) ===")
rows = read("EDP21", ["RCVPRN", "RCVPRT", "MESTYP"])
if rows and rows[0][0] != "<err>":
    for r in rows[:40]:
        print("  RCVPRN=%-14s RCVPRT=%s MESTYP=%s" % (r[0], r[1], r[2] if len(r) > 2 else ""))
else:
    print("  EDP21:", rows)
c.close()
