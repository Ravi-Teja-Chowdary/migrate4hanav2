# Value Mapping & Transformation Ruleset — Functional Consultant Guide

> The Migrate4HANA value-mapping layer lets you (a functional consultant) define
> how legacy ECC field values get translated to S/4HANA values **without
> touching Python code**. Everything is editable JSON in S3.

## TL;DR — The 3-step edit workflow

```powershell
# 1. Pull current files from S3 into the repo
.\scripts\manage-value-maps.ps1 -Action pull

# 2. Edit value-maps\matrix.json and/or value-maps\ruleset.json in any editor
#    (VS Code, Notepad++, even plain Notepad)

# 3. Push back (auto-validates first; refuses to push if either file is broken)
.\scripts\manage-value-maps.ps1 -Action push
```

The `push` action also flips the Lambda's `M4H_TRANSFORM_RULES` env var so the
new ruleset activates on the next cold start (or immediately if you re-run
`.\deploy-data-migrator.ps1`).

Want to see what's different from S3 without pulling? Use `-Action diff`.
Want to syntax-check your local edits? Use `-Action validate`.

---

## The two files explained

### `matrix.json` — the value-mapping tables

Each top-level key is a **named lookup table**. The contents are simple `source → target` key/value pairs.

```jsonc
{
  "company_code_map": {
    "1000": "US01",    // legacy ECC BUKRS=1000 maps to S/4 BUKRS=US01
    "2000": "DE01",
    "BP01": "US01"     // catches the alternate legacy alias
  },
  "currency_map": {
    "DEM": "EUR",      // German mark collapses to euro
    "FRF": "EUR",      // same for French franc
    "USD": "USD"       // pass-through when source = target (still document it!)
  }
}
```

Keys with a leading underscore (`_meta`, `_doc`) are **comments** — the engine ignores them, you keep them for documentation.

Source values are matched **case-insensitively after trim**, so `"  1000  "` and `"1000"` both hit `"1000"`.

### `ruleset.json` — the per-object transform pipeline

For each migration object (`Customer`, `Vendor`, ...), you list:

- `transforms[]` — what to do to the record (run in order, top to bottom)
- `dq_rules[]` — what makes a record valid (run after transforms; failures get quarantined as `DATA_QUALITY_REJECTION`)

```jsonc
{
  "object_rules": {
    "Customer": {
      "transforms": [
        { "type": "TRIM",      "field": "KUNNR" },
        { "type": "UPPER",     "field": "LAND1" },
        { "type": "VALUE_MAP", "field": "LAND1", "table": "country_map",       "on_missing": "keep" },
        { "type": "VALUE_MAP", "field": "BUKRS", "table": "company_code_map",  "on_missing": "keep" },
        { "type": "VALUE_MAP", "field": "WAERS", "table": "currency_map",      "on_missing": "default", "default": "EUR" }
      ],
      "dq_rules": [
        { "type": "MANDATORY",   "field": "KUNNR" },
        { "type": "MAX_LEN",     "field": "NAME1", "len": 35 },
        { "type": "REGEX_VALID", "field": "LAND1", "pattern": "^[A-Z]{2}$" }
      ]
    }
  }
}
```

---

## Transform reference

| Type | Required keys | Optional keys | What it does |
|---|---|---|---|
| `FIELD_MAP` | `source`, `target` | `default`, `drop_source` | Copy/rename a field. If source is null and `default` set, uses default. If `drop_source=true`, removes the original. |
| `VALUE_MAP` | `field`, `table` | `on_missing` (`keep` \| `default` \| `reject`), `default`, `reject_sentinel` | Translate via a named matrix table. `keep` = leave original unchanged. `default` = use `default`. `reject` = inject `__UNMAPPED__` (pair with a `MANDATORY` or `ALLOWED` DQ rule to flush it). |
| `REGEX_CLEANSE` | `field`, `pattern` | `replacement` (default `""`), `flags` | Scrub dirty data via regex sub. E.g. `pattern: "\\s{2,}", replacement: " "` collapses double-spaces. |
| `CONST` | `field`, `value` | – | Set a field to a constant value (useful for `MANDT` = client, `KOKRS` = controlling area). |
| `TRIM` | `field` | – | Strip leading + trailing whitespace. |
| `UPPER` | `field` | – | Uppercase the value. |
| `PAD` | `field`, `width` | `char` (default `"0"`), `side` (`left` \| `right`) | Pad to fixed width. E.g. left-pad MATNR to 18 zeros. |

## DQ gate reference

