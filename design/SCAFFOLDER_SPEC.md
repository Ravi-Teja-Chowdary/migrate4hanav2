# Object Scaffolder — Design Specification

**Tier:** Roadmap Tier 1.A (the multiplier)
**Engine:** Opus 4.7 (architecture / meta-programming)
**Status:** Draft v1, 2026-06-14
**Audience:** Future-me, future engineers, Fable 5 prompts that generate the 107+ objects this scaffolder will produce

---

## 1. Why this exists

The roadmap calls for ~107 more SAP migration objects (master, transactional,
historical, configuration). Today each new object is a week of hand-coding:

  - extraction RFC against ECC,
  - transformation rules (legacy → S/4 schema),
  - load BAPI / IDoc / LTMOM template,
  - dead-letter classification,
  - reconciliation verify-key shape,
  - dependency wiring into the spine.

A 107-week grind is not the plan. The scaffolder collapses each object to:

  1. Author a **single JSON object definition** (~80 lines, half of which is field maps).
  2. Run `python scaffolder/build.py <object>.json`.
  3. Get back a drop-in `<object>_spine.py` that subclasses `BaseSpineOrchestrator`,
     wires `PersistentKeyMap` for idempotency, raises `DeadLetterException` correctly,
     emits a `verify_key` the `Reconciler` can use, supports MC/IDoc/LTMOM/BODS lanes,
     and registers itself via `@register_spine`. Plus matching unit + integration
     test stubs.

**Target leverage:** 5 days → 1 day per object. At the same engineer-hour budget,
107 objects ships in ~21 weeks instead of 107.

---

## 2. Where it fits in the existing runtime

The scaffolder does NOT introduce a new runtime layer. It generates code that
satisfies **the existing contract** in `lambda/utils/base_spine_orchestrator.py`.
Every generated module must:

  - Subclass `BaseSpineOrchestrator` (read its abstract methods + lifecycle).
  - Be registered via `@register_spine` so `UnifiedLoader` dispatches to it
    before its legacy mech-based fallback.
  - Use the shared `PersistentKeyMap` for cross-run idempotency.
  - Plug into `TransformationEngine` for value-mapping + DQ gates.
  - Emit `LoadResult.verify_key` so `Reconciler.reconcile()` can read the
    record back from the system-of-record table.
  - Honor `tenant_id` (already part of the base constructor).
  - Support `dry_run=True` for CI smoke tests.

The 35 hand-written `*_spine.py` files in `lambda/utils/` already follow this
shape. The scaffolder's job is to mechanize what's currently boilerplate.

---

## 3. Object Definition — the input JSON

Every object is described by a single `definitions/<object>.json` file. The
shape is fixed; no free-form drift. Required fields are marked `[req]`; everything
else has a documented default.

