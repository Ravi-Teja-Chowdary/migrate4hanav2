#!/usr/bin/env python
"""
idoc_post_material.py — post a *properly structured* MATMAS05 IDoc so S/4 creates
a real material (target status 53), proving the end-to-end data write.

Builds the E1MARAM (material header) + E1MAKTM (description) segments using the
ACTUAL field layout read from DD03L, so values land at the correct offsets.
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
PW = os.environ["M4H_TARGET_PASSWD"]
CLIENT = t["target_client"]
OWN_LS = "S4HCLNT100"
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=CLIENT,
               user=t["target_user"], passwd=PW, lang="EN")


def layout(seg):
    """Ordered (position, field, length) for an IDoc segment from DD03L."""
    r = c.call("RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
               OPTIONS=[{"TEXT": f"TABNAME = '{seg}'"}],
               FIELDS=[{"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "POSITION"},
                       {"FIELDNAME": "LENG"}], ROWCOUNT=999)
    rows = []
    for d in r.get("DATA", []):
        fn, pos, leng = [p.strip() for p in d["WA"].split("|")]
        if fn and not fn.startswith("."):
            rows.append((int(pos), fn, int(leng)))
    rows.sort()
    return rows


def build(seg, values):
    """Build the flat SDATA string for a segment, placing values by field name."""
    lay = layout(seg)
    out = []
    for _pos, fn, leng in lay:
        out.append(str(values.get(fn, "")).ljust(leng)[:leng])
    return "".join(out), lay


MATNR = "M4HPROOF011"

# pull a real material group from T023 so MATKL is valid
_mg = c.call("RFC_READ_TABLE", QUERY_TABLE="T023", DELIMITER="|",
             FIELDS=[{"FIELDNAME": "MATKL"}], ROWCOUNT=1)
MATKL = (_mg.get("DATA") or [{"WA": "001"}])[0]["WA"].split("|")[0].strip() or "001"
print("using material group MATKL =", MATKL)

# PSTAT='K' = maintain Basic Data view; MATKL + GEWEI are required by field status
e1maram_vals = {"MSGFN": "005", "MATNR": MATNR, "MTART": "HALB", "MBRSH": "M",
                "MEINS": "EA", "PSTAT": "K", "MATKL": MATKL, "GEWEI": "KG"}
e1maktm_vals = {"MSGFN": "005", "SPRAS": "E", "SPRAS_ISO": "EN", "MAKTX": "Migrate4HANA write-proof material"}

maram_sdata, maram_lay = build("E1MARAM", e1maram_vals)
maktm_sdata, maktm_lay = build("E1MAKTM", e1maktm_vals)
print("E1MARAM fields:", [f for _p, f, _l in maram_lay][:12], "...")
print("E1MAKTM fields:", [f for _p, f, _l in maktm_lay][:12])

now = datetime.now()
control = [{
    "TABNAM": "EDI_DC40", "MANDT": CLIENT, "DIRECT": "2",
    "IDOCTYP": "MATMAS05", "MESTYP": "MATMAS",
    "SNDPOR": "SAPM4H", "SNDPRT": "LS", "SNDPRN": "M4HSENDER",
    "RCVPOR": f"SAP{t['target_sid']}", "RCVPRT": "LS", "RCVPRN": OWN_LS,
    "CREDAT": now.strftime("%Y%m%d"), "CRETIM": now.strftime("%H%M%S"),
}]
data = [
    {"SEGNAM": "E1MARAM", "MANDT": CLIENT, "SEGNUM": "000001", "PSGNUM": "000000",
     "HLEVEL": "01", "SDATA": maram_sdata.ljust(1000)},
    {"SEGNAM": "E1MAKTM", "MANDT": CLIENT, "SEGNUM": "000002", "PSGNUM": "000001",
     "HLEVEL": "02", "SDATA": maktm_sdata.ljust(1000)},
]

print(f"\nposting MATMAS05 IDoc for material {MATNR} ...")
c.call("IDOC_INBOUND_ASYNCHRONOUS", IDOC_CONTROL_REC_40=control, IDOC_DATA_REC_40=data)
try:
    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
except Exception:
    pass
time.sleep(3)

# read back newest MATMAS IDoc status + any status text
r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDC", DELIMITER="|",
           OPTIONS=[{"TEXT": "DIRECT = '2' AND MESTYP = 'MATMAS'"}],
           FIELDS=[{"FIELDNAME": "DOCNUM"}, {"FIELDNAME": "STATUS"},
                   {"FIELDNAME": "CRETIM"}], ROWCOUNT=10)
rows = sorted([[p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])],
              key=lambda x: x[2])
newest = rows[-1] if rows else None
print("newest MATMAS IDoc:", newest)
if newest:
    docnum = newest[0]
    st = c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDS", DELIMITER="|",
                OPTIONS=[{"TEXT": f"DOCNUM = '{docnum}'"}],
                FIELDS=[{"FIELDNAME": "STATUS"}, {"FIELDNAME": "STATXT"}], ROWCOUNT=20)
    print("status messages:")
    for d in st.get("DATA", []):
        v = [p.strip() for p in d["WA"].split("|")]
        print("   ", v)

# check if the material now exists in MARA
mara = c.call("RFC_READ_TABLE", QUERY_TABLE="MARA", DELIMITER="|",
              OPTIONS=[{"TEXT": f"MATNR LIKE '%{MATNR}%'"}],
              FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "MTART"}], ROWCOUNT=5)
print("\nMARA lookup for", MATNR, ":", [[p.strip() for p in d["WA"].split("|")] for d in mara.get("DATA", [])] or "NOT FOUND yet")
c.close()
