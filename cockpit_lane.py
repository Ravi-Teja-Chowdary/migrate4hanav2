"""
cockpit_lane — the SAP Migration Cockpit lane for objects with NO official create BAPI
(road-to-production P2-1; the UNIFIED_PLAN.md MC-1..MC-4 epic, made concrete + honest).

WHY THIS EXISTS
    The direct-API product (bapi_migrate / bucket2 / bucket3) covers everything that has an
    official released BAPI/OData — the large majority. A small TAIL has NO create API in SAP at
    all and can only go through SAP's built-in Migration Cockpit: probed live this session —
      * Activity Type                       (BAPI_ACTIVITYTYPE_* not callable)
      * QM Inspection Method                (no BAPI_INSPMETHOD_CREATE)
      * QM Master Inspection Characteristic (no BAPI_INSPCHAR_CREATE)
      * Work Center                         (no released create BAPI)
    For these, the SAP-sanctioned path is: stage rows into the MC staging tables, then run the
    cockpit's Prepare -> Simulate -> Migrate. Staging is programmatic (direct HANA, MC-1.3).
    The RUN trigger is programmatic IF the MC OData service is activated on the target.

HONEST GATE (discovered live, S/4 2020 rel 816; recorded in UNIFIED_PLAN MC-2)
    The classic MC OData service `CA_DATA_MIGRATION_SRV` is NOT activated on this target, and
    the IWFND catalog exposes no LTMC/DMC staging OData service. So the cockpit RUN step needs a
    one-time client action: EITHER activate the MC OData service (/n/IWFND/MAINT_SERVICE), OR
    create the project + staging tables once in LTMC — after which staging + trigger + result
    read-back are all programmatic. This module routes the tail objects, checks that gate, and
    reports exactly what's ready vs what needs that one-time activation. Read-only.

    M4H_TARGET_CLIENT=100 py -3.7 cockpit_lane.py            # plan/readiness -> COCKPIT_LANE.md
"""
import os, sys, datetime
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))

REPORT = "COCKPIT_LANE.md"

# no-BAPI objects -> (source table for a volume read, MC object name, staging-object hint)
NO_BAPI = [
    ("Activity Type", "CSLA", "Activity Type", "S_CSLA"),
    ("QM Inspection Method", "QMTB", "Inspection Method", "S_QMTB"),
    ("QM Master Inspection Characteristic", "QPMK", "Master Inspection Characteristic", "S_QPMK"),
    ("Work Center", "CRHD", "Work Center", "S_CRHD"),
]


def _mc_odata_active(eng):
    """Is the MC OData service published on the target? Check the IWFND service registry.
    (Read-only; returns True/False/None.)"""
    for tab, fld, like in (("/IWFND/I_MED_SRH", "SERVICE", "%DATA_MIGRATION%"),):
        try:
            rows = eng.read_table(eng.tgt, tab, [fld], "%s LIKE '%s'" % (fld, like))
            return len(rows) > 0
        except Exception:
            continue
    return None   # couldn't determine


def main():
    from migration_engine import Engine
    client = os.environ.get("M4H_TARGET_CLIENT", "200")
    eng = Engine(); ecc = eng.ecc

    def cnt(tab):
        try:
            cols = eng.read_table(ecc, "DD03L", ["FIELDNAME"], "TABNAME = '%s'" % tab)
            f0 = [c["FIELDNAME"].strip() for c in cols if not c["FIELDNAME"].strip().startswith(".")][:1]
            return len(eng.read_table(ecc, tab, f0)) if f0 else 0
        except Exception:
            return 0

    rows = [(label, mc, cnt(src), src, stg) for (label, src, mc, stg) in NO_BAPI]
    odata = _mc_odata_active(eng)
    # is the staging infra present? (the kit staging FMs / staging schema) — proxy: DS_MAPPING readable
    try:
        from object_catalog import Catalog
        cat = Catalog(eng); staging_ready = len(cat.mass_transfers()) > 0
    except Exception:
        staging_ready = False
    eng.close()

    trigger = ("programmatic (MC OData active)" if odata is True
               else "ONE-TIME client step required: activate MC OData service OR create project in LTMC"
               if odata is False else "unknown (probe inconclusive) — verify MC OData / LTMC on target")

    lines = [f"# Cockpit lane — no-BAPI object tail — target client {client}", "",
             f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Read-only. These objects have no "
             "official create BAPI, so they migrate via SAP's Migration Cockpit (stage → prepare → "
             "simulate → migrate). Staging is programmatic; the RUN trigger depends on the gate below._", "",
             f"**Staging infrastructure (DS_MAPPING catalog reachable):** {'✅ yes' if staging_ready else '🔴 no'}",
             f"**MC RUN trigger:** {trigger}", "",
             "| object | MC object | source rows | source table | staging object |",
             "|---|---|---:|---|---|"]
    for label, mc, c, src, stg in rows:
        lines.append(f"| {label} | {mc} | {c} | {src} | {stg} |")
    lines += ["",
              "### Path per object (SAP-sanctioned)",
              "1. **Stage** the source rows into the MC staging table (direct HANA — `hana_staging.load_staging`, "
              "programmatic, no file-size cap).",
              "2. **Prepare → Simulate → Migrate** via the MC OData runtime — **programmatic once the gate above "
              "is satisfied**; today it needs the one-time activation/LTMC step noted above.",
              "3. **Read results** (application log / transfer list) back by API into the same reconcile path.",
              "",
              "> Honest status: the routing + staging are buildable now; the automated RUN is gated on a "
              "one-time client Basis action (activate the MC OData service, or create the project in LTMC "
              "once). This is a target-activation prerequisite, not a tool gap — the same objects run at "
              "volume through this lane once it's satisfied. Full loop detail: `UNIFIED_PLAN.md` MC-1..MC-4."]
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))
    print("wrote %s | %d no-BAPI objects | staging_ready=%s | odata=%s" % (REPORT, len(rows), staging_ready, odata))
    for label, mc, c, src, stg in rows:
        print("  %-38s source rows=%d (MC: %s)" % (label, c, mc))


if __name__ == "__main__":
    main()
