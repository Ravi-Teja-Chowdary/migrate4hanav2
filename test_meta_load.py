"""P2.4 proof: load a material from JUST a material number — the meta-resolver
derives every required field automatically, then it posts to status 53."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection
from idoc_loader import IDocLoader
from meta_recipe import MetaRecipeResolver

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

ldr = IDocLoader(c, own_logical_system="S4HCLNT100", sender="M4HSENDER",
                 client=t["target_client"], target_sid=t["target_sid"])
resolver = MetaRecipeResolver(c)

# Only the key is provided — everything else is auto-resolved.
source_row = {"MATNR": "M4HMETA001"}
res = ldr.post_resolved("Material", source_row, resolver)

print("=== meta-resolved field sources ===")
for field, via in res.get("resolution", {}).items():
    print(f"  {field:18} <- {via}")
print(f"\nDOCNUM={res.get('docnum')}  STATUS={res.get('status')}  created={res.get('created')}")
c.close()
