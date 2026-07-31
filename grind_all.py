"""
grind_all — automate the ENTIRE M02 catalog (all 230 objects) via the staging lane.

For every object in /1LT/DS_MAPPING (object_catalog), infer its ECC source table from
the primary structure, scaffold a recipe against the exact registered staging table,
and run it through migration_engine. Records an honest per-object result:
  staged  = rows written+verified   |  empty = recipe ran, 0 source rows
  no-automap = staging cols didn't map to source  |  no-source/error = source missing
This is the breadth pass: it makes the tool demonstrably handle 100+ objects (a recipe
generated + executed per object); objects with ECC data stage rows, the rest are the
industry objects with no source data on this system.

    py -3.7 grind_all.py            # full catalog
"""
import os, sys, json, traceback
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine
from object_catalog import Catalog
import scaffold_recipe as scf

MT = "M02"
# primary STRUCT_IDENT -> ECC source table (confident set; others fall back to S_-strip)
SRC = {
 "S_MARA": "MARA", "S_MAKT": "MAKT", "S_BNKA": "BNKA", "S_CEPC": "CEPC", "S_CSKS": "CSKS",
 "S_CSLA": "CSLA", "S_AUFK": "AUFK", "S_EINA": "EINA", "S_KLAH": "KLAH", "S_CABN": "CABN",
 "S_TCURR": "TCURR", "S_BSIK": "BSIK", "S_BSID": "BSID", "S_BSIS": "BSIS", "S_BATCH": "MCH1",
 "S_BOM_HEADER": "STKO", "S_EQUI": "EQUI", "S_GENERAL": "SKA1", "S_KEY": "ANLA",
 "S_CUST_GEN": "KNA1", "S_SUPPL_GEN": "LFA1", "S_PVBE": "PVBE", "S_MERCHANDISECAT": "T023",
 "S_CHANGEMASTER": "AENR", "S_EKKO": "EKKO", "S_CONDITIONS": "KONH", "S_QPMK": "QPMK",
 "S_QMTB": "QMTB", "S_VBAK": "VBAK", "S_EORD": "EORD", "S_GROUP": "PLKO",
 "S_WORK_CNTR_HDR": "CRHD", "S_MKAL": "MKAL", "S_QPGR": "QPGR", "S_QINF": "QINF",
 "S_QPAM": "QPAM", "S_QPAC": "QPAC", "S_MPLA": "MPLA", "S_ITEM": "MPOS",
 "S_FUN_LOCATION": "IFLOT", "S_TASKLIST_HDR": "PLKO", "S_PROJECT_DEF": "PROJ",
 "S_NETWORK": "AUFK", "S_CUSTMAT": "KNMT", "S_DOCUMENTDATA": "DRAW", "S_SAG_HEADER": "EKKO",
 "S_SDCO_HEADER": "VBAK", "S_SD_SAG_HEADER": "VBAK", "S_MARITC": "MARC", "S_MARLRG": "MARA",
 "S_MATVAR": "MARA", "S_PKHD": "PKHD", "S_MARC": "MARC", "S_MVKE": "MVKE",
}


def source_for(struct):
    if struct in SRC:
        return SRC[struct]
    return struct[2:] if struct.startswith("S_") else struct   # fallback: strip S_


def main():
    eng = Engine(allow_proposed=True)
    cat = Catalog(eng)
    objs = cat.objects(MT)
    print(f"catalog M02: {len(objs)} objects", flush=True)
    results = []
    for i, obj in enumerate(sorted(objs), 1):
        struct, table = cat.primary(MT, obj)
        src = source_for(struct)
        row = {"object": obj, "struct": struct, "src": src, "table": table}
        try:
            recipe = scf.scaffold(eng, table, src, "master", obj)
            nmap = len(recipe["structures"][0]["map"])
            row["mapped"] = nmap
            if nmap == 0:
                row["result"] = "no-automap"
            else:
                info = eng.run(recipe)[0]
                row["built"] = info["built"]; row["verified"] = info.get("verified_rows")
                row["result"] = "staged" if (info.get("verified_rows") or 0) > 0 else "empty"
        except Exception as ex:
            msg = str(ex)
            row["result"] = "no-source" if ("NOT_FOUND" in msg or "TABLE" in msg.upper()) else "error"
            row["err"] = msg[:80]
        results.append(row)
        print(f"[{i:>3}/{len(objs)}] {row['result']:>10} {obj:<24} src={src:<12} "
              f"map={row.get('mapped','-')} verified={row.get('verified','-')}", flush=True)
    eng.close()
    json.dump(results, open(os.path.join("catalog", "grind_all_results.json"), "w"), indent=1)
    from collections import Counter
    c = Counter(r["result"] for r in results)
    print("\n===== GRIND-ALL SUMMARY =====")
    for k, v in c.most_common():
        print(f"  {k:<12} {v}")
    print(f"  staged+empty (recipe ran) = {c['staged'] + c['empty']}")
    print("wrote catalog/grind_all_results.json")


if __name__ == "__main__":
    main()
