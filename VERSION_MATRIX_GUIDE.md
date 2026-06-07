# Version Matrix — Picking the (ECC source → S/4 target) Pair

> Migrate4HANA's runtime adapts to which **source ECC** and **target S/4HANA**
> versions you're migrating between. Pick the pair once in the UI and the tool
> automatically routes extract path, package size, template format, and
> Fargate fan-out for the rest of the run.

## Where it lives in the product

- **UI**: Sidebar → **Setup → Version Matrix** (`/versions`)
- **Backend API** (FastAPI, served by `api_server.py`):
  - `GET  /api/versions/supported` — catalog of valid pairs + their routing tags
  - `GET  /api/versions/detected`  — auto-detect via `RFC_SYSTEM_INFO` (source) + `CVERS` table read (target)
  - `GET  /api/versions/selected`  — currently saved pair + resolved routing plan
  - `POST /api/versions/selected`  — persist a (source, target, optional DB) selection
- **Runtime module**: `lambda/utils/version_matrix.py` — single source of truth for the catalog + routing rules

## Supported pair matrix (51 valid combinations)

| Source ECC | EHP | Targets allowed |
|---|---|---|
| ECC 6.0 (no EHP) | 0 | 1909, 2020, 2021, 2022 |
| ECC 6.0 EHP1 | 1 | 1909, 2020, 2021, 2022 |
| ECC 6.0 EHP2 | 2 | 1909, 2020, 2021, 2022 |
| ECC 6.0 EHP3 | 3 | 1909, 2020, 2021, 2022 |
| ECC 6.0 EHP4 | 4 | 1909, 2020, 2021, 2022, 2023, 2024, 2025 |
| ECC 6.0 EHP5 | 5 | same |
| ECC 6.0 EHP6 | 6 | same |
| ECC 6.0 EHP7 | 7 | same |
| ECC 6.0 EHP8 | 8 | same |

**Forbidden pairs**: EHP0–3 → 2023+. Reason: 12+ year jump from a non-Unicode-stable EHP onto a modern S/4 release isn't field-validated. The tool refuses with a clear message and points to the workarounds (upgrade source EHP or target 1909–2021).

## What the selection drives

Every saved selection compiles into a **RoutingPlan**, computed deterministically from these tags:

| Tag | Possible values | What it changes |
|---|---|---|
| `extract_strategy` | `LEGACY_CHUNKED` / `MODERN_BULK` | Pull pattern: header-keys-first multi-stage with strict packaging (legacy) vs. modern bulk reads with open-SQL hints (HANA-on-source only) |
| `package_size` | 5,000 / 10,000 / 25,000 / 50,000 rows | Per-RFC `RFC_READ_TABLE` pull size. Conservative on legacy DBs to prevent short dumps. |
| `template_format` | `LEGACY_LSMW_XML` (target ≤ 1909) / `FIORI_MC_CSV` (target ≥ 2020) | Output file shape for the staging-objects lane |
| `fargate_fan_out` | `LOW` / `HIGH` | Concurrency cap for the Fargate read pool |
| `cluster_read_safety` | `STRICT` / `RELAXED` | Guardrails when extracting from cluster tables (BSEG, RFBLG, KOCLU) |
| `odata_ltmc_supported` | `true` / `false` | Whether `migration-cockpit-orchestrator` Lambda will attempt MC OData (target ≥ 2020 only) or fall straight to runbook-manual-gate |
| `bp_external_numbering` | `true` (all targets ≥ 1909) | Drives CVI two-phase Business Partner unification (covered by `[[partner-readiness-cvi]]`) |

## The source-database override

Inside the UI, after picking the (source, target) pair you can also pick a **Source database override**:

- *Use catalogue default* — for EHP0–EHP6 = `ANY_DB`; EHP7–EHP8 = `ANY_DB` (conservative; most real installs are still on Oracle/MSSQL).
- `HANA` — promote the extract path to `MODERN_BULK` with 25k+ row packages, relaxed cluster reads, high Fargate fan-out.
- `ANY_DB` — explicit conservative path.

The auto-detect button calls `RFC_SYSTEM_INFO` and reads `RFCDBSYS` to set this for you when possible (returns `HDB` on HANA).

## How auto-detect works (no manual mapping)

When you click **Detect now**, the backend:

