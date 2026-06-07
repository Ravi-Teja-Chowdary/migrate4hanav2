# Dynamic Schema Guide — DDIC-introspected BAPI field catalogs

> Migrate4HANA's field-coverage gate (the layer that decides which custom
> ZZ_*/CI_* fields a BAPI can actually transport, vs. which must go to the
> LTMC staging file) has two operating modes:
>
> - **Static** (default): a hand-curated baseline in `lambda/utils/bapi_field_catalog.py`.
>   Stable, hand-reviewed. Same shape across all customers. ~25 objects.
> - **Dynamic** (F3, this guide): runtime DDIC introspection against the live
>   target. Self-updating per customer + per S/4 release. No code change when
>   a customer extends a BAPI with a BADI append.
>
> Both modes are wired. Dynamic activates when you set one env var on the
> Lambda; otherwise the static baseline is used unchanged.

## TL;DR — turn dynamic schema on

```powershell
aws lambda update-function-configuration --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --environment "Variables={M4H_DYNAMIC_SCHEMA_S3=s3://migrate4hana-schemas-prod/dynamic-schema}"
```

Make sure the bucket exists (one-time):

```powershell
aws s3 mb s3://migrate4hana-schemas-prod --region us-east-1
```

The next data-migrator run will:
1. Read the target S/4's DDIC at startup via `DD_BAPI_PARAMETER_GET`
2. Cache the compiled field sets in S3 with a 7-day TTL
3. Use them as the field-coverage gate input for the rest of the run

Subsequent runs against the same target reuse the cache — startup cost is paid once per landscape.

## What gets cached + where

```
s3://migrate4hana-schemas-prod/dynamic-schema/<SID>/<CLIENT>/<S4_RELEASE>/<OBJECT>.json
```

Example: `s3://migrate4hana-schemas-prod/dynamic-schema/S4H/100/S4HANA_2023/Material.json`

Cache payload:

```json
{
  "sid": "S4H",
  "client": "100",
  "s4_release": "S4HANA_2023",
  "object_type": "Material",
  "bapi": "BAPI_MATERIAL_SAVEDATA",
  "fields": ["MATERIAL", "MATL_TYPE", "BASE_UOM", "PLANT", ...],
  "written_at": 1717830000.0,
  "source": "rfc"
}
```

`source` tells you where it came from: `"rfc"` (introspected from the live target), `"fallback"` (used the static baseline because RFC failed), or `"manual"` (a human-edited cache file).

## The 3-tier resolution chain

Per object on every cold start (or after the TTL expires):

```
1. S3 cache (fresh?)                 -> use it (zero RFC calls)
2. RFC introspect via DD_BAPI_PARAMETER_GET   -> compile + cache the result
3. RFC fallback via DD03L                      -> compile + cache the result
4. Static catalog (bapi_field_catalog.py)     -> use it (no cache write)
```

Failures at any tier bubble cleanly to the next. The field-coverage gate never crashes a run.

## When dynamic > static

- **Customer has BADI-extended a BAPI.** Static knows nothing about `BAPI_TE_KNA1` additions; dynamic picks them up the moment the customer's S/4 introspects.
- **S/4 release upgrade.** Static was hand-curated against S/4 2021; the customer upgrades to S/4 2025 with a 12-field BAPI extension. Static lags; dynamic stays current.
- **Multi-target landscapes.** A customer with 4 different S/4 tenants (dev/qual/prod/dr) gets per-tenant catalogs cached separately.

## When static is fine

- POC or evaluation runs against the SAP IDES Fully-Activated Appliance.
- Single S/4 target with no customer extensions.
- Cost-sensitive setups that want to avoid one extra RFC round-trip per cold start.

## Cache lifecycle controls

```
M4H_DYNAMIC_SCHEMA_S3            "s3://bucket/prefix"   (empty = static only)
M4H_DYNAMIC_SCHEMA_TTL_SEC       7 days (= 604800)
M4H_TARGET_RELEASE               "S4HANA_2023"  (informational; goes into cache key)
```

To force a refresh (e.g. after the customer ships a BADI):

```bash
# Just delete the cached object - the next run rebuilds from RFC
aws s3 rm s3://migrate4hana-schemas-prod/dynamic-schema/S4H/100/S4HANA_2023/Material.json
```

Or pass `force_refresh=True` programmatically from a one-off script:

```python
from dynamic_schema_builder import build_schema
schema = build_schema("Material", conn=target_conn,
                       sid="S4H", client="100", s4_release="S4HANA_2023",
                       cache_s3_uri="s3://migrate4hana-schemas-prod/dynamic-schema",
                       force_refresh=True)
```

## How the field-coverage gate uses the catalog

Inside `lambda/utils/bapi_coverage.py`, the gate:

1. Receives a record (e.g. `{KUNNR, NAME1, ZZ_LOYALTY, ZZ_FRAUD_RISK}`)
2. Looks up the field set for object `Customer` (dynamic if configured, else static)
3. Computes the **delta** — keys present in the record but not in the catalog (`{ZZ_LOYALTY, ZZ_FRAUD_RISK}`)
4. Routes the delta to an LTMC staging file (preserved for manual import) and lets the BAPI take only the supported fields
5. The spine orchestrator (F2) gets the catalog as `loader.bapi_field_catalog` and uses it to **drop** Z fields that aren't transportable from `EXTENSIONIN` (counts the drops as a quality metric)

## When you'd want to introspect manually

You're debugging a customer's BAPI extension and want to know exactly what fields their S/4 thinks `BAPI_CUSTOMER_CREATEFROMDATA1` supports. Quick local script:

```python
import sys; sys.path.insert(0, "lambda/utils")
from pyrfc import Connection
from dynamic_schema_builder import build_schema, introspect_via_dd_bapi_parameter_get

# Open a connection to the customer's S/4 dev system
conn = Connection(ashost="customer-s4-dev", sysnr="00", client="100",
                  user="MIGRATE_ADMI", passwd="...", lang="EN")

# Either get the compiled set:
schema = build_schema("Customer", conn=conn, sid="S4D", client="100",
                      s4_release="CUSTOMER_DEV")
print(sorted(schema.fields))

# Or get the raw introspection rows for debugging:
print(introspect_via_dd_bapi_parameter_get(conn, "BAPI_CUSTOMER_CREATEFROMDATA1"))
```

## Validation status

- **Module + cache logic**: 15 unit tests, all green (mocked RFC + mocked S3).
- **Real-system introspection**: deferred to F5 Phase B (needs S/4 tunnel hot to actually call DDIC).
- **End-to-end Lambda integration**: code-complete; sets `loader.bapi_field_catalog` from dynamic results when `M4H_DYNAMIC_SCHEMA_S3` is set; falls back gracefully on any failure.

## Reference

- Module: `lambda/utils/dynamic_schema_builder.py`
- Static fallback: `lambda/utils/bapi_field_catalog.py`
- Field-coverage gate: `lambda/utils/bapi_coverage.py`
- Tests: `tests/test_dynamic_schema_builder.py` (15 tests)
- Wiring: `lambda/data-migrator/handler.py` — search for `dynamic_schema_active`
- Cache bucket: `s3://migrate4hana-schemas-<env>` (set via `M4H_DYNAMIC_SCHEMA_S3`)
