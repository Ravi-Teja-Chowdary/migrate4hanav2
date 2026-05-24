"""
De-risk P2.1: can we read the SPECIFIC field-required errors of a status-51
IDoc over RFC (not just the generic MK101 wrapper)?

Tries, in order, for the newest status-51 MATMAS IDoc:
  A. BAPI_IDOC_INPUT1 / re-read EDIDS with all message records
  B. Application log via APPL_LOG_READ_DB (classic) keyed by the IDoc
  C. BAL_* modern app-log read

Prints whatever specific messages it can surface.
"""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

# newest MATMAS IDoc that is NOT 53 (an error one), else newest overall
r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDC", DELIMITER="|",
           OPTIONS=[{"TEXT": "DIRECT = '2' AND MESTYP = 'MATMAS'"}],
           FIELDS=[{"FIELDNAME": "DOCNUM"}, {"FIELDNAME": "STATUS"}, {"FIELDNAME": "CRETIM"}],
           ROWCOUNT=300)
rows = sorted([[p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])], key=lambda x: x[2])
err = [x for x in rows if x[1] != "53"]
docnum = (err[-1] if err else rows[-1])[0]
print("probing IDoc DOCNUM:", docnum, "status:", (err[-1] if err else rows[-1])[1])

print("\n--- A) ALL EDIDS message records ---")
r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDS", DELIMITER="|",
           OPTIONS=[{"TEXT": f"DOCNUM = '{docnum}'"}],
           FIELDS=[{"FIELDNAME": "STATUS"}, {"FIELDNAME": "STAMID"}, {"FIELDNAME": "STAMNO"},
                   {"FIELDNAME": "STAPA1"}, {"FIELDNAME": "STAPA2"}, {"FIELDNAME": "STAPA3"},
                   {"FIELDNAME": "STAPA4"}, {"FIELDNAME": "APPL_LOG"}], ROWCOUNT=50)
applog_handles = set()
for d in r.get("DATA", []):
    v = [p.strip() for p in d["WA"].split("|")]
    print("  ", v)
    if len(v) >= 8 and v[7]:
        applog_handles.add(v[7])

print("\n--- B) APPL_LOG_READ_DB by log handle(s):", applog_handles or "(none in EDIDS)")
for handle in applog_handles:
    try:
        res = c.call("APPL_LOG_READ_DB", EXTERNAL_NUMBER=handle)
        msgs = res.get("MESSAGES", [])
        print(f"  handle {handle}: {len(msgs)} messages")
        for m in msgs[:20]:
            print("    ", m.get("MSGID"), m.get("MSGNO"), m.get("MSGV1"), m.get("MSGV2"))
    except Exception as e:
        print(f"  APPL_LOG_READ_DB failed: {type(e).__name__}: {str(e)[:120]}")

# C) try BAL search by object for IDoc
print("\n--- C) APPL_LOG_READ_DB by OBJECT=IDOC ---")
try:
    res = c.call("APPL_LOG_READ_DB", OBJECT="IDOC", EXTERNAL_NUMBER=docnum)
    for m in res.get("MESSAGES", [])[:20]:
        print("    ", m.get("MSGID"), m.get("MSGNO"), m.get("MSGV1"), m.get("MSGV2"))
except Exception as e:
    print(f"  failed: {type(e).__name__}: {str(e)[:120]}")
c.close()
