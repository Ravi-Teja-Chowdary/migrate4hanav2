"""Ask BAPI_MATERIAL_SAVEDATA what a minimal material needs (diagnostic; NOT committed)."""
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection
t = json.loads((ROOT / "connections.json").read_text())["lift_and_shift_target"]
c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"], client=t["target_client"],
               user=t["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

res = c.call("BAPI_MATERIAL_SAVEDATA",
             HEADDATA={"MATERIAL": "M4HPROOF002", "IND_SECTOR": "M",
                       "MATL_TYPE": "HALB", "BASIC_VIEW": "X"},
             CLIENTDATA={"BASE_UOM": "EA", "MATL_GROUP": ""},
             CLIENTDATAX={"BASE_UOM": "X", "MATL_GROUP": ""},
             MATERIALDESCRIPTION=[{"LANGU": "EN", "LANGU_ISO": "EN",
                                   "MATL_DESC": "Migrate4HANA proof material"}])
print("BAPI_MATERIAL_SAVEDATA RETURN:")
ret = res.get("RETURN", {})
ret = ret if isinstance(ret, list) else [ret]
for m in ret:
    print(f"  {m.get('TYPE')} {m.get('ID')}{m.get('NUMBER')}: {m.get('MESSAGE')}")
# do NOT commit — diagnostic only
c.call("BAPI_TRANSACTION_ROLLBACK")
c.close()
