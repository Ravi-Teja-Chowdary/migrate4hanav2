"""
grind — drive the M02 object breadth to 'staged' at scale.

For each object in SOURCE_MAP: look up its exact staging table from the MC registry
(object_catalog / /1LT/DS_MAPPING), scaffold a recipe against its ECC source table,
stage it through migration_engine, and record an honest result. Objects that fail,
map nothing, or have no source rows are logged as such — never silently counted.

    py -3.7 grind.py                 # run the whole map
    py -3.7 grind.py Z_BANK_2_M02    # run one object

Writes catalog/grind_results.json and prints a summary. Recipes persist to recipes/.
The MC Migrate step stays app-gated (the founder clicks it); this only stages.
"""
import os, sys, json, traceback
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine
from object_catalog import Catalog
import scaffold_recipe as scf

MT = "M02"

# object ident -> (ECC source table, structure-id label). Curated for the data-bearing
# objects of an ECC/IDES source across every functional area. Industry objects (EHS,
# oil&gas PRA, JVA, treasury, HCM, dangerous goods) are intentionally omitted — no
# source data — and reported separately as 'no-source (industry)'.
SOURCE_MAP = {
    # ---- FI / CO master ----
    "Z_GL_ACCOUNT_3_M02": ("SKA1", "general"),
    "Z_GL_ACC_EXT_M02":   ("SKA1", "general"),
    "Z_KOSTL_MASTER_M02": ("CSKS", "master"),
    "Z_LSTAR_CREATE_M02": ("CSLA", "master"),
    "Z_PRCTR_MSTR2_M02":  ("CEPC", "master"),
    "Z_INTORDER_2_M02":   ("AUFK", "master"),
    "Z_CO_BUS_PROC_M02":  ("CBPR", "master"),
    "Z_BANK_2_M02":       ("BNKA", "general"),
    "Z_EXCH_RATE_M02":    ("TCURR", "rates"),
    # ---- Product / material family (MARA/MAKT) ----
    "Z_PROD_EXT_2_M02":   ("MAKT", "text"),
    "Z_PROD_LONGTXT_M02": ("MARA", "master"),
    "Z_PROD_SERV_M02":    ("MAKT", "text"),
    "Z_MAT_CONSUMP_M02":  ("MARA", "master"),
    "Z_PROD_CONSUMP_M02": ("MARA", "master"),
    "Z_INVENTORY_2_M02":  ("MKPF", "master"),
    "Z_BATCHES_M02":      ("MCH1", "master"),
    "Z_BATCHES_PLANT_M02": ("MCH1", "master"),
    # ---- Classification ----
    "Z_CHARACT_M02":      ("CABN", "master"),
    "Z_CLASS_2_M02":      ("KLAH", "master"),
    # ---- Purchasing ----
    "Z_PURCH_INF_V2_M02": ("EINA", "master"),
    "Z_PUR_INF_E_V2_M02": ("EINA", "master"),
    "Z_SOURCE_LIST_M02":  ("EORD", "master"),
    "Z_PUR_ORDER_2_M02":  ("EKKO", "master"),
    "Z_CONTRACTS_M02":    ("EKKO", "master"),
    "Z_SCHED_AGRMNT_M02": ("EKKO", "master"),
    # ---- Sales / conditions ----
    "Z_SLS_ORDER_2_M02":  ("VBAK", "master"),
    "Z_SD_CONTRACT_M02":  ("VBAK", "master"),
    "Z_SD_SCHED_AGR_M02": ("VBAK", "master"),
    "Z_CONDITIONS_M02":   ("KONH", "master"),
    "Z_SD_CONDITION_M02": ("KONH", "master"),
    "Z_MM_CONDITION_M02": ("KONH", "master"),
    "Z_CUSTMAT_INF_M02":  ("KNMT", "master"),
    "Z_RFM_MC_M02":       ("T023", "master"),
    # ---- PP / logistics master ----
    "Z_BOM_M02":          ("STKO", "master"),
    "Z_BOM_3_M02":        ("STKO", "master"),
    "Z_ROUTING_M02":      ("PLKO", "master"),
    "Z_WORK_CNTR_M02":    ("CRHD", "master"),
    "Z_PRODUCT_VER_M02":  ("MKAL", "master"),
    "Z_PP_PSA_M02":       ("PVBE", "master"),
    # ---- QM ----
    "Z_MSTR_CHAR_M02":    ("QPMK", "master"),
    "Z_INSP_METHOD_M02":  ("QMTB", "master"),
    "Z_QM_CATALOG_M02":   ("QPGR", "master"),
    "Z_QM_QINF_2_M02":    ("QINF", "master"),
    "Z_SELECTED_SET_M02": ("QPAM", "master"),
    "Z_SELSET_CODE_M02":  ("QPAC", "master"),
    # ---- PM / EAM ----
    "Z_EQUIPMENT_2_M02":  ("EQUI", "master"),
    "Z_FUNC_LOC_2_M02":   ("IFLOT", "master"),
    "Z_MAINT_PLAN_3_M02": ("MPLA", "master"),
    "Z_MAINT_ITEM_M02":   ("MPOS", "master"),
    # ---- FI balances / open items / assets ----
    "Z_GL_BALANCE_M02":   ("BSIS", "master"),
    "Z_OPEN_ITEM_AP_M02": ("BSIK", "master"),
    "Z_OPEN_ITEM_AR_M02": ("BSID", "master"),
    "Z_FIXED_ASSET_M02":  ("ANLA", "master"),
    # ---- PS ----
    "Z_PS_PROJECT_M02":   ("PROJ", "master"),
    "Z_WBS_ELEMENT_M02":  ("PRPS", "master"),
    # ---- Documents ----
    "Z_DOCU_INFOREC_M02": ("DRAW", "master"),
}


