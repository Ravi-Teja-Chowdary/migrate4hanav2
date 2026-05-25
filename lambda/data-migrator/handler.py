"""
data-migrator (lift-and-shift) — MC/IDoc/LTMOM template generator only.

This Lambda used to do in-place loading. In lift-and-shift it has ONE job:
read the routed object spec, extract data from ECC via pyrfc, and emit
*tool-native templates* to S3:

    * MC lane     -> CSV/XLSX in the MC staging-table layout
    * IDoc lane   -> per-object IDoc XML files
    * LTMOM lane  -> mapping spec + sample CSV (manual SLT/LTMOM build)
    * BODS lane   -> dataflow-input CSV with column metadata

It does NOT push anything into S/4HANA. Push is done by the lane
orchestrators (migration-cockpit-orchestrator / idoc-orchestrator /
ltmom-orchestrator).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

try:
    import sapnwrfc  # noqa: F401
except Exception:  # pragma: no cover
    pass

try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

try:
    from unified_loader import UnifiedLoader, OBJECT_MECHANISM  # type: ignore
except Exception:  # pragma: no cover
    UnifiedLoader = None
    OBJECT_MECHANISM = {}

try:
    from currency_config import CurrencyConfigReconciler  # type: ignore
except Exception:  # pragma: no cover
    CurrencyConfigReconciler = None

try:
    from reconciler import Reconciler  # type: ignore
except Exception:  # pragma: no cover
    Reconciler = None

try:
    from key_map import KeyMap  # type: ignore
except Exception:  # pragma: no cover
    KeyMap = None

S3 = boto3.client("s3")
SECRETS = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

# Conservative per-invoke caps; production batching happens upstream.
MAX_ROWS_PER_TEMPLATE = int(os.environ.get("MAX_ROWS_PER_TEMPLATE", "50000"))

# Actually post extracted data into S/4 (via idoc_loader) when M4H_LOAD_TO_S4=1.
LOAD_TO_S4 = os.environ.get("M4H_LOAD_TO_S4", "0") == "1"
LOAD_MAX_ROWS = int(os.environ.get("M4H_LOAD_MAX_ROWS", "5"))
OWN_LOGICAL_SYSTEM = os.environ.get("M4H_TARGET_LOGSYS", "S4HCLNT100")
IDOC_SENDER = os.environ.get("M4H_IDOC_SENDER", "M4HSENDER")


def _ecc(secret_id: str):
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection
    return Connection(ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
                      client=sec["client"], user=sec["user"],
                      passwd=sec.get("passwd") or sec.get("password"),
                      lang=sec.get("lang", "EN"))


def _read_table(conn, table: str, fields: list, where: str = "", max_rows: int = MAX_ROWS_PER_TEMPLATE) -> list:
    opts = [{"TEXT": where}] if where else []
    fld = [{"FIELDNAME": f} for f in fields]
    # DELIMITER='|' so multi-field rows split cleanly (without it RFC_READ_TABLE
    # returns fixed-width WA and the split produces garbage columns).
    res = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                    OPTIONS=opts, FIELDS=fld, ROWCOUNT=max_rows)
    cols = [f["FIELDNAME"] for f in res.get("FIELDS", [])]
    rows = []
    for r in res.get("DATA", []):
        parts = [p.strip() for p in r["WA"].split("|")]
        rows.append(dict(zip(cols, parts)))
    return rows, cols


def _target_connection():
    """RFC connection to the TARGET S/4 (for loading data in), from local:target."""
    sec = json.loads(SECRETS.get_secret_value(SecretId="local:target")["SecretString"])
    from pyrfc import Connection
    return Connection(ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
                      client=sec["client"], user=sec["user"],
                      passwd=sec.get("passwd") or sec.get("password"), lang="EN")


def _emit_mc_csv(run_id: str, obj_name: str, rows: list, cols: list) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    key = f"runs/{run_id}/data-migrator/mc/{obj_name}.csv"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key, Body=buf.getvalue().encode(),
                  ContentType="text/csv")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_idoc_xml(run_id: str, obj_name: str, idoc_type: str, rows: list) -> str:
    """Minimal IDoc XML envelope; real per-segment population is delegated
    to idoc-orchestrator using the segment definitions on the target."""
    body_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                  f'<{idoc_type}_BATCH count="{len(rows)}">']
    for r in rows:
        seg = "".join(f"<{k}>{v}</{k}>" for k, v in r.items())
        body_parts.append(f"<{idoc_type}>{seg}</{idoc_type}>")
    body_parts.append(f"</{idoc_type}_BATCH>")
    key = f"runs/{run_id}/data-migrator/idoc/{obj_name}.xml"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                  Body="\n".join(body_parts).encode(),
                  ContentType="application/xml")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_ltmom_spec(run_id: str, obj_name: str, cols: list) -> str:
    spec = {"object": obj_name, "source": "ECC", "target": "S/4HANA",
            "fields": [{"source": c, "target": c, "transform": "identity"} for c in cols],
            "instructions": "LTMOM mapping is built manually on target; "
                            "this spec is the design input."}
    key = f"runs/{run_id}/data-migrator/ltmom/{obj_name}.json"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key, Body=json.dumps(spec, indent=2).encode(),
                  ContentType="application/json")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_currency_config(run_id: str, manifest: dict, csv_text: str) -> dict:
    """Write the currency-customizing deploy package (the prerequisite TCURV rate
    types + TCURF factors the target is missing) for controlled, transport-grade
    apply. Returns the artifact locations."""
    base = f"runs/{run_id}/data-migrator/config/exchange_rate_customizing"
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.json",
                  Body=json.dumps(manifest, indent=2).encode(), ContentType="application/json")
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.csv",
                  Body=csv_text.encode(), ContentType="text/csv")
    return {"manifest": f"s3://{STAGING_BUCKET}/{base}.json",
            "review_csv": f"s3://{STAGING_BUCKET}/{base}.csv"}


def _emit_key_map(run_id: str, km) -> dict:
    """Persist the run's source->target key registry as a first-class artifact:
    a JSON for programmatic lookup by later stages / dependent objects, and a CSV
    for audit. This is how transactional data follows remapped/renumbered keys."""
    base = f"runs/{run_id}/data-migrator/keymap/key_mapping"
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.json",
                  Body=json.dumps(km.to_dict(), indent=2).encode(), ContentType="application/json")
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.csv",
                  Body=km.to_csv().encode(), ContentType="text/csv")
    return {"registry": f"s3://{STAGING_BUCKET}/{base}.json",
            "audit_csv": f"s3://{STAGING_BUCKET}/{base}.csv"}


# ── Object → source-table mapping for batch-mode runs ────────────────────────
# When the runner invokes data-migrator without an explicit object_spec, we
# iterate over the stage-3 DAG and apply this canonical mapping per object.
DEFAULT_OBJECT_TABLES = {
    "Customer":          {"table": "KNA1", "fields": ["KUNNR", "NAME1", "LAND1", "ORT01"], "lane": "MC"},
    "Vendor":            {"table": "LFA1", "fields": ["LIFNR", "NAME1", "LAND1", "ORT01"], "lane": "MC"},
    "Material":          {"table": "MARA", "fields": ["MATNR", "MTART", "MATKL", "MEINS"], "lane": "MC"},
    "BusinessPartner":   {"table": "BUT000", "fields": ["PARTNER", "TYPE", "BPKIND", "BU_GROUP"], "lane": "MC"},
    "CompanyCode":       {"table": "T001", "fields": ["BUKRS", "BUTXT", "ORT01", "LAND1"], "lane": "MC"},
    "GLAccount":         {"table": "SKA1", "fields": ["KTOPL", "SAKNR", "XBILK"], "lane": "MC"},
    "CostCenter":        {"table": "CSKS", "fields": ["KOKRS", "KOSTL", "DATBI"], "lane": "MC"},
    "ProfitCenter":      {"table": "CEPC", "fields": ["KOKRS", "PRCTR", "DATBI"], "lane": "MC"},
    "Plant":             {"table": "T001W", "fields": ["WERKS", "NAME1", "LAND1"], "lane": "MC"},
    "ChartOfAccounts":   {"table": "T004", "fields": ["KTOPL", "KTPLT", "MWSKZ"], "lane": "MC"},
    "ControllingArea":   {"table": "TKA01", "fields": ["KOKRS", "BEZEI", "WAERS"], "lane": "MC"},
    "OpenPO":            {"table": "EKKO", "fields": ["EBELN", "BUKRS", "LIFNR", "BSTYP"], "lane": "MC"},
    "OpenSO":            {"table": "VBAK", "fields": ["VBELN", "AUART", "KUNNR", "VKORG"], "lane": "MC"},
    "OpenAR":            {"table": "BSID", "fields": ["BUKRS", "KUNNR", "BELNR", "DMBTR"], "lane": "MC"},
    "OpenAP":            {"table": "BSIK", "fields": ["BUKRS", "LIFNR", "BELNR", "DMBTR"], "lane": "MC"},
    "BankStatements":    {"table": "FEBKO", "fields": ["KUKEY", "ESNUM", "BANKL", "BANKN"], "lane": "IDOC", "idoc_type": "FINSTA01"},
    "ExchangeRates":     {"table": "TCURR", "fields": ["KURST", "FCURR", "TCURR", "GDATU", "UKURS", "FFACT", "TFACT"], "lane": "IDOC", "idoc_type": "EXCHRATE_CREATE01"},
    "AssetMaster":       {"table": "ANLA", "fields": ["BUKRS", "ANLN1", "ANLN2", "ANLKL"], "lane": "MC"},
    "BOM":               {"table": "MAST", "fields": ["MATNR", "WERKS", "STLAN", "STLNR"], "lane": "MC"},
    "Routing":           {"table": "MAPL", "fields": ["MATNR", "WERKS", "PLNTY", "PLNNR"], "lane": "MC"},
    "WorkCenter":        {"table": "CRHD", "fields": ["OBJID", "ARBPL", "WERKS"], "lane": "MC"},
}


def _load_dag(run_id: str) -> dict:
    """Load the routing DAG written by stage 3 (object-router)."""
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=f"runs/{run_id}/object-router/dag.json")
        return json.loads(obj["Body"].read())
    except Exception as ex:
        return {"nodes": [], "_load_error": str(ex)}


def _process_one_object(conn, run_id: str, node: dict, loader=None) -> dict:
    """Extract one object from ECC and emit lane-appropriate artifact."""
    obj_name = node.get("object", "UNKNOWN")
    lane = (node.get("lane") or "MC").upper()
    mapping = DEFAULT_OBJECT_TABLES.get(obj_name)

    if not mapping:
        # Unknown object — emit a placeholder so downstream stages don't blow up
        key = f"runs/{run_id}/data-migrator/skipped/{obj_name}.json"
        S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                      Body=json.dumps({"object": obj_name, "lane": lane,
                                       "status": "skipped", "reason": "no source-table mapping"},
                                      indent=2).encode())
        return {"object": obj_name, "lane": lane, "status": "skipped",
                "reason": "no canonical mapping", "artifact": f"s3://{STAGING_BUCKET}/{key}"}

    table = mapping["table"]
    fields = mapping["fields"]
    try:
        rows, cols = _read_table(conn, table, fields, "")
    except Exception as e:
        # Empty placeholder — pipeline shouldn't halt on a single missing table
        rows, cols = [], fields
        err_note = f"ECC read failed: {type(e).__name__}: {str(e)[:120]}"
    else:
        err_note = None

    artifacts = {}
    target_lane = mapping.get("lane", lane).upper()
    if target_lane == "MC":
        artifacts["mc_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)
    elif target_lane == "IDOC":
        idoc_type = mapping.get("idoc_type", obj_name)
        artifacts["idoc_xml"] = _emit_idoc_xml(run_id, obj_name, idoc_type, rows)
    elif target_lane == "LTMOM":
        artifacts["ltmom_spec"] = _emit_ltmom_spec(run_id, obj_name, cols)
        artifacts["sample_csv"] = _emit_mc_csv(run_id, f"{obj_name}_sample", rows[:1000], cols)
    else:
        artifacts["raw_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)

    result = {"object": obj_name, "lane": target_lane, "row_count": len(rows),
              "artifacts": artifacts, "note": err_note,
              "status": "ok" if err_note is None else "partial"}

    # Optionally LOAD the extracted rows into S/4 via the best mechanism (BAPI/IDoc)
    if loader is not None and rows and loader.supported(obj_name):
        try:
            result["load"] = loader.load_object(obj_name, rows, LOAD_MAX_ROWS)
        except Exception as e:
            result["load"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    # RECONCILE: prove every record the BAPI said it created actually persisted in
    # the target's system of record (reads keys back; ties created == verified).
    if (loader is not None and Reconciler is not None and result.get("load")
            and "error" not in result["load"]):
        try:
            result["reconciliation"] = Reconciler(loader.c).reconcile(
                obj_name, result["load"], extracted=len(rows))
        except Exception as e:
            result["reconciliation"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    # ExchangeRates: run the currency-customizing READINESS check. Rates only post
    # when their TCURV type + TCURF factor exist in the target; this reports the
    # exact prerequisite delta (and its coverage impact) and emits a deploy package
    # the config team applies via transport — closing the gap to ~100% the right way.
    if (obj_name == "ExchangeRates" and loader is not None and rows
            and CurrencyConfigReconciler is not None):
        try:
            rec = CurrencyConfigReconciler(conn, loader.c)
            rep = rec.diff(rate_rows=rows)
            manifest, csv_text = rec.build_artifact(rep)
            artifacts.update(_emit_currency_config(run_id, manifest, csv_text))
            result["currency_config_readiness"] = {
                "coverage_before": rep["coverage_before"],
                "coverage_after_provisioning": rep["coverage_after_provisioning"],
                "missing_rate_types": rep["missing_rate_type_count"],
                "missing_factors": rep["missing_factor_count"],
                "deploy_package": {"manifest": artifacts.get("manifest"),
                                   "review_csv": artifacts.get("review_csv")},
            }
        except Exception as e:
            result["currency_config_readiness"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return result


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    mode = event.get("mode", "generate_templates")
    spec = event.get("object_spec") or {}
    log_stage_event(run_id, "data-migrator", "start", {"mode": mode, "object": spec.get("object")})

    secret_id = (event.get("ecc_secret_id")
                 or os.environ.get("ECC_SECRET_ID")
                 or event.get("ecc_creds_arn")
                 or event.get("source_creds_arn")
                 or "local:ecc")
    if not secret_id:
        return {"status": "blocked", "reason": "ecc_secret_id / ecc_creds_arn required", "run_id": run_id}

    # ── Batch mode: no object_spec → iterate over stage-3 DAG ─────────────────
    if not spec.get("object"):
        dag = _load_dag(run_id)
        nodes = [n for n in dag.get("nodes", [])
                 if (n.get("lane") or "").upper() in ("MC", "IDOC", "LTMOM")]
        if not nodes:
            return {"status": "ok", "run_id": run_id, "mode": mode,
                    "note": "no MC/IDoc/LTMOM nodes in DAG — nothing to extract",
                    "dag_load": dag.get("_load_error")}
        try:
            conn = _ecc(secret_id)
        except Exception as e:
            log_stage_event(run_id, "data-migrator", "error", {"connect": str(e)})
            return {"status": "error", "reason": f"ECC connect failed: {e}", "run_id": run_id}

        # Optional S/4 loader (real write path) — only when M4H_LOAD_TO_S4=1
        loader = None
        if LOAD_TO_S4 and UnifiedLoader is not None:
            try:
                tsec = json.loads(SECRETS.get_secret_value(SecretId="local:target")["SecretString"])
                tconn = _target_connection()
                loader = UnifiedLoader(tconn, own_logical_system=OWN_LOGICAL_SYSTEM,
                                       sender=IDOC_SENDER,
                                       client=tsec.get("client", "100"),
                                       target_sid=tsec.get("sid", "S4H"))
                log_stage_event(run_id, "data-migrator", "load_enabled",
                                {"max_rows": LOAD_MAX_ROWS, "mechanisms": OBJECT_MECHANISM})
            except Exception as e:
                log_stage_event(run_id, "data-migrator", "load_disabled", {"reason": str(e)[:160]})

        results = []
        for node in nodes:
            try:
                results.append(_process_one_object(conn, run_id, node, loader=loader))
            except Exception as e:
                results.append({"object": node.get("object"), "status": "error",
                                "error": f"{type(e).__name__}: {str(e)[:200]}"})

        # Build + persist the source->target key registry (dependent objects + audit)
        key_map_info = None
        if KeyMap is not None:
            km = KeyMap()
            for r in results:
                km.add_many(r.get("object"), (r.get("load") or {}).get("key_mappings"))
            if km.to_rows():
                key_map_info = {**_emit_key_map(run_id, km), "stats": km.stats()}

        # Write batch summary so downstream validator can read it
        loaded_to_s4 = sum((r.get("load", {}) or {}).get("created_in_s4", 0) for r in results)
        recon_reports = [r["reconciliation"] for r in results
                         if isinstance(r.get("reconciliation"), dict)
                         and "error" not in r["reconciliation"]]
        summary = {"run_id": run_id, "mode": mode, "object_count": len(results),
                   "ok_count": sum(1 for r in results if r.get("status") == "ok"),
                   "partial_count": sum(1 for r in results if r.get("status") == "partial"),
                   "error_count": sum(1 for r in results if r.get("status") == "error"),
                   "skipped_count": sum(1 for r in results if r.get("status") == "skipped"),
                   "load_to_s4_enabled": bool(loader),
                   "objects_created_in_s4": loaded_to_s4,
                   "reconciliation": Reconciler.rollup(recon_reports) if Reconciler else None,
                   "key_mapping": key_map_info,
                   "results": results}
        S3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/data-migrator/summary.json",
                      Body=json.dumps(summary, default=str, indent=2).encode(),
                      ContentType="application/json")
        log_stage_event(run_id, "data-migrator", "ok", summary)
        return {"status": "success", **summary}

    # ── Single-object mode (legacy) ───────────────────────────────────────────
    obj_name = spec.get("object", "UNKNOWN")
    table = spec.get("source_table", obj_name)
    fields = spec.get("fields", [])
    where = spec.get("where_clause", "")
    lane = (spec.get("lane") or "MC").upper()

    try:
        conn = _ecc(secret_id)
        rows, cols = _read_table(conn, table, fields, where)
    except Exception as e:
        log_stage_event(run_id, "data-migrator", "error", {"ecc_read": str(e)})
        return {"status": "error", "reason": f"ECC read failed: {e}", "run_id": run_id}

    artifacts = {}
    if lane == "MC":
        artifacts["mc_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)
    elif lane == "IDOC":
        idoc_type = spec.get("idoc_type", obj_name)
        artifacts["idoc_xml"] = _emit_idoc_xml(run_id, obj_name, idoc_type, rows)
    elif lane == "LTMOM":
        artifacts["ltmom_spec"] = _emit_ltmom_spec(run_id, obj_name, cols)
        artifacts["sample_csv"] = _emit_mc_csv(run_id, f"{obj_name}_sample", rows[:1000], cols)
    else:
        artifacts["raw_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)

    summary = {"run_id": run_id, "status": "ok", "object": obj_name, "lane": lane,
               "row_count": len(rows), "artifacts": artifacts}
    log_stage_event(run_id, "data-migrator", "ok", summary)
    return summary
