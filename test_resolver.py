"""Prove the MetaRecipeResolver derives VALID values from the target's own config."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection
from meta_recipe import MetaRecipeResolver

t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
r = MetaRecipeResolver(c)

# Required fields the IDoc path needs for a material — resolve each with NO hardcoded values
print("Resolving material required fields from the live system's own config:")
for table, field in [("MARA", "MATKL"), ("MARA", "GEWEI"), ("MARA", "MEINS"),
                     ("MARA", "MTART"), ("MARA", "MBRSH")]:
    res = r.resolve(table, field, source_row={})
    print(f"  {table}-{field:6} -> value={res['value']!r:12} via {res['via']}")

# source-row preference check
print("\nSource-row preference (row already has MEINS):")
res = r.resolve("MARA", "MEINS", source_row={"MEINS": "ST"})
print(f"  MARA-MEINS -> value={res['value']!r} via {res['via']}")
c.close()