def short(ident):
    s = ident
    if s.startswith("Z_"):
        s = s[2:]
    if s.endswith("_" + MT):
        s = s[:-(len(MT) + 1)]
    return s.title().replace("_", "")


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    eng = Engine(allow_proposed=True)   # breadth: resolve org via proposed mappings
    cat = Catalog(eng)
    results = []
    items = [(only, SOURCE_MAP[only])] if only else sorted(SOURCE_MAP.items())
    for ident, (src, sid) in items:
        row = {"object": ident, "source": src}
        try:
            stg = cat.primary_table(MT, ident)
            row["staging"] = stg
            if not stg:
                row["result"] = "not-in-catalog"; results.append(row); continue
            recipe = scf.scaffold(eng, stg, src, sid, short(ident))
            nmap = len(recipe["structures"][0]["map"])
            row["mapped_cols"] = nmap
            row["unmapped_cols"] = len(recipe.get("_unmapped_staging_columns", []))
            json.dump(recipe, open(os.path.join("recipes", short(ident).lower() + ".json"), "w"), indent=2)
            if nmap == 0:
                row["result"] = "no-automap"; results.append(row); continue
            info = eng.run(recipe)[0]
            row["built"] = info["built"]; row["verified"] = info.get("verified_rows")
            row["skipped"] = info["skipped"]
            row["result"] = "staged" if (info.get("verified_rows") or 0) > 0 else "staged-empty"
        except Exception as e:
            row["result"] = "error"; row["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        results.append(row)
        r = row
        print(f"[{r['result']:>13}] {ident:<24} src={src:<7} "
              f"map={r.get('mapped_cols','-')} built={r.get('built','-')} verified={r.get('verified','-')}"
              + (f"  {r.get('error','')}" if r.get("error") else ""))
    eng.close()
    json.dump(results, open(os.path.join("catalog", "grind_results.json"), "w"), indent=2)
    # summary
    from collections import Counter
    c = Counter(r["result"] for r in results)
    print("\n===== GRIND SUMMARY =====")
    for k, v in c.most_common():
        print(f"  {k:<16} {v}")
    staged = [r for r in results if r["result"] == "staged"]
    print(f"\nSTAGED OK: {len(staged)} objects")
    print("wrote catalog/grind_results.json")


if __name__ == "__main__":
    main()