```json
{
  "object_type":            "PurchaseRequisition",      // [req] PascalCase identity
  "source_key_field":       "BANFN",                    // [req] the ECC primary key column
  "home_table":             "EBAN",                     // [req] S/4 SoR table for verify_key

  "category":               "Transactional",            // Master|Transactional|Historical|Configuration
  "phase":                  "explore",                  // prepare|explore|realize|post_conversion|cutover

  "extract": {
    "rfc": "RFC_READ_TABLE",                            // RFC_READ_TABLE | BAPI_<name> | custom
    "tables": [                                          // 1..N source tables (FK-joined by source_key_field)
      {
        "name": "EBAN",
        "fields": ["BANFN","BNFPO","BSART","BSAKZ","LOEKZ","MATNR",
                   "MENGE","MEINS","BADAT","LFDAT","WERKS","LGORT"],
        "where": "LOEKZ <> 'X'",                         // optional filter (cluster-aware preflight applies)
        "primary": true                                  // exactly one table marks itself primary
      },
      { "name": "EBKN", "fields": ["BANFN","KOSTL","SAKNR","PS_PSP_PNR"], "join_on": ["BANFN"] }
    ],
    "package_size":        1000,                         // default 1000, capped by cluster_table_awareness
    "delta_field":         "AEDAT",                      // optional CDC watermark column
    "max_rows_per_template": 50000                        // batch cap for MC/IDoc emission
  },

  "transform": {
    "field_maps": {                                       // source_field -> target_canonical
      "BANFN":  "PR_NUMBER",
      "BSART":  "DOC_TYPE",
      "WERKS":  "PLANT",
      "MATNR":  "MATERIAL"
    },
    "value_maps": {                                       // optional: lookup tables for code translation
      "DOC_TYPE": { "NB": "NB", "RV": "RV", "ZZNB": "NB" }
    },
    "dq_gates": [
      { "field": "MATERIAL", "rule": "non_empty",
        "on_fail": "dead_letter", "code": "MISSING_MATERIAL" },
      { "field": "MENGE",    "rule": "positive_number",
        "on_fail": "dead_letter", "code": "INVALID_QUANTITY" }
    ],
    "computed_fields": [                                  // host-derived values (e.g., concatenations)
      { "name": "PR_DESCRIPTION",
        "expr": "f\"{row.get('BSART','')} {row.get('MATNR','')}\".strip()" }
    ]
  },

  "fk": {                                                 // [req when applicable] foreign keys to other objects
    "MATERIAL":   "Material",
    "PLANT":      "Plant",
    "COST_CTR":   "CostCenter"
  },

  "load": {
    "primary_lane":   "BAPI",                             // BAPI | MC | IDoc | LTMOM | BODS
    "fallback_lane":  "MC",                               // optional: lane used if BAPI unavailable on release
    "bapi": {
      "function":     "BAPI_PR_CREATE",
      "header_struct": "PRHEADER",
      "item_struct":  "PRITEM",
      "extension_structure": "BAPI_TE_EBAN",              // "" if not applicable
      "commit_with_wait": true
    },
    "mc": {                                                // Migration Cockpit lane
      "object_id":   "PURCHASE_REQUISITION",
      "staging_template": "S_PURCHASE_REQUISITION"
    },
    "idoc": {                                              // IDoc lane
      "basic_type":  "PREQCR01",
      "message_type": "PREQCR"
    },
    "ltmom": {                                             // LTMOM mapping spec
      "source_object": "S_PR_HEADER",
      "target_object": "BANFN"
    }
  },

  "verify": {
    "key_field":   "BANFN",                                // S/4 column that gets the target key
    "value_fields": ["MATNR","MENGE","WERKS","BADAT"]      // optional value tie-out columns
  },

  "extensions": {
    "supports_ZZ_fields": true,                            // EXTENSIONIN / EXTENSIONINX wiring
    "supports_partners":  false,                           // KNVP/LFM1-style partner rows
    "supports_conditions": false,                          // pricing conditions
    "supports_longtexts": false
  },

  "telemetry": {
    "stage_event_name":  "data-migrator",
    "category":          "PurchasingReadiness",            // pilot_readiness_probe category
    "affects":           ["PurchaseRequisition"]           // downstream objects whose readiness depends on this
  },

  "version_routing": {
    "ECC60_EHP1": { "use_bapi": "BAPI_PR_CREATE" },        // version_matrix.py picks one
    "ECC60_EHP6": { "use_bapi": "BAPI_PR_CREATE" },
    "S4HANA_2020": { "use_bapi": "BAPI_PR_CREATE_FROM_DATA", "deprecated_fields": ["ZZOLD"] },
    "S4HANA_2022": { "use_bapi": "BAPI_PR_CREATE_FROM_DATA" }
  }
}
```

**Schema enforcement.** A JSON Schema in `scaffolder/object_definition.schema.json`
validates every file before code-gen. Unknown fields are a hard error (catches
typos like `extact:` instead of `extract:`). A `scaffolder/lint.py` runs in CI
and rejects malformed definitions.

---

## 4. What gets generated

For one input `definitions/PurchaseRequisition.json` the scaffolder emits four
files atomically:

### 4.1 `lambda/utils/purchase_requisition_spine.py`

The spine orchestrator subclass. Structure (deterministic, no LLM in this path):

