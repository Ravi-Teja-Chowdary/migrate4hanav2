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

try:
    import compliance  # type: ignore
except Exception:  # pragma: no cover
    compliance = None

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


def _target_odata():
    """OData (HTTPS gateway) client to the TARGET S/4 — the door RFC can't open for
    transaction-ready partner creation. None if requests/odata_client unavailable."""
    try:
        from odata_client import ODataClient
        sec = json.loads(SECRETS.get_secret_value(SecretId="local:target")["SecretString"])
        port = int(os.environ.get("M4H_ODATA_PORT", "44300"))
        return ODataClient(sec["ashost"], sec["user"], sec.get("passwd") or sec.get("password"),
                           client=sec.get("client", "100"), port=port)
    except Exception:
        return None


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
    "OpenPO":            {"table": "EKKO", "fields": ["EBELN", "BSART", "BUKRS", "EKORG", "EKGRP", "LIFNR", "WAERS"], "where": "BSTYP = 'F'", "lane": "MC"},
    "OpenSO":            {"table": "VBAK", "fields": ["VBELN", "AUART", "KUNNR", "VKORG"], "lane": "MC"},
    "OpenAR":            {"table": "BSID", "fields": ["BUKRS", "KUNNR", "BELNR", "DMBTR", "SHKZG", "WAERS"], "lane": "MC"},
    "OpenAP":            {"table": "BSIK", "fields": ["BUKRS", "LIFNR", "BELNR", "DMBTR", "SHKZG", "WAERS"], "lane": "MC"},
    "BankStatements":    {"table": "FEBKO", "fields": ["KUKEY", "ESNUM", "BANKL", "BANKN"], "lane": "IDOC", "idoc_type": "FINSTA01"},
    "ExchangeRates":     {"table": "TCURR", "fields": ["KURST", "FCURR", "TCURR", "GDATU", "UKURS", "FFACT", "TFACT"], "lane": "IDOC", "idoc_type": "EXCHRATE_CREATE01"},
    "AssetMaster":       {"table": "ANLA", "fields": ["BUKRS", "ANLN1", "ANLN2", "ANLKL"], "lane": "MC"},
    "BOM":               {"table": "MAST", "fields": ["MATNR", "WERKS", "STLAN", "STLNR"], "lane": "MC"},
    "Routing":           {"table": "MAPL", "fields": ["MATNR", "WERKS", "PLNTY", "PLNNR"], "lane": "MC"},
    "WorkCenter":        {"table": "CRHD", "fields": ["OBJID", "ARBPL", "WERKS"], "lane": "MC"},
}


# Cross-run migration ledger: the durable source->target record that makes re-runs
# idempotent (resume, don't duplicate). Stable key (not per run_id) so it accumulates.
LEDGER_KEY = "migration-ledger/key_mapping.json"


def _load_ledger():
    """Load the cross-run migration ledger into a KeyMap (empty if first run)."""
    if KeyMap is None:
        return None
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=LEDGER_KEY)
        return KeyMap.from_dict(json.loads(obj["Body"].read()))
    except Exception:
        return KeyMap()


def _save_ledger(km) -> None:
    """Persist the (now-merged) ledger so the next run reuses instead of re-creating."""
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=LEDGER_KEY,
                      Body=json.dumps(km.to_dict(), indent=2).encode(),
                      ContentType="application/json")
    except Exception:
        pass


# ── Delta / CDC: extract only records changed since the last watermark ────────
# Delta mode (M4H_CDC_DELTA=1) filters each object's extraction by a change-date field
# >= the persisted watermark — incremental migration + the cutover delta load. NOTE:
# KNA1/LFA1 only carry ERDAT (created) — so customer/vendor delta catches NEW masters;
# CHANGED existing ones need change documents (CDHDR/CDPOS), a future enhancement.
CDC_DELTA = os.environ.get("M4H_CDC_DELTA", "0") == "1"
CDC_STATE_KEY = "migration-ledger/cdc-watermark.json"
CDC_FIELDS = {
    "Customer": ["ERDAT"], "Vendor": ["ERDAT"], "Material": ["LAEDA", "ERSDA"],
    "OpenPO": ["AEDAT"], "OpenAR": ["CPUDT"], "OpenAP": ["CPUDT"],
}


def _load_watermark():
    """Last CDC watermark (YYYYMMDD) — None on first run (=> full extract)."""
    if os.environ.get("M4H_CDC_WATERMARK"):
        return os.environ["M4H_CDC_WATERMARK"]
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=CDC_STATE_KEY)
        return json.loads(obj["Body"].read()).get("watermark")
    except Exception:
        return None


def _save_watermark(wm: str) -> None:
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=CDC_STATE_KEY,
                      Body=json.dumps({"watermark": wm}).encode(), ContentType="application/json")
    except Exception:
        pass


def _cdc_where(obj: str, watermark: str) -> str:
    """Delta WHERE for an object: any of its change-date fields >= watermark."""
    fields = CDC_FIELDS.get(obj)
    if not (fields and watermark):
        return ""
    return "( " + " OR ".join("%s >= '%s'" % (f, watermark) for f in fields) + " )"


def _load_dag(run_id: str) -> dict:
    """Load the routing DAG written by stage 3 (object-router)."""
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=f"runs/{run_id}/object-router/dag.json")
        return json.loads(obj["Body"].read())
    except Exception as ex:
        return {"nodes": [], "_load_error": str(ex)}


