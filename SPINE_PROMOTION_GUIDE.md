# Spine Promotion Guide — turning a staging object into a fully automated load

> Migrate4HANA has two delivery tiers for object support:
>
> - **Staging-file tier** (127 objects today): the data-migrator extracts ECC rows
>   and writes a Migration Cockpit template CSV. A human drives the import via
>   MC. Working but labor-intensive.
> - **Spine tier** (25 objects today, growing): the orchestrator drives the
>   full extract → transform → DQ → FK-resolve → BAPI/OData → reconcile → audit
>   cycle automatically. This is the **production** target.
>
> F2 introduced `BaseSpineOrchestrator`. This guide is how you promote any
> staging-tier object onto the spine in ~150 LOC.

## When to promote an object

Promote when:

- It has a stable, supported SAP BAPI / OData service (look in `bapi_loader.py` first)
- Customer cutover scenarios actually use it in volume (>1k records typical)
- The legacy LSMW/MC import is the bottleneck

Stay on the staging tier when:

- The object is so configuration-dependent it's basically a customising migration (use BC sets)
- No supported BAPI exists (e.g. some PP master data — promotion has to wait for OData coverage in the target release)
- The current MC flow is fine and volume is low

## The 6-step promotion pattern

### 1. Pick the source key field

The single field whose value is the object's primary identity:

```
Customer → KUNNR    Vendor → LIFNR    Material → MATNR    Asset → ANLN1+ANLN2
```

### 2. Pick the target BAPI signature + the EXTENSIONIN structure name

Two things to know about your target:

- The BAPI function module name and its HEADDATA + sub-tables
- The append structure used for the custom fields (`BAPI_TE_xxx`, conventionally `BAPI_TE_<source-table>`)

Easiest way: open SE37 in the target system, plug in the BAPI name, and read the import/table parameters.

### 3. Write the subclass — ~150 LOC

Example, abbreviated, for `BankAccount`:

```python
from base_spine_orchestrator import BaseSpineOrchestrator, register_spine

@register_spine
class BankAccountSpineOrchestrator(BaseSpineOrchestrator):
    object_type           = "BankAccount"
    source_key_field      = "BANKL"
    extension_structure   = "BAPI_TE_BNKA"
    fk_fields             = {}      # bank country LAND1 is customising, not migration ledger

    def build_payload(self, row, ext_rows):
        return {
            "BANK_CTRY": row["BANKS"],
            "BANK_KEY":  row["BANKL"],
            "BANK_NAME": row.get("BANKA") or "",
            "CITY":      row.get("ORT01") or "",
            "EXTENSIONIN":  ext_rows,
        }

    def call_bapi(self, payload):
        resp = self.c.call("BAPI_BANK_CREATE", **payload)
        ret  = resp.get("RETURN") or {}
        if isinstance(ret, dict): ret = [ret]
        if any(m.get("TYPE") in ("E","A") for m in ret):
            return None, [m["MESSAGE"] for m in ret]
        return payload["BANK_KEY"], [m["MESSAGE"] for m in ret]
```

That's it for the simplest case. The base class provides:

- Lifecycle (`load_one` runs transform → validate → FK resolve → ZZ-field packing → build → BAPI)
- `TransformationEngine` (F4) integration — DQ rejections become clean dead-letters
- `PersistentKeyMap` (F1) integration — registers `(source, target)` so dependent objects find it
- EXTENSIONIN packing + EXTENSIONINX activation
- Field-coverage gate (drops Z fields not in the BAPI catalogue, counts the drops as a quality metric)
- Stats (`SpineStats`) — attempts, created, matched_existing, remapped, dead_letter, dropped Z fields
- Concurrency-safe (`load_many` is sequential; for parallel pools each thread gets its own orchestrator instance)
- Dry-run mode for plan-only smoke tests

### 4. Deeper objects: subtables (MARC/MARD/MBEW/PARTNERS/CONDITIONS/TEXTS)

For objects with subtables, `build_payload` returns a `dict` with the subtable keys; the base class's `load_one` automatically counts `PARTNERS` / `ORDER_PARTNERS` / `CONDITIONS_IN` / `LONGTEXTS` rows into the `LoadResult`.

Reusable helpers in `base_spine_orchestrator.py`:

```python
normalise_partner_rows(rows, role_field="PARVW", number_field="KUNNR",
                       key_map=self.key_map, source_object="Customer")
normalise_condition_rows(rows, item_index=10)
normalise_text_rows(rows, langu="EN")
```

