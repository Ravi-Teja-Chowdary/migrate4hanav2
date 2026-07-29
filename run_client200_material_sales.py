"""
run_client200_material_sales — migrate ECC material SALES-ORG views (MVKE) +
their tax classification (MLAN) into client 200 through the SAP Migration
Cockpit "Material" object, via the direct HANA staging-table lane.

WHY THE MIGRATION COCKPIT (and not BAPI / OData) — proven this session
    * BAPI_MATERIAL_SAVEDATA ignores TAXCLASSIFICATIONS -> MG172 "tax
      classifications not fully maintained", even with a valid mapped org and the
      exact target tax category. Confirmed live on client 200.
    * OData API_PRODUCT_SRV exposes no sales-org (MVKE) entity, and its tax child
      (A_ProductSalesTax) silently no-ops on a material with no sales view.
    * A direct MLAN write is refused by the Basis Kit (delivery class A, app data).
    The Migration Cockpit "Material" object runs the SAME logic as MM01 — it
    maintains the sales view and its tax classification as one unit, which is the
    coupling that defeats every lighter mechanism.

THE LANE
    ECC MVKE (+ MLAN tax) ─▶ org_mapper.resolve() translates VKORG/VTWEG/plant to
    the target org units ─▶ hana_staging.load_staging() bulk-writes the transformed
    rows into the Material object's HANA staging table ─▶ mc_job_trigger.trigger_
    mc_load() runs simulate+transfer ─▶ verify MVKE landed on client 200.

    Reuses org_mapper.py (the governed org mapping) and the existing MC infra
    (hana_staging.py, mc_job_trigger.py). Net-new only: skips (material, sales
    area) combos already present on target.

PREREQUISITES (the lane guards for both and tells you exactly what to do)
    1. M4H_HANA_PASSWD (+ M4H_HANA_USER=SYSTEM on the CAL) — the staging DB login.
    2. An MC project on the target using the *Staging Tables* method, containing
       the "Material" migration object. That project generates the staging table
       this lane writes to. Set its ids via M4H_MC_PROJECT / M4H_MC_OBJECT and,
       if auto-discovery can't find it, M4H_MC_SALES_STAGING_TABLE.
    3. Confirmed org mappings (org_mapper.json) — run org_mapper.py and confirm
       the DE/US sales-org rows first (or pass --allow-proposed to use proposals).
"""
import os, sys, json, time
from collections import defaultdict, Counter
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from org_mapper import OrgMap
from hana_staging import from_connections, HanaStagingError

MC_PROJECT = os.environ.get("M4H_MC_PROJECT", "M4H_MATERIAL")
MC_OBJECT = os.environ.get("M4H_MC_OBJECT", "Material")
STAGING_OVERRIDE = os.environ.get("M4H_MC_SALES_STAGING_TABLE", "")
ALLOW_PROPOSED = "--allow-proposed" in sys.argv


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="~",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, x["WA"].split("~"))) for x in r.get("DATA", [])]


def discover_sales_staging(hs):
    """Find the Material object's sales-view staging table. MC "staging tables"
    projects generate tables in the SAP LT namespace ('/1LT/…'); the sales-view
    table carries both a material key (MATNR/PRODUCT) and VKORG. We restrict to
    the /1LT/ namespace so we never mistake a standard application table (e.g. a
    PCA or pricing table that happens to have MATNR+VKORG) for a staging target."""
    if STAGING_OVERRIDE:
        return STAGING_OVERRIDE
    cur = hs.connect().cursor()
    cur.execute(
        "SELECT t.TABLE_NAME FROM TABLE_COLUMNS t "
        "JOIN TABLE_COLUMNS v ON t.SCHEMA_NAME=v.SCHEMA_NAME AND t.TABLE_NAME=v.TABLE_NAME "
        "WHERE t.SCHEMA_NAME=? AND t.TABLE_NAME LIKE '/1LT/%' "
        "AND t.COLUMN_NAME IN ('MATNR','PRODUCT') AND v.COLUMN_NAME='VKORG' "
        "ORDER BY t.TABLE_NAME LIMIT 5", (hs.schema,))
    hits = cur.fetchall(); cur.close()
    return hits[0][0] if hits else None


SETUP_HELP = """
-- SET UP THE MC "Material" PROJECT (one-time, in the S/4 Fiori launchpad) --
 1. Open the app  "Migrate Your Data - Migration Cockpit"  (or tx LTMC).
 2. Create -> New Migration Project.
      * Mass Transfer ID / name: something like M4H_MATERIAL
      * Data Transfer Option:  "Transfer Data Using Staging Tables"
      * Database Schema:  the schema shown by this tool (SAPHANADB)
 3. Add Migration Object:  select  "Material"  (product master, incl. sales).
 4. Save/activate -- this GENERATES the staging tables in that schema.
 5. Re-run this lane with:
      M4H_MC_PROJECT=<your project id>  M4H_MC_OBJECT=Material  py -3.7 run_client200_material_sales.py
    (if auto-discovery can't find the table, set M4H_MC_SALES_STAGING_TABLE too).
"""


