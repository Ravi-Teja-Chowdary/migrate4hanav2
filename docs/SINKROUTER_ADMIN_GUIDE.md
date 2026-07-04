# SinkRouter admin guide

Ops-facing reference for the four sinks the WS4 SinkRouter fans out to.

## The sinks

| Sink | Destination | Contract shape |
|---|---|---|
| `SnowflakeSink`   | S3 JSONL stage → Snowpipe auto-ingest | Row buffered per (tenant, object); flush writes `.jsonl` batches |
| `S3ParquetSink`   | S3 clean-room in Hive-partitioned JSONL (Parquet in future) | `tenant=<>/object=<>/date=<>` |
| `SalesforceSink`  | Salesforce REST upsert via `External_Id__c` | PATCH per row; DDB tracks status |
| `EventBusSink`    | EventBridge custom bus `Migrate4HANA.spine` | `DetailType=DataLoaded.<obj>` |

## 1. Configuring the router

```python
from lambda.utils.sink_router import (
    SinkRouter, SnowflakeSink, S3ParquetSink,
    SalesforceSink, EventBusSink)
import boto3
import urllib3

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")
events = boto3.client("events")

router = SinkRouter(sinks=[
    SnowflakeSink(s3_client=s3, stage_bucket="m4h-snowflake-stage-prod"),
    S3ParquetSink(s3_client=s3, archive_bucket="m4h-clean-room-prod"),
    SalesforceSink(
        instance_url="https://acme.my.salesforce.com",
        oauth_creds=<load from Secrets Manager>,
        http_client=urllib3.PoolManager(),
        dynamodb_client=ddb),
    EventBusSink(events_client=events,
                  event_bus_name="migrate4hana-data-fabric"),
])
```

Wire into the spine's post-BAPI callback so every SUCCESSFUL row also
fans out to the sinks:

```python
def _post_load(row, disposition, spine):
    if disposition in ("created", "matched_existing"):
        router.fan_out(spine.object_type, row["source_key"], row,
                        tenant_id=spine.tenant_id)
```

## 2. Snowflake sink

### 2.1 What lands in S3

Each `flush()` writes one JSONL file per (tenant, object) into:

```
s3://<stage_bucket>/snowflake-stage/<tenant>/<object>/<epoch>.jsonl
```

Row shape:
```json
{"source_key": "MAT001", "row": {"MAKTX": "Widget", ...}, "_loaded_at": "2026-07-03T..."}
```

### 2.2 Snowpipe wiring

- Terraform: `terraform/modules/snowpipe/`
- SQL: `scripts/snowpipe/snowflake_side.sql`
- Verifier: `lambda/snowpipe-verifier/handler.py`

The verifier queries `m4h_raw` every 15 minutes and publishes:
- `Migrate4HANA/Snowpipe/RowsLoaded` (dims: Tenant, ObjectType)
- `Migrate4HANA/Snowpipe/PipeStuckSeconds` (freshness)

### 2.3 Common issues

| Symptom | Cause | Fix |
|---|---|---|
| Files sit in S3 stage but never load | Snowpipe not subscribed to SNS | Check `terraform output snowpipe_sns_topic_arn` matches `NOTIFICATION_CHANNEL` on the PIPE |
| Load history empty | Storage integration lost external ID | Re-run `DESC STORAGE INTEGRATION` + update `terraform.tfvars` |
| Verifier emits `VerifierFailed=1` | JWT signing failed | Check `cryptography` lib in Lambda layer + Secret payload has valid PEM |

## 3. Salesforce sink

### 3.1 Auth model

OAuth2 client-credentials flow (Salesforce Connected App with
"Enable Client Credentials Flow" checked). The sink caches the token
until 60s before expiry, then refreshes.

### 3.2 Upsert semantics

`PATCH /services/data/v60.0/sobjects/<Object>/External_Id__c/<id>`

- 201 = insert
- 204 = update
- 200 = update with body (some releases)
- 4xx = FAILED with the SF error body captured

Upsert is inherently idempotent — re-running the same load cannot create
duplicates.

### 3.3 DDB tracker (`salesforce_sync_status`)

Every write records:

| Attribute | Purpose |
|---|---|
| `tenant_id` (HK) | Multi-tenant partition |
| `external_id` (RK) | SAP source key |
| `sf_object` | Account / Contact / Order / Product2 / etc |
| `last_status` | PENDING / SYNCED / FAILED |
| `attempt_count` | Monotonic counter |
| `last_synced_at` | ISO-8601 UTC (set only on SYNCED) |
| `last_error` | Truncated to 400 chars |
| `sf_id` | Salesforce's internal ID (set on 2xx response bodies) |
| `payload_json` | Cached upsert payload for retry_failed() |

GSI `by_tenant_status` lets you list FAILED rows per tenant in O(hits).

### 3.4 Retry FAILED rows

```python
result = sink.retry_failed(tenant_id="acme", max_rows=500)
# {"synced": <n>, "failed": <n>, "candidates": <total>}
```

Idempotent — safe to call on a cron.

### 3.5 Common issues

| Symptom | Cause | Fix |
|---|---|---|
| All rows FAILED with `DUPLICATES_DETECTED` | SF matching rule active | Disable rule for `External_Id__c` field |
| All rows FAILED with 401 | Token expired mid-batch | Sink auto-refreshes; if this persists, check Connected App status |
| Sync status stays PENDING | No http_client configured | Set `M4H_SALESFORCE_INSTANCE_URL` + secret ARN |
| Payload > 40 KB | SF Base-64 body cap | Sink truncates `Raw_Payload__c` to 32 KB; extend via custom `_build_payload` |

## 4. S3 Parquet sink

Currently ships as JSONL for Lambda-runtime compatibility. Convert to
Parquet post-write via a Glue crawler or Athena `CREATE TABLE AS`:

```sql
CREATE TABLE m4h_lake_parquet WITH (
    format = 'PARQUET',
    external_location = 's3://m4h-clean-room-prod/parquet/'
) AS SELECT * FROM m4h_lake_jsonl;
```

Partitions are already Hive-style so Athena picks them up automatically.

## 5. EventBridge sink

Fires one event per row to bus `migrate4hana-data-fabric`. Downstream
subscribers pattern-match on `DetailType = DataLoaded.<object>`.

Example downstream rule:

```json
{
  "source":     ["migrate4hana.spine"],
  "detail-type": ["DataLoaded.Customer"]
}
```

## 6. Fault isolation

`SinkRouter.fan_out()` catches per-sink exceptions and continues. One sink
failing does NOT block the others. The result list includes `{"sink": X,
"error": "..."}` for each failure so downstream code can page selectively.

## 7. Observability

CloudWatch metric namespace `Migrate4HANA/Sink`:
- `sink.fanout.count` (dim: sink)
- `sink.fanout.error` (dim: sink)
- `sink.flush.rows` (dim: sink)

Alarms wired in `terraform/modules/observability/` fire when any sink's
error rate exceeds 5% over 10 minutes.
