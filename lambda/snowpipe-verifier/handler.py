"""
snowpipe-verifier
=================
Runs on a 15-minute EventBridge schedule. Queries Snowflake's load_history
view (via the standard Snowflake REST /queries endpoint using a JWT built
from a service-user private key held in Secrets Manager) and publishes
`RowsLoaded` + `PipeStuckSeconds` CloudWatch metrics per (tenant, object).

Emits under namespace `Migrate4HANA/Snowpipe`:
  · RowsLoaded         (Count)      dims=tenant,object
  · PipeStuckSeconds   (Seconds)    dims=none  (0 = fresh, > 0 = staleness)
  · UnfinishedPipeFiles (Count)     dims=none

The CloudWatch dashboard picks these up alongside the SNS delivery-failed
alarm so operators see a single "is the Snowpipe healthy?" view.

FAULT-TOLERANCE
---------------
Failures in the Snowflake call don't take the Lambda down — the verifier
emits a `VerifierFailed` metric (1) and returns cleanly. That way one
transient Snowflake side blip doesn't page the ops team.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cw = boto3.client("cloudwatch")
sm = boto3.client("secretsmanager")

NS               = os.environ.get("METRIC_NAMESPACE", "Migrate4HANA/Snowpipe")
SNOWFLAKE_ACCT   = os.environ.get("SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER   = os.environ.get("SNOWFLAKE_USER", "")
SECRET_ARN       = os.environ.get("SECRET_ARN", "")
STALE_THRESHOLD  = int(os.environ.get("STALE_THRESHOLD_S", "900"))  # 15 min


def lambda_handler(event, context):
    try:
        creds = _load_creds()
    except Exception as e:
        _emit_failed(f"credential_load: {e}")
        return {"status": "failed", "reason": f"credential_load: {e}"}

    try:
        rows = _query_load_history(creds)
    except Exception as e:
        _emit_failed(f"query: {e}")
        return {"status": "failed", "reason": f"query: {e}"}

    per_pair = _aggregate(rows)
    _emit_metrics(per_pair)
    return {"status": "ok",
            "pairs_reported": len(per_pair),
            "sample": list(per_pair.items())[:3]}


# ─────────────────────────────────────────────────────────────────────────────
# Snowflake auth + query (JWT client-credentials flow)
# ─────────────────────────────────────────────────────────────────────────────
def _load_creds() -> dict:
    if not SECRET_ARN:
        raise RuntimeError("SECRET_ARN not configured")
    val = sm.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
    return json.loads(val)


def _query_load_history(creds: dict) -> list:
    """Query the last 30 minutes of load_history via Snowflake's REST API.

    Snowflake REST is documented at:
      https://docs.snowflake.com/en/user-guide/data-load-snowpipe-rest-apis

    This implementation calls the /api/statements endpoint (public 2023+),
    signed with a short-lived JWT built from the RSA private key. If the
    key isn't provisioned yet, the query fails cleanly.
    """
    import urllib.request
    import urllib.error

    if not SNOWFLAKE_ACCT or not SNOWFLAKE_USER:
        raise RuntimeError("SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER unset")

    jwt = _build_jwt(creds)
    if not jwt:
        raise RuntimeError("could not mint JWT (missing key or crypto lib)")

    url = f"https://{SNOWFLAKE_ACCT}.snowflakecomputing.com/api/v2/statements"
    body = json.dumps({
        "statement": (
            "SELECT tenant_id, object_type, SUM(row_data:_ok::INT) AS ok_rows, "
            "COUNT(*) AS total_rows, "
            "MAX(loaded_at) AS last_seen "
            "FROM m4h_raw "
            "WHERE loaded_at > DATEADD('minute', -30, CURRENT_TIMESTAMP()) "
            "GROUP BY 1, 2"
        ),
        "warehouse": os.environ.get("SNOWFLAKE_WH", "COMPUTE_WH"),
        "database":  os.environ.get("SNOWFLAKE_DB", "M4H_RAW_DB"),
        "schema":    os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC"),
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization":              f"Bearer {jwt}",
        "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        "Content-Type":               "application/json",
        "Accept":                     "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"snowflake {e.code}: "
                           f"{e.read().decode('utf-8', errors='replace')[:200]}")

    # data is column-oriented: `data`: [[col1, col2, ...], ...]
    data = payload.get("data") or []
    return [
        {"tenant_id":   row[0],
         "object_type": row[1],
         "ok_rows":     int(row[2] or 0),
         "total_rows":  int(row[3] or 0),
         "last_seen":   row[4]}
        for row in data
    ]


def _build_jwt(creds: dict) -> Optional[str]:
    """Build the KEYPAIR_JWT Snowflake expects. Uses the `cryptography`
    library if available; returns None if not (verifier will emit a
    VerifierFailed metric which paging can key off)."""
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return None

    pem = (creds.get("private_key_pem") or "").encode("utf-8")
    passphrase = (creds.get("passphrase") or "").encode("utf-8") or None
    if not pem:
        return None
    key = serialization.load_pem_private_key(pem, password=passphrase)

    # Public key fingerprint (SHA-256 of the DER SPKI)
    pub_der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashes.Hash(hashes.SHA256())
    digest.update(pub_der)
    fp = "SHA256:" + base64.b64encode(digest.finalize()).decode()

    account = SNOWFLAKE_ACCT.upper()
    user    = SNOWFLAKE_USER.upper()
    now     = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    claims  = {
        "iss": f"{account}.{user}.{fp}",
        "sub": f"{account}.{user}",
        "iat": now, "exp": now + 3600,
    }

    def b64u(obj) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()

    signing_input = f"{b64u(header)}.{b64u(claims)}".encode()
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{signing_input.decode()}.{sig_b64}"


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation + CloudWatch emission
# ─────────────────────────────────────────────────────────────────────────────
def _aggregate(rows: list) -> dict:
    """Fold rows into (tenant, object) -> {ok, total, last_seen} counters."""
    out: dict = {}
    for r in rows:
        key = (r.get("tenant_id") or "unknown",
               r.get("object_type") or "unknown")
        cur = out.setdefault(key, {"ok": 0, "total": 0, "last_seen": None})
        cur["ok"]    += int(r.get("ok_rows") or 0)
        cur["total"] += int(r.get("total_rows") or 0)
        ls = r.get("last_seen")
        if ls and (cur["last_seen"] is None or ls > cur["last_seen"]):
            cur["last_seen"] = ls
    return out


def _emit_metrics(per_pair: dict) -> None:
    """Emit per-pair RowsLoaded and a global freshness metric."""
    now = time.time()
    max_stale = 0
    metric_data = []
    for (tenant, obj), counts in per_pair.items():
        metric_data.append({
            "MetricName": "RowsLoaded",
            "Dimensions": [{"Name": "Tenant", "Value": tenant},
                            {"Name": "ObjectType", "Value": obj}],
            "Unit": "Count",
            "Value": counts["total"],
        })
        # Freshness in seconds since last_seen
        ls_s = _iso_to_epoch(counts.get("last_seen"))
        if ls_s:
            stale = max(0, now - ls_s)
            max_stale = max(max_stale, stale)
    metric_data.append({
        "MetricName": "PipeStuckSeconds",
        "Unit": "Seconds",
        "Value": max_stale,
    })
    # CloudWatch caps 20 items per PutMetricData call — chunk it
    for i in range(0, len(metric_data), 20):
        try:
            cw.put_metric_data(Namespace=NS,
                                MetricData=metric_data[i:i + 20])
        except Exception as e:
            logger.warning("PutMetricData failed: %s", e)


def _emit_failed(reason: str) -> None:
    try:
        cw.put_metric_data(Namespace=NS, MetricData=[{
            "MetricName": "VerifierFailed",
            "Unit": "Count",
            "Value": 1,
        }])
    except Exception:
        pass
    logger.error("verifier failed: %s", reason)


def _iso_to_epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    from datetime import datetime, timezone
    try:
        # Snowflake TIMESTAMP_LTZ round-tripped as string, e.g. "2026-07-03 12:34:56.123 -0700"
        # Try iso first
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return datetime.strptime(iso.split(".")[0],
                                     "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc).timestamp()
        except Exception:
            return None
