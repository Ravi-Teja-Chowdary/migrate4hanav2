# Migrate4HANA — Unified Hardening + MC Direct-Staging Validation Plan

**Created:** 2026-07-17 · **Owner:** solo founder + Claude pair · **Branch:** aws-lift-and-shift

## How to use this file

This is the single implementation backlog. We work **top to bottom** — each phase depends on
the ones above it. Every task has: **what**, **why**, **files**, and **done-when** (acceptance).
Check boxes as we land them. Nothing here changes business behavior silently; every SAP-side
write stays governed by the existing preflight/consent gates.

**Supported-scope decision (LOCKED 2026-07-17):** the tool targets **ECC 6.0 EHP0–EHP8 →
S/4HANA 2020–2025** (floor is 2020; 1909 out of scope). This is the north star for every phase;
Phase H-VER makes it real.

**Three streams merged into one sequence:**
- **H** = hardening roadmap items (from the 2026-07-17 production-readiness review).
- **MC** = the Migration Cockpit direct-staging validation epic (the 99 MC lanes are mapped but
  data execution through them is unvalidated; replace file-upload staging with direct HANA
  staging-table ingestion + a fully programmatic Create→Prepare→Map→Simulate→Migrate loop).
- **H-VER** = version-range coverage across ECC EHP0–8 → S/4 2020–2025, centered on universal
  BAPI-signature auto-discovery + a representative-pair validation matrix.

The MC epic is the biggest single value-add (it closes the largest coverage gap — 99 of 132
objects), so it sits in the middle, after the safety rails it depends on and before the
version-range and breadth/polish tail.

---

## Grounding: what already exists (do not rebuild)

| Concern | Current state | File |
|---|---|---|
| MC trigger strategy chain | ltmc_api → odata → xbp_job → bapi_substitute → idoc_inbound | `lambda/utils/mc_job_trigger.py` |
| MC orchestrator (stage 16/24) | stages template → triggers → monitors → reconciles (FILE-based today) | `lambda/migration-cockpit-orchestrator/handler.py` |
| MC OData v4 reference | `/sap/opu/odata4/sap/api_migrationcockpit_object_runtime` (Transfer POST) | `mc_job_trigger.py:275` |
| MC OData v2 base | `CA_DATA_MIGRATION_SRV` base url | `connections.json` `lift_and_shift_target.mc_base_url` |
| HANA target profile | `hana_host / hana_sysnr=02 / hana_schema=SAPHANADB / hana_user=SAPHANADB` | `connections.json` |
| File exporter | builds MC CSV templates | `lambda/utils/mc_file_exporter.py` |
| Value-map management | PowerShell tooling exists | `scripts/manage-value-maps.ps1` |
| Self-healing customizing loop | stage 15b, kit v1.1 upsert | `lambda/utils/prep_push_loop.py` |
| Transformation engine | value-map + cleanse + DQ | `lambda/utils/transformation_engine.py` |

**Design rule carried from the whole project:** discover live, don't hardcode. Exact MC staging
table names and some OData entity sets are release-specific — Phase MC-1 introspects them at
runtime (same philosophy as the `DDIF_FIELDINFO_GET` schema intersection that made extraction
version-robust).

---

## Required S/4HANA Migration Cockpit API surface (deliverable: endpoint reference)

These are the endpoints the programmatic loop targets. Names marked **(discover)** are confirmed
at runtime in MC-1.2 because they vary by release; the rest are stable across S/4 2020–2025.

### A. Migration Cockpit OData (project + object lifecycle)
- **v2 service root:** `/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV/`
- **v4 runtime:** `/sap/opu/odata4/sap/api_migrationcockpit_object_runtime/`
- Project CRUD: `MigrationProjectSet` / `MigrationProject('<PROJ>')`
- Objects in a project: `.../MigrationObjectSet` (filter by project)
- Actions (v2 `POST` function-imports / v4 bound actions):
  - `CreateProject` (name, mass-transfer id, transfer method = *Direct transfer* / *Staging tables*)
  - `PrepareStagingTables` / `ActivateObject`
  - `ProcessMappingTasks` (returns unresolved-task list)
  - `SimulateObject` / `Simulate`
  - `MigrateObject` / `Migrate`
  - `GetStatus` / `Object('<id>')/Status`