```
"""
purchase_requisition_spine — GENERATED FROM definitions/PurchaseRequisition.json
DO NOT EDIT BY HAND — re-run `python scaffolder/build.py PurchaseRequisition`
to regenerate after editing the JSON definition.

Generator: scaffolder v1.x  •  Source SHA: <sha256-of-json>  •  Built: <utc-iso>
"""
from __future__ import annotations
from typing import Optional
from base_spine_orchestrator import (
    BaseSpineOrchestrator, LoadResult, register_spine,
    DEAD_LETTER_BAPI, DEAD_LETTER_DQ, DEAD_LETTER_FK,
    DISP_CREATED, DISP_REMAPPED, DISP_MATCHED_EXISTING,
    build_extensioninx,
)

# ── Field maps lifted from the JSON definition ─────────────────────────────
HEADER_FIELDS = {...}        # from transform.field_maps (header subset)
ITEM_FIELDS = {...}          # from transform.field_maps (item subset)
VALUE_MAPS = {...}           # from transform.value_maps
DQ_GATES = (...,)            # tuple of (field, rule_fn, dead_letter_code)


@register_spine
class PurchaseRequisitionSpineOrchestrator(BaseSpineOrchestrator):
    object_type           = "PurchaseRequisition"
    source_key_field      = "BANFN"
    extension_structure   = "BAPI_TE_EBAN"
    fk_fields             = {"MATNR": "Material", "WERKS": "Plant",
                             "KOSTL": "CostCenter"}

    def validate(self, row: dict) -> Optional[str]:
        for field, rule_fn, code in DQ_GATES:
            err = rule_fn(row.get(field))
            if err:
                return f"{code}: {err}"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        header = {tgt: row.get(src, "") for src, tgt in HEADER_FIELDS.items()}
        # value-map application (deterministic; idempotent)
        for fld, vmap in VALUE_MAPS.items():
            if fld in header and header[fld] in vmap:
                header[fld] = vmap[header[fld]]
        items = self._build_items(row)
        payload = {"PRHEADER": header, "PRITEM": items, "_src_key": row.get("BANFN", "")}
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def _build_items(self, row: dict) -> list:
        # Item construction from joined tables (per extract.tables)
        ...   # generator emits the loop based on the JSON

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str], Optional[dict]]:
        src_key = payload.pop("_src_key", "")
        resp = self.c.call("BAPI_PR_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target_key = (resp.get("NUMBER") or "").strip()
        if hard or not target_key:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, msgs, None, None
        self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        verify_key = {"table": "EBAN",
                      "key": {"BANFN": target_key},
                      "values": {f: payload["PRHEADER"].get(f, "")
                                 for f in ("MATNR", "WERKS")}}
        return target_key, msgs, DISP_CREATED, verify_key
```

Crucially: **everything above is deterministic string-template output** from the
JSON definition. No LLM in the generation path. The same JSON produces the same
Python every run.

### 4.2 `lambda/utils/tests/test_purchase_requisition_spine.py`

```python
# GENERATED — covers the contract surface the base class guarantees + the
# definition-specific gates. Keep this file checked in so CI runs it.
import pytest
from purchase_requisition_spine import PurchaseRequisitionSpineOrchestrator

def test_object_type_registered(): ...
def test_dq_gate_missing_material_dead_letters(): ...
def test_dq_gate_negative_quantity_dead_letters(): ...
def test_fk_unresolved_material_is_dead_letter(): ...
def test_dry_run_returns_created_without_calling_bapi(): ...
def test_value_map_translates_doc_type(): ...
def test_extension_rows_capped_at_100(): ...
def test_idempotent_replay_hits_ledger_short_circuit(): ...
def test_verify_key_shape_matches_reconciler_input(): ...
```

Tests use the same `FakeRfcConn` fixture the existing spines tests use (already
in the repo). They cover the JSON-derived rules + the inherited base contract.

### 4.3 `lambda/utils/templates/purchase_requisition/`

Lane templates the four lane orchestrators consume:

```
purchase_requisition/
├── mc/staging_PURCHASE_REQUISITION.json    # MC staging-table layout
├── idoc/PREQCR01_envelope.xml              # IDoc skeleton + segment map
├── ltmom/source_S_PR_HEADER.json           # LTMOM source structure
└── ltmom/mapping_BANFN.json                # LTMOM field-mapping spec
```

These are also pure templates rendered from the JSON definition — the lane
orchestrators load them at runtime, the spine orchestrator dispatches to them
when `load.primary_lane` ≠ `"BAPI"` or the BAPI is unavailable on the target
release.

### 4.4 `lambda/utils/tests/integration/test_purchase_requisition_live.py`

```python
# GENERATED — runs against a real S/4 only when M4H_LIVE_INTEGRATION=1.
# Used by phase_b_validate_<n> modes in data-migrator and by the nightly
# breadth-grind job. Skipped in normal CI.
@pytest.mark.skipif(os.getenv("M4H_LIVE_INTEGRATION") != "1", reason="needs live S/4")
def test_load_one_real_record(): ...
```

---

