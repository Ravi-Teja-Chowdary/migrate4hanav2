# Migration recipes

Declarative definitions of SAP Migration Cockpit objects for `migration_engine.py`
(Phase A of `DATA_MIGRATION_ROADMAP.md`). **Adding an object = adding a recipe here,
not writing engine code.** Run one with:

```
M4H_HANA_USER=SYSTEM M4H_HANA_PASSWD=<pw> py -3.7 migration_engine.py recipes/<name>.json
```

## Recipe shape

```jsonc
{
  "object": "Product",
  "description": "...",
  // OPTIONAL — the driving key set shared by all structures (so the same records
  // get every view). Omit for objects whose structures scope themselves.
  "key_scope": {
    "driver": {"conn":"ecc","table":"MVKE","key":"MATNR","fields":["MATNR","VKORG"],"where":"..."},
    "require_org_mapped": {"field":"VKORG","dim":"sales_org"},   // drop keys whose org isn't mapped
    "require_on_target":  {"table":"MARA","key_field":"MATNR"},  // drop keys not on the target
    "limit": 10
  },
  "structures": [
    {
      "id": "sales",
      "staging_signature": ["PRODUCT","VKORG","MTPOS"],   // columns that uniquely find the /1LT/DS* table
      "builder": "declarative",                            // or a name in CUSTOM_BUILDERS
      "source": {"conn":"ecc","table":"MVKE","fields":[...],"where":"...","limit":0},
      "key_src": "MATNR",                                  // source field filtered against key_scope
      "text_join": {"table":"CEPCT","field":"KTEXT","on":"PRCTR","where":"SPRAS = 'E'"},
      "map": [
        {"col":"PRODUCT","src":"MATNR","fn":"lstrip0"},
        {"col":"VKORG","src":"VKORG","fn":"org","dim":"sales_org"},        // org_mapper resolve
        {"col":"VTWEG","src":"VTWEG","fn":"org","dim":"distribution_channel","default":"10"},
        {"col":"DWERK","src":"DWERK","fn":"org","dim":"plant","allow_blank":true},
        {"col":"MTPOS","src":"MTPOS","fn":"copy","default":"NORM"},
        {"col":"LANGU","fn":"const","val":"E"},
        {"col":"KTEXT","from_text_join":true}
      ]
    }
  ]
}
```

## Transforms (`fn`)
- `copy` — trimmed source value (default)
- `lstrip0` — strip leading zeros (material/number keys)
- `const` — literal `val`
- `org` — resolve via `org_mapper` for `dim` (sales_org / distribution_channel / plant / division).
  `allow_blank:true` → blank when unmapped; `default:"X"` → fallback; otherwise the row is skipped.

Field options: `default` (fallback when value is blank), `from_text_join` (fill from the `text_join`).

## Custom builders
For structures too complex for the map, set `"builder": "<name>"` and register a function in
`migration_engine.CUSTOM_BUILDERS` returning `(rows, fields, skipped)`. Current: `product_basic_from_target`
(echo current target basic data — never blank it), `product_tax_positional` (ECC `MLAN` TAXMn → the
target's `TSTL` categories). Keep these rare; prefer declarative.

## Examples
- `product.json` — Product: basic (custom) + sales (declarative + org-mapping) + tax (custom).
- `profit_center.json` — fully declarative second object; proof that a new object needs only a recipe.
