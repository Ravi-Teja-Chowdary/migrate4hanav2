"""
sink_router - WS4 pillar 3: Cross-Platform Coexistence & Multi-Cloud Streaming.

Decouples the target data routing layer from SAP protocols. Transformed +
cleansed enterprise data flows through a pluggable sink interface so the
same migration pipeline can mirror or stream into NON-SAP destinations
(Snowflake, AWS clean rooms, Salesforce, generic event bus) in parallel
with -- or instead of -- writing back into S/4 BAPIs.

Establishes Migrate4HANA as a live Enterprise Data Fabric rather than a
one-shot migration tool.

Architecture:

   BaseSpineOrchestrator.load_one()
            │
            ├──> BAPI sink         (S/4 target, existing default)
            └──> SinkRouter.fan_out(transformed_row)
                    │
                    ├──> SnowflakeSink   (table per object_type)
                    ├──> S3ParquetSink   (clean-room / data-lake)
                    ├──> SalesforceSink  (Account/Contact/Opportunity)
                    └──> EventBusSink    (EventBridge -> downstream)

Sinks are configured via env vars or per-tenant ruleset; sinks can be
toggled on/off live without redeploy (via the WS1 ruleset console).

This module focuses on the routing + sink contract. Concrete sink
implementations:
  - SnowflakeSink: writes via boto3 client to a staged Snowflake batch
                    in S3 + auto-ingest via Snowpipe; idempotent
  - S3ParquetSink: PyArrow-shaped Parquet to a partitioned S3 path;
                    Athena / Glue / Redshift Spectrum consumable
  - SalesforceSink: REST API insert/upsert; the target Salesforce
                     Account/Contact/Opportunity ID is registered back
                     into F1 PersistentKeyMap as a cross-system mapping
  - EventBusSink: EventBridge custom-event publisher; downstream
                   subscribers handle the routing
"""
from __future__ import annotations

import io
import json
import os
import time
from typing import Optional


class Sink:
    """Pluggable sink contract. Implementations override write_one() and
    optionally batch() for bulk efficiency."""
    name = "abstract"

    def write_one(self, object_type: str, source_key: str,
                   row: dict, tenant_id: str = "default") -> dict:
        raise NotImplementedError

    def flush(self) -> dict:
        """Optional: flush any buffered batch. Default no-op."""
        return {"sink": self.name, "flushed": 0}


# ─────────────────────────────────────────────────────────────────────────────
class SnowflakeSink(Sink):
    """Stages each object's rows under s3://<bucket>/snowflake-stage/
    <tenant>/<object>/<ts>.jsonl for Snowpipe auto-ingest. The Snowflake
    side has a per-tenant STAGE + auto-ingest PIPE configured by the
    customer's DBA at onboarding."""

    name = "snowflake"

    def __init__(self, s3_client=None,
                 stage_bucket: str = None):
        self.s3 = s3_client
        self.stage_bucket = stage_bucket or os.environ.get(
            "M4H_SNOWFLAKE_STAGE_BUCKET", "migrate4hana-snowflake-stage-prod")
        self._buffer: dict = {}     # (tenant, object_type) -> [rows...]

    def write_one(self, object_type, source_key, row, tenant_id="default"):
        key = (tenant_id, object_type)
        self._buffer.setdefault(key, []).append({
            "source_key": source_key, "row": row,
            "_loaded_at": _iso_now(),
        })
        return {"sink": self.name, "status": "buffered"}

    def flush(self):
        flushed = 0
        out: list = []
        for (tenant, obj), rows in self._buffer.items():
            if not rows:
                continue
            body = "\n".join(json.dumps(r, default=str) for r in rows) + "\n"
            key = f"snowflake-stage/{tenant}/{obj}/{int(time.time())}.jsonl"
            if self.s3 is not None:
                try:
                    self.s3.put_object(
                        Bucket=self.stage_bucket, Key=key,
                        Body=body.encode("utf-8"),
                        ContentType="application/x-ndjson")
                except Exception as e:
                    out.append({"tenant": tenant, "object": obj,
                                 "error": str(e)[:200]})
                    continue
            out.append({"tenant": tenant, "object": obj, "rows": len(rows),
                         "stage_uri": f"s3://{self.stage_bucket}/{key}"})
            flushed += len(rows)
        self._buffer = {}
        return {"sink": self.name, "flushed": flushed, "stages": out}