## 5. Generator architecture

```
┌─────────────────────────────────┐
│  definitions/<object>.json      │  (the only file a human edits)
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  scaffolder/                    │
│    object_definition.schema.json│  jsonschema validation
│    lint.py                      │  CI-enforced linter
│    build.py                     │  main entry point
│    templates/                   │  jinja2 templates per artifact
│      spine.py.j2                │
│      test_unit.py.j2            │
│      test_integration.py.j2     │
│      lane_mc.json.j2            │
│      lane_idoc.xml.j2           │
│      lane_ltmom_source.json.j2  │
│      lane_ltmom_mapping.json.j2 │
│    rules/                       │  python predicates for DQ rules
│      non_empty.py               │
│      positive_number.py         │
│      iso_date.py                │
│      sap_unit_of_measure.py     │
│      ...                        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  lambda/utils/                  │
│    <object>_spine.py            │  (generated, do-not-edit header)
│    templates/<object>/...       │  (generated lane templates)
│    tests/test_<object>_spine.py │  (generated unit tests)
│    tests/integration/...        │  (generated live tests)
└─────────────────────────────────┘
```

**Generator language: Python 3.11 + jinja2.** Both already in the repo's
requirements. Jinja2's whitespace control + autoescape-off-for-Python make
emitting valid Python the simplest path (vs string concat or AST building).
The DQ rule library (`rules/non_empty.py`, `rules/positive_number.py`, etc.)
is a flat directory of pure functions that the spine imports — they do NOT
get inlined into generated code. That way a rule fix patches every object at
once, not 107 separate copies.

---

## 6. The non-negotiable contracts the generator must preserve

These are the existing system invariants. The generator's tests assert each
one on every generated module:

| Contract | Source of truth | Enforced by |
|---|---|---|
| Idempotency on replay | `PersistentKeyMap.resolve()` ledger-hit short-circuit at base step 2.5 | `test_idempotent_replay_hits_ledger_short_circuit` |
| DQ rejection → `DEAD_LETTER_DQ` | base step 2 raises into `_dead()` | `test_dq_gate_*_dead_letters` |
| Unresolved FK → `DEAD_LETTER_FK` | base step 3 | `test_fk_unresolved_*_is_dead_letter` |
| BAPI fail → rollback + `DEAD_LETTER_BAPI` | base step 7 + each spine's `call_bapi` | `test_bapi_failure_triggers_rollback` |
| `verify_key` reaches reconciler | `LoadResult.verify_key` non-None on success | `test_verify_key_shape_matches_reconciler_input` |
| Extension overflow → `DEAD_LETTER_EXTENSION_OVERFLOW` at 100 rows | base step 4 | `test_extension_rows_capped_at_100` |
| Multi-tenant: `tenant_id` flows to sinks | base constructor + `_fan_out_to_sinks` | `test_tenant_id_propagates_to_sinks` |
| Dry-run never calls SAP | base step 6 | `test_dry_run_returns_created_without_calling_bapi` |
| Version routing chooses correct BAPI | `version_matrix.py` consults `load.version_routing` | `test_version_routing_selects_bapi_per_release` |

---

## 7. Multi-tenant boundary

The scaffolder is **infrastructure**, not data plane — it generates code that
runs identically for every tenant. The tenant boundary lives in the runtime:

  - `BaseSpineOrchestrator.__init__` already accepts `tenant_id` (default
    `"default"` for backwards-compat).
  - Generated `call_bapi` MUST NOT hardcode anything tenant-specific. The
    `self.c` connection it uses is already tenant-scoped by the Lambda's
    secret lookup (the runtime resolves `target_creds_arn` from JWT claims
    before constructing the orchestrator).
  - `LoadResult.target_key` is namespaced by `(tenant_id, object_type)` in the
    `PersistentKeyMap` so customer A's BANFN 4500000001 doesn't collide with
    customer B's. The base class already does this; the generator must NOT
    add any per-tenant logic to the spine itself.

If a generated spine wants to be tenant-aware (e.g. a per-tenant value map),
it reads from `self.transformer` — the `TransformationEngine` is constructed
per-tenant by the runtime and its rules are tenant-scoped. No tenant string
ever enters the generated module's hot path.

---

## 8. Code-gen flow

`python scaffolder/build.py <object>` is the entry point. Idempotent and
deterministic:

