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

S3 = boto3.client("s3")
SECRETS = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

# Conservative per-invoke caps; production batching happens upstream.
MAX_ROWS_PER_TEMPLATE = int(os.environ.get("MAX_ROWS_PER_TEMPLATE", "50000"))


def _ecc(secret_id: str):
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection
    return Connection(ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
                      client=sec["client"], user=sec["user"],
                      passwd=sec["password"], lang=sec.get("lang", "EN"))


def _read_table(conn, table: str, fields: list, where: str = "", max_rows: int = MAX_ROWS_PER_TEMPLATE) -> list:
    opts = [{"TEXT": where}] if where else []
    fld = [{"FIELDNAME": f} for f in fields]
    res = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, OPTIONS=opts, FIELDS=fld, ROWCOUNT=max_rows)
    cols = [f["FIELDNAME"] for f in res.get("FIELDS", [])]
    rows = []
    for r in res.get("DATA", []):
        parts = [p.strip() for p in r["WA"].split("|")]
        rows.append(dict(zip(cols, parts)))
    return rows, cols


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


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    mode = event.get("mode", "generate_templates")
    spec = event.get("object_spec") or {}
    log_stage_event(run_id, "data-migrator", "start", {"mode": mode, "object": spec.get("object")})

    if mode == "extract":
        # Discovery-only: list candidate objects, count rows. Used in Phase 4.
        return {"status": "ok", "run_id": run_id, "mode": mode,
                "note": "extract counts are produced by discovery-engine; this is a no-op in lift-and-shift"}

    secret_id = event.get("ecc_secret_id", os.environ.get("ECC_SECRET_ID", ""))
    if not secret_id:
        return {"status": "blocked", "reason": "ecc_secret_id required", "run_id": run_id}

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