`MaterialSpineOrchestrator` (`lambda/utils/material_spine.py`) is the canonical worked example — MARA + MARC + MARD + MBEW + MARM + MAKT subtables + Z-field absorption in ~250 LOC.

### 5. Override the lifecycle hooks where needed

- `transform(row)` — default applies `self.transformer`; override for object-specific pre-cleansing
- `validate(row)` — default returns None; override to return an error string for non-DQ rejections
- `resolve_fk(row)` — default uses `fk_fields` to look up registry; override for composite or conditional FK resolution
- `build_payload(row, ext_rows)` — REQUIRED
- `call_bapi(payload)` — REQUIRED; must return `(target_key, messages)`

### 6. Test it

Copy `tests/test_spine_orchestrator.py` and adapt the `_ToySpine` pattern. Mock SAP via `FakeRfcConnection`, drive happy path + every dead-letter code + Z-field absorption + dry-run. Aim for ~12 tests per object; each takes ~10 minutes to write.

## Where the spine plugs into the existing pipeline

`UnifiedLoader.load_object(obj, rows, max_rows)` now consults the spine registry FIRST:

```
get_spine("Material") -> MaterialSpineOrchestrator    -> use the spine path
get_spine("Customer") -> None (not yet promoted)      -> fall through to legacy BapiLoader path
```

Adding a new spine is **purely additive**. Existing objects keep their legacy code paths until they're individually promoted; nothing breaks on day one.

## The dead-letter taxonomy

Every dead-letter carries a code so the operator can route by failure mode:

| Code | Meaning | Likely cause |
|---|---|---|
| `DATA_QUALITY_REJECTION` | DQ gate from `TransformationEngine` rejected | Mandatory field missing, regex failed, etc. — fix in the source extract or the F4 ruleset |
| `MISSING_DEPENDENCY` | FK can't resolve (e.g. SO references unknown Customer) | Earlier object failed to load; rerun in DAG order |
| `BAPI_FAILURE` | SAP BAPI returned an error or raised | Read `messages`; rollback already happened |
| `TARGET_COLLISION` | Source key already names a *different* object in target | Re-run with collision strategy = `remap` |
| `EXTENSIONIN_OVERFLOW` | More than 100 Z fields per record | Probably bad mapping; review source EXTENSIONIN list |

## Reference

- Base class: `lambda/utils/base_spine_orchestrator.py`
- Worked example: `lambda/utils/material_spine.py` (Material Master, deep view)
- Tests: `tests/test_spine_orchestrator.py` (20 tests, all green)
- Dispatcher integration: `lambda/utils/unified_loader.py` (`_load_via_spine` + registry check)
- F1 key_map: see `[[ngrok-local-ecc-bridge]]` for the live cross-run ledger semantics
- F4 transformation: see `VALUE_MAPPING_GUIDE.md` for ruleset authoring

## What needs validation against a real SAP system

The unit tests use a mocked `FakeRfcConnection`. Before promoting an object in production:

1. Run `BankAccountSpineOrchestrator(real_conn).load_one(real_row)` from a Lambda invoke
2. Check the `samples` field of the result — confirm the actually-loaded record matches the source
3. Run reconciliation against the freshly-loaded target — counts must match

For Material specifically, the Phase B validation steps (once your ECC + S/4 tunnel is up):

```powershell
# 1) Stage a small Material extract
$payload = @{
    run_id        = "f2-material-validate-001"
    ecc_secret_id = "migrate4hana/prod/sap-credentials"
    object_spec   = @{ object = "Material"; source_table = "MARA";
                       fields = @("MATNR","MTART","MBRSH","MEINS","MATKL"); lane = "MC" }
} | ConvertTo-Json -Depth 4 -Compress
$payload | Out-File -Encoding ASCII payload.json

aws lambda invoke --region us-east-1 --function-name migrate4hana-data-migrator-prod `
    --cli-binary-format raw-in-base64-out --payload file://payload.json f2-stage.json

# 2) Flip the load-to-S4 env var, then re-run with the spine path; verify the
#    MaterialSpineOrchestrator drives BAPI_MATERIAL_SAVEDATA on the real target.
aws lambda update-function-configuration --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --environment "Variables={M4H_LOAD_TO_S4=1, M4H_LOAD_MAX_ROWS=3}"
```

(Tracked under F5 - scale benchmark and real-S/4 validation share the same connectivity prerequisites.)