- Mapping-task entity sets (MC-3): `ValueMappingSet`, `FixedValueSet` (or `MappingTaskSet` with a
  `TaskType` discriminator) **(discover)**
- Message/log entity set (MC-4): `ApplicationLogSet` / `Object('<id>')/Messages` and the
  **Transfer List** entity for Direct-Transfer lanes **(discover)**

### B. HANA staging schema (direct ingestion — bypasses the 100 MB file cap)
- Connection: `hdbcli` (SAP HANA Python driver) to `hana_host:3<NN>15` (SQL port; NN = hana_sysnr),
  schema `SAPHANADB` (the "Remote SAP HANA Database Schema" the MC project points at).
- Staging tables per object follow the MC pattern `/1LT/DS<mass-transfer-id><object><table>` or the
  project-schema `<PREFIX>_<OBJECT>_<STRUCT>` — **(discover)** via `SYS`.`TABLES`/`TABLE_COLUMNS`.

### C. Fallbacks already wired (keep as degradation path)
- v4 `Transfer` POST (file bytes) — `mc_job_trigger.py` odata strategy
- XBP background job `/UI/MIG_OBJ_LOAD` — universal
- BAPI-substitute + IDoc-inbound — last resort

---

## PHASE H0 — Foundational safety rails (quick; everything else leans on these)

- [x] **H0.1 — Externalize the JWT secret (fail-closed in prod).** ✅ 2026-07-17: default is now
  fail-closed (bare/prod start with no secret refuses to boot); dev auto-gen gated behind M4H_DEV=1
  / M4H_ENV=dev; existing .jwt_secret still honored for returning local boxes. Verified offline
  across 6 env cases + token stability (same secret survives restart, different secret invalidates —
  proving why the old auto-gen-on-restart was the hole). `api_server.py:_ensure_jwt_secret`.
  *Why:* auto-generated secret invalidates tokens on restart and isn't operator-controlled;
  a security review blocks on it.
  *Files:* `api_server.py` (`_ensure_jwt_secret`, `_JWT_SECRET`).
  *Done-when:* prod start with `M4H_JWT_SECRET` unset refuses to boot (clear error); set → stable
  tokens across restart. Dev keeps the auto-gen convenience behind an explicit `M4H_DEV=1`.

- [x] **H0.2 — Apply + verify the scoped `ZM4H_MIGRATION_ADMIN` role.** ✅ 2026-07-17:
  new preflight check `check_rfc_user_privilege` uses live-verified `BAPI_USER_GET_DETAIL` to read
  the RFC user's PROFILES + roles; WARN on SAP_ALL ("over-privileged for production; apply scoped
  role + remove SAP_ALL"), PASS on scoped-role-without-SAP_ALL, non-blocking. Live-run on S/4:
  correctly flags MIGRATE_ADMI's SAP_ALL as WARN, all 11 checks intact (fixed the fragile
  `checks[-3]` kit guard to reference the kit check directly). `BASIS_KIT_OPERATIONS.md` §3.5 has
  the full PFCG runbook (S_RFC/FUGR ZM4H, S_NUMBER, S_TABU_NAM incl. the kit-v1.1 customizing
  surface). Applying the role itself stays a customer PFCG action (CAL has no PFCG).
  `preflight_verifier.py`.

