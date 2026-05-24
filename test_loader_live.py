"""Live test of the reusable IDocLoader: post a couple of materials, show status."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection
from idoc_loader import IDocLoader

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

ldr = IDocLoader(c, own_logical_system="S4HCLNT100", sender="M4HSENDER",
                 client=t["target_client"], target_sid=t["target_sid"])

rows = [
    {"MATNR": "M4HLOAD001", "MAKTX": "Loader test material one"},
    {"MATNR": "M4HLOAD002", "MAKTX": "Loader test material two", "MTART": "HALB", "MEINS": "EA"},
]
for row in rows:
    res = ldr.post("Material", row)
    print(f"\n{row['MATNR']}:")
    print(f"  DOCNUM={res.get('docnum')}  STATUS={res.get('status')}  created={res.get('created')}")
    if res.get("missing_fields"):
        print(f"  missing required fields: {res['missing_fields']}")
    for m in res.get("messages", [])[:6]:
        print(f"  msg: {m}")
c.close()
