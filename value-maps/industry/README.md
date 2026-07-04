# Industry variant value maps

Value-map addenda that widen the base `../matrix.json` for specific
industries. Each file is deep-merged into the base matrix at runtime when
the deploy flag `M4H_INDUSTRY_VARIANT=<industry>` is set. Ruleset entries
that reference table names introduced here will resolve to the merged
value on lookup.

Priority ordering (lowest -> highest, later wins):
  1. `matrix.json`          — universal base
  2. `industry/<name>.json` — industry-specific additions & overrides
  3. `matrix.override.json` — per-tenant overrides (customer-specific)

The industry files DO NOT redefine everything from the base — they only
add or override what's meaningfully different. Fields that are common
across industries (currency, country, language) stay in the base map.

Supported industries (2026-07-03):
  - **retail**          — EAN types, seasonality, colour codes, size grid
  - **pharma**          — GMP compliance flags, batch expiry indicators
  - **discrete_mfg**    — BOM usage types, engineering change codes
  - **utility**         — functional location types, meter categories

## How to activate an industry variant

```powershell
# Lambda env var (via terraform.tfvars or aws lambda update-function-configuration)
M4H_INDUSTRY_VARIANT = "retail"

# Or via the wizard UI: "Industry template" dropdown on the scope step.
```

## Cross-industry deep-merge rules

- Scalar keys in the industry file **override** the base value.
- Objects (`{...}`) are recursively deep-merged; keys in the industry file
  take precedence.
- Arrays are **replaced** wholesale (not appended); the industry file must
  ship the complete replacement.

## Adding a new industry variant

1. Copy `retail.json` as a starting template.
2. Rename the top-level `_meta.variant` field.
3. Keep only the tables you want to override / add.
4. Test locally with `python -m lambda.utils.transformation_engine
   --matrix value-maps/matrix.json --industry value-maps/industry/<name>.json`.
