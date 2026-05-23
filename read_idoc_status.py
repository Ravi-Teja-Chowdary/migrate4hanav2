"""Read the full application error messages for the newest inbound MATMAS IDoc."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

docnum = sys.argv[1] if len(sys.argv) > 1 else None
if not docnum:
    r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDC", DELIMITER="|",
               OPTIONS=[{"TEXT": "DIRECT = '2' AND MESTYP = 'MATMAS'"}],
               FIELDS=[{"FIELDNAME": "DOCNUM"}, {"FIELDNAME": "CRETIM"}], ROWCOUNT=20)
    rows = sorted([[p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])], key=lambda x: x[1])
    docnum = rows[-1][0]
print("IDoc DOCNUM:", docnum)

r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDS", DELIMITER="|",
           OPTIONS=[{"TEXT": f"DOCNUM = '{docnum}'"}],
           FIELDS=[{"FIELDNAME": "STATUS"}, {"FIELDNAME": "STAMID"}, {"FIELDNAME": "STAMNO"},
                   {"FIELDNAME": "STAPA1"}, {"FIELDNAME": "STAPA2"}, {"FIELDNAME": "STAPA3"},
                   {"FIELDNAME": "STAPA4"}, {"FIELDNAME": "STATXT"}], ROWCOUNT=50)
print("status records (STATUS | msg-class msg-no | vars | text):")
for d in r.get("DATA", []):
    v = [p.strip() for p in d["WA"].split("|")]
    status, mid, mno = v[0], v[1], v[2]
    vars_ = "/".join(x for x in v[3:7] if x)
    txt = v[7] if len(v) > 7 else ""
    # resolve the real message text from T100 if we have class+number
    real = ""
    if mid and mno:
        try:
            mt = c.call("RFC_READ_TABLE", QUERY_TABLE="T100", DELIMITER="|",
                        OPTIONS=[{"TEXT": f"SPRSL = 'E' AND ARBGB = '{mid}' AND MSGNR = '{mno}'"}],
                        FIELDS=[{"FIELDNAME": "TEXT"}], ROWCOUNT=1)
            if mt.get("DATA"):
                real = mt["DATA"][0]["WA"].split("|")[0].strip()
        except Exception:
            pass
    print(f"  {status}  {mid}{mno}  vars=[{vars_}]  {real or txt}")
c.close()
