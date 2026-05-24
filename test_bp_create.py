"""Create a REAL (committed) Business Partner via BAPI and verify it in BUT000 —
proving the MDG/IDoc bottleneck is cracked and the scorecard's BUT000 can move."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection
from bapi_loader import BapiLoader

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
b = BapiLoader(c)

for name in ["Migrate4HANA Customer Alpha", "Migrate4HANA Vendor Beta"]:
    res = b.create_business_partner(name, category="2", commit=True)
    print(f"{name!r}:")
    print(f"  status={res['status']}  partner={res.get('partner')}  verified_in_BUT000={res.get('verified')}")
    if res.get("messages"):
        print(f"  messages: {res['messages']}")
c.close()
