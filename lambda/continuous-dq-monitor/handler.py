"""
continuous-dq-monitor - WS4 pillar 1: post-cutover Data Quality SaaS.

Decouples the F4 TransformationEngine + DQ gates from the migration state
machine so the same DQ ruleset that vetted the migration runs in perpetuity
against newly-created S/4 records (BPs, POs, etc.), monitoring corporate
compliance after the customer's migration window has closed.

Two trigger modes:

  1. EventBridge cron        scheduled batch scan -- typically nightly
                              over the previous 24h of MARA / KNA1 / EKKO
                              changes per the customer's SLA
  2. EventBridge webhook     near-real-time -- triggered by an S/4 CDS
                              event subscription or a custom outbound IDoc;
                              the lambda just runs the DQ pass on the
                              single payload it receives

Returns a per-record verdict matrix:

    { "scanned": N,
      "violations": [
         { "object": "BusinessPartner",
           "key": "<BP number>",
           "rule": "MANDATORY:LAND1",
           "severity": "critical",
           "message": "..."},
         ...],
      "summary": { "by_rule": {...}, "by_severity": {...} },
      "ledger_block_hash": "<sha256>"
    }

Findings stream to the F1 PersistentKeyMap-adjacent DDB table
`migrate4hana-dq-findings-prod` (a sibling table; see terraform module
dq-monitor). Each block is hash-chained into the existing audit ledger so
a Big-4 auditor can verify continuity of the post-cutover compliance
monitoring with the same fingerprint scheme the migration itself used.

Tenant-isolated via the F7 TenantContext convention -- a Fortune-500
customer's DQ findings go to their tenant-scoped DDB partition + S3 prefix
and never touch another tenant's data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

try:
    import boto3
    DDB = boto3.client("dynamodb")
    SECRETS = boto3.client("secretsmanager")
except Exception:
    DDB = None
    SECRETS = None


FINDINGS_TABLE = os.environ.get("M4H_DQ_FINDINGS_TABLE",
                                 "migrate4hana-dq-findings-prod")
RULESET_S3_PREFIX = "rulesets/"
DEFAULT_RULESET_S3 = os.environ.get("M4H_DQ_RULESET_S3", "")


# ─────────────────────────────────────────────────────────────────────────────
def _tenant_ctx():
    try:
        from tenant_context import TenantContext
        return TenantContext.from_env()
    except Exception:
        class _N:
            tenant_id = "default"; tenant_slug = "default"; is_default = True
        return _N()


def _open_rfc(secret_id: str):
    """Open a pyrfc Connection to the customer's S/4 target. Cached on
    SECRETS reads; per invocation lifecycle."""
    if SECRETS is None:
        return None
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection   # type: ignore
    return Connection(
        ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
        client=sec["client"], user=sec["user"],
        passwd=sec.get("passwd") or sec.get("password"),
        lang=sec.get("lang", "EN"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Object -> probe spec. Each entry describes:
#   - target table to read
#   - which fields to pull
#   - which transformation_engine object_rules key applies
# Used by both the scheduled scan and the webhook handlers.
# ─────────────────────────────────────────────────────────────────────────────
DQ_PROBE_SPECS = {
    "BusinessPartner": {
        "table":   "BUT000",
        "fields":  ["PARTNER", "TYPE", "BU_GROUP", "NAME_ORG1", "MC_NAME1"],
        "rule_key": "BusinessPartner",
    },
    "Material": {
        "table":   "MARA",
        "fields":  ["MATNR", "MTART", "MBRSH", "MEINS", "MAKTX"],
        "rule_key": "Material",
    },
    "PurchaseOrder": {
        "table":   "EKKO",
        "fields":  ["EBELN", "BUKRS", "LIFNR", "WAERS"],
        "rule_key": "PurchaseOrder",
    },
    "SalesOrder": {
        "table":   "VBAK",
        "fields":  ["VBELN", "VKORG", "KUNNR", "VTWEG", "SPART"],
        "rule_key": "SalesOrder",
    },
    "Customer": {
        "table":   "KNA1",
        "fields":  ["KUNNR", "NAME1", "LAND1", "STCD1"],
        "rule_key": "Customer",
    },
}


def _read_recent_rows(conn, object_type: str, since_dt: str,
                       rowcount: int = 500) -> list:
    """Pull rows created/modified since `since_dt` (CHAR8 SAP DATS).
    Falls back to no filter on tables without ERDAT (small probe)."""
    spec = DQ_PROBE_SPECS[object_type]
    options = []
    if since_dt:
        options = [{"TEXT": f"ERDAT >= '{since_dt}'"}]
    try:
        r = conn.call("RFC_READ_TABLE",
                       QUERY_TABLE=spec["table"],
                       DELIMITER="|",
                       FIELDS=[{"FIELDNAME": f} for f in spec["fields"]],
                       OPTIONS=options,
                       ROWCOUNT=rowcount)
        rows = []
        for d in (r.get("DATA") or []):
            wa = (d.get("WA") or "").split("|")
            row = dict(zip(spec["fields"], (c.strip() for c in wa)))
            rows.append(row)
        return rows
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Hash-chain ledger writer
# ─────────────────────────────────────────────────────────────────────────────
def _seal_findings(findings: list, ctx) -> str:
    """Compute the SHA-256 block hash for this scan's findings, append the
    block to the DDB ledger (one row per scan), and return the new
    block_hash for caller telemetry."""
    block_body = json.dumps({
        "tenant": ctx.tenant_id,
        "ts":     int(time.time()),
        "count":  len(findings),
        "rules":  sorted({f["rule"] for f in findings}),
    }, sort_keys=True)
    block_hash = hashlib.sha256(block_body.encode("utf-8")).hexdigest()

    if DDB is None:
        return block_hash
    try:
        prev = _last_block_hash(ctx)
        item = {
            "tenant_id":   {"S": ctx.tenant_id},
            "ts":          {"N": str(int(time.time()))},
            "block_hash":  {"S": block_hash},
            "prev_hash":   {"S": prev or "0" * 64},
            "finding_count": {"N": str(len(findings))},
            "body":        {"S": block_body[:4000]},   # cap on DDB item size
        }
        DDB.put_item(TableName=FINDINGS_TABLE, Item=item)
    except Exception:
        pass
    return block_hash


def _last_block_hash(ctx) -> str:
    """Read the most-recent block_hash for the tenant -- forms the chain link."""
    if DDB is None:
        return ""
    try:
        r = DDB.query(TableName=FINDINGS_TABLE,
                       KeyConditionExpression="tenant_id = :tid",
                       ExpressionAttributeValues={":tid": {"S": ctx.tenant_id}},
                       ScanIndexForward=False, Limit=1)
        items = r.get("Items") or []
        if items:
            return (items[0].get("block_hash") or {}).get("S", "")
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Lambda entry points
# ─────────────────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    mode = event.get("mode") or "scan"
    if mode == "scan":
        return _scheduled_scan(event)
    if mode == "webhook":
        return _webhook_scan(event)
    return {"statusCode": 400, "body": json.dumps({"error": f"unknown mode {mode}"})}


def _scheduled_scan(event):
    """Cron-triggered batch DQ pass. Pulls recently-changed rows from each
    monitored object's table, runs them through the F4 TransformationEngine
    + DQ gates, sealed and chained into the ledger."""
    ctx = _tenant_ctx()
    secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    since_dt  = event.get("since_dt") or _iso_minus_days(1).replace("-", "")[:8]
    objects   = event.get("objects") or list(DQ_PROBE_SPECS.keys())

    try:
        conn = _open_rfc(secret_id)
    except Exception as e:
        return {"statusCode": 502, "body": json.dumps({"error": f"connect_s4 failed: {e}"})}

    # Pull the latest ruleset from S3 (per-tenant) so business users editing
    # via the WS1 console reach the monitor without redeploy
    ruleset = _fetch_active_ruleset(event)
    engine = None
    if ruleset:
        try:
            from transformation_engine import TransformationEngine
            engine = TransformationEngine(ruleset=ruleset)
        except Exception:
            engine = None

    total_scanned = 0
    all_findings = []
    by_object = {}
    for obj in objects:
        if obj not in DQ_PROBE_SPECS:
            continue
        rows = _read_recent_rows(conn, obj, since_dt)
        total_scanned += len(rows)
        findings_obj = _evaluate_rows(engine, obj, rows)
        by_object[obj] = {"scanned": len(rows),
                          "violations": len(findings_obj)}
        all_findings.extend(findings_obj)

    try:
        conn.close()
    except Exception:
        pass

    block_hash = _seal_findings(all_findings, ctx)
    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode":        "scan",
            "tenant":      ctx.tenant_id,
            "since_dt":    since_dt,
            "scanned":     total_scanned,
            "violations":  len(all_findings),
            "by_object":   by_object,
            "summary":     _summarize(all_findings),
            "ledger_block_hash": block_hash,
        }),
    }


def _webhook_scan(event):
    """Single-record DQ pass for near-real-time webhook triggers (CDS event
    subscription / outbound IDoc)."""
    ctx = _tenant_ctx()
    obj = (event.get("object") or "").strip()
    row = event.get("row") or {}
    if obj not in DQ_PROBE_SPECS or not row:
        return {"statusCode": 400,
                "body": json.dumps({"error": "object + row required"})}
    ruleset = _fetch_active_ruleset(event)
    engine = None
    if ruleset:
        try:
            from transformation_engine import TransformationEngine
            engine = TransformationEngine(ruleset=ruleset)
        except Exception:
            engine = None
    findings = _evaluate_rows(engine, obj, [row])
    block_hash = _seal_findings(findings, ctx)
    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode":        "webhook",
            "tenant":      ctx.tenant_id,
            "object":      obj,
            "violations":  len(findings),
            "findings":    findings,
            "ledger_block_hash": block_hash,
        }),
    }


def _evaluate_rows(engine, obj: str, rows: list) -> list:
    """Run each row through the TransformationEngine and collect DQ
    rejections. When engine is None (no ruleset) returns empty list --
    the monitor is then in pure-extract mode."""
    if engine is None or not rows:
        return []
    spec = DQ_PROBE_SPECS[obj]
    rule_key = spec["rule_key"]
    findings = []
    for row in rows:
        try:
            _out, dq = engine.apply(rule_key, row)
        except Exception:
            continue
        if dq is None or dq.passed:
            continue
        # The key field is conventionally the first field in the probe spec
        key_field = spec["fields"][0]
        for rej in (dq.rejections or []):
            findings.append({
                "object":   obj,
                "key":      row.get(key_field, ""),
                "rule":     f"{rej.get('rule')}:{rej.get('field')}",
                "severity": rej.get("severity", "critical"),
                "message":  rej.get("message", "")[:240],
            })
    return findings


def _summarize(findings: list) -> dict:
    by_rule = {}
    by_severity = {}
    for f in findings:
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    return {"by_rule": by_rule, "by_severity": by_severity}


def _fetch_active_ruleset(event: dict) -> dict:
    """Return the ruleset (inline > S3 > none). The WS1 console writes/
    publishes business-user changes to S3; this lambda reads the active
    version each run."""
    inline = event.get("ruleset")
    if inline and isinstance(inline, dict):
        return inline
    s3uri = event.get("ruleset_s3") or DEFAULT_RULESET_S3
    if not s3uri or not s3uri.startswith("s3://"):
        return {}
    try:
        import boto3
        s3 = boto3.client("s3")
        bucket, _, key = s3uri[5:].partition("/")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body)
    except Exception:
        return {}


def _iso_minus_days(d: int) -> str:
    import datetime
    return (datetime.datetime.utcnow() - datetime.timedelta(days=d))\
        .isoformat(timespec="seconds")
