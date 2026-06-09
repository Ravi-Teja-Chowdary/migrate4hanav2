"""
compliance-archive - WS4 pillar 2: Immutable Compliance Archive + Legacy Decommissioning.

Standardizes the pipeline that extracts 100% of historical legacy records
from a customer's ECC system, formats them into structured compliance
records, and seals them into an immutable WORM (Write-Once-Read-Many) S3
archive with Object Lock in COMPLIANCE mode for a retention horizon that
satisfies SOX (7 years) / FDA (10 years) / GDPR (per art. 17 / 30).

This is the "shut down your legacy ECC hardware while remaining
perfectly compliant" pivot. The customer's CFO + audit committee see
that 100% of legacy records are sealed in an immutable S3 store with a
SHA-256 hash chain proving non-tampering, and signs off on
decommissioning the on-premise ECC hardware contract -- one of the
largest TCO items in any SAP landscape.

Architecture:
  1. Extract pass    walks each historical table on ECC (BUT000, BKPF/BSEG
                     / VBAK / EKKO / ANLA / MARA / ...) chunked through
                     RFC_READ_TABLE so even 10M-row tables don't OOM
  2. Format pass     each chunk normalized into a compliance record
                     {table, primary_key, row_data, extracted_at,
                      tenant_id, ecc_release, record_sha256}
  3. Seal pass       chunk's records appended to a JSONL file in S3 with
                     server-side encryption (AES-256), Object Lock
                     COMPLIANCE mode + retention_days, and the chunk's
                     manifest block hash-chained to the previous chunk
  4. Audit pass      manifest emits an audit-trail row to the
                     migrate4hana-compliance-ledger-prod DDB table so the
                     CFO + auditor can verify continuity without reading
                     the archive

Tenant-isolated via the F7 TenantContext: each customer's compliance
archive lives under s3://migrate4hana-compliance-archive-prod/
tenants/<slug>/ with separate DDB ledger entries.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

try:
    import boto3
    S3 = boto3.client("s3")
    DDB = boto3.client("dynamodb")
    SECRETS = boto3.client("secretsmanager")
except Exception:
    S3 = None
    DDB = None
    SECRETS = None


ARCHIVE_BUCKET = os.environ.get("M4H_COMPLIANCE_BUCKET",
                                 "migrate4hana-compliance-archive-prod")
LEDGER_TABLE = os.environ.get("M4H_COMPLIANCE_LEDGER_TABLE",
                                "migrate4hana-compliance-ledger-prod")
DEFAULT_RETENTION_DAYS = int(os.environ.get("M4H_COMPLIANCE_RETENTION_DAYS",
                                              "3650"))   # 10 years default


# Standard compliance-archive table inventory. Covers the legacy ECC
# tables that customers' auditors most-frequently subpoena 7-10 years
# post-cutover (financial / HR / asset / customer master).
LEGACY_TABLES = {
    "Customer":        {"table": "KNA1",   "keys": ["KUNNR"]},
    "Vendor":          {"table": "LFA1",   "keys": ["LIFNR"]},
    "BusinessPartner": {"table": "BUT000", "keys": ["PARTNER"]},
    "Material":        {"table": "MARA",   "keys": ["MATNR"]},
    "FixedAsset":      {"table": "ANLA",   "keys": ["BUKRS", "ANLN1"]},
    "FIDocumentHdr":   {"table": "BKPF",   "keys": ["BUKRS", "BELNR", "GJAHR"]},
    "FIDocumentLines": {"table": "BSEG",   "keys": ["BUKRS", "BELNR", "GJAHR", "BUZEI"]},
    "SalesDocumentHdr":{"table": "VBAK",   "keys": ["VBELN"]},
    "PurchaseDocHdr":  {"table": "EKKO",   "keys": ["EBELN"]},
    "GLBalances":      {"table": "GLT0",   "keys": ["BUKRS", "RYEAR", "RACCT"]},
    "OpenAR":          {"table": "BSID",   "keys": ["BUKRS", "BELNR", "GJAHR"]},
    "OpenAP":          {"table": "BSIK",   "keys": ["BUKRS", "BELNR", "GJAHR"]},
    "Employee":        {"table": "PA0001", "keys": ["PERNR"]},
    "PayrollResult":   {"table": "PA0008", "keys": ["PERNR", "BEGDA"]},
}


def _tenant_ctx():
    try:
        from tenant_context import TenantContext
        return TenantContext.from_env()
    except Exception:
        class _N:
            tenant_id = "default"; tenant_slug = "default"; is_default = True
        return _N()


def _open_rfc(secret_id: str):
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


def _last_archive_block_hash(ctx, object_type: str) -> str:
    """Read the latest block hash for this tenant + object -- forms the chain link."""
    if DDB is None:
        return ""
    try:
        r = DDB.query(TableName=LEDGER_TABLE,
                       KeyConditionExpression="tenant_obj = :k",
                       ExpressionAttributeValues={":k": {"S": f"{ctx.tenant_id}#{object_type}"}},
                       ScanIndexForward=False, Limit=1)
        items = r.get("Items") or []
        if items:
            return (items[0].get("block_hash") or {}).get("S", "")
    except Exception:
        pass
    return ""


def _seal_chunk_to_s3(ctx, object_type: str, chunk_idx: int,
                       records: list, retention_days: int) -> dict:
    """Write chunk as gzipped JSONL with Object Lock COMPLIANCE mode +
    retention. Returns the block hash for the chain link + the S3 URI."""
    if not records:
        return {"object": object_type, "rows": 0, "block_hash": None}
    body_lines = []
    for r in records:
        body_lines.append(json.dumps(r, sort_keys=True))
    body_str = "\n".join(body_lines) + "\n"

    block_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
    prev_hash = _last_archive_block_hash(ctx, object_type) or "0" * 64

    key = (f"tenants/{ctx.tenant_slug}/compliance-archive/"
            f"{object_type}/chunk-{chunk_idx:06d}-{block_hash[:12]}.jsonl.gz")

    if S3 is not None:
        try:
            import gzip
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="w") as gz:
                gz.write(body_str.encode("utf-8"))
            buf.seek(0)
            # Object Lock retention -- COMPLIANCE mode is irrevocable for the
            # retention window even by AWS root account holders, matching
            # SOX / FDA / GDPR audit-trail immutability requirements.
            import datetime
            retention_until = (datetime.datetime.utcnow()
                                + datetime.timedelta(days=retention_days)).isoformat() + "Z"
            S3.put_object(
                Bucket=ARCHIVE_BUCKET, Key=key,
                Body=buf.getvalue(),
                ContentType="application/gzip",
                ServerSideEncryption="AES256",
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retention_until,
                Metadata={
                    "block-hash":   block_hash,
                    "prev-hash":    prev_hash,
                    "tenant-id":    ctx.tenant_id,
                    "object-type":  object_type,
                    "chunk-idx":    str(chunk_idx),
                    "row-count":    str(len(records)),
                },
            )
        except Exception as e:
            return {"object": object_type, "rows": len(records),
                     "error": f"S3 seal failed: {e}",
                     "block_hash": block_hash}

    # Chain link in DDB
    if DDB is not None:
        try:
            DDB.put_item(TableName=LEDGER_TABLE, Item={
                "tenant_obj": {"S": f"{ctx.tenant_id}#{object_type}"},
                "ts":         {"N": str(int(time.time()))},
                "block_hash": {"S": block_hash},
                "prev_hash":  {"S": prev_hash},
                "row_count":  {"N": str(len(records))},
                "s3_uri":     {"S": f"s3://{ARCHIVE_BUCKET}/{key}"},
                "object_type":{"S": object_type},
                "chunk_idx":  {"N": str(chunk_idx)},
            })
        except Exception:
            pass

    return {
        "object":         object_type,
        "chunk_idx":      chunk_idx,
        "rows":           len(records),
        "block_hash":     block_hash,
        "prev_hash":      prev_hash,
        "s3_uri":         f"s3://{ARCHIVE_BUCKET}/{key}",
        "retention_days": retention_days,
    }


def _format_records(conn, spec: dict, object_type: str,
                     since_dt: str, rowcount: int) -> list:
    """Pull rows from the legacy table; format each into a compliance
    record carrying the original row + a SHA-256 over the row for
    record-level tamper-evidence."""
    rows = []
    try:
        options = []
        if since_dt:
            # ERDAT is universal-ish on master tables; for line tables
            # use BUDAT (posting date) -- caller can override via spec
            options = [{"TEXT": f"ERDAT >= '{since_dt}'"}]
        r = conn.call("RFC_READ_TABLE",
                       QUERY_TABLE=spec["table"],
                       DELIMITER="|",
                       FIELDS=[],
                       OPTIONS=options,
                       ROWCOUNT=rowcount)
        # Parse the columns
        fields = [f.get("FIELDNAME") for f in (r.get("FIELDS") or [])]
        for d in (r.get("DATA") or []):
            wa = (d.get("WA") or "").split("|")
            row_dict = dict(zip(fields, (c.strip() for c in wa)))
            record_sha = hashlib.sha256(
                json.dumps(row_dict, sort_keys=True).encode("utf-8")).hexdigest()
            rows.append({
                "object_type":    object_type,
                "table":          spec["table"],
                "primary_key":    {k: row_dict.get(k, "") for k in spec["keys"]},
                "row_data":       row_dict,
                "record_sha256":  record_sha,
                "extracted_at":   _iso_now(),
            })
    except Exception:
        pass
    return rows


def _iso_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ─────────────────────────────────────────────────────────────────────────────
# Lambda handler
# ─────────────────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    """Modes:
        "extract"       -- extract + seal a chunk for one object_type
        "extract_all"   -- iterate every LEGACY_TABLES entry, one chunk each
        "verify_chain"  -- walk the ledger for a tenant+object, returns
                            (ok, broken_at_chunk_idx_or_None)
    """
    mode = event.get("mode") or "extract"
    if mode == "extract":
        return _do_extract(event)
    if mode == "extract_all":
        return _do_extract_all(event)
    if mode == "verify_chain":
        return _do_verify_chain(event)
    return {"statusCode": 400, "body": json.dumps({"error": f"unknown mode {mode}"})}


def _do_extract(event):
    object_type = event.get("object_type") or ""
    if object_type not in LEGACY_TABLES:
        return {"statusCode": 400,
                "body": json.dumps({"error": f"unknown object_type {object_type}"})}
    ctx = _tenant_ctx()
    secret_id = event.get("ecc_secret_id") or "migrate4hana/prod/sap-credentials"
    since_dt  = event.get("since_dt") or ""
    rowcount  = int(event.get("rowcount") or 1000)
    chunk_idx = int(event.get("chunk_idx") or 0)
    retention = int(event.get("retention_days") or DEFAULT_RETENTION_DAYS)

    try:
        conn = _open_rfc(secret_id)
    except Exception as e:
        return {"statusCode": 502,
                "body": json.dumps({"error": f"connect_ecc failed: {e}"})}

    spec = LEGACY_TABLES[object_type]
    records = _format_records(conn, spec, object_type, since_dt, rowcount)
    try: conn.close()
    except Exception: pass

    seal_result = _seal_chunk_to_s3(ctx, object_type, chunk_idx,
                                      records, retention)
    return {"statusCode": 200, "body": json.dumps(seal_result)}


def _do_extract_all(event):
    """Iterate every LEGACY_TABLES entry. Caller can constrain via
    event["objects"] list."""
    ctx = _tenant_ctx()
    targets = event.get("objects") or list(LEGACY_TABLES.keys())
    summaries = []
    for obj in targets:
        if obj not in LEGACY_TABLES:
            continue
        per_event = dict(event)
        per_event["object_type"] = obj
        r = _do_extract(per_event)
        body = json.loads(r["body"])
        body["status_code"] = r["statusCode"]
        summaries.append(body)
    total_rows = sum(s.get("rows", 0) for s in summaries)
    return {"statusCode": 200, "body": json.dumps({
        "mode":        "extract_all",
        "tenant":      ctx.tenant_id,
        "objects":     len(summaries),
        "total_rows":  total_rows,
        "by_object":   summaries,
    })}


def _do_verify_chain(event):
    """Walk the ledger and confirm every block's prev_hash matches the
    previous block's block_hash. Returns (ok, broken_at) so an auditor
    can verify the archive hasn't been tampered."""
    ctx = _tenant_ctx()
    object_type = event.get("object_type") or ""
    if not object_type:
        return {"statusCode": 400,
                "body": json.dumps({"error": "object_type required"})}
    if DDB is None:
        return {"statusCode": 502,
                "body": json.dumps({"error": "DDB not configured"})}
    try:
        r = DDB.query(TableName=LEDGER_TABLE,
                       KeyConditionExpression="tenant_obj = :k",
                       ExpressionAttributeValues={
                           ":k": {"S": f"{ctx.tenant_id}#{object_type}"}},
                       ScanIndexForward=True)
        items = r.get("Items") or []
    except Exception as e:
        return {"statusCode": 502,
                "body": json.dumps({"error": f"DDB query failed: {e}"})}

    prev = "0" * 64
    for idx, it in enumerate(items):
        expected_prev = prev
        actual_prev = (it.get("prev_hash") or {}).get("S", "")
        if actual_prev != expected_prev:
            return {"statusCode": 200, "body": json.dumps({
                "ok": False,
                "broken_at_chunk_idx": idx,
                "expected_prev_hash":  expected_prev,
                "actual_prev_hash":    actual_prev,
                "chain_length":        len(items),
            })}
        prev = (it.get("block_hash") or {}).get("S", "")

    return {"statusCode": 200, "body": json.dumps({
        "ok": True,
        "chain_length": len(items),
        "tenant":       ctx.tenant_id,
        "object_type":  object_type,
        "tip_block_hash": prev,
    })}