```
1. Load definitions/<object>.json
2. Validate against object_definition.schema.json (fail-fast on schema error)
3. Lint: cross-checks (e.g., every FK target must be a known object_type;
   every value_maps key must appear in field_maps; primary table must exist)
4. Detect output collisions: if lambda/utils/<object>_spine.py exists and is
   NOT marked "GENERATED FROM definitions/<object>.json", REFUSE to overwrite
   — that's a hand-written spine the engineer wants kept. (See §10.)
5. Render each jinja template into a temp file
6. py_compile each generated .py to catch any syntax issue
7. Run black + isort + ruff --fix on each generated .py
8. Move temp files into place atomically
9. Stamp the JSON's SHA into the file header so a future regen knows
   whether the source has drifted
10. Print a one-line summary: "Generated <object>: spine + 4 lane templates
    + 9 unit tests + 1 integration test"
```

**Batch mode:** `python scaffolder/build.py --all` walks `definitions/` and
regenerates every object whose JSON SHA no longer matches the stamp in the
generated spine. CI runs this in `--check` mode (fail-on-drift) so a PR that
edits a JSON definition without running the generator is caught.

---

## 9. The DQ rule library (the multiplier within the multiplier)

`scaffolder/rules/` is a flat directory of single-purpose pure functions, each
in its own file. Examples:

```python
# scaffolder/rules/non_empty.py
def non_empty(v) -> str:
    """Return error message if value is empty/None/whitespace, else ''."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return "value is empty"
    return ""
```

```python
# scaffolder/rules/positive_number.py
def positive_number(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return f"not numeric: {v!r}"
    return "" if n > 0 else f"not positive: {n}"
```

JSON definitions reference rules by name: `{"rule": "non_empty"}`. The
generator emits `from scaffolder.rules.non_empty import non_empty` at the top
of the spine and `non_empty(row.get(field))` in the DQ gate. Adding a new
rule = adding one file, no spine regeneration needed (rules are imported
at runtime). Fixing a rule patches every spine at once.

The starter rule library ships with: `non_empty`, `positive_number`,
`non_negative_number`, `iso_date`, `sap_unit_of_measure`, `currency_iso_4217`,
`material_number_format`, `bukrs_company_code`, `werks_plant`, `langu_code`,
`sap_client_3char`, `decimal_max_digits`, `regex_match`, `in_set`,
`fk_required_when`. Each ships with unit tests. New rules land via PR.

---

## 10. Migration path for the 35 already-hand-written spines

The 35 `*_spine.py` files in `lambda/utils/` (material, customer, vendor,
business_partner, bank, profit_center, …, production_bom) are NOT regenerated
automatically. They were built before the scaffolder existed and may have
hand-tuned BAPI logic (Customer's two-step BP create + role assign is a real
example).

**Two-phase migration:**

1. **Phase A — author a JSON definition for each existing spine** that
   produces output BYTE-IDENTICAL to the hand-written one. The scaffolder
   gains a `--diff <object>` flag that generates into a temp dir and diffs
   against the existing file. We iterate the JSON until the diff is empty.
2. **Phase B — flip the existing spine to "generated"** by replacing it with
   the generator's output (which now matches byte-for-byte) and committing
   both the JSON and the regenerated .py. Done.

A spine with logic that genuinely doesn't fit the JSON schema (e.g.,
multi-BAPI orchestration like Customer's BP-then-role) stays hand-written
but gets a `definitions/<object>.json` with `"generator": "manual"` — the
scaffolder skips it. We add scaffolder features over time to fold those
back in.

---

## 11. Acceptance criteria for the scaffolder v1

Before this is "done":

  1. JSON schema validates against 3 real example definitions (one Master,
     one Transactional, one Configuration).
  2. Generated spine for `PurchaseRequisition` (greenfield — no hand-written
     version exists yet) loads 5/5 synthetic records into the live S/4 at
     `35.168.102.2` via the `phase_b_validate_f2`-style probe mode.
  3. Generated unit tests pass (`pytest lambda/utils/tests/test_purchase_requisition_spine.py`).
  4. Generated integration test loads 1 real record against live S/4 when
     `M4H_LIVE_INTEGRATION=1`.
  5. CI lint catches a deliberately broken JSON (unknown field, missing
     required field, FK referencing nonexistent object_type) on a PR.
  6. `scaffolder/build.py --all --check` returns clean against committed
     definitions; introducing drift fails CI.
  7. Re-running `build.py` against the same JSON produces a byte-identical
     output file (proves determinism — no LLM in the path, no timestamp
     drift, no map iteration order leak).

