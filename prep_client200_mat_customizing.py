"""
prep_client200_mat_customizing — replicate the material-master customizing that
the S/4 target (client 200) is missing versus the ECC source, so the material
Basic view can carry the real base unit of measure and material group:

  * T006 / T006A  — units of measure (+ language texts / ISO codes)
  * T023 / T023T  — material groups (+ descriptions)

All four are delivery-class C (customizing) and pushed via the Basis Kit
Z_M4HTABLE_UPSERT (same technique used for TSTL/TSKM). Idempotent.
"""
import os, sys, json
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from basis_kit_installer import push_rows_via_kit

cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


def real_fields(c, tab):
    r = c.call("DDIF_FIELDINFO_GET", TABNAME=tab)
    return [f["FIELDNAME"] for f in r.get("DFIES_TAB", [])
            if not f["FIELDNAME"].startswith(".") and f["FIELDNAME"] != "MANDT"]


def rows(c, tab, fields, where=""):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=tab, DELIMITER="|",
               OPTIONS=([{"TEXT": where}] if where else []),
               FIELDS=[{"FIELDNAME": x} for x in fields], ROWCOUNT=0)
    return [dict(zip(fields, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


def push_missing(tab, keyfields, textfilter=""):
    """Push ECC rows whose key isn't present on the target. keyfields = the
    subset that identifies 'missing' (e.g. MSEHI for T006, MATKL for T023)."""
    fields = real_fields(ec, tab)
    ecc = rows(ec, tab, fields, textfilter)
    tgt = rows(sc, tab, fields, textfilter)
    tgt_keys = {tuple(r[k] for k in keyfields) for r in tgt}
    missing = [r for r in ecc if tuple(r[k] for k in keyfields) not in tgt_keys]
    print(f"{tab}: ecc={len(ecc)} target={len(tgt)} missing={len(missing)}", flush=True)
    if not missing:
        return
    res = push_rows_via_kit(sc, tab, fields, missing)
    print(f"  pushed {tab}: upserted={res.get('upserted')} failed={res.get('failed')}", flush=True)


# units first (T006 keyed by MSEHI); texts only for EN to keep it lean
push_missing("T006", ["MSEHI"])
push_missing("T006A", ["SPRAS", "MSEHI"], "SPRAS = 'E'")
# material groups
push_missing("T023", ["MATKL"])
push_missing("T023T", ["SPRAS", "MATKL"], "SPRAS = 'E'")

ec.close(); sc.close()
print("customizing replication done", flush=True)