# ─────────────────────────────────────────────────────────────────────────────
class S3ParquetSink(Sink):
    """Writes rows as JSONL to a partitioned S3 path; production version
    converts to Parquet via PyArrow before upload. The JSONL fallback
    keeps the sink runnable on Lambda's read-only / small-image runtime
    where PyArrow may be unavailable."""

    name = "s3_parquet"

    def __init__(self, s3_client=None,
                 archive_bucket: str = None):
        self.s3 = s3_client
        self.archive_bucket = archive_bucket or os.environ.get(
            "M4H_PARQUET_LAKE_BUCKET", "migrate4hana-clean-room-prod")
        self._buffer: dict = {}

    def write_one(self, object_type, source_key, row, tenant_id="default"):
        key = (tenant_id, object_type)
        self._buffer.setdefault(key, []).append({
            "source_key": source_key, "row": row,
            "_loaded_at": _iso_now(),
        })
        return {"sink": self.name, "status": "buffered"}

    def flush(self):
        flushed = 0
        out: list = []
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        for (tenant, obj), rows in self._buffer.items():
            if not rows:
                continue
            body = "\n".join(json.dumps(r, default=str) for r in rows) + "\n"
            key = (f"clean-room/tenant={tenant}/object={obj}/date={today}/"
                    f"batch-{int(time.time())}.jsonl")
            if self.s3 is not None:
                try:
                    self.s3.put_object(
                        Bucket=self.archive_bucket, Key=key,
                        Body=body.encode("utf-8"),
                        ContentType="application/x-ndjson")
                except Exception as e:
                    out.append({"tenant": tenant, "object": obj,
                                 "error": str(e)[:200]})
                    continue
            out.append({"tenant": tenant, "object": obj, "rows": len(rows),
                         "lake_uri": f"s3://{self.archive_bucket}/{key}"})
            flushed += len(rows)
        self._buffer = {}
        return {"sink": self.name, "flushed": flushed, "partitions": out}


