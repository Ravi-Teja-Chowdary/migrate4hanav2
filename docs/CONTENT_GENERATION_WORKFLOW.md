# Content generation workflow — enterprise-hardening pass 2026-07-03

How to regenerate the field catalogs, mapping matrices, dependency DAGs,
and MC templates for a new target release without hand-editing any of
those files.

## The four content assets

| Asset | File | Regeneration tool |
|---|---|---|
| BAPI field catalog | `lambda/utils/bapi_field_catalog.py` + `value-maps/bapi_field_catalog.<release>.json` | `scripts/generate_field_catalog.ps1` |
| Value-mapping matrix | `value-maps/matrix.json` + `value-maps/industry/<variant>.json` | manual edit (curated) |
| Dependency DAG | `lambda/utils/dependency_dag.py` | manual + `scripts/visualize_dag.py` |
| MC file templates | `lambda/utils/mc_file_exporter.py::MC_TEMPLATES` | manual + `register_template_extension()` |

## 1. BAPI field catalog

### 1.1 Regenerate against a new target release

```powershell
.\scripts\generate_field_catalog.ps1 `
    -Host vhcalabaci -SystemNumber 00 -Client 100 `
    -User ATH -Passwd '****' -Release S4H2023

# Output: value-maps/bapi_field_catalog.S4H2023.json
```

Under the hood the script:
1. Reads `scripts/bapi_map.json` — the `object_type → FM name` map
2. For each FM, calls `RFC_GET_FUNCTION_INTERFACE` (SAP-released
   introspection) to walk the parameter tree
3. For each table/structure parameter, calls `DDIF_FIELDINFO_GET`
   (SAP-released) to expand its field list from DD03L
4. Merges with the in-code baseline (`bapi_field_catalog.as_dict()`)
5. Writes the union to `value-maps/bapi_field_catalog.<release>.json`

The script does NOT call any non-released FM. No custom Z-code is
transported. All introspection is read-only.

### 1.2 Activate the generated catalog in Lambda

```powershell
aws lambda update-function-configuration `
    --function-name migrate4hana-data-migrator-prod `
    --environment 'Variables={M4H_BAPI_FIELD_CATALOG_JSON=value-maps/bapi_field_catalog.S4H2023.json}'
```

`bapi_field_catalog._load_env_addendum()` picks up this path at import
time and merges over the baseline. No code change or redeploy needed.

### 1.3 Verify coverage

```powershell
python -c "
import os; os.environ['M4H_BAPI_FIELD_CATALOG_JSON']='value-maps/bapi_field_catalog.S4H2023.json'
import sys; sys.path.insert(0,'lambda/utils')
from bapi_field_catalog import known_objects, for_object
print('objects:', len(known_objects()))
for o in sorted(known_objects()):
    print(f'  {o:30s} {len(for_object(o))} fields')
"
```

## 2. Value-mapping matrix — industry variants

The base map lives at `value-maps/matrix.json`. Industry-specific overrides
live at `value-maps/industry/<variant>.json`:

- `retail.json`       — EAN types, seasons, colour + size grids
- `pharma.json`       — GMP flags, batch status, DEA schedule
- `discrete_mfg.json` — BOM usage, lot size, MRP type
- `utility.json`      — funcloc categories, meter types, tariff codes

### 2.1 Activate an industry variant

```powershell
# Runtime — merged over base
aws lambda update-function-configuration `
    --function-name migrate4hana-data-migrator-prod `
    --environment 'Variables={M4H_INDUSTRY_VARIANT=retail}'
```

The industry file is deep-merged into `matrix.json` at runtime; scalar
keys are overridden, object keys are recursively merged, array keys are
replaced wholesale.

### 2.2 Add a new industry

1. Copy `value-maps/industry/retail.json` to a new file
2. Rename `_meta.variant`
3. Keep only the tables that meaningfully differ from the base
4. Test with:
```powershell
python lambda/utils/transformation_engine.py `
    --matrix value-maps/matrix.json `
    --industry value-maps/industry/<new>.json `
    --sample-object Material
