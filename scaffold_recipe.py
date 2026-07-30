"""
scaffold_recipe — auto-generate a recipe skeleton for migration_engine.

Writing recipes for 100+ objects by hand is the slow part. This reads an MC
staging table's columns (from HANA) and a candidate ECC source table's fields
(from DDIC), auto-maps columns that share a name (or a known alias), tags org-unit
columns with the right org_mapper dimension, and prints a ready-to-refine recipe
JSON. The human then fills the few TODO gaps and runs it through the engine.

    py -3.7 scaffold_recipe.py <staging_table> <source_table> [--id X] [--object Y]
e.g. py -3.7 scaffold_recipe.py /1LT/DSS4H000012 MAKT --id text --object ProductText

It does NOT guess business logic — unmapped staging columns are listed under
"_unmapped_staging_columns" so nothing is silently dropped.
"""
import os, sys, json, argparse
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine

# staging column -> org_mapper dimension
ORG_DIMS = {"VKORG": "sales_org", "VTWEG": "distribution_channel",
            "WERKS": "plant", "DWERK": "plant", "SPART": "division"}
# common staging<->source name aliases (MC frequently renames keys semantically)
ALIASES = {"PRODUCT": "MATNR", "MATERIAL": "MATNR",
           "RATE_TYPE": "KURST", "FROM_CURR": "FCURR", "TO_CURRNCY": "TCURR",
           "MERCHANDISECATEGORY": "MATKL",
           # controlling / CO
           "CO_AREA": "KOKRS", "CO_BUSPROC": "PRZNR",
           # document management (DRAW keys)
           "DOCUMENTTYPE": "DOKAR", "DOCUMENTNUMBER": "DOKNR",
           "DOCUMENTPART": "DOKTL", "DOCUMENTVERSION": "DOKVR"}
# columns whose values are material-like numbers → strip leading zeros
LSTRIP = {"PRODUCT", "MATERIAL", "MATNR", "MATERIALBYCUSTOMER"}
SKIP = ("MANDT",)  # never map; kit forces client


def ddic_fields(eng, table):
    """Real DB column names of `table` from DD03L on the SOURCE (ECC), so we never
    map a staging column onto a DDIC field RFC_READ_TABLE can't read (FIELD_NOT_VALID).
    Drop '.INCLUDE'/'.APPEND' markers (they start with '.')."""
    rows = eng.read_table(eng.ecc, "DD03L", ["FIELDNAME"], "TABNAME = '%s'" % table)
    return {r["FIELDNAME"].strip() for r in rows
            if r.get("FIELDNAME", "").strip() and not r["FIELDNAME"].startswith(".")}


def scaffold(eng, staging_table, source_table, sid, obj):
    scols = [c["column"] for c in eng.hs.describe_staging(staging_table)
             if not c["column"].startswith(SKIP) and not c["column"].startswith("/1LT/")]
    sfields = ddic_fields(eng, source_table)
    mapping, unmapped, used = [], [], []
    for col in scols:
        src = col if col in sfields else ALIASES.get(col) if ALIASES.get(col) in sfields else None
        if not src:
            unmapped.append(col); continue
        used.append(src)
        if col in ORG_DIMS:
            mapping.append({"col": col, "src": src, "fn": "org", "dim": ORG_DIMS[col]})
        elif col in LSTRIP or src == "MATNR":
            mapping.append({"col": col, "src": src, "fn": "lstrip0"})
        else:
            mapping.append({"col": col, "src": src, "fn": "copy"})
    # signature = first 2-3 mapped columns (usually the keys); refine if ambiguous
    sig = [m["col"] for m in mapping[:3]] or scols[:2]
    recipe = {
        "object": obj,
        "description": f"SCAFFOLD — {obj} from {source_table} into {staging_table}. "
                       f"Refine map / fill unmapped, then run through migration_engine.",
        "structures": [{
            "id": sid,
            "staging_table": staging_table,
            "staging_signature": sig,
            "builder": "declarative",
            "source": {"conn": "ecc", "table": source_table,
                       "fields": sorted(set(used)), "where": "", "limit": 20},
            "map": mapping,
        }],
        "_unmapped_staging_columns": unmapped,
        "_note": f"{len(mapping)}/{len(scols)} columns auto-mapped; {len(unmapped)} need a "
                 f"decision (default/const/custom source field).",
    }
    return recipe


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("staging_table"); ap.add_argument("source_table")
    ap.add_argument("--id", default="master"); ap.add_argument("--object", default="Object")
    ap.add_argument("--out")
    args = ap.parse_args()
    eng = Engine()
    try:
        rec = scaffold(eng, args.staging_table, args.source_table, args.id, args.object)
    finally:
        eng.close()
    text = json.dumps(rec, indent=2)
    if args.out:
        open(args.out, "w").write(text); print(f"wrote {args.out}")
    else:
        print(text)