1. Opens an RFC connection to the saved ECC system (using the password cached after the last "Test connection")
2. Calls `RFC_SYSTEM_INFO`
3. Reads `RFCSI_EXPORT.RFCSAPRL` (the SAP_BASIS release, e.g. `753`) and `RFCDBSYS` (the DB family)
4. Maps the release using `lambda/utils/version_matrix.py::detect_source_ecc_version` (kernel-release-to-EHP lookup is well-known and stable for ECC 6.0)
5. Does the equivalent for S/4 — opens RFC, calls `RFC_READ_TABLE` against `CVERS`, finds the `S4CORE` row, maps its `RELEASE` to a year (100 → 1909, 101 → 2020, … 108 → 2025)

If detection succeeds the UI auto-fills the dropdowns. If it fails (no live session, unmapped release, etc.) the auto-detect bar shows the specific error and you select manually.

## Where the saved selection lives + how downstream code consumes it

Persisted location: `connections.json` under the `versions` key. Example:

```json
{
  "ecc":       { "ashost": "...", "sysnr": "41", ... },
  "s4hana":    { "ashost": "...", "sysnr": "00", ... },
  "versions":  {
    "source_code": "ECC60_EHP8",
    "target_code": "S4HANA_2023",
    "source_db":   "HANA",
    "detected_at": "2026-06-07T14:30:00.000Z",
    "saved_at":    "2026-06-07T14:31:12.444Z"
  }
}
```

Downstream Lambdas read this via `GET /api/versions/selected` (which also returns the compiled RoutingPlan), or by importing `lambda/utils/version_matrix.py` directly and calling `routing_for_pair(source_code, target_code, source_db)`.

## What's NOT yet wired (deferred to F2 / F5 Phase B)

The tag **values** are computed and persisted in this session's F6 work. **What still needs to land** is the runtime that reads these tags and changes its behavior:

| Tag | Status |
|---|---|
| `template_format` (LSMW XML vs Fiori CSV) | `migration-cockpit-orchestrator` already emits Fiori CSV; LSMW XML lane is queued behind real 1909 system access |
| `extract_strategy` + `package_size` | `data-migrator` currently uses one path; switching needs real validation against an EHP4 system (we only have EHP8) |
| `fargate_fan_out` | The Fargate task definition is fixed today; concurrency-aware routing comes in F5 (scale work) |
| `cluster_read_safety` | Already used by `lambda/utils/cluster_table_awareness.py` for BSEG/RFBLG/KOCLU — needs to plug into the saved selection |
| `odata_ltmc_supported` | Already used by orchestrator; will read from saved selection in next iteration |

These are tracked under F2 (BaseSpineOrchestrator, where the strategy-pattern dispatch lives) and F5 (scale benchmark). Each one wants a real-system validation cycle that we deferred from this session.

## Reference

- Catalog: `lambda/utils/version_matrix.py` (227 lines, stdlib-only)
- Unit tests: `tests/test_version_matrix.py` (18 tests covering catalog shape, routing, HANA override, RFC detection)
- Backend: `api_server.py` — search for `# ROUTES - VERSION MATRIX`
- Frontend: `frontend/src/pages/VersionMatrix.jsx`
- API client: `frontend/src/lib/api.js` (`versionsSupported`, `versionsDetected`, `versionsSelected`, `saveVersions`)
- Sidebar entry: `frontend/src/components/Shell.jsx` → Setup → Version Matrix

## Why each tag exists (one paragraph per pillar)

- **`extract_strategy`** is the single biggest performance dial. Modern ECCs on HANA can pull 50k rows in one shot using open-SQL optimization; an EHP3 on AnyDB will short-dump if you ask for more than 5k. Mis-routing here turns a 2-hour run into a 2-day support ticket.

- **`template_format`** is the difference between SAP's old LSMW XML migration objects (≤ 1909) and the modern Migration Cockpit CSV staging tables (≥ 2020). Picking the wrong format means the lane orchestrator's CSV gets rejected on upload.

- **`fargate_fan_out`** governs how many parallel Fargate workers the heavy stages launch. HANA-on-source can comfortably take 32+ concurrent readers; a non-HANA ECC on Oracle will crash under that load.

- **`cluster_read_safety`** decides whether cluster-table reads (BSEG, RFBLG, KOCLU — anywhere SAP stores rows in a packed binary column) get a strict header-keys-first preflight or can use a more aggressive bulk read. Strict is mandatory on legacy DB stacks.

- **`odata_ltmc_supported`** determines whether the orchestrator attempts an automated `LTMC_MIGRATION_OBJECTS_SRV` OData call. S/4 1909 doesn't expose this service, so the orchestrator falls straight to the manual-gate runbook lane there (still defensible — that's what `runbook_only` mode is for).