```

## 3. Dependency DAG

The DAG is declared in `lambda/utils/dependency_dag.py::DependencyDAG.from_defaults()`
as a `{dependent: {required...}}` dict. To add an object:

```python
# In from_defaults():
"MyNewObject": {"Material", "CustomerHierarchy"},
```

The topological sort auto-picks it up. Cycle detection runs on every
sort. Missing masters are pulled in transitively when `scope` is used.

### 3.1 Visualise for stakeholder review

```powershell
python scripts\visualize_dag.py --out dag.dot
dot -Tsvg dag.dot -o dag.svg     # requires Graphviz
dot -Tpng dag.dot -o dag.png
```

Nodes are colour-coded by lane:
- 🔵 blue      — BAPI-lane
- 🟣 purple    — MC file-lane
- 🟠 orange    — IDoc-lane
- ⚫ grey      — other/unassigned

### 3.2 Scope-limited render

For a targeted "what has to happen before this object?" diagram:

```powershell
python scripts\visualize_dag.py --scope OutboundDelivery,IncomingInvoice
```

Only the two objects + their transitive dependencies land in the DOT.

## 4. MC file templates

The 102 entries in `MC_TEMPLATES` cover the standard S/4 catalog. Each
entry may declare four keys:

| Key | Required | Purpose |
|---|---|---|
| `csv_columns` | ✅ | The full ordered column set the MC template accepts |
| `mandatory`   | ✅ | Subset of `csv_columns` that must be non-empty per row |
| `template`    | ✅ | The MC template name on S/4 (e.g. `MC_PP_ROUTING_TEMPLATE_V1`) |
| `target_table`| ✅ | The primary S/4 target table (informational) |
| `filter_condition` | optional | Extract-time filter; row is skipped if the predicate fails. See below. |
| `default_values`   | optional | `{col: value}` applied at build_payload when the source row omits the column. |

### 4.1 Extend a template at deploy time

Without editing the source:

```python
from mc_file_exporter import register_template_extension

# Extract only company code 0001, default WAERS to EUR
register_template_extension(
    "HouseBank",
    filter_condition = {"BUKRS": "0001"},
    default_values   = {"WAERS": "EUR"})
```

Call once at Lambda cold start (e.g. from a bootstrap module the handler
imports). Both keys are additive; subsequent calls merge.

### 4.2 filter_condition predicate forms

- Scalar        — `{"BUKRS": "0001"}` — string equality
- List/set/tuple — `{"BANKS": ["DE","US","GB"]}` — membership
- Dict `{op, val}`:
    - `{"op": "startswith", "val": "US"}`
    - `{"op": "gt",         "val": 100}`
    - `{"op": "lt",         "val": 100}`
    - `{"op": "in",         "val": [...]}`
    - `{"op": "eq",         "val": "X"}`

Unknown ops err on the side of inclusion (a typo doesn't drop the whole
extract). Filtered-out rows never reach `load_one`, so they don't inflate
the dead-letter counter — they are extracted-and-skipped.

### 4.3 Add a new MC template

Append to `MC_TEMPLATES` dict:

```python
"MyNewObject": {
    "csv_columns":         ["FIELD1", "FIELD2", "FIELD3"],
    "mandatory":           ["FIELD1"],
    "template":            "MC_XX_MYNEWOBJECT_V1",
    "target_table":        "ZTAB",
    "filter_condition":    {"MANDT": "800"},
    "default_values":      {"FIELD3": "DEFAULT"},
},
```

The factory registers it automatically at import time.

## 5. Continuous refresh

For customers on the SaaS deployment, we refresh content nightly:

```yaml
# .github/workflows/refresh-content.yml
on:
  schedule: [{cron: "0 5 * * *"}]   # 05:00 UTC daily
jobs:
  refresh:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate catalog
        run: |
          .\scripts\generate_field_catalog.ps1 `
            -Host ${{secrets.S4_HOST}} -SystemNumber ${{secrets.S4_SYSNR}} `
            -Client ${{secrets.S4_CLIENT}} -User ${{secrets.S4_USER}} `
            -Passwd ${{secrets.S4_PASS}} -Release S4H2023
      - name: PR if changed
        uses: peter-evans/create-pull-request@v6
        with:
          title: "content: nightly BAPI catalog refresh"
          branch: content/nightly-refresh
```

## 6. Ownership

- BAPI field catalog: **ownership migrate4hana-content team**
- Value maps + industry variants: **customer content lead** (base) + **industry SMEs** (variants)
- DAG: **migrate4hana-content team** (product decision)
- MC templates: **migrate4hana-content team** (product decision)