If all 7 pass, the scaffolder is the multiplier the roadmap depends on.

---

## 12. What the scaffolder explicitly does NOT do

These remain outside the generator's scope to keep its boundary tight:

  - **It does not write the JSON definitions for you.** Authoring the field
    maps, picking the BAPI, choosing the lane is engineer judgment per object.
    (Tier 2's ECC profiler will eventually pre-fill a starter JSON from
    inspection of a live ECC, but that's a separate tier.)
  - **It does not generate the BAPI itself.** SAP ships those; we wrap them.
  - **It does not invent simplification rules.** Tier 5 handles ABAP code
    remediation; this scaffolder only touches the data-plane spine.
  - **It does not bypass the 4 SOX gates.** Generated objects flow through
    the same ASSESS / DATA-PREP / VALIDATE / CUTOVER gates as the existing 13.
    The scaffolder is a code-gen tool, not a governance shortcut.
  - **It does not handle inter-object orchestration.** When a Sales Order
    needs Customer + Material loaded first, that's the spine-master's job
    (dependency DAG in `dependency_dag.py`). The scaffolder generates
    per-object modules; the DAG that wires them together is hand-curated.

---

## 13. The Day-in-the-Life: adding a 14th object

The end-to-end flow once v1 ships:

```
$ cp definitions/_template.json definitions/InventoryReservation.json
$ vim definitions/InventoryReservation.json
    # — 80 lines: source tables RKPF/RESB, fields, FKs to Material+Plant,
    #   target BAPI BAPI_RESERVATION_CREATE1, verify on RESB, DQ on quantity.

$ python scaffolder/build.py InventoryReservation
    Generated InventoryReservation: spine + 4 lane templates +
                                    9 unit tests + 1 integration test

$ pytest lambda/utils/tests/test_inventory_reservation_spine.py -v
    9 passed in 1.42s

$ python scripts/invoke-lambda.py data-migrator --mode phase_b_validate_f2 \
    --object_type InventoryReservation --count 5
    {status: ok, created: 5/5, dead_letter: 0, verify: 5/5 reconciled}

$ git add definitions/InventoryReservation.json lambda/utils/*inventory_reservation*
$ git commit -m "Add InventoryReservation object (autogen via scaffolder)"
```

Elapsed: ~half a day for a competent engineer. Compare to the ~week the
hand-written path takes today.

That ratio — 5× → 10× per object — is exactly the multiplier the rest of the
roadmap is sized around. Build this first; everything else compounds on it.

---

## 14. Open decisions for v1.1

Not blocking v1, but to revisit:

  - **Should the JSON definitions live in the repo, or in a separate
    `migrate4hana-definitions` repo?** (Argument for: customer-specific
    overrides cleanly separated. Argument against: cross-repo PR coordination.)
    Default for v1: in this repo under `definitions/`.
  - **AST-based generation instead of jinja2?** Cleaner for refactors but
    adds complexity. Defer until we hit the first refactor pain.
  - **Should the scaffolder also generate Step Functions ASL state-machine
    entries** for new objects? Currently those are hand-authored in
    `terraform/modules/pipeline/asl.json`. Tier 8 territory; keep this
    scaffolder scoped to data-plane code-gen for now.
  - **Custom-customer overrides** — when a customer's KNA1 has a Z field
    we want loaded but our base definition doesn't list it, where does the
    override live? Likely a sibling `definitions/_overrides/<customer_id>/<object>.patch.json`
    that deep-merges over the base JSON at build time. Scoped out of v1.

---

## 15. Status

| Component | Status |
|---|---|
| Object Definition JSON schema | spec'd above, not yet `.schema.json` file |
| Generator entry point `build.py` | not started |
| Jinja templates (5: spine + 4 lanes) | not started |
| DQ rule library (15 starter rules) | not started |
| CI lint integration | not started |
| Phase A JSON for the 35 existing spines | not started — Phase A starts after the 3 acceptance objects pass |
| First fresh object via scaffolder (PurchaseRequisition) | not started |

**Next step under this spec:** approve, then I write the JSON schema file +
`build.py` + the first three jinja templates (`spine.py.j2`, `test_unit.py.j2`,
`lane_mc.json.j2`). That's the [Fable 5] block — high-volume template
authoring with the spec above as the contract.