def main():
    cfg = json.load(open("connections.json"))
    e, s = cfg["ecc"], cfg["lift_and_shift_target"]
    om = OrgMap()

    # 1) prerequisite: HANA staging reachable + Material staging table exists
    try:
        hs = from_connections(cfg); hs.connect()
    except HanaStagingError as ex:
        print(f"HANA staging not reachable: {ex}\nSet M4H_HANA_USER=SYSTEM and "
              f"M4H_HANA_PASSWD, then re-run.", flush=True)
        return
    staging = discover_sales_staging(hs)
    if not staging:
        print("No MC 'Material' sales-view staging table found on the target.", flush=True)
        print(SETUP_HELP, flush=True)
        hs.close(); return
    cols = [c["column"] for c in hs.describe_staging(staging)]
    print(f"staging table: {staging} ({len(cols)} columns)", flush=True)

    # 2) read source sales views + tax, translate via org_mapper
    ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                    user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
    sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                    user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
    tgt_mat = {r["MATNR"].lstrip("0") for r in rt(sc, "MARA", ["MATNR"])}
    have = {(r["MATNR"].lstrip("0"), r["VKORG"].strip(), r["VTWEG"].strip())
            for r in rt(sc, "MVKE", ["MATNR", "VKORG", "VTWEG"])}
    # source MLAN tax classification, keyed by material (first non-blank TAXM1 per country)
    mtax = defaultdict(dict)
    for r in rt(ec, "MLAN", ["MATNR", "ALAND", "TAXM1"]):
        v = (r.get("TAXM1") or "").strip()
        if v:
            mtax[r["MATNR"].lstrip("0")][r["ALAND"].strip()] = v

    src = rt(ec, "MVKE", ["MATNR", "VKORG", "VTWEG", "DWERK", "VMSTA", "SKTOF", "MTPOS"])
    rows, skips = [], Counter()
    for r in src:
        m = r["MATNR"].lstrip("0")
        if m not in tgt_mat:
            skips["material-not-on-target"] += 1; continue
        vk = om.resolve("sales_org", r["VKORG"].strip(), require_confirmed=not ALLOW_PROPOSED)
        vt = om.resolve("distribution_channel", r["VTWEG"].strip(), require_confirmed=not ALLOW_PROPOSED)
        if not vk:
            skips[f"unmapped-salesorg-{r['VKORG'].strip()}"] += 1; continue
        if not vt:
            skips[f"unmapped-distchan-{r['VTWEG'].strip()}"] += 1; continue
        if (m, vk, vt) in have:
            skips["already-on-target"] += 1; continue
        dw = om.resolve("plant", r["DWERK"].strip(), require_confirmed=not ALLOW_PROPOSED) if r.get("DWERK") else ""
        # superset of likely staging columns; load_staging writes only what exists
        rows.append({"MATNR": m, "PRODUCT": m, "VKORG": vk, "VTWEG": vt,
                     "DWERK": dw or "", "DELYG_PLNT": dw or "",
                     "MTPOS": r.get("MTPOS", ""), "SKTOF": r.get("SKTOF", ""),
                     "TAXKM": next(iter(mtax.get(m, {}).values()), ""),  # first tax class value
                     "VMSTA": ""})
    ec.close()
    print(f"transformed {len(rows)} net-new sales-view rows; skips: {dict(skips.most_common(8))}", flush=True)
    if not rows:
        print("Nothing to stage (confirm org mappings, or pass --allow-proposed).", flush=True)
        hs.close(); sc.close(); return

    # 3) load staging + 4) trigger the MC job
    res = hs.load_staging(staging, rows, truncate=True)
    print(f"staged: inserted={res['inserted']} failed={res['failed']} "
          f"cols={res['columns']}", flush=True)
    if res["errors"]:
        print("  sample staging errors:", res["errors"][:3], flush=True)
    hs.close()

    from mc_job_trigger import trigger_mc_load
    print(f"triggering MC transfer: project={MC_PROJECT} object={MC_OBJECT}", flush=True)
    job = trigger_mc_load(sc, project_id=MC_PROJECT, object_id=MC_OBJECT)
    print("MC job:", json.dumps(job, default=str)[:400], flush=True)

    # 5) verify
    landed = len({(r["MATNR"].lstrip("0"), r["VKORG"].strip(), r["VTWEG"].strip())
                  for r in rt(sc, "MVKE", ["MATNR", "VKORG", "VTWEG"])})
    print(f"MVKE sales views on client 200 after run: {landed}", flush=True)
    sc.close()


if __name__ == "__main__":
    main()