- [x] **H0.3 — RFC auto-reconnect + retry wrapper.** ✅ 2026-07-17: `lambda/utils/rfc_session.py`
  `ResilientRfc` re-dials on transport failures with capped backoff; **never** retries
  `ABAPApplicationError`/`ABAPRuntimeError`/`LogonError`. 5 unit tests pass. **Live-verified on
  S/4:** discovered pyrfc actually raises `RFCError` "connection is closed" (not
  `CommunicationError`) — caught by the message-hint fallback (discover-don't-assume paid off).
  Adopted at the factory chokepoints `_ecc()` + `_target_connection()` in
  `data-migrator/handler.py` (so the parallel worker pool inherits it too), behind
  `M4H_RFC_RESILIENT` (default on) with a raw-Connection fallback. Live regression on ECC+S/4:
  normal ops identical (0 spurious reconnects), forced-drop recovers in 1 reconnect.

- [x] **H0.4 — Report aggregator reads the cumulative ledger.** ✅ 2026-07-17: added
  `data_migration.cumulative_on_target` (from the cross-run ledger) + a per-run-vs-cumulative
  scope note in dirty_data_handling; clamped the negative `records_missing` artifact to 0 with an
  explanation. Verified against real FULL-002 on disk — cumulative shows **5,090 records / 10
  objects** (vs the misleading per-run 51), `-288` gone, real PDF re-rendered (1.0 MB). Both
  aggregator copies (runner + shared) kept in sync + agree; PDF generator shows a "Cumulative
  records live on target" row. `run_local_lift_and_shift.py`, `aggregator.py`,
  `pdf_report_generator.py`.

---

## PHASE MC-1 — Direct HANA staging-table ingestion (prompt req 1)

Replace file-upload staging (100 MB cap, ZIP constraints) with direct writes into the target
HANA staging schema — our engine acts as the ETL tool.

- [ ] **MC-1.1 — HANA staging connection layer.**
  *What:* `hdbcli`-based connection manager to `SAPHANADB` on the target HANA, sourced from the
  `connections.json` hana_* profile + a Secrets-Manager/env password (never persisted, same policy
  as SAP RFC creds).
  *Files:* new `lambda/utils/hana_staging.py`; extend `connections.json` schema doc.
  *Done-when:* `connect()` opens a session, `SELECT CURRENT_USER FROM DUMMY` round-trips; creds
  handled to the same standard as `M4H_TARGET_PASSWD`.

- [ ] **MC-1.2 — Staging-table introspection per MC object.**
  *What:* given a migration project + object, discover the object's staging table(s) and column
  definitions from `SYS.TABLES`/`SYS.TABLE_COLUMNS` (name pattern is release-specific — discover,
  don't hardcode). Cache the schema map per run.
  *Files:* `hana_staging.py` (`describe_staging(project, object)`).
  *Done-when:* for a known MC object we print its staging table + typed columns live from the CAL.

- [ ] **MC-1.3 — Transformed-data → staging-table writer.**
  *What:* take the transformation engine's output rows for an object and bulk-`INSERT` them into the
  discovered staging table(s), typed/validated against the discovered columns, chunked for volume.
  Idempotent (truncate-object-scope or upsert by staging key) so re-runs are safe.
  *Files:* `hana_staging.py` (`load_staging(project, object, rows)`); call site in a new MC lane
  (MC-2.3).
  *Done-when:* one object's rows land in its staging table, verified by count + spot-read; a
  >100 MB-equivalent row volume ingests without the file-path limits.

---

## PHASE MC-2 — Programmatic execution sequence + queue control (prompt req 2)

- [ ] **MC-2.1 — MC OData client.**
  *What:* thin client over the CA_DATA_MIGRATION / api_migrationcockpit services with
  CSRF-token fetch, session cookies, and typed calls for: CreateProject(method=staging),
  PrepareStagingTables, ProcessMappingTasks, Simulate, Migrate, GetStatus.
  *Files:* new `lambda/utils/mc_odata_client.py` (reuse the `requests`/urllib pattern already in
  `mc_job_trigger.py`; honor `verify=False` only for the CAL, configurable for prod TLS).
  *Done-when:* each call returns parsed status against the live MC service; endpoint names that were
  marked **(discover)** are pinned from the live `$metadata`.

- [ ] **MC-2.2 — Concurrency-aware queue manager.**
  *What:* submit objects respecting SAP's default **8 concurrent migration jobs**; keep a small
  parallel window (configurable, default ≤ min(8, cores)) so the object queue never floods; backfill
  as jobs complete.
  *Files:* `mc_odata_client.py` or new `lambda/utils/mc_queue.py`.
  *Done-when:* submitting 30 objects never exceeds the cap; log shows steady-state ≤8 in-flight.

- [ ] **MC-2.3 — New orchestrator lane: `hana_staging`.**
  *What:* wire MC-1 + MC-2 into a first-class lane in the orchestrator, ahead of the file-based
  strategies (which stay as fallback). Sequence per object:
  create/reuse project → ingest staging (MC-1.3) → prepare → process mappings (MC-3) →
  simulate → parse results (MC-4) → migrate → parse results.
  *Files:* `lambda/migration-cockpit-orchestrator/handler.py`, `mc_job_trigger.py` (register lane).
  *Done-when:* one MC object goes end-to-end through direct staging with no file upload and no Fiori
  click.

---

## PHASE MC-3 — Automated mapping-task resolution (prompt req 3)

The "Process mapping tasks" step must never pause for a human.

- [ ] **MC-3.1 — Detect unresolved mapping tasks.**
  *What:* after Prepare, query the object's mapping tasks; classify into Value-mapping vs
  Fixed-value vs structural.
  *Files:* `mc_odata_client.py` (`list_mapping_tasks(project, object)`).
  *Done-when:* unresolved tasks for an object are enumerated programmatically.

- [ ] **MC-3.2 — Pre-populate value-mapping tasks.**
  *What:* inject target values for source values via the mapping API, sourced from our existing
  value-map store (reuse `scripts/manage-value-maps.ps1` data + the transformation engine's maps).
  *Files:* `mc_odata_client.py` (`put_value_mapping`), bridge to `transformation_engine.py` maps.
  *Done-when:* a value-mapping task that would block simulation is auto-filled and clears.

- [ ] **MC-3.3 — Inject fixed-value tasks.**
  *What:* set default target-field values (org units, defaults from discovered config) via the
  fixed-value API before simulate.
  *Files:* `mc_odata_client.py` (`put_fixed_value`); pull defaults from the discovered-config
  (`config_discovery`) already threaded in the loader.
  *Done-when:* simulate proceeds with zero human mapping interaction for a mapped object.

---

## PHASE MC-4 — Telemetry & result extraction (prompt req 4)

No Fiori login to see results — pull everything by API and pipe to our UI.

- [ ] **MC-4.1 — Post-simulate / post-migrate log query.**
  *What:* after each of simulate + migrate, query the application-log / message endpoints; normalize
  into success / warning / error records with object + row context.
  *Files:* `mc_odata_client.py` (`get_messages(project, object, phase)`).
  *Done-when:* the same info a human sees in the Fiori log is available as structured JSON.

- [ ] **MC-4.2 — Transfer List parser (Direct-Transfer lanes).**
  *What:* for Direct-Transfer objects, parse the Transfer List — the exact data the target API uses
  to create records + the applied mapping-rule results — into per-row lineage.
  *Files:* new `lambda/utils/mc_transfer_list.py`.
  *Done-when:* for one Direct-Transfer object we can show source-row → target-create + which rules
  fired.

- [ ] **MC-4.3 — Pipe results into the orchestrator UI (real-time).**
  *What:* stream the normalized success/warning/error stream into the existing telemetry/progress
  surface so the wizard shows MC validation live (same channel as the spine telemetry).
  *Files:* `lambda/utils/telemetry.py`, `api_server.py` progress endpoints, `frontend` project page.
  *Done-when:* an MC run's per-object simulate/migrate results appear live in the UI without a Fiori
  session.

- [ ] **MC-4.4 — MC validation gate.**
  *What:* fold MC results into the reconciliation verdict + dead-letter feed so the self-healing
  loop (stage 15b) and the Excel fix-retry loop cover MC objects too.
  *Files:* `lambda/utils/reconciler.py`, `prep_push_loop.py`, `reprocess_manager.py`.
  *Done-when:* an MC object's errors flow into the same triage + heal path as BAPI objects.

---

## PHASE H-VER — Version-range coverage: ECC 6.0 EHP0–EHP8 → S/4HANA 2020–2025

**Scope decision (LOCKED 2026-07-17):** supported range is **ECC 6.0 EHP0 through EHP8** (source)
→ **S/4HANA 2020 through 2025** (target). **Floor is 2020 — S/4HANA 1909 is OUT of scope** (its
LSMW-XML fork is a separate funded project if a 1909 customer ever appears). Effective grid:
9 sources × 6 targets = **54 pairs**.

**Feasibility basis:** achievable with no architectural blocker because the engine already
*discovers live* rather than hardcoding — `DDIF_FIELDINFO_GET` for schema, `FUPARAREF` for BAPI
signatures, live NRIV/customizing reads. The source EHP range is nearly free (EHP diffs are
additive on a stable core the extractor already intersects). The 2020–2025 target band is
homogeneous (same Fiori MC, CVI/BP-led numbering, largely the same BAPIs). We prove a
representative spread, not all 54 cells, and rely on live discovery for the interpolation.

- [ ] **H-VER.1 — Drop 1909 / set the 2020 floor in the matrix.**
  *What:* remove `S4HANA_1909` from `TARGET_S4_RELEASES`; remove the now-dead
  `LEGACY_LSMW_XML` branch expectations; adjust `routing_for_pair` guardrails (the EHP0–3 → 2023+
  refusal stays; re-check that EHP0–3 → 2020/2021/2022 is allowed).
  *Files:* `lambda/utils/version_matrix.py`, `tests/test_version_matrix.py`, `VERSION_MATRIX_GUIDE.md`.
  *Done-when:* supported-pairs API returns only the 54-cell (EHP0–8 × 2020–2025) grid, minus any
  guardrail-refused extreme jumps; tests updated.

- [ ] **H-VER.2 — Universal BAPI-signature auto-discovery (the centerpiece).**
  *Why:* today BAPI signatures are fixed reactively (we patched ProfitCenter when it broke). Making
  every spine probe its BAPI's live signature (`FUPARAREF` + `DDIF_FIELDINFO_GET`) and adapt
  parameter names/structures automatically is what makes the whole 2020–2025 target band
  self-adapting instead of 6 hardcoded variants.
  *What:* a shared `bapi_signature.py` helper that, per BAPI, returns the live import/export/table
  params + their structure fields; spines build payloads against the discovered signature and drop
  unknown fields with a metric instead of hard-failing. Generalizes the pattern already proven on
  ProfitCenter, PO (POHEADER-PO_NUMBER), and the kit FMs.
  *Files:* new `lambda/utils/bapi_signature.py`; adopt in `base_spine_orchestrator.py` +
  the per-object spines + `bapi_loader.py`.
  *Done-when:* a spine run against two different S/4 releases builds correct payloads with zero
  code change, and an intentionally-renamed/removed BAPI param is handled gracefully (metric, not
  crash). Unit + one live run.

- [ ] **H-VER.3 — Source EHP-range extraction hardening.**
  *What:* confirm the extract path across the EHP spread — `RFC_READ_TABLE` 512-byte row-width
  handling, `GET_SORTED`/`ROWSKIPS` paging, non-HANA (AnyDB) EHP0–5 behavior, Unicode edge cases.
  Add the DB-family promotion (HANA → MODERN_BULK) test.
  *Files:* `lambda/data-migrator/handler.py` extract path, `abap_generator.scan_ecc`,
  `version_matrix.routing_for_pair`.
  *Done-when:* extraction verified against the newest available EHP and (if reachable) an older
  AnyDB EHP; row-width + paging edges have tests.

- [ ] **H-VER.4 — Representative-pair validation matrix.**
  *What:* define + run the minimum spread that credibly covers the 54 cells:
  corners `EHP0→2020`, `EHP8→2025`, plus a mid `EHP6→2023` (extend if systems are available).
  Each: a full closed-loop run recorded (records on target, dead-letter rate, preservation).
  *Files:* a `version-validation/` results log; reuse the `LOCAL-E2E-FULL` harness.
  *Done-when:* ≥3 pairs across the corners+middle have live run records; results table in the guide.

- [ ] **H-VER.5 — MC surface across releases.**
  *What:* confirm the MC-1..MC-4 direct-staging + OData surface resolves per release via the
  `(discover)` introspection (staging-table names, entity sets, message endpoints differ 2020→2025).
  Fold into the H-VER.4 runs so version proof and MC proof are the same test.
  *Files:* `mc_odata_client.py`, `hana_staging.py` (discovery already release-aware by design).
  *Done-when:* the MC loop runs on the oldest (2020) and newest (2025) reachable target unchanged.

- [ ] **H-VER.6 — UI honesty for the supported range.**
  *What:* the version selector shows the 54-cell grid; pairs with a live run record are marked
  "validated", the rest "supported (schema-adaptive) — pending first live run". No pair is implied
  as proven that isn't.
  *Files:* `frontend/src/pages/v2/WizardVersions.jsx`, `version_matrix.supported_pairs()` (add a
  `validated` flag sourced from the H-VER.4 results log).
  *Done-when:* UI claims match the validation record; no overclaim.

---

## PHASE H1 — Production-readiness closure (after MC data path is proven)

- [ ] **H1.1 — External-code-egress control.** Finish the local-LLM (Ollama) routing so
  high-sensitivity ABAP stays on-prem, OR make the Anthropic path an explicit documented opt-in with
  the masking guarantees written down. *Files:* `lambda/code-analyzer/genai_router.py`
  (`_select_backends` currently forces anthropic), `pseudonymize.py`.
  *Done-when:* sensitivity=high routes off the public API, or the opt-in + masking contract is
  documented and enforced.

  *(Version coverage moved up to its own Phase H-VER — see above.)*

- [ ] **H1.3 — Real-volume test.** One run against a realistically-sized dataset (millions of docs)
  to surface timeout/memory/pagination edges the demo can't. *Done-when:* a large-volume run
  completes and its failure modes are catalogued (this is where the true SLO number comes from).

- [ ] **H1.4 — Persist signed consent to a compliance ledger.** timestamp + signer + kit-audit
  correlation. *Files:* `preflight_verifier.py`, `api_server.py`, a ledger store.
  *Done-when:* every governed run leaves an auditable consent trail.

---

## PHASE H2 — Breadth & polish (last)

- [ ] **H2.1 — Broaden proven Tier-1 object coverage** (~13–20 loaded live of 50 defs) in dependency
  order until the full breadth is closed-loop verified.
- [ ] **H2.2 — Cutover rollback story** beyond idempotent resume: document + automate "failed
  halfway" recovery.
- *(Per-version behavior / 1909 LSMW fork: OUT of scope — floor is 2020, see H-VER. Revisit only
  as a separately-funded project if a 1909 customer materializes.)*

---

## Global acceptance for "production-safe fire-and-forget"

The plan is done when, on a **real customer landscape** (not the CAL):
1. One Auto-mode run drives preflight → consent → plan → apply → **MC direct-staging validate
   (simulate) → migrate** → self-heal → reconcile → truthful PDF, unattended after the one-time
   SE37 kit install and the two governance sign-offs.
2. MC lanes (99 objects) execute + validate programmatically — no Fiori login, no file-size cap.
3. Dead-letter under the agreed SLO at real volume; every residual failure named.
4. Security review clears: externalized secrets, scoped role, controlled/greenlit code egress,
   audit trail.
5. Supported range **ECC 6.0 EHP0–EHP8 → S/4HANA 2020–2025** (54-cell grid); a representative
   spread (corners + middle, ≥3 pairs) proven live, the rest schema-adaptive, and UI claims match
   the validation record exactly.

---

## Working notes / open questions to resolve as we go
- Confirm the target's MC transfer method supports "Staging tables (remote HANA)" vs only
  "Direct transfer" — decides whether MC-1 staging or MC-4.2 transfer-list is the primary path per
  object. (Introspect in MC-1.2 / MC-2.1 from live `$metadata`.)
- HANA SQL port: `3<hana_sysnr>15` → `30215` for sysnr 02; verify reachability/SG like the RFC ports.
- Live FM name quirk on current CAL: `Z_M4HTABLE_UPSERT` (kit v1.1) — resolver handles both spellings.