| Type | Required keys | Optional keys | Rejects when... |
|---|---|---|---|
| `MANDATORY` | `field` | – | Field is missing, null, or empty string. |
| `REGEX_VALID` | `field`, `pattern` | `flags` | Value doesn't match the regex. |
| `MAX_LEN` | `field`, `len` | – | `str(value)` is longer than `len`. |
| `ALLOWED` | `field`, `values[]` | – | Value isn't in the list (case-insensitive). |
| `UNIQUE` | `field` | – | Same value seen before in the same run (cross-record). |
| `CROSS_FIELD_VALIDATE` | `expect: {field, op, value}` | – | Business rule fails (`op` = `eq`/`ne`/`in`/`startswith`/`endswith`). |

A rejected record becomes a **dead-letter** entry with `status: "DATA_QUALITY_REJECTION"` and detailed reasons — never sent to BAPI, never silently dropped.

---

## Walkthroughs

### "I need to add a new company code mapping"

```powershell
.\scripts\manage-value-maps.ps1 -Action pull
```

Open `value-maps\matrix.json`, find `"company_code_map"`, add your line:

```json
"company_code_map": {
  "1000": "US01",
  "2000": "DE01",
  "7000": "CA01"      <-- new
}
```

```powershell
.\scripts\manage-value-maps.ps1 -Action validate    # sanity check
.\scripts\manage-value-maps.ps1 -Action push        # uploads + activates
```

Done. The next data-migrator invocation will use the new mapping.

### "I need to reject customers without a valid email"

Add a DQ rule to `Customer`:

```json
"dq_rules": [
  ...existing rules...,
  { "type": "REGEX_VALID", "field": "SMTP_ADDR",
    "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$" }
]
```

Customers with malformed SMTP_ADDR will go to dead-letter with reason
`field SMTP_ADDR value 'xxx' fails pattern ...`.

### "I want to merge plants 1100 + 1200 into a single plant P100"

In `matrix.json`:

```json
"plant_map": {
  "1100": "P100",
  "1200": "P100",
  "2100": "P200"
}
```

Then in `ruleset.json` add a transform to the object that has the WERKS field:

```json
{ "type": "VALUE_MAP", "field": "WERKS", "table": "plant_map", "on_missing": "keep" }
```

`push` + done. Both legacy plants now collapse into `P100`.

### "I want to validate my edits before pushing"

```powershell
.\scripts\manage-value-maps.ps1 -Action validate
```

Output:
```
==> Validating matrix.json
    company_code_map            7 entries
    currency_map               17 entries
    ...
    -> 10 tables, 72 entries total

==> Validating ruleset.json
    Customer          8 transforms   5 DQ gates
    Vendor            7 transforms   3 DQ gates
    ...
    -> ruleset OK

Validation: PASS
```

Any JSON syntax error or missing required field fails the validation with a
clear message + the file refuses to push.

---

## How it works behind the scenes (one paragraph)

When the data-migrator Lambda starts, `transformation_engine.from_env()` reads
two env vars: `M4H_TRANSFORM_RULES` (the S3 URI of the ruleset) and
`M4H_MAPPING_S3` (the S3 URI of the matrix). It downloads both, validates the
schema, pre-compiles every regex, and hands the `TransformationEngine` to the
`UnifiedLoader`. For every record extracted from ECC, the engine runs the
object's transform pipeline in order, then evaluates the DQ gates. Passing
records flow on to the BAPI factory; failing records become dead-letter audit
entries with their rejection reasons. **The engine never raises** — a malformed
transform turns into a DQ rejection, never a crashed load.

---

## When to NOT use this layer

The transformation engine is **deterministic and stateless per record** (except
`UNIQUE`). It's the right tool for:

- Cross-system value translations (`DEM → EUR`, `1000 → US01`)
- Field renaming + reshaping
- Per-field validation
- Simple cleansing

It's NOT the right tool for:

- **Cross-object key resolution** (e.g. "this sales order's KUNNR was renumbered
  to a new BP_ID in the customer load earlier"). That's what the runtime
  key_map (DynamoDB) does — see `lambda/utils/key_map.py`.
- **Multi-row aggregation** (e.g. "summarize this customer's open items into
  a single carry-forward balance"). That's a custom batch job, not a transform.
- **Decisions that need an LLM** (e.g. "infer the right tax category from
  free-text product descriptions"). That's the code-analyzer remediation lane.

Use the right tool for the right job.

---

## Reference

- Engine source: `lambda/utils/transformation_engine.py`
- Default seed files: `value-maps/matrix.json` + `value-maps/ruleset.json`
- Admin script: `scripts/manage-value-maps.ps1`
- Unit tests (cover all transform + DQ ops): `tests/test_transformation_ruleset.py`
- Activation env vars on data-migrator Lambda:
  - `M4H_TRANSFORM_RULES = "s3://<mapping-bucket>/mappings/ruleset.json"`
  - `M4H_MAPPING_S3      = "s3://<mapping-bucket>/mappings/matrix.json"`