def _process_one_object(conn, run_id: str, node: dict, loader=None, cdc_watermark=None) -> dict:
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
    base_where = mapping.get("where", "")
    # Delta/CDC: AND a change-date filter onto the base WHERE when a watermark is set.
    cdc_where = _cdc_where(obj_name, cdc_watermark) if cdc_watermark else ""
    delta_applied = bool(cdc_where)
    where = (f"( {base_where} ) AND {cdc_where}" if base_where and cdc_where
             else cdc_where or base_where)
    err_note = None
    try:
        rows, cols = _read_table(conn, table, fields, where)
    except Exception as e:
        if delta_applied:   # bad CDC field etc. — fall back to a full extract
            try:
                rows, cols = _read_table(conn, table, fields, base_where)
                delta_applied = False
                err_note = "cdc filter failed; full extract fallback"
            except Exception as e2:
                rows, cols = [], fields
                err_note = f"ECC read failed: {type(e2).__name__}: {str(e2)[:120]}"
        else:
            rows, cols = [], fields
            err_note = f"ECC read failed: {type(e).__name__}: {str(e)[:120]}"

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
    if cdc_watermark and delta_applied:   # only objects that actually have a CDC field
        result["delta"] = {"applied": True, "since": cdc_watermark,
                           "changed_rows": len(rows)}

    # Optionally LOAD the extracted rows into S/4 via the best mechanism (BAPI/IDoc).
    # Per-object cap overrides the global one (M4H_LOAD_MAX_ROWS_<OBJECT>) — e.g. run
    # ExchangeRates at volume while keeping side-effecting objects (BP/PO) at a few rows.
    if loader is not None and rows and loader.supported(obj_name):
        omax = int(os.environ.get("M4H_LOAD_MAX_ROWS_" + obj_name.upper(), LOAD_MAX_ROWS))
        try:
            result["load"] = loader.load_object(obj_name, rows, omax)
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
                # Live source->target registry, shared across the run so dependent
                # objects (OpenPO -> Vendor) resolve refs; source conn for PO items.
                loader.key_map = _load_ledger()   # cross-run ledger -> idempotent re-runs
                loader.source_conn = conn
                loader.odata = _target_odata()   # transaction-ready partner creation (OData)
                loader.target_conn_factory = _target_connection   # parallel mass-load pool
                log_stage_event(run_id, "data-migrator", "load_enabled",
                                {"max_rows": LOAD_MAX_ROWS, "mechanisms": OBJECT_MECHANISM,
                                 "odata_partner_create": bool(loader.odata and loader.odata_ready())})
            except Exception as e:
                log_stage_event(run_id, "data-migrator", "load_disabled", {"reason": str(e)[:160]})

        # Delta/CDC: in delta mode, extract only records changed since the watermark.
        run_watermark = _load_watermark() if CDC_DELTA else None

        results = []
        for node in nodes:
            try:
                results.append(_process_one_object(conn, run_id, node, loader=loader,
                                                   cdc_watermark=run_watermark))
            except Exception as e:
                results.append({"object": node.get("object"), "status": "error",
                                "error": f"{type(e).__name__}: {str(e)[:200]}"})

        # Advance the watermark to today so the next delta run only picks up newer changes.
        new_watermark = time.strftime("%Y%m%d")
        if CDC_DELTA or _load_watermark() is None:
            _save_watermark(new_watermark)

        # Persist the live source->target key registry (built during the run as
        # objects loaded; consumed by dependent objects, then written for audit).
        key_map_info = None
        km = getattr(loader, "key_map", None) if loader else None
        if km is not None and km.to_rows():
            key_map_info = {**_emit_key_map(run_id, km), "stats": km.stats()}
            _save_ledger(km)   # persist the merged ledger for idempotent re-runs

        # Dead-letter: genuinely failed records across objects -> a report for targeted
        # reprocessing (a subsequent idempotent re-run picks these up; successes are skipped).
        dead_letters = [{"object": r.get("object"), **d}
                        for r in results for d in (r.get("load") or {}).get("dead_letter", [])]
        dead_letter_info = None
        if dead_letters:
            dkey = f"runs/{run_id}/data-migrator/dead-letter/failed_records.json"
            S3.put_object(Bucket=STAGING_BUCKET, Key=dkey,
                          Body=json.dumps(dead_letters, indent=2).encode(),
                          ContentType="application/json")
            dead_letter_info = {"failed_records": len(dead_letters),
                                "artifact": f"s3://{STAGING_BUCKET}/{dkey}",
                                "reprocess": "idempotent re-run reloads these; loaded records are skipped"}

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
                   "cdc": {"mode": "delta" if CDC_DELTA else "full",
                           "watermark_used": run_watermark, "next_watermark": new_watermark,
                           "changed_rows_extracted": sum((r.get("delta") or {}).get("changed_rows", 0)
                                                         for r in results if r.get("delta"))},
                   "idempotency": {"newly_created": loaded_to_s4,
                                   "reused_from_ledger": sum((r.get("load", {}) or {}).get("reused_from_ledger", 0)
                                                             for r in results)},
                   "reconciliation": Reconciler.rollup(recon_reports) if Reconciler else None,
                   "support_compliance": compliance.audit(results) if compliance else None,
                   "key_mapping": key_map_info,
                   "dead_letter": dead_letter_info,
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