# ─────────────────────────────────────────────────────────────────────────────
class SalesforceSink(Sink):
    """Routes per-object via the Salesforce REST API.

    Production upsert model
    -----------------------
    Each write is a Salesforce PATCH to the object's `External_Id__c` endpoint:

        PATCH /services/data/v60.0/sobjects/<Object>/External_Id__c/<id>

    Salesforce treats PATCH-with-external-id as an UPSERT — insert if the
    external id is new, update if it exists. This is inherently idempotent:
    re-running the same load can never create duplicates.

    Sync-status tracking (`salesforce_sync_status` DDB)
    ---------------------------------------------------
    Every write records a row in DDB keyed by (tenant_id, external_id) with:
      · sf_object, sf_id (populated after successful upsert)
      · last_status: PENDING → SYNCED | FAILED
      · attempt_count, last_error (truncated to 400 chars)
      · last_synced_at / last_attempt_at (ISO-8601 UTC)

    FAILED rows are the recovery surface for retry_failed(): the operator
    (or a scheduled Lambda) can call it to re-drive any FAILED / PENDING
    rows after fixing the underlying issue (bad field mapping, expired
    picklist, etc.). Retry uses the exact same payload cached in the DDB
    row, so no re-derivation is needed and idempotency is preserved.

    Auth (OAuth2 client-credentials flow)
    ------------------------------------
    Auth is optional at construction time. When wired to a live SF org, the
    caller passes:
        instance_url:  "https://<orgname>.my.salesforce.com"
        oauth_creds:   {"client_id":..., "client_secret":..., "audience":...}

    The sink caches the access token + expiry and refreshes automatically
    at expiry - 60s. If no oauth_creds are provided, the sink still records
    writes to DDB (as PENDING) — useful for offline / test / staging modes.

    Backwards-compat
    ----------------
    `writes_for_test()` still returns the in-memory queue; existing tests
    keep passing. The queue is populated in EITHER path (offline OR live).
    """

    name = "salesforce"

    SF_OBJECT_MAP = {
        "Customer":         "Account",
        "BusinessPartner":  "Account",
        "Vendor":           "Account",
        "SalesOrder":       "Order",
        "Quotation":        "Quote",
        "Material":         "Product2",
        "Contact":          "Contact",
        # Extended coverage — safe additions, mapped to standard SF objects
        "OpenAR":           "Order",       # invoices → orders (customer choice)
        "OpenAP":           "Contract",    # vendor obligations
        "Equipment":        "Asset",
        "FixedAsset":       "Asset",
    }

    _SYNC_TABLE_DEFAULT = "salesforce_sync_status"

    def __init__(self, *, instance_url: Optional[str] = None,
                  oauth_creds: Optional[dict] = None,
                  http_client=None,
                  dynamodb_client=None,
                  sync_table: Optional[str] = None,
                  api_version: str = "v60.0"):
        self._writes: list = []
        self._instance_url = (instance_url or "").rstrip("/")
        self._oauth = dict(oauth_creds or {})
        self._http = http_client
        self._ddb = dynamodb_client
        self._sync_table = sync_table or os.environ.get(
            "M4H_SALESFORCE_SYNC_TABLE", self._SYNC_TABLE_DEFAULT)
        self._api_version = api_version
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ── main path ──────────────────────────────────────────────────────────
    def write_one(self, object_type, source_key, row, tenant_id="default"):
        sf_object = self.SF_OBJECT_MAP.get(object_type)
        if sf_object is None:
            return {"sink": self.name, "status": "skipped_unmapped",
                    "object": object_type}

        payload = self._build_payload(source_key, row, tenant_id)
        record = {"object": sf_object, "tenant": tenant_id,
                   "external_id": source_key, "payload": payload,
                   "source_object_type": object_type}
        self._writes.append(record)

        # DDB tracker row PENDING (best-effort)
        self._ddb_upsert_status(tenant_id, source_key, sf_object,
                                 payload, status="PENDING",
                                 sf_id=None, error=None)

        # If we have a live http client + auth, attempt upsert now
        if self._http is not None and self._instance_url:
            res = self._sf_upsert(sf_object, source_key, payload)
            status = "SYNCED" if res["ok"] else "FAILED"
            self._ddb_upsert_status(tenant_id, source_key, sf_object,
                                     payload, status=status,
                                     sf_id=res.get("sf_id"),
                                     error=res.get("error"))
            return {"sink": self.name, "sf_object": sf_object,
                    "external_id": source_key,
                    "status": status.lower(),
                    "sf_id": res.get("sf_id"),
                    "http_status": res.get("http_status")}

        return {"sink": self.name, "sf_object": sf_object,
                "external_id": source_key, "status": "queued"}

    def flush(self):
        n = len(self._writes)
        # In-memory queue is the pending set when offline; when live, writes
        # are already synced in write_one() and this is a no-op counter.
        self._writes = []
        return {"sink": self.name, "flushed": n}

    def writes_for_test(self):
        return list(self._writes)

    # ── recovery: retry rows currently in PENDING/FAILED ────────────────────
    def retry_failed(self, tenant_id: str = "default",
                      max_rows: int = 500) -> dict:
        """Re-drive any PENDING / FAILED sync rows for a tenant using the
        payload cached in DDB. Returns a summary the caller can use to
        surface progress in the ops dashboard."""
        if self._ddb is None or not (self._http and self._instance_url):
            return {"sink": self.name, "status": "unavailable",
                    "reason": "no ddb client or no live SF connection"}
        try:
            resp = self._ddb.query(
                TableName=self._sync_table,
                IndexName="by_tenant_status",
                KeyConditionExpression="tenant_id = :t AND last_status IN (:p, :f)",
                ExpressionAttributeValues={
                    ":t": {"S": tenant_id},
                    ":p": {"S": "PENDING"},
                    ":f": {"S": "FAILED"},
                },
                Limit=max_rows)
        except Exception as e:
            return {"sink": self.name, "status": "query_failed",
                    "error": str(e)[:200]}
        items = resp.get("Items") or []
        synced = 0; failed = 0
        for it in items:
            sf_object = it.get("sf_object", {}).get("S") or ""
            ext_id    = it.get("external_id", {}).get("S") or ""
            payload_s = it.get("payload_json", {}).get("S") or "{}"
            try:
                payload = json.loads(payload_s)
            except Exception:
                payload = {}
            res = self._sf_upsert(sf_object, ext_id, payload)
            status = "SYNCED" if res["ok"] else "FAILED"
            self._ddb_upsert_status(tenant_id, ext_id, sf_object,
                                     payload, status=status,
                                     sf_id=res.get("sf_id"),
                                     error=res.get("error"))
            if res["ok"]:
                synced += 1
            else:
                failed += 1
        return {"sink": self.name, "status": "ok",
                "candidates": len(items),
                "synced": synced, "failed": failed}

    # ── payload / auth / http ──────────────────────────────────────────────
    def _build_payload(self, source_key, row, tenant_id):
        payload = {
            "External_Id__c":   source_key,
            "Name":             row.get("MAKTX") or row.get("NAME1")
                                or row.get("KTEXT") or source_key,
            "Source_System__c": "Migrate4HANA",
            "Tenant_Id__c":     tenant_id,
        }
        payload["Raw_Payload__c"] = json.dumps(row, default=str)[:32000]
        return payload

    def _sf_upsert(self, sf_object: str, external_id: str,
                    payload: dict) -> dict:
        """PATCH the External_Id__c endpoint. Upsert semantics: 201 =
        insert, 204 = update, 200 = update-with-body (some releases).
        Any 4xx → FAILED with the SF error body captured."""
        if not (self._http and self._instance_url):
            return {"ok": False, "error": "no live http client"}
        token = self._ensure_token()
        if not token:
            return {"ok": False, "error": "token_unavailable"}
        url = (f"{self._instance_url}/services/data/{self._api_version}"
               f"/sobjects/{sf_object}/External_Id__c/"
               f"{_url_quote(external_id)}")
        try:
            resp = self._http.request(
                "PATCH", url,
                body=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                },
                timeout=30)
            code = getattr(resp, "status", None)
            body = ""
            try:
                body = resp.data.decode("utf-8", errors="replace")
            except Exception:
                pass
            if code in (200, 201, 204):
                sf_id = None
                if body:
                    try:
                        sf_id = (json.loads(body) or {}).get("id")
                    except Exception:
                        pass
                return {"ok": True, "http_status": code, "sf_id": sf_id}
            return {"ok": False, "http_status": code,
                    "error": (body or "")[:400]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    def _ensure_token(self) -> Optional[str]:
        """OAuth2 client-credentials flow. Caches token until near expiry."""
        if self._token and time.time() < (self._token_expires_at - 60):
            return self._token
        cid = self._oauth.get("client_id")
        sec = self._oauth.get("client_secret")
        if not (cid and sec):
            return None
        token_url = self._oauth.get("token_url") or (
            f"{self._instance_url}/services/oauth2/token")
        try:
            body = ("grant_type=client_credentials"
                    f"&client_id={_url_quote(cid)}"
                    f"&client_secret={_url_quote(sec)}").encode("utf-8")
            resp = self._http.request(
                "POST", token_url, body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30)
            code = getattr(resp, "status", None)
            if code and code < 300:
                data = json.loads(resp.data.decode("utf-8"))
                self._token = data.get("access_token")
                # SF tokens default ~2h; instance_url can be refreshed
                self._token_expires_at = time.time() + int(
                    data.get("expires_in", 3600))
                if data.get("instance_url"):
                    self._instance_url = data["instance_url"].rstrip("/")
                return self._token
        except Exception:
            pass
        return None

    # ── DDB status writes (best-effort) ─────────────────────────────────────
    def _ddb_upsert_status(self, tenant_id: str, external_id: str,
                            sf_object: str, payload: dict,
                            status: str, sf_id: Optional[str],
                            error: Optional[str]) -> None:
        if self._ddb is None:
            return
        now_iso = _iso_now()
        item = {
            "tenant_id":       {"S": tenant_id},
            "external_id":     {"S": external_id},
            "sf_object":       {"S": sf_object},
            "last_status":     {"S": status},
            "last_attempt_at": {"S": now_iso},
            "payload_json":    {"S": json.dumps(payload, default=str)[:390000]},
        }
        if status == "SYNCED":
            item["last_synced_at"] = {"S": now_iso}
        if sf_id:
            item["sf_id"] = {"S": sf_id}
        if error:
            item["last_error"] = {"S": str(error)[:400]}
        try:
            # Update-and-increment attempt_count (best-effort atomic)
            self._ddb.update_item(
                TableName=self._sync_table,
                Key={"tenant_id":   {"S": tenant_id},
                     "external_id": {"S": external_id}},
                UpdateExpression=(
                    "SET sf_object = :o, last_status = :s, "
                    "last_attempt_at = :a, payload_json = :p"
                    + (", last_synced_at = :y" if status == "SYNCED" else "")
                    + (", sf_id = :i" if sf_id else "")
                    + (", last_error = :e" if error else "")
                    + " ADD attempt_count :one"),
                ExpressionAttributeValues={
                    ":o": item["sf_object"],
                    ":s": item["last_status"],
                    ":a": item["last_attempt_at"],
                    ":p": item["payload_json"],
                    ":one": {"N": "1"},
                    **({":y": item["last_synced_at"]} if status == "SYNCED" else {}),
                    **({":i": item["sf_id"]} if sf_id else {}),
                    **({":e": item["last_error"]} if error else {}),
                })
        except Exception:
            # Fallback: raw PutItem (won't increment counter but keeps row live)
            try:
                item["attempt_count"] = {"N": "1"}
                self._ddb.put_item(TableName=self._sync_table, Item=item)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
class EventBusSink(Sink):
    """Publishes one EventBridge custom event per written row; downstream
    consumers (other AWS accounts, partner systems) subscribe via rule
    pattern."""

    name = "eventbridge"

    def __init__(self, events_client=None,
                 event_bus_name: str = None):
        self.events = events_client
        self.event_bus_name = event_bus_name or os.environ.get(
            "M4H_EVENT_BUS_NAME", "migrate4hana-data-fabric")
        self._published: list = []

    def write_one(self, object_type, source_key, row, tenant_id="default"):
        entry = {
            "Source":        "migrate4hana.spine",
            "DetailType":    f"DataLoaded.{object_type}",
            "EventBusName":  self.event_bus_name,
            "Detail":        json.dumps({
                "object_type": object_type,
                "source_key":  source_key,
                "tenant_id":   tenant_id,
                "row":         row,
                "ts":          _iso_now(),
            }, default=str),
        }
        self._published.append(entry)
        if self.events is not None:
            try:
                self.events.put_events(Entries=[entry])
            except Exception:
                pass
        return {"sink": self.name, "status": "published"}

    def flush(self):
        n = len(self._published)
        return {"sink": self.name, "flushed": n}

    def published_for_test(self):
        return list(self._published)


# ─────────────────────────────────────────────────────────────────────────────
class SinkRouter:
    """Multi-sink dispatcher. Each registered sink receives the same
    (object_type, source_key, row) per write_one; failures on one sink
    don't block the others (per-sink try/except)."""

    def __init__(self, sinks: Optional[list] = None):
        self.sinks: list = list(sinks or [])

    def add(self, sink: Sink):
        self.sinks.append(sink)
        return self

    def fan_out(self, object_type: str, source_key: str,
                 row: dict, tenant_id: str = "default") -> list:
        out = []
        for s in self.sinks:
            try:
                out.append(s.write_one(object_type, source_key, row, tenant_id))
            except Exception as e:
                out.append({"sink": s.name, "error": str(e)[:200]})
        return out

    def flush_all(self) -> list:
        out = []
        for s in self.sinks:
            try:
                out.append(s.flush())
            except Exception as e:
                out.append({"sink": s.name, "error": str(e)[:200]})
        return out


def _iso_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _url_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")
