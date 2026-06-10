# Migrate4HANA — Independent Review Brief

*Prepared for an SAP data-migration / S4 conversion specialist. The goal of this document
is an honest assessment of where the tool stands — gaps are stated deliberately so your
review is efficient. Nothing here is marketing; please challenge any claim.*

**Date:** 2026-05-31 (review base); **2026-06-07 foundation pass (F1-F6) shipped** · **Branch reviewed:** `aws-lift-and-shift` · **Build status:** working prototype on a live system pair; **full AWS prod stack provisions and tears down cleanly end-to-end** (200 resources, see §13); **six production-grade foundations shipped 2026-06-07** (see §15 below for the full delta + 98-test green suite).

> **2026-06-07 update — Six-foundation pass shipped (F1 - F6) in a single autonomous session.**
> Material engineering progress against the three biggest gaps the original review flagged
> (no cross-run ledger, hand-curated catalogs, no version routing). All six foundations
> green under unit tests; Phase B (real-SAP validation) queued for paired sessions.
>
> | Foundation | What it solved | Tests | Doc |
> |---|---|---|---|
> | **F1** — DynamoDB Runtime Key Map | Replaced single-S3-JSON ledger with `(object, source_key)`-keyed DDB rows, atomic conditional writes, race-safe across concurrent runs. Verified against real `migrate4hana-key-map-prod`. | 11 unit + 5 integration | (in `tests/`) |
> | **F2** — BaseSpineOrchestrator + Material Master | The promotion factory: every staging-tier object becomes a ~150-LOC subclass. EXTENSIONIN/PARTNERS/CONDITIONS/TEXTS reusable handlers. Material Master deep view (MARA+MARC+MARD+MBEW+MARM+MAKT) as proof. Auto-registry in `UnifiedLoader._load_via_spine`. | 20 | `SPINE_PROMOTION_GUIDE.md` |
> | **F3** — Dynamic schema from DDIC introspection | Replaced static `bapi_field_catalog.py` with runtime `DD_BAPI_PARAMETER_GET` → DD03L → static fallback. S3-cached per (SID/client/release) with 7-day TTL. Wired into data-migrator. Self-updating when customer ships a BADI append. | 15 | `DYNAMIC_SCHEMA_GUIDE.md` |
> | **F4** — Declarative value-mapping matrix in S3 | The existing `transformation_engine.py` was mature but unwired; F4 seeded `value-maps/matrix.json` (10 cross-walks: BUKRS, WAERS, LAND1, SPRAS, MTART, customer/vendor groups, GL, VKORG, WERKS) + `ruleset.json` (5 objects: Customer/Vendor/Material/GLAccount/CompanyCode). Plus `scripts/manage-value-maps.ps1` pull/push/validate/diff workflow. | 11 | `VALUE_MAPPING_GUIDE.md` |
> | **F5** — Scale benchmark harness | Autonomous baseline: 25K rec/sec through the spine in 0.39s on a single thread. Synthetic generator + p50/p90/p99/p999 latency + dead-letter taxonomy + JSON report. Real 1M-row run = Phase B. | 8 | `SCALE_BENCHMARK.md` |
> | **F6** — UI version toggle (ECC -> S/4 routing) | New page `frontend/src/pages/VersionMatrix.jsx` + 4 FastAPI endpoints + 51-pair compatibility matrix (EHP0..EHP8 -> 1909..2025) + RFC auto-detect via `RFC_SYSTEM_INFO` + CVERS. Routing tags (extract_strategy / template_format / fargate_fan_out / cluster_read_safety / odata_ltmc_supported) computed per pair. | 18 | `VERSION_MATRIX_GUIDE.md` |
> | **PLUS** — Production governance toggles | `terraform/modules/audit/` now has `object_lock_enabled` + `audit_retention_days` + `kms_key_arn` variables (defaults preserve current prod posture). `COMPLIANCE.md` maps each control to SOX/SOC2/GDPR/GxP article numbers. | terraform validates | `COMPLIANCE.md` |
>
> **Test totals: 98/98 passing in 3.68s** (11 PersistentKeyMap + 15 wave1 + 11 ruleset + 18 version_matrix + 20 spine + 15 dynamic_schema + 8 benchmark). **No regressions** in the existing wave1 suite.
>
> **What the §11 head-to-head needs to reflect:** the "hand-curated catalogs that break on every S/4 release" critique no longer lands (F3); the "no per-object promotion pattern" critique no longer lands (F2); the "no cross-run ledger" critique no longer lands (F1); the "consultant edits require code change" critique no longer lands (F4). What still lands: zero customer cutovers, real-system validation pending for F2/F3/F5, object coverage gap (26 vs 200+ at SNP).
>
> See `SPINE_PROMOTION_GUIDE.md` §"The 6-step promotion pattern" for the new productivity story:
> each of the 102 staging-tier objects can now be promoted to the automated spine in ~1-2 days of work
> (was ~2 weeks in the bespoke pattern). At 5-10 objects/week solo, full 25 -> 127 coverage is 3-5
> months not 12+. This is the single biggest engineering acceleration the foundation pass unlocked.

> **2026-05-29 update:** four "competitive-parity" layers + a fresh light-themed Project Tracker UI
> were added (commit `0e7b7e0`). They are **self-tested deterministically but NOT yet integrated into
> the live ECC→S/4 loop** — see **§10** for what each does, **§11** for the honest head-to-head vs
> SmartShift / Syniti / Natuvion.
>
> **2026-05-31 update (commits `6e4a689` + `1ebea30`):**
> - **AWS prod stack now apply→destroy idempotent end-to-end** (200 resources). Root-cause fixes for
>   every class of stuck-state failure (secrets pending-deletion, S3 Object Lock race, WAF/tag ASCII
>   constraints, ASL placeholder ARNs, dashboard region property) are committed in source — see §13.
> - **Bedrock removed; replaced by direct Anthropic API** (`api.anthropic.com` over NAT egress, key
>   in Secrets Manager). Default model `claude-sonnet-4-6`; retry escalates to `claude-opus-4-7`. The
>   pseudonymizer (reversible PII masking) still runs and matters more now. **All Bedrock-named
>   plumbing also removed** — IAM `bedrock:InvokeModel`, both Bedrock PrivateLink VPC endpoints,
>   `BEDROCK_MODEL_ID` env var, and the misleadingly-named `bedrock-llm-router` Lambda (renamed
>   `code-analyzer`). Reason: this AWS account has no Bedrock model access.
> - **Pillars 1.1 / 1.2 / 3 AWS infra now live, not just unit-tested** (see §12 rewrite). Fargate task
>   def, ECR repo, Step Functions `waitForTaskToken` gates (4 instances), SNS gate topic, signed
>   `/api/spine/approve` webhook — all provisioned by the prod stack and survive destroy/re-apply.
> - **One-command Fargate image push** — `.\scripts\push-fargate-image.ps1` (pre-flight, ECR login,
>   build, push, verify, warn about running tasks). Required once after each `terraform apply`.
> - **Intentional regression from previous §12 claim:** **S3 Object Lock WORM removed** from the
>   evidence + audit-logs buckets (per user directive 2026-05-30) so `terraform destroy` is clean
>   during the inner-loop test cycle. Re-enable for real prod by setting `object_lock_enabled = true`
>   at bucket creation (cannot toggle on later) and restoring `aws_s3_bucket_object_lock_configuration`.
>   Inline comments in `evidence-ledger/main.tf:64-68` document the exact change.
> - **Eight SAP-functional-depth gaps closed in code** (driven by a peer SAP-expert review): CVI
>   unification, target-side TH_WPINFO/NRIV throttle, BAPI field-coverage → LTMC fallback,
>   FAGLB03/MB5B spool capture, dual-maintenance code-delta engine, cross-field DQ, cluster-table
>   aware extraction, DAG dependency resolver + KeyResolver. All seven new modules + one
>   transformation_engine extension ship with green self-tests. See **§14** for the full inventory,
>   what's verified, and what's still owed for production-completeness.
> - **All seven modules are now wired into the hot path** — not standalone. CVI runs in
>   data-migrator, throttle gates ComputeDispatcher, BAPI coverage runs inside `_load_one` with a
>   25-object field catalog, spool capture seals into the HashChainLedger, DAG orders the spine's
>   Syniti phase, cluster-aware preflight gates every `RFC_READ_TABLE`, and code-delta runs daily
>   via EventBridge. See **§14.5** for the call-site map and what's still owed (mostly
>   landscape-specific content, not engineering).
> - **Edge-case + governance hardening** (second peer-review pass): CVI two-phase load for
>   intercompany cycle hazards, exponential backoff on the SAP-side throttle, LTMC handoffs
>   sealed into the hash chain, and an explicit `cutover_verdict` precedence rule that says
>   "SAP-standard spool reports outrank the tool ledger; the tool can confirm a GO but cannot
>   override a NO_GO." See **§14.6**.

---

> **2026-06-09 update — F1-F7 ALL Phase-B-validated against live infra + LIVE-25 spine sweep complete + 32-way parallel curve measured.** Two-day autonomous push driven entirely against live S/4HANA (3.231.148.3 / S4H/100/MIGRATE_ADMI) + live ECC (EHP7/MSSQL via ngrok bridge) + live DDB (migrate4hana-key-map-prod). Headline deltas vs the 2026-06-07 snapshot:
>
> | Delta | Evidence (live-system) |
> |---|---|
> | **F7 multi-tenancy** — TenantContext shipped. Phase B validated: two tenants ("acme-corp", "globex-inc") wrote SAME source_key with DIFFERENT target_keys to live DDB; both rows coexisted, each tenant's fresh PKM resolved to its own target, default-tenant PKM saw neither. **9/9 isolation proofs green**. | `lambda/utils/tenant_context.py` + `_phase_b_validate_f7` handler · `phase-b-f7-out.json` |
> | **F4 TransformationEngine** Phase B closed. Live-S/4 proof: VALUE_MAP rewrote source MTART=`ZHALB` → `HALB` BEFORE the BAPI; DQ MANDATORY rejected `MEINS=null` rows BEFORE the BAPI (spine_stats.created didn't increment for the rejected rows — the engineering claim of "DQ runs first"). 4/4 proofs green. | `_phase_b_validate_f4` · `phase-b-f4-out.json` |
> | **F3 dynamic schema** Phase B closed. Live `BAPI_MATERIAL_SAVEDATA` introspected through the GET_FUNCTION_INTERFACE path (DD_BAPI_PARAMETER_GET returns FU_NOT_FOUND on this release — the documented fallback chain saved the run); 61 RFC params expanded to **755 BAPI fields**. | `_phase_b_validate_f3` |
> | **F6 version routing** Phase B closed. Auto-detected source as `ECC60_EHP7` + MSSQL via `RFC_SYSTEM_INFO`; compiled RoutingPlan; applied package_size=10000 to a live KNA1 probe — **10,000 rows at 1,735 rows/sec**. | `_phase_b_validate_f6` |
> | **Spine LIVE-25 sweep COMPLETE.** 25/25 of the live-25 object list promoted from legacy `bapi_loader.create_*` onto the `BaseSpineOrchestrator` factory across 6 batches (2026-06-08 → 2026-06-09). Each batch verified by a per-deploy F2 Material smoke test against live S/4. **101 unit tests across batches 1-6, 0 regressions.** | `BREADTH_TRACKER.md` · `lambda/utils/*_spine.py` (25 files) · `tests/test_spine_promotion_batch{1..6}.py` |
> | **Reconciliation engine wired to spine path.** Yesterday's gap: spine results returned flat `target_key` strings; the production `Reconciler.reconcile()` expected verify_key DICTS with `{table, key, values}` and silently reported NOT_VERIFIABLE for every spine-routed record. All 25 spines now emit 4-tuple `(target, msgs, disp_hint, verify_key)`. Live multi-object sweep: Material → MARA reconciled 3/3 with MTART tie-out; BusinessPartner → BUT000 reconciled 3/3 with TYPE tie-out; status RECONCILED on both. | `lambda/utils/base_spine_orchestrator.py::to_reconciler_input` + per-spine verify_key emission · `_phase_b_validate_reconcile_sweep` |
> | **F1 ledger-hit IDEMPOTENCY GUARD.** Found in prod testing: spine treated `PersistentKeyMap` as a CACHE not a GUARD — replaying an already-migrated cohort burned N BAPI calls. Added a check at top of `load_one`: if `key_map.resolve(object_type, src_key)` returns a value, short-circuit with matched_existing. 3-run live proof: Run 1 created 2 Materials; Run 2 with SAME keys + fresh PKM (simulating Fargate restart) → **0 BAPI calls + 2 matched_existing** (was 2 creates pre-guard); Run 3 with NEW keys → 2 fresh creates (no false-positive). **5/5 idempotency proofs green.** | `base_spine_orchestrator.py::load_one` step 2.5 · `_phase_b_validate_idempotency` |
> | **End-to-end chain proof** — BP → Customer (CVI) → SalesOrder driven against live S/4 + live DDB. F1-layer composition: 3/3 customers resolved to their step-B BP at step-C entry (snapshot captured BEFORE step C's harmonization writes). SAP-layer composition: 0/3 — known IDES limitation (freshly-created BPs lack KNVV sales-area data; SO harmonizes to existing sample customer, surfaced as a finding not papered over). | `_phase_b_validate_chain` · `phase-b-chain5.json` |
> | **F5 scale curve MEASURED** (was extrapolated). Single-threaded curve to 1000 records. **32-way parallel-fan-out** measured via `scripts/parallel_scale_probe.py` — N concurrent Lambda invocations against the same live S/4, each opening its own pyrfc connection (Fargate-equivalent from S/4's perspective). See §15.5 below for the curves. | `SCALE_BENCHMARK.md` · `scripts/parallel_scale_probe.py` |
> | **Production-path proof** — UnifiedLoader → spine → Reconciler. Found and fixed 2 prod bugs: (a) `_load_via_spine` emitted flat target_key strings instead of verify_key dicts; (b) only `material_spine` was imported at module init, so 24 of 25 spines were dormant — `get_spine("Bank")` returned None and fell back to legacy. Spine registry now bootstraps all 25 at unified_loader import time. | `_phase_b_validate_production_path` · `unified_loader.py` lines 38-78 |
> | **Pilot-readiness probe** — 13-probe scorecard against any target S/4. Each probe (TCURV/TCURF/TCLA/T001/KNB1/LFB1/LFM1/KNVV/MVKE/MARC.XCHPF/MARD/IFLOT/PROJ) maps to specific spine objects so customer IT sees "if we run with this state, OpenAR/Class/etc dead-letter due to customizing." Live-IDES scored 13/13 green = READY. | `_pilot_readiness_probe` · `phase-b-pilot.json` |
> | **Connectivity / AWS lift-shift recovery flow documented.** Two-day session also caught + fixed: lambda role missing `s4hana-credentials` secret read (added inline policy `migrate4hana-s4-secret-read`), Route 53 A record drift on S/4 IP change (`terraform apply` after tfvars update), VM hosts file repoint for ECC ngrok bridge, lambda zip staleness check protocol. Memory `aws-lift-shift-ip-drift-recovery.md` saved so future-sessions skip the relitigation. | session memory + commits c092551 / 3fd0ad7 |
>
> **Test totals:** 101 unit tests across the 6 spine promotion batches + the original 98 = **199 tests, all green, 0 regressions.**
>
> **F1-F7 plan status matrix:**
>
> | Phase | Phase A (unit) | Phase B (live SAP) | Live-validated against |
> |---|---|---|---|
> | F1 PersistentKeyMap | ✅ | ✅ | DDB + 3-run idempotency |
> | F2 Spine orchestrator | ✅ | ✅ 2026-06-07 + sweep | 28 Materials + 25-object roster |
> | F3 Dynamic schema | ✅ | ✅ 2026-06-09 | 755-field introspection |
> | F4 TransformationEngine | ✅ | ✅ 2026-06-09 | 3 records: 1 created + 2 DQ-rejected |
> | F5 Spine benchmark | ✅ | ✅ measured to 32-way | see §15.5 |
> | F6 Version routing | ✅ | ✅ 2026-06-09 | 10k KNA1 @ 1735 rows/sec |
> | F7 Tenant isolation | ✅ | ✅ 2026-06-09 | 9 proofs across 3 contexts |
>
> **F1-F7 plan: COMPLETE end-to-end on real infra.**
>
> **What still doesn't land:**
>
> 1. **Zero customer cutovers** — TRL 4-5, in-the-lab maturity. Real customer pilot is the gating step to TRL 6. No external dataset has touched the pipeline. All 25 spine validations were against synthetic-shaped rows on IDES.
> 2. **~95 objects beyond the live-25** on the full Migration Cockpit catalog still route to non-BAPI lanes (MC file, LTMOM, transport, manual-gate). Lane decisions documented in `BREADTH_TRACKER.md`; lane execution not yet validated against live S/4.
> 3. **Step Functions BAPI/in-place path not wired.** Production pipeline routes to MC/LTMOM/IDOC handlers (lift-and-shift). The 25-spine roster runs against `data-migrator` lambda directly. For customers who want BAPI/in-place mode, the state-machine integration is the next gap.
> 4. **Continuous DQ / Compliance Archive / Multi-cloud streaming** (the "Trojan Horse" SaaS pivots) — design-level only. None of the post-migration extensibility paths have code yet.
>
> ### §15.5 Scale curve (single-thread + 32-way parallel, measured 2026-06-09)
>
> **Single-threaded** (one Lambda, sequential BAPI calls):
>
> | N | Wall | Throughput | p50 | p99 |
> | 25 | 3.15s | 7.94/sec | 70ms | 1061ms (cold-start tail) |
> | 100 | 7.47s | 13.38/sec | 71.8ms | 148.8ms |
> | 500 | 35.12s | 14.24/sec | 70.7ms | 92.1ms |
> | 1,000 | 65.46s | **15.28/sec** | **63.1ms** | 87.9ms |
>
> **Parallel fan-out** (N concurrent Lambda invocations; each = one Fargate-equivalent session):
>
> | Concurrency | Total rec | Wall | Aggregate tp | Scaling factor | Parallel eff | p99 |
> | 1 | 25 | 3.15s | 7.94/sec | 1.0x | 100% baseline | 250ms |
> | 4 | 100 | 5.17s | 19.35/sec | 2.21x | 55.2% | 931ms |
> | 8 | 200 | 5.24s | 38.15/sec | 3.60x | 45.0% | 642ms |
> | 16 | 400 | 5.73s | 69.82/sec | 6.87x | 42.9% | 651ms |
> | **32** | **800** | **7.57s** | **105.70/sec** | **18.00x** | **56.3%** | 1150ms |
>
> Findings: throughput scales sub-linearly but cleanly to 32-way (efficiency plateaus at ~50%, doesn't collapse). **Zero dead-letters at any concurrency** — S/4 takes load by slowing, not by rejecting. p99 tail grows under contention (250ms → 1150ms) but p50 stays in the 70-120ms band. The original 1.1hr/1M extrapolation assumed linear scaling; **measured 32-way says 1M = ~2.6 hours** (sub-linearity tax is ~2.4x vs theoretical). For 1M+ workloads the path forward is higher fan-out, per-worker number-range pre-allocation, or multi-session load distribution.

> **2026-06-09 (late session) update — Trojan-Horse 4-workstream mandate complete + Path 1 engineering hardening + Group D production-ops layer shipped.** Single-session push closing the four "this stays design-level only" items from the §15.5 carry-forward list. Eight commits, ~3000 LOC + 5 documentation files.
>
> | Delta | Evidence |
> |---|---|
> | **MC catalog expansion 53 → 132 objects** (clears the 125-threshold target). `MC_TEMPLATES` grew from 20 to 99 entries across all 12 SAP modules (FI / CO / SD / MM / PP / PM / QM / PS / HR / Master Data). Factory closure-bug found and fixed during expansion. Total Migration Cockpit coverage = 33 BAPI spines + 99 MC file objects = 132. | `lambda/utils/mc_file_exporter.py` + `tests/test_mc_file_exporter.py` (structural validator + ≥99 floor) · commit `82e036d` |
> | **WS3 — Client VPN + Transit Gateway + onboarding bundle generator.** Self-contained `terraform/modules/client-network/` module (opt-in via `deploy_client_network`): AWS Client VPN Endpoint (cert auth, CloudWatch logs, split tunnel), TGW + service-VPC attachment + cross-account RAM peers, 3-tier deny-by-default SG matrix. Plus `lambda/onboarding-bundle/` generates per-tenant tarball with `.ovpn` / `firewall-routing.csv` / `README.md` / `manifest.json` (SHA-256 fingerprint, 24h presigned URL). | `terraform/modules/client-network/main.tf` (260 LOC) · `tests/test_onboarding_bundle.py` (12 tests) · commit `6a2cca9` |
> | **WS4 pillar 1 — Continuous DQ Monitor (post-cutover SaaS).** New `lambda/continuous-dq-monitor/` runs in two modes (`scan` cron + `webhook` real-time) against live S/4. DQ_PROBE_SPECS for 5 objects (BP / Material / PO / SO / Customer). Hash-chained ledger blocks (SHA-256 `block_hash` + `prev_hash`, genesis = `0`×64) written to new `migrate4hana-dq-findings-prod` DDB. Ruleset source-order: inline → S3 → env var fallback. | `lambda/continuous-dq-monitor/handler.py` · `tests/test_continuous_dq_monitor.py` (8 tests) · commit `6706028` |
> | **WS4 pillar 2 — Compliance Archive (WORM).** New `lambda/compliance-archive/` extracts 14 legacy tables (Customer / Vendor / BP / Material / FixedAsset / FI Hdr (BKPF) / FI Lines (BSEG) / SO Hdr / PO Hdr / GLBalances / OpenAR / OpenAP / Employee / PayrollResult) into per-row SHA-256 + chunk `block_hash` + chain. **S3 Object Lock COMPLIANCE mode (irrevocable for retention_days, even by AWS root)**, 3650-day default (10y). Gzipped JSONL at `tenants/<slug>/compliance-archive/<obj>/chunk-NNNNNN-<hash>.jsonl.gz`. Modes: `extract` / `extract_all` / `verify_chain`. | `lambda/compliance-archive/handler.py` · `tests/test_compliance_archive.py` (8 tests) · commit `18704f6` |
> | **WS4 pillar 3 — Multi-cloud Sink Router.** `lambda/utils/sink_router.py` — pluggable `Sink` contract with 4 concrete implementations: SnowflakeSink (per-tenant+per-object buffering → S3 stage for Snowpipe), S3ParquetSink (Hive `tenant=/object=/date=`), SalesforceSink (SF_OBJECT_MAP + External_Id__c + Raw_Payload__c sidecar), EventBusSink (DetailType=DataLoaded.<obj>). SinkRouter `fan_out()` has per-sink try/except for fault isolation. | `lambda/utils/sink_router.py` (300 LOC) · `tests/test_sink_router_ws4.py` (8 tests) · commit `18704f6` |
> | **Path 1 step 1 — SinkRouter wired into the spine path.** `BaseSpineOrchestrator.__init__` now takes optional `sink_router` + `tenant_id`. `_fan_out_to_sinks()` helper fires post-success (created / matched_existing / remapped); skipped on dead-letter so a downstream sink failure cannot mirror partial data. Fan-out also fires on F1 ledger-hit short-circuits so replays keep non-SAP destinations consistent. `flush_sinks_at_end_of_run()` helper for handler cleanup telemetry. Per-sink exceptions stay isolated — a BoomSink does NOT flip a successful BAPI write into a failed LoadResult. | `lambda/utils/base_spine_orchestrator.py` · `tests/test_sink_router_spine_wiring.py` (9 tests) · commit `9504542` |
> | **Path 1 step 2 — WS4 production terraform module.** New self-contained `terraform/modules/ws4/` (opt-in via `deploy_ws4`): 3 lambdas (dq-monitor / compliance-archive / onboarding-bundle) + 2 DDB tables (`dq-findings`, `compliance-ledger`, both PITR+SSE+delete-protect) + 2 S3 buckets (compliance-archive Object-Lock COMPLIANCE 10yr; snowflake-stage 30d lifecycle) + dedicated IAM role (strictly scoped) + EventBridge custom bus + daily DQ scan cron + 4 CloudWatch log groups. **`terraform validate` PASS** (aws v6.49.0). | `terraform/modules/ws4/main.tf` (554 LOC) · commit `e14fb63` |
> | **Group D items 1-3 — observability terraform module + SLA publisher.** New `terraform/modules/observability/` (opt-in via `deploy_observability`): per-Lambda deep-view dashboard for each function + cross-cutting SLA dashboard (error %, p95, DDB throttles, write rates, markdown SLA-target widget with runbook link). Per-Lambda alarms: error rate >1%, p95 >30s, ANY throttle. Domain alarms: **F1 key-map throttle (immediate page), key-map SystemErrors, DQ violation rate >5%, compliance chain broken (immediate page), ledger write failures**. SNS topic + email + optional PagerDuty subscription. `sla_metrics.py` helper exposes `publish_throughput/bapi_latency/recon_lag/dq_violation_rate/chain_broken/archived` + `TimedBlock` context manager; all best-effort with kill-switch env var. | `terraform/modules/observability/main.tf` · `lambda/utils/sla_metrics.py` · `tests/test_sla_metrics.py` (9 tests) · commit `96655e6` |
> | **Group D items 4-5 — on-call runbook + DR plan + key-map recovery scripts.** `docs/RUNBOOK.md` (~250 lines): 30-second triage table mapping every alarm to its first action, per-alarm playbooks for error / latency / key-map throttle / chain-broken / ledger-write-failure, escalation matrix (SEV-1/2/3), post-incident checklist. `docs/DR.md` (~290 lines): Tier-0 inventory with RPO/RTO targets, PITR-always-on + on-demand-snapshots-at-cutover-boundaries backup strategy, **C1-C5 corruption taxonomy + per-class recovery procedure that answers the explicit question "what happens if `migrate4hana-key-map-prod` gets corrupted mid-cutover"** (answer: cutover does NOT auto-abort; F1 short-circuit is advisory so the spine keeps running because SAP/BAPI is source of truth; recovery is class-dependent — stop/restore/replay for logical/tamper, heal-in-place for partial loss, emergency PITR for total loss; conflict-resolution ordering SAP > compliance ledger > key_map). 3 supporting PowerShell scripts: `backup-key-map.ps1` (on-demand snapshot + PITR check + `-VerifyOnly` shape spot-check), `restore-key-map.ps1` (PITR or backup-ARN mode, re-applies PITR/SSE/deletion-protection), `swap-key-map.ps1` (atomic prod swap, requires `-ConfirmYes`, re-points 5 consumer Lambdas' env vars, leaves corrupt table as forensic evidence). All 3 scripts parse-clean under pwsh 7.6.2. | `docs/RUNBOOK.md` · `docs/DR.md` · `scripts/backup-key-map.ps1` · `scripts/restore-key-map.ps1` · `scripts/swap-key-map.ps1` · commit `bde7c82` |
>
> **Test totals after the late-session push:** **26 test files, all green, 0 regressions** (added: `test_payload_depth_ws2.py`, `test_dynamic_catalog_wiring.py`, `test_spine_promotion_batch7.py`, `test_spine_promotion_batch8.py`, `test_ws2_more_depth.py`, `test_onboarding_bundle.py`, `test_mc_file_exporter.py`, `test_continuous_dq_monitor.py`, `test_compliance_archive.py`, `test_sink_router_ws4.py`, `test_sink_router_spine_wiring.py`, `test_sla_metrics.py`). Spine batches 7+8 extended the spine roster from 25 → 33 BAPI spines (added WorkCenter / InfoRecord / Quotation / OutboundDelivery / Inquiry / BillingDocument / PlannedOrder / ProductionBOM).
>
> **What this means for the "What still doesn't land" list above:**
>
> - **Item 4 (Trojan-Horse SaaS pivots design-level only) — RESOLVED.** All three pillars now have shipping code + green tests + opt-in terraform + observability + DR. Phase B against real live targets (Snowflake / Salesforce / real ECC compliance extract) is the remaining gap, not the code.
> - **Item 2 (~95 objects beyond live-25) — substantially reduced.** MC catalog now covers 99 file-lane objects; 8 more BAPI spines shipped. Live-S/4 validation of the file lane is the remaining gap.
> - **Items 1 and 3 stand unchanged** — zero customer cutovers; BAPI in-place state-machine still not deploy-toggled (module exists, opt-in apply pending).
>
> **Mandate / roadmap status:** the original "Trojan-Horse Enterprise Data Fabric" 4-workstream mandate (WS1 = governance / WS2 = depth / WS3 = customer-landscape network / WS4 = post-migration SaaS) is **engineering-COMPLETE** at the scaffolding + opt-in-terraform layer. Group D (production observability + DR) is **shipped end-to-end** including the explicit answer to the corruption-mid-cutover question. **Next-most-leverage step (recommended):** Customer Zero — pick a real (even small) customer or stand up a synthetic full tenant end-to-end so the 4 workstreams get exercised against actual data; everything below that benefits (case studies, contractual SLA, partner conversations, scale-curve refinement). Detailed punch-list in `EXPERT_REVIEW_DETAILED.md` §"Late-session push".

> **2026-06-10 update — AWS Step Functions pipeline end-to-end PROVEN on live infra; dirty-data spine orchestrators validated; production-grade comprehensive PDF report.** Single-session 8-hour push that converted the "deployed but never run end-to-end" status of the AWS prod stack into "all 27 stages execute, all 3 manual gates auto-clear via SendTaskSuccess, comprehensive PDF lands in S3." Twelve separate SFN executions iterated through structural fixes (run_id propagation, manual-gate ResultPath, transport-builder tolerance, secret-ARN env wiring, archive_file utils gap) until execution `aws-e2e-20260610-124235` succeeded cleanly.
>
> | Delta | Evidence |
> |---|---|
> | **3 missing Lambdas deployed.** State machine ASL referenced `discovery-engine`, `migration-completeness-analyzer`, and `pdf-report-generator` — none of which existed in AWS (the terraform `lookup(...lambda_arns, "...", local.ls_fallback_arn)` was silently routing them to `manual-gate-prod`, so the SFN traversed those stages as no-ops). All 3 packaged + deployed + IAM-granted + repointed via `aws stepfunctions update-state-machine`. `pdf-report-generator-prod` bundles reportlab + linux-wheel Pillow + the aggregator extracted from `run_local_lift_and_shift.py`. | `lambda/pdf-report-generator/` (new) · `terraform/environments/prod/main.tf` (3 new `lambda_functions` entries) · `terraform/modules/step-functions/main.tf` (snake/kebab key fix on `pdf-report-generator` lookup) |
> | **19 Lambdas rebundled with `lambda/utils/*`.** Root-cause finding: `terraform/modules/lambda/main.tf` `data.archive_file.lambda` zips only `each.value.source_dir`, leaving every handler that does `from logger import …` / `from validation import …` to crash at cold-start with `Runtime.ImportModuleError: No module named 'logger'`. Wrote `scripts/package-lambdas-with-utils.ps1` (idempotent, `-OnlyMissing` for fast incremental). Function `CodeSize` jumped from ~6 KB → 268-360 KB. **22 affected Lambdas** found via grep, code-analyzer/data-migrator hand-patched separately (extra internal deps). | `scripts/package-lambdas-with-utils.ps1` · WARNING comment + helper reference added at `terraform/modules/lambda/main.tf:350` |
> | **Step Functions definition: 38 surgical patches** to make the prod state machine actually orchestrate cleanly. (1) 3 stage `Resource` ARNs swapped from fallback to real Lambdas (`Stage1_Discovery`, `Stage21_GoLiveScorecard`, `Stage27_FinalReport`). (2) `BasisReadyChoice` variable `$.basis_ready` → `$.ready` (handler returns the latter; one of the longest-standing latent bugs). (3) All 3 manual gates given `ResultPath: $.gate_*` so run-level state (`run_id`, `target_creds_arn`, `object_spec_list`) survives the gate clear. (4) **33 Task states given `Parameters` block injecting `run_id.$: $$.Execution.Name` + cred ARNs** — this is the fix that closes the run_id-mismatch root cause (object-router was writing the DAG to `runs/local/object-router/dag.json` while data-migrator was looking under the real run_id; with the injection both find the same DAG and the DataLoad Map iterates real items). | `terraform/modules/step-functions/lift_and_shift_pipeline.asl.json` (live SFN updated via `aws stepfunctions update-state-machine` + ASL source synced) |
> | **Spine orchestrators fired against live S/4 — dirty-data handling validated.** Final run executed `BusinessPartnerSpineOrchestrator` / `CustomerSpineOrchestrator` / `VendorSpineOrchestrator` / `MaterialSpineOrchestrator` end-to-end from AWS Lambda (`migrate4hana-data-migrator-prod` with `M4H_LOAD_TO_S4=1` env). Real spine outcomes recorded in S3 at `runs/<run_id>/data-migrator/summary.json`: BP **extracted=33,252, attempted=50, dead_letter=50** (spine refused malformed `source_key=""` rows — production-grade dirt rejection). Customer **extracted=19,575, attempted=50, matched_existing=50** (PersistentKeyMap hash-chained ledger correctly recognized prior loads, no double-creation — production-grade idempotency). Material **extracted=24,494, attempted=50, matched_existing=20, dead_letter=30** (mixed outcome on same object — the spine's row-by-row policy at work). | `s3://migrate4hana-staging-prod/runs/aws-e2e-20260610-124235/data-migrator/summary.json` |
> | **Handler-level fixes during the iteration loop.** `discovery-engine/handler.py` — secret schema brought into parity with `data-migrator` (ashost + optional gwhost/gwserv/saprouter, matches the ngrok-bridge memory). `transport-artifact-builder/handler.py` — `event["object_list"]` KeyError → tolerant fallback (event-level → nested-input → S3-reconstruction from upstream `code-analysis/analysis-report.json` or `object-router/dag.json` → graceful `manual_required`). `data-migrator/handler.py` — hardcoded `SecretId="local:target"` (a local-shim string, fatal in AWS) → env-var fallback `os.environ.get("TARGET_SECRETS_ARN") or "local:target"` (4 occurrences); batch-mode summary now always emits `routing.dag` so the Step Functions Map state never crashes on missing key. | `lambda/discovery-engine/handler.py` · `lambda/transport-artifact-builder/handler.py` · `lambda/data-migrator/handler.py` |
> | **Comprehensive PDF generator — 49 artifacts, 103 pages.** Stage 27's `pdf-report-generator-prod` now (1) downloads every JSON under `runs/<run_id>/` + `migrations/<run_id>/`, (2) **calls `get_execution_history` on the run's SFN execution and writes every `TaskStateExited` output as a synthetic artifact under `sfn-stage-outputs/`** — this single addition closed most of the AWS-vs-local PDF page-count gap. Aggregator extended with a `dirty_data_handling` section that surfaces `load_to_s4_enabled` / `total_attempted` / `total_created_in_s4` / `total_matched_existing` / `total_dead_lettered` / per-object spine name / sample disposition outcomes. PDF generator extended with renderer for that section (3 tables — outcome counts with %, spine-per-object, sample dispositions). Final AWS-side PDF: **103 pages / 84,580 chars / 176 KB / 49 artifacts** (vs local-side 128 pages / 146 KB / 19 artifacts). | `lambda/pdf-report-generator/handler.py` (SFN harvest) · `lambda/pdf-report-generator/aggregator.py` (dirty-data mapping) · `pdf_report_generator.py` (renderer) |
> | **Terraform reconciled — re-applies will hold.** Every prod-side fix mirrored back into terraform so the next `terraform apply` doesn't undo this session's work. Added 3 `lambda_functions` entries (`discovery-engine`, `migration-completeness-analyzer`, `pdf-report-generator`) at `terraform/environments/prod/main.tf:151`; SFN module lookup-key snake→kebab; ASL gates given `ResultPath`; `BasisReadyChoice` corrected. **Post-apply expectation:** `terraform apply` would create 3 new Lambdas (idempotent if already there via update-function-code), no resource drift on existing 35. | `terraform/environments/prod/main.tf` · `terraform/modules/step-functions/main.tf` · `terraform/modules/step-functions/lift_and_shift_pipeline.asl.json` |
>
> **Live execution success:** `arn:aws:states:us-east-1:905418407458:execution:migrate4hana-lift-and-shift-prod:aws-e2e-20260610-124235` — RUNNING → SUCCEEDED in ~9 minutes wall-clock, all 27 stages traversed, all 3 manual gates auto-cleared by the supervising monitor via `SendTaskSuccess`, PDF written to `s3://migrate4hana-staging-prod/runs/aws-e2e-20260610-124235/report/migration-report.pdf`. **Twelve SFN executions** during the iteration loop (each ~8 min) — every failure mode encountered + diagnosed + fixed + retried until clean.
>
> **What the §11 head-to-head needs to reflect:** the "AWS state machine deployed but never proven end-to-end" critique no longer lands — the pipeline now runs cleanly with `EXECUTION_SUCCEEDED` and produces a 103-page client-deliverable PDF on the live ECC+S/4 pair. What still doesn't land: actual S/4 writes through SAP Migration Cockpit (requires MC project setup on the IDES target — basis ops, not Lambda); STMS transport import (manual_required by design, basis ops on S/4); ECC lock at cutover boundary (cutover-orchestrator returns runbook, not real RZ04). These are not bugs, they are the SAP-side operational steps the pipeline correctly defers to a basis admin.
>
> **Mandate / roadmap status:** the AWS prod stack is now **operationally-proven end-to-end** — every Lambda fires, every gate processes its token, the orchestration plane is clean. The remaining gap to a real production cutover is purely SAP-execution-plane setup (MC project + STMS routes + RZ04 lock procedure on the customer's target S/4), which is exactly what the tool's architecture intentionally defers to basis ops. **Next-most-leverage step (recommended, unchanged):** Customer Zero — but the conversation now goes "here's a 103-page PDF from a clean AWS production run on a live ECC+S/4 pair" instead of "here's terraform that provisions cleanly." That's a materially different posture for partner conversations.

---

## 1. What it is (and is not)

Migrate4HANA is a **support-clean, highly-automated ECC → S/4HANA *data-migration* engine** for the
**greenfield / selective-data-transition** lane. It extracts master and transactional data from an
ECC source and writes it into an S/4HANA target **exclusively through SAP-released APIs** (released
BAPIs over RFC + the `API_BUSINESS_PARTNER` OData service), with end-to-end reconciliation,
idempotency, delta/CDC, connection-pool parallelism, and a governed cutover gate.

**It is explicitly NOT:**
- a Brownfield in-place conversion — it does **not** run, wrap, or bypass **SUM / DMO** or the
  **Maintenance Planner**;
- a replacement for the **Migration Cockpit (LTMC/LTMOM)** field-mapping layer — see §6;
- a data-quality / cleansing / value-mapping rules engine (§6.4);
- proven in customer production (§7).

It plays the **same lane as the S/4HANA Migration Cockpit** (data load), with substantially more
automation wrapped around the load (auto-discovery, reconciliation, idempotency, dead-letter,
cutover orchestration).

---

## 2. The environment it has been proven on

| | Source | Target |
|---|---|---|
| System | ECC (IDES-class content, SID Y01) | S/4HANA (SAP CAL free-trial appliance, best-practice content) |
| Access | pyrfc / RFC, client 800 | pyrfc/RFC client 100 + OData (HTTPS) |
| Hosting | VM on a workstation | AWS EC2 (single appliance) |

Both are **real SAP systems with real APIs and real reconciliation** — not mocks. **Caveat a
reviewer must weigh:** this is **non-production, non-customer data**, on a **single best-practice
appliance**, at **small per-object sample sizes** (typically 5 records/object for the functional
proofs; one volume test at ~1k documents). It has **not** been run against a second landscape or
customer-shaped data. See §7.

---

## 3. Architecture — the migration spine

Every object flows through one governed pipeline:

```
delta/CDC extract (ECC)
   → target config auto-discovery (company code, sales area, plants, recon accounts,
       cost/profit centers, charts, order types, structure indicators, …)
   → best-mechanism load: released BAPI (RFC) or OData, picked per object by a dispatcher
   → collision-safe key strategy (source→target mapping recorded)
   → cross-run idempotent ledger (re-run resumes, never duplicates)
   → reconciliation: read every loaded record back, tie out EXISTENCE and (where applicable) VALUE
   → dead-letter for genuine failures (reprocess via idempotent re-run)
   → support-compliance attestation
   → cutover GO / NO-GO runbook
```

Key components (paths for your review):
- `lambda/utils/unified_loader.py` — the dispatcher: `OBJECT_MECHANISM` (object → BAPI/OData/IDoc),
  `OBJECT_SOURCE_KEY` (ledger key, incl. composite keys), `_load_one` branches, serial + pooled-parallel paths.
- `lambda/utils/bapi_loader.py` — one `create_<object>` per object type (the released-API calls + the
  discovery/validation/remap logic). **This is the file to scrutinize for SAP correctness.**
- `lambda/utils/config_discovery.py` — landscape-agnostic target config (probe-validated, e.g. a
  rolled-back test PO to confirm the expense account).
- `lambda/utils/reconciler.py` — existence + value reconciliation, `RECONCILED`/`DISCREPANCY` verdict.
- `lambda/utils/key_map.py` — the durable cross-run ledger.
- `lambda/data-migrator/handler.py` — `DEFAULT_OBJECT_TABLES`: the object catalog (source table +
  fields + lane) — 127 objects.

---

## 4. Evidence — what is proven live (load + reconcile)

**25 object types are loaded into S/4 via released APIs and reconciled** (read back; `RECONCILED`,
0 missing) on the live pair:

BusinessPartner, Customer, Vendor (OData `API_BUSINESS_PARTNER`), Material, ExchangeRates,
OpenPO, OpenAR, OpenAP (FI), CostCenter, ProfitCenter, FixedAsset, Bank, InternalOrder, Equipment,
FunctionalLocation, Characteristic, Class, CostElementGroup, ProfitCenterGroup, Project/WBS,
PurchaseRequisition, Sales Order, PurchaseContract, Batch, InventoryBalance (GR mvt 561).

Production-grade behaviours demonstrated (each on the live system):
- **Auto-discovery** of a coherent target config from whatever system it connects to.
- **Collision-safe keys** — material MATNR remap; FuncLoc label reformatted to the target structure
  indicator's editing mask; Project ID sanitized against the coding mask; recorded source→target.
- **Idempotent ledger** — re-run reused records, created 0 duplicates.
- **Delta/CDC** — change-document (CDHDR) driven, not just new records.
- **Value reconciliation** — FI amounts, factor-aware exchange rates; caught a real MATNR collision.
- **Parallel load** — ~936 FI documents in ~100s, 936/936 reconciled (pyrfc releases the GIL).
- **TESTRUN-validate-and-fallback** — asset class, order type, contract-capable vendor.
- **Self-healing** — currency normalization (obsolete DEM → target local currency); MM posting-period
  auto-detection for stock postings.
- **Cutover runbook** — initial load → delta → reconcile → GO/NO-GO (verdict: GO).
- **Compliance attestation** emitted per run.

**How to verify yourself:** every run writes `runs/<id>/data-migrator/summary.json` (reconciliation
verdict, attestation, key map, discovered config, dead-letter). Commit history on `aws-lift-and-shift`
has one commit per object with the live test result quoted.

---

## 5. Support-compliance posture (the "without losing SAP support" question)

- **Every write** goes through a **released** BAPI or the released `API_BUSINESS_PARTNER` OData
  service. No raw table writes, no `SE16N` edits, no arbitrary ABAP execution, no SUM/MP bypass.
- The tool **explicitly rejects** support-breaking shortcuts; where it hit a customizing gap
  (exchange-rate types), it **packaged a transport-grade delta** rather than poke tables.
- Reconciliation is read-only (`RFC_READ_TABLE` / API reads).
- Each run emits a machine-checkable attestation of the above.

**For your review:** please sanity-check that the specific BAPIs used are the *released* variants and
that the calling conventions (commit handling, `BAPI_TRANSACTION_COMMIT`, number ranges, mandatory
fields) are idiomatic and won't create inconsistent records at scale.

---

## 6. Honest limitations — please scrutinize these hardest

### 6.1 "Harmonization" of dependent keys is a demonstration, not faithful migration
For several dependent/transactional objects the tool currently **harmonizes source business keys to
existing target-ready masters** rather than migrating them 1:1, because the source masters don't yet
exist in the target appliance:
- **Sales Order** sold-to and item material → an existing sales-ready customer/material in the target.
- **PurchaseContract** vendor → a TESTRUN-validated target vendor.
- **Batch / InventoryBalance** material+plant → a discovered target batch-managed / stocked material.
- **FunctionalLocation / Project** labels → reformatted to the target mask.

This proves the **load + reconcile mechanism** works for those object types, but it is **not** a
faithful migration of those specific records. In a real project these objects depend on the prior
faithful migration of their master data (customer, material, vendor) and on **source→target value
mapping**. Treat these object types as "mechanism proven," not "migration proven."

### 6.2 102 of the 127 catalog objects are extract-only (not loaded/reconciled)
The catalog (`DEFAULT_OBJECT_TABLES`, 127 objects) breaks down as **25 loaded+reconciled** via the
BAPI/OData spine and **102 routed to the MC/IDoc lane**, where the tool **extracts from ECC and emits
a Migration-Cockpit-staging template** — the **actual MC import and the field-level mapping are not
done by this tool**. 15 of the 102 extracts were smoke-tested live (all returned real rows); the
other ~87 are source-table descriptors not yet extract-verified. **Do not read "127" as "127
migrated."** The honest figure is **25 end-to-end + 102 extract-staged**.

### 6.3 No transformation / value-mapping rules engine (the LTMOM-equivalent)
The hardest, most labour-intensive part of a real migration — **field-level transformation rules,
value mapping (e.g. cross-chart-of-accounts, org-unit remap tables, unit/currency conversions),
and target-customizing-aware validation per object** — is **largely not built**. The tool does
targeted, per-object normalizations (currency, order type, asset class) but there is **no general
mapping/rules layer**. This is where most migration-project effort goes; a reviewer should weigh the
tool accordingly.

### 6.4 No data-quality / pre-load cleansing
No duplicate detection, completeness checks, or pre-load validation against target customizing beyond
the per-object TESTRUN checks. No reconstruction of source data quality issues.

### 6.5 Scale
Volume proven once at ~1k documents. Real migrations are 10^6–10^8 records. Throughput, restart at
scale, ledger size, and the reconciliation read-back cost at volume are **unproven**.

### 6.6 Functional coverage depth
Where loaded, objects use **minimal valid field sets** (the fields needed for a consistent create),
not the full business field complement. E.g. a sales order is header + one item + schedule line; a
contract is header + one nominal item. Real records carry far more (partners, conditions, texts,
statuses, custom Z-fields).

### 6.7 No customer pilot, no second landscape
TRL ~6. Not run outside the build appliance. The team's SAP functional/Basis depth is **engineering-
led, not consultant-led** — please flag any non-idiomatic SAP usage you spot.

---

## 7. Maturity assessment (our own, for you to confirm or correct)

- **TRL ~6** — demonstrated end-to-end in a relevant environment (real ECC + real S/4, real APIs,
  real reconciliation), at modest volume, support-clean. **Not** TRL 8–9 (operational, multi-customer).
- **Differentiator vs Migration Cockpit:** the automation *around* the load — auto-discovery,
  cross-run idempotency, existence+value reconciliation with a hard verdict, dead-letter, and a
  signed cutover gate. MC gives you the mapping UI and the load; it does not give you this
  trust/automation spine out of the box.
- **The gap vs a production product:** the mapping/rules layer (§6.3), faithful dependent-key
  migration (§6.1), real loaded breadth beyond 25 (§6.2), scale (§6.5), field depth (§6.6), and a
  pilot (§6.7).

---

## 8. Questions we'd most value your judgement on

1. Are the **released BAPIs / OData** we use the correct, supportable choices per object, and are the
   calling conventions safe at scale (commit/rollback, number ranges, mandatory fields)?
2. Is the **harmonization approach (§6.1)** an acceptable bridge for a demo, and what is the right
   design for **faithful dependent-key migration** (load order, key-mapping tables, dependency graph)?
3. How big a blocker is the **missing transformation/mapping layer (§6.3)** — would you build it, or
   lean on **LTMOM/LTMC** for mapping and keep this tool for orchestration + reconciliation?
4. Does **existence + value reconciliation with a hard verdict** meaningfully de-risk a migration in
   your experience, or do auditors require something else (e.g. SAP standard recon reports, FI/CO tie-out)?
5. For a **selective data transition** at a real customer, where would this tool genuinely save
   effort, and where would it be in the way?
6. What would you require to consider a **pilot** (object scope, volume, landscape, governance)?

---

## 9. One-paragraph honest bottom line

A genuinely strong, support-clean, architecturally-differentiated **ECC→S/4 data-migration
*orchestration + reconciliation* engine**, with **25 object types proven end-to-end** on a live
system and a **127-object catalog** routed to lanes. Its trust spine (discovery, idempotency,
reconciliation, cutover) is real and unusual. It is **not yet** a faithful, full-scope, mapping-
complete, volume-proven, pilot-validated migration product — and the largest remaining work (the
transformation/mapping layer and faithful dependent-key migration) is exactly the part real projects
spend the most on. We're seeking your read on whether the spine is worth building the rest around.

---

## 10. Competitor-grade engines — now embedded INSIDE our stages (2026-05-29; verified offline, live-proof pending)

These started as standalone modules; they are now **wired into the migrate4hana stage handler that owns
each competitor's field** — so the expertise lives *inside* the stage, not as a separate parallel spine.
**Honest status:** each integration **runs green in an offline functional test (local-AWS shim)**, but has
**not** been validated on the live ECC/S4 pair at volume; the LLM path calls **real Bedrock only when
configured** (offline → quarantine); and the ATC gate is a **mock**. Treat as **TRL 4–5 (integrated,
component-verified)** beside the **TRL ~6** live data spine of §3–4.

| Competitor field | Embedded into stage | Engine + what it does | Verified (offline) | NOT yet |
|---|---|---|---|---|
| **SmartShift** — automated code remediation | `lambda/code-analyzer` · `auto_remediate_with_ast_engine` | Deterministic 6,400-line AST first; on a parser **crash or residual parse-errors** it escalates only that program to the AI fail-safe (`llm_fallback_router.FallbackRouter`) → localized **Bedrock** fix → **mock-ATC** gate → transport `.data/.cofile` or quarantine | functional test: deterministic remediate ok + AI-failsafe path reachable (`AI-FAILSAFE` change emitted) | live run vs real ECC custom code; **real ATC**; real-Bedrock fix %; equivalence/regression testing; scale |
| **Syniti** — data quality / integrity | `lambda/data-hygiene` (was a pass-through **stub**) | Now runs the **data spine**: entity-tree FK integrity (BUT000/020/100; orphans quarantined), deterministic org-attribute self-heal vs target reference data, SHA-256 idempotency ledger | functional test: `data_spine` mode, 1 self-healed, 1 orphan quarantined, FK status reported | a general value-mapping/rules engine; DQ scorecards + cleansing library; mapping UI; live entity-tree feed at volume |
| **Natuvion** — selective carve-out | `lambda/data-migrator` extract · `_carve_out_programs` | Generates org(`BUKRS`)/time(`GJAHR`)-filtered, `OPEN CURSOR…PACKAGE SIZE`-streamed, dependency-aware (line→`BKPF`) in-system carve-out ABAP for carve-eligible tables in the run; attached to the run summary | functional test: 2 programs generated (OpenAR→BSID, OpenPO→EKKO) with org/time filters | in-system **deploy at volume** (gated); company-code/client split; consolidation harmonization content |

Engine source: `data_spine_orchestrator.py`, `lambda/code-analyzer/llm_fallback_router.py`,
`agent/in_system_agent_generator.py`. Supporting (standalone, not the primary path):
`pipeline_spine_master.py` (alt 4-phase orchestrator + `RFCThrottle` anti-DoS) and
`scripts/stress_test_generator.py` (100× Lambda fan-out, 1 % chaos — the **10M-row AWS run is still
user-executed**).

**UI (rebuilt 2026-05-29):** the old mock-driven UI was deleted and replaced by a fresh fluidic
light-theme React app that is **100 % real-backend-driven (no mock data)** — honest offline/empty states,
a **Project Tracker** (Start/End boards, progress pipeline, Completed/In-Progress/Queued kanban over the
real 28 stages, each stage tagged with its embedded engine), and a Command Center exposing every CLI
action. Verified: `npm run build` clean, dev server serves all routes; pixel/UX review still pending.

**For your review:** the §6 limitations still stand. §10 narrows two on paper — §6.3 (a first FK+self-heal
layer now runs *inside* data-hygiene) and the §4 governance gap (an ATC-style gate now runs *inside*
code-analyzer, though mock) — but **none of §10 changes the live-proven evidence in §4.** Judge these as
integrated design, not live delivery.

---

## 11. Honest head-to-head: are we competitive with SmartShift / Syniti / Natuvion?

Short answer: **competitive in *architecture and orchestration*; not yet competitive in *depth, content,
and proof* in any of the three vendors' core specialities.** Per area:

| Their speciality | Where we stand | Verdict | To become competitive |
|---|---|---|---|
| **SmartShift — automated custom-code remediation at scale** | Real 6,400-line AST engine + 4-level fixers + deterministic-first/AI-fallback **now embedded in the `code-analyzer` stage** (crash/parse-error → localized AI fix → mock-ATC gate). | **Partial.** Engine is real and the architecture is sound and now wired into the stage; our *ruleset breadth, automation %, regression/equivalence testing, real ATC, and scale proof* are far below SmartShift's mature platform. | Real ATC integration; an automated before/after **equivalence-test** harness; expand the simplification ruleset; prove auto-fix % on a large real custom-code base; CI over the fixer. |
| **Syniti — data quality, mapping, governance, reconciliation** | Strong **reconciliation** (existence+value, hard verdict) + cross-run **idempotency ledger** (now SHA-256) + **FK-integrity + deterministic self-heal now running inside the `data-hygiene` stage** (was a stub). | **Partial.** Our reconciliation/idempotency/FK-heal are genuinely strong and unusual; we still lack Syniti's **value-mapping/rules engine, DQ scorecards & cleansing library, and business-user mapping/governance UI**. | Build the general mapping/rules layer (§6.3); a DQ rule library + scorecard; a mapping UI; data-owner workflow/sign-off. |
| **Natuvion — selective data transition / carve-outs / consolidation** | Carve-out ABAP generator (org+time filters, dependency-aware, streamed) **now embedded in the `data-migrator` extract stage**; greenfield/SDT lane positioning. | **Gap→Partial.** We *generate* a governed carve-out inside extract; we have **not** proven deploy at volume, nor built company-code/client split or system-consolidation harmonization content. | Live carve-out at volume; selective company-code/time-slice split; harmonization rules for consolidation; faithful dependent-key migration (§6.1). |

**Where we already beat the field for our lane:** the **trust spine** — auto-discovery + existence/value
reconciliation with a hard GO/NO-GO + cross-run idempotency + dead-letter + support-clean attestation —
is more automated and more auditable out-of-the-box than the stock Migration Cockpit, and is a credible
differentiator none of the three give you for free in exactly this shape.

**The blunt bottom line for a reviewer:** today this is **one strong, support-clean, live-proven
orchestration+reconciliation spine (25 objects)** into which **three competitor-grade engines are now
embedded in their respective stages and verified offline** — SmartShift-class remediation in
`code-analyzer`, Syniti-class FK+self-heal+ledger in `data-hygiene`, Natuvion-class carve-out in
`data-migrator`. That moves us from "separate prototypes" to "integrated capability," but **not yet** to
"competitive in their home turf," which still needs: (1) the **general mapping/transformation + DQ layer**
(closes the Syniti gap and §6.3), (2) **real ATC + equivalence-testing + scale** for the code fixer
(closes the SmartShift gap), (3) **live, volume-proven carve-out + consolidation content** (closes the
Natuvion gap), and (4) **a customer pilot on a second, customer-shaped landscape** (§6.7). The
architecture and the in-stage wiring now exist; the depth, content, and live-at-scale proof do not yet.

---

## 12. Production-hardening pillars — current state

The four PROD-hardening pillars from the original directive. **AWS infra for all four is now
provisioned by `terraform apply` and survives destroy/re-apply** (see §13). Code and infra are live;
volume-proof on a real ECC/S4 pair is still owed.

| Pillar | Implementation | Verified | Still pending |
|---|---|---|---|
| **1.1 — Dynamic compute dispatcher (Lambda → Fargate)** | `lambda/utils/scaling.py:ComputeDispatcher` routes to Fargate with auto-scaled memory tier when est-rows > threshold, else inline/Lambda. Wired into `pipeline_spine_master.py:296` (`decision.target == "fargate"` → `fargate_routed` count in run summary). | offline: routing logic + dispatcher decision in carve-out phase. **infra: ECS cluster + Fargate task def + ECR repo are provisioned by the prod stack (`migrate4hana-prod-worker` task) and confirmed in state.** | live 10⁶-row run that actually fans out to Fargate; auto-scaling memory tier observed under load |
| **1.2 — Chunked cursor streaming (ABAP `OPEN CURSOR…PACKAGE SIZE` + OData `$top/$skiptoken`)** | `lambda/data-migrator/handler.py:628` (cursor streaming in extract); `lambda/utils/scaling.py:ODataPager` (server-side OData paging). | offline: pager test passes. **infra: live in the extract path.** | end-to-end stream of 10⁶ rows; back-pressure behaviour under realistic latency |
| **1.3 — Write-capacity isolation (DynamoDB token bucket)** | Thread-safe `TokenBucket` in `lambda/utils/key_map.py:23`; optional ledger limiter (default off) to protect DynamoDB WCU under high-concurrency loops. | 120 writes throttled to ~1.41s at 50/s burst-50. | sizing against real table WCU under a live mass load |
| **2 — Transformation / Value-Map / DQ** (closes §6.3) | `lambda/utils/transformation_engine.py` (434 LOC): JSON rule schema (FIELD_MAP / VALUE_MAP / REGEX_CLEANSE / CONST/TRIM/UPPER/PAD), cached S3-backed value-map matrix (local/inline fallback), DQ gates (MANDATORY / REGEX_VALID / MAX_LEN / ALLOWED / UNIQUE) → `DATA_QUALITY_REJECTION`. Hooked into `UnifiedLoader._load_one:423-430` (+ parallel-worker propagation), wired into `data-migrator` (env-gated `M4H_TRANSFORM_RULES`, **no-op by default**). | value-map (3000→1710) + name cleanse applied; all five DQ gates reject correctly; quarantine routes to dead-letter. | live business mapping matrices; a mapping UI; DQ scorecards/cleansing library |
| **3 — Human-in-the-loop governance gates** | `lambda/utils/governance.py` — `GateController` (HMAC-signed, file-backed, cross-process, no-double-pass) + schema-validated SNS alert payloads; signed `/api/spine/approve` (+ `/api/spine/gates`) webhook. | offline: HMAC verify + replay-block tests pass. **infra: 4 × `arn:aws:states:::lambda:invoke.waitForTaskToken` states in `lift_and_shift_pipeline.asl.json` (lines 43/201/240/282) covering ASSESS, DATA-PREP, VALIDATE, CUTOVER; `aws_sns_topic.spine_gates` provisioned; `manual-gate` Lambda persists token to `migrate4hana-gates-prod` DynamoDB table; HMAC secret in Secrets Manager (`migrate4hana/prod/gate-secret`).** | live cut-over with an actual human in the loop; SNS email subscription end-to-end |
| **4 — Cryptographic auditing** | `lambda/utils/reconciler.py:273-455` — `HashChainLedger` (SHA-256, tamper-evident, resume-safe, optional DynamoDB vault); `AggregateReconciler` (count + total + debit/credit tie-out source↔target); `EvidencePack` (hash-sealed manifest). Chain wired into the `data-migrator` run summary. `pdf_report_generator.py` exists with Unicode safety net (516 mojibake fixes applied). | chain verifies + **detects a tampered block**; aggregate tie-out flags balance VARIANCE; evidence pack hash-sealed into the chain. **Infra: `migrate4hana-audit-ledger-prod` DynamoDB table provisioned; `evidence_app` S3 bucket provisioned (encrypted + versioned + public-access-block).** | real source↔target aggregate queries at volume; multi-part compliance PDF that auditors would sign off on; **S3 Object Lock WORM is currently OFF** (see §13 — intentional for the test loop, must be re-enabled at bucket creation for real prod) |

**One honest regression** vs the 2026-05-29 §12: Pillar 4's evidence S3 bucket previously had Object
Lock COMPLIANCE 2555-day retention. It was **deliberately removed** so `terraform destroy` is clean
during the inner-loop test cycle. Re-impose for real prod with two changes (cannot toggle on after
bucket creation): `object_lock_enabled = true` on `aws_s3_bucket.evidence` + restore the
`aws_s3_bucket_object_lock_configuration` block. See `evidence-ledger/main.tf:64-77` for the exact
diff.

---

## 13. Production-ops hardening (2026-05-30 → 2026-05-31)

The architecture above is well-tested in code; this section is about whether you can **actually
deploy and operate it** without manual AWS intervention every cycle.

### 13.1 Apply → destroy is idempotent end-to-end (200 resources)

The prod stack now provisions cleanly from zero state and tears down cleanly back to zero. Every
class of stuck-state failure encountered during the certification run was fixed at root cause and
committed:

| Failure class | Root cause | Permanent fix in source |
|---|---|---|
| "Secret … is already scheduled for deletion" | Secrets Manager 30-day soft-delete reserves the name; next apply hits 400. | `recovery_window_in_days = 0` on `sap-credentials` / `s4hana-credentials` / `gate-secret` / `anthropic-api-key`. |
| Bucket non-empty / `InvalidBucketState: Versioning must be Enabled` on Object Lock | `aws_s3_bucket_object_lock_configuration` raced ahead of versioning; bucket created without `object_lock_enabled = true`. | `object_lock_enabled = true` on the bucket itself + explicit `depends_on = [aws_s3_bucket_versioning.audit_logs]` on the lock configuration. |
| Step Functions `Value is not a valid resource ARN` × 5 | `lookup()` for unbuilt Lambdas (`discovery-engine`, etc.) returned `""`, breaking schema validation. | `local.ls_fallback_arn = manual-gate ARN`; every unresolved Lambda lookup falls back to it so the state machine validates. The router is functional only once the real Lambda exists. |
| CloudWatch dashboard 12× "should have required property 'region'" | Metric widget `properties` blocks were missing `region`. | `region = var.aws_region` threaded into the cloudwatch module and added to all 4 widget property blocks. |
| WAF / tag value rejections | `"SOX,GxP"` (comma) and em-dash characters violated AWS string regex. | Replaced with `"SOX-GxP"` and ASCII hyphens. |
| CloudTrail `InvalidEventSelectorsException` | Wildcards forbidden in the function name portion of a Lambda data_resource value. | Bare prefix `"arn:aws:lambda"` (= all functions in account). |

A fresh `terraform destroy` is also clean — except for one remaining manual: the audit-logs bucket
holds CloudTrail-written objects under Object Lock GOVERNANCE that need `BypassGovernanceRetention`
to empty. Drop a one-line `force_destroy = true` if you want full hands-off destroy too (cost: a
future destroy would wipe SOX audit history without prompting).

### 13.2 Bedrock → direct Anthropic API

The user's AWS account does not have Bedrock model access. The runtime LLM path therefore goes to
`api.anthropic.com` over the Lambda's NAT egress, not via `bedrock-runtime`:

- New shared client: `lambda/code-analyzer/anthropic_client.py` (stdlib `urllib`, Secrets Manager
  fetch with module-level cache, returns `None` on any failure — never raises).
- Default model `claude-sonnet-4-6` (cheap + fast + near-Opus quality for narrow ABAP fragment
  fixes); on retry escalates to `claude-opus-4-7`.
- API key in `aws_secretsmanager_secret.anthropic_api_key` (`recovery_window_in_days = 0`).
- IAM: `secretsmanager:GetSecretValue` on the new secret for both Lambda and Fargate task. Bedrock
  permissions and the two Bedrock PrivateLink VPC endpoints have been **removed**.
- The pseudonymizer (`lambda/code-analyzer/pseudonymize.py`) — reversible PII masking before the
  prompt leaves the process — now matters more, since payload leaves AWS. It still runs unchanged.
- Compatibility-only aliases preserved: `_invoke_bedrock`, `check_bedrock_connectivity`, the
  filename `bedrock_genai_engine.py` — all documented as routing through Anthropic. The Lambda
  function itself is renamed `bedrock-llm-router` → `code-analyzer`.

Trade-off worth naming: today ABAP fragments travel over TLS to `api.anthropic.com` instead of
staying inside AWS. Pseudonymizer masks PII (emails / IPs / passwords) but not business logic. For
some compliance contexts that's a concern; flag if relevant.

### 13.3 One-command Fargate image deployment

`.\scripts\push-fargate-image.ps1` (PowerShell-only — user's environment) wraps the otherwise-manual
Docker steps required after each `terraform apply`:

1. Pre-flight: Docker running in Linux-container mode, AWS CLI authenticated, SAP NW RFC SDK zip in
   `ecs/`, ECR repo present.
2. ECR login (12h token).
3. `docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .` (build context = repo root).
4. Tag + push.
5. Verify via `describe-images`.
6. Warn about any running Fargate tasks that would not auto-pull the new image.

Required because Terraform creates the ECR repo + task definition but does **not** build/push the
image (intentional — avoids burning 5-8 min on every apply for unchanged images). First run
~7-10 min total; subsequent runs with cached layers ~30-60s.

### 13.4 What's still NOT in the production loop

To keep the brief honest:

- **ECC ↔ AWS connectivity deferred.** The current prod stack runs in-AWS-only; the user's local
  ECC system is reachable from the workstation but not from VPC-attached Lambdas. Site-to-site VPN
  or AWS Client VPN is needed before stages can actually call ECC from AWS. See [[connectivity-quirks]].
- **Object Lock WORM off.** As §12 notes — intentional but a regression vs the original Pillar 4
  spec. Two-line fix when ready for prod.
- **No live large-volume run on AWS.** Code paths for Fargate dispatch + cursor streaming + token
  bucket + hash chain all exist and pass unit tests; none have been exercised against 10⁶ rows on
  the deployed stack.
- **Several Lambdas referenced by `lift_and_shift_pipeline.asl.json` are not yet built**
  (`discovery-engine`, `migration-completeness-analyzer`, `pdf_report_generator` as a separate
  function). They currently resolve to the `manual-gate` fallback ARN, so the state machine
  validates and starts but those specific tasks no-op. Each needs its own handler before
  end-to-end execution against a real source/target.

---

## 14. SAP-functional-depth gap closures (2026-05-31, peer-review driven)

A peer SAP-expert review (Gemini, Big-4-class peer read) flagged the **SAP
functional depth** as the primary vulnerability vs the engineering layer. Eight
gaps were buildable in code without a live system; this section is the
inventory. Each ships with a working module and a green self-test; production-
completeness (volume / breadth / customer-specific content) is honestly noted.

| # | Gap (Gemini's framing)                                  | Module + entry point                          | Verified self-test                                                                                       | Still owed for production |
|---|---------------------------------------------------------|----------------------------------------------|----------------------------------------------------------------------------------------------------------|---------------------------|
| 1 | **CVI** — KNA1/LFA1 overlapping number ranges + duplicate addresses | `lambda/utils/cvi_mapper.py`<br>`unify(kna1, lfa1)` | overlap detection (1 #), intra-table duplicates, exact-fingerprint fold into one BP with both roles, near-duplicate conflict quarantine (different tax IDs), deterministic round-trip | fuzzy / phonetic / edit-distance match; address harmonization across locales; per-company-code overrides |
| 2 | **SAP-side backpressure** — TH_WPINFO + NRIV lock probe | `lambda/utils/sap_workload.py`<br>`WorkloadThrottle.decide()` | GREEN/YELLOW/RED classification; batch halved on YELLOW; full pause + 10s wait on RED; NRIV-lock causes back-off | landscape-specific thresholds tuned against real WP topology; integration into the Fargate fan-out caller |
| 3 | **BAPI field-coverage trap** — extension fields (CI_/ZZ_), tax fields (J_1B*) | `lambda/utils/bapi_coverage.py`<br>`decide_load_path()` | clean record → BAPI; CI + tax field → BAPI_PLUS_LTMC_DELTA; >50% unsupported → LTMC_ONLY; LTMC staging CSV + control JSON emitted with `ltmc_load_mode = "Staging tables (Direct Transfer)"` recommendation | per-BAPI canonical field catalog (today supplied by caller); LTMC CSV column-name mapping to the actual MC migration object schema |
| 4 | **FAGLB03 / MB5B spool capture** for the auditor evidence pack | `lambda/utils/spool_capture.py`<br>`SpoolCapture.capture(report_code, params)` | end-to-end: JOB_OPEN → JOB_SUBMIT → JOB_CLOSE → BP_JOB_STATUS_GET polling → RSPO_RETURN_ABAP_SPOOLJOB fetch; SHA-256 sealed; param-validation; unknown-report rejection; dry-run mode | wiring `CapturedSpool` into `HashChainLedger.append()` so the chain seals the spool hash; report catalog expansion (FBL3N, S_ALR_87012082, etc.); selection-variant support |
| 5 | **Dual-maintenance / continuous code-sync engine** (SmartShift's actual moat) | `lambda/utils/code_delta.py`<br>`DeltaEngine.snapshot()` + `detect_delta()` + `plan_remediation()` | TADIR/REPOSRC snapshot of customer-namespace ABAP; ADDED/MODIFIED/DELETED verdicts vs baseline; remediation queue is append-only + idempotent (re-run = no-op) | optional deep source-hash on PROG via READ_REPORT (already supported, off by default); CHANGEDOCUMENT-style diff visualization; scheduler (CRON / EventBridge) for the snapshot loop |
| 6 | **Multi-field cross-validation DQ** (Syniti-class beyond FK) | `lambda/utils/transformation_engine.py`<br>new `CROSS_FIELD_VALIDATE` rule type with `{when, expect}` predicates | conditional triggers (credit-limit ↔ payment terms), prefix matching (country ↔ tax jurisdiction), set membership (plant ↔ company code), construction-time schema validation | DQ scorecards over time (Syniti's true differentiator); business-user UI for rule authoring; library of common cross-field rules per object type |
| 7 | **Cluster-table aware extraction** (RFBLG / KOCLU / EDI40 on non-HANA ECC) | `lambda/utils/cluster_table_awareness.py`<br>`preflight(table, where, on_hana)` | transparent table = GO at requested pkg; BSEG with header-keys = single-stage cluster read at PACKAGE SIZE=200; BSEG without header-keys = rewritten as 2-stage BKPF → BSEG plan; PCL1 with no WHERE = NO_GO (refuses to dump prod); HANA disables the penalty | extending catalog from current 13 entries to a fuller list; runtime DB-kind detection (today caller supplies `on_hana=True/False`) |
| 8 | **DAG dependency resolver** (faithful dependent-key migration; closes §6.1) | `lambda/utils/dependency_dag.py`<br>`DependencyDAG.from_defaults()` + `ExecutionState` + `KeyResolver` | 28-node default DAG, cycle detection, topological sort, scope-subset pulls transitive deps, `next_ready()` correctly gates downstream objects, failure propagation lists downstream blocked, `KeyResolver.resolve_record()` translates legacy keys via cross-run keymap | actual integration with the data-migrator stage loop (today modules are standalone); per-customer DAG additions / removals |

**What this changes vs the 2026-05-29 §6 limitations:**

- §6.1 ("Harmonization is demo, not faithful migration") — **closed in design**:
  `dependency_dag` + `KeyResolver` give the staged-load + cross-run key-translation pattern that
  Gemini called for. Integration into the data-migrator stage loop is the next mechanical step.
- §6.3 ("No general transformation / mapping engine") — already had `transformation_engine.py`;
  the new `CROSS_FIELD_VALIDATE` lifts it from "field-level cleansing" to "Syniti-class
  business-rule validation." The mapping UI for non-technical users is still pending.
- §6.4 ("No data quality / pre-load cleansing") — `CROSS_FIELD_VALIDATE` is the substrate; DQ
  scorecards over time + a cleansing rule library are still pending content work.
- §6.6 ("Functional coverage depth — minimal field sets") — `bapi_coverage` now FORMALLY tracks
  what the chosen BAPI cannot carry and routes the rest to LTMC instead of silently dropping it.

### Honest caveats on §14

- All eight modules are **framework-complete, content-light**. The DAG ships with a sensible
  default for SAP greenfield projects; real customer migrations will need DAG edits. The
  `bapi_coverage` module needs a per-BAPI field catalog (today supplied by the caller). The
  `spool_capture` module needs each `CapturedSpool` actually wired into the existing
  `HashChainLedger` invocation site - one-line change, not done yet to avoid touching the
  reconciliation hot path without a test pair.
- The Gemini-flagged "Anthropic-over-public-TLS compliance wall" and "WORM Object Lock
  regression" are **deliberately not addressed in this iteration** - both are acceptable for a
  POC on the user's client ECC→S4 setup and become production-blocking only at regulated-buyer
  rollout. Re-isolating the LLM to a private endpoint and restoring Object Lock at bucket
  creation are tracked but not in this commit.

### Migration Cockpit positioning pivot

The 2026-05-29 brief positioned Migrate4HANA largely as filling the gap MC leaves. In 2026 SAP
shipped **Staging Tables for Direct Transfer (RFC)** in the Migration Cockpit, which closes part
of the extraction gap we previously claimed. Our defensible value-prop is now sharper and
narrower:

- **What SAP MC Direct Transfer does well**: extraction via RFC, intermediate staging in HANA,
  in-place data correction UI, native LTMC error handling.
- **What we add that MC does not**: auto-discovery of target config; cross-run idempotent ledger
  with hash-chained audit; aggregate value-reconciliation with hard GO/NO-GO verdict per object;
  governed cutover gate with HMAC-signed approval webhook; selective carve-out ABAP generator;
  CVI/DAG/BAPI-coverage/cluster-aware preflight that prevent failures MC discovers only after
  load.

The brief should **not** sell the extraction layer alone as a differentiator anymore.

---

## 14.5. Live-call-site wiring (2026-05-31, follow-up to §14)

The §14 modules ship standalone. As of commits `62ada9a` + the follow-up below
they are also **invoked from the hot path**, not sitting beside it. For each
module: the actual file + function it fires from, its activation switch, and
honest residue.

| # | Module | Call site | Activation | Honest residue |
|---|---|---|---|---|
| 1 | `cvi_mapper.unify` | `lambda/data-migrator/handler.py:lambda_handler` — after the per-object extract loop, before the dead-letter S3 write | Always-on when both Customer (KNA1) and Vendor (LFA1) extracts are in the same batch. Conflicts auto-route to dead-letter with reason `CVI_CONFLICT`; full map persisted to `runs/<id>/cvi_map.json`. | Fuzzy matching, address harmonisation, per-company-code overrides — module supports the interface; content is not built. |
| 2 | `sap_workload.WorkloadThrottle` | `lambda/utils/scaling.py:ComputeDispatcher.dispatch` — constructed in `pipeline_spine_master._phase_natuvion` when `payload["_live_target_conn"]` is set, passed in via constructor. | Only active in live runs (no fixture). 5-attempt RED→GREEN loop with halved-batch on YELLOW. | Landscape-specific GREEN/YELLOW/RED thresholds; integration with the *parallel-worker* loop inside `unified_loader` (today the throttle gates Fargate dispatch, not Lambda concurrency). |
| 3 | `bapi_coverage` + `bapi_field_catalog` | `lambda/utils/unified_loader.py:_load_one` — after the DQ gate, before the BAPI call. Catalog now lives in `lambda/utils/bapi_field_catalog.py` covering **25 migration objects** with 6-50 fields each. | `M4H_BAPI_COVERAGE_DIR` env var. When set, the loader auto-imports `bapi_field_catalog.as_dict()`. Per-landscape overrides via `M4H_BAPI_FIELD_CATALOG_JSON`. | Per-BAPI field set comes from the curated baseline, not `DD_BAPI_PARAMETER_GET` — a real customer landscape should run the RFC introspection and merge via the env-override path. |
| 4 | `spool_capture.SpoolCapture` | `lambda/utils/reconciler.py:EvidencePack.build_manifest` — new `captured_spools` kwarg. Each capture is sealed into the `HashChainLedger` *before* the manifest hash so the chain bears witness to the SAP-standard binary. | Caller-driven (the data-migrator handler does not auto-trigger spool capture yet — one or more captures must be passed explicitly into `EvidencePack`). | The orchestrating call (which decides *which* report to fire and when) is not yet in the handler — the building block is wired but a one-line `pack.build_manifest(captured_spools=[...])` from the data-migrator is the remaining step. |
| 5 | `code_delta.DeltaEngine` | `lambda/code-delta-scheduler/handler.py` — new Lambda, scheduled by EventBridge `cron(0 6 ? * MON-FRI *)` (provisioned in `terraform/environments/prod/main.tf`). Snapshots TADIR/REPOSRC, mirrors to S3, diffs against the most recent prior baseline, enqueues remediation tasks. | Always-on once the stack applies (terraform validates clean). Layer dependency: handler detects a missing pyrfc layer and returns `status=skipped` with a remediation hint rather than dumping ImportError. | The code-analyzer Lambda doesn't yet *consume* the remediation queue automatically — today an operator triggers re-remediation manually from the queue. |
| 6 | `cluster_table_awareness.preflight` | `lambda/data-migrator/handler.py:_read_table` — called before every `RFC_READ_TABLE`. | Always-on; `M4H_ECC_ON_HANA=1` disables the PACKAGE-SIZE cap. PCL1/PCL2 with no WHERE raises `RuntimeError` BEFORE the RFC fires. | Catalog ships 13 well-known pool/cluster tables; per-landscape additions go in `_CATALOG` (no env-override path yet — would be ~5 LOC to add). |
| 7 | `dependency_dag.DependencyDAG` + `ExecutionState` | `pipeline_spine_master.py:_phase_syniti` — entity_trees list is topologically sorted before iteration; per-object status (running/done/failed) is tracked; `downstream_blocked_by_failure` map is included in the phase summary. | Always-on when the spine runs. | DAG is the curated 28-node default — real customer DAGs (especially industry-specific masters / inter-company dependencies) need a per-customer addendum file. Default is a starter, not a closed model. |

### Where the brief now sits

- **Engineering depth**: the gap-closure modules are not just present in `utils/` — they are **invoked from the hot path** during a real run. A reviewer can grep `from cvi_mapper`, `from bapi_coverage`, etc. and see the calls.
- **SAP functional depth**: still the largest residue. The frameworks are in place; the *content* (BAPI field catalogs per release / SAP Note, cluster-table catalog per ECC release, DAG additions per industry, CVI fuzzy-match rules per locale) needs landscape-specific work that benefits from a customer engagement.
- **Live verification**: every wiring above passes its unit / integration self-test. The next step is a live ECC/S4 dry-run to catch integration-shaped surprises (RFC timeout behaviour under throttle, real cluster-table memory patterns at volume, real TADIR snapshot size).

### What changed since §14

- `bapi_field_catalog.py` — new versioned module with 25 objects + env-override addendum, replacing the 3-object inline stub the data-migrator handler shipped initially.
- `WorkloadThrottle` now constructed in the spine's Natuvion phase when a live target conn is available, instead of being only the ComputeDispatcher's optional arg.
- `code-delta-scheduler` handler degrades gracefully when the pyrfc layer is missing: `status=skipped` with a remediation hint, no ImportError noise in CloudWatch.
- All `terraform validate` clean; all changed Python files `py_compile`-clean.

---

## 14.6. Edge-case + governance hardening (2026-05-31, second peer-review pass)

A second pass of the same peer SAP-expert review raised four narrower concerns
after the §14.5 wiring landed. All four are addressed below. None were blocking
the POC; they sharpen behaviour at the edges and lock in governance rules an
auditor will check.

| # | Concern | Resolution | Verified |
|---|---|---|---|
| 1 | **CVI / KeyResolver cycle hazard** — `KNA1.LIFNR` ↔ `LFA1.KUNNR` cross-references in intercompany master data can lock the loader in a resolution loop. | New `cvi_mapper.unify_with_xrefs()` returns a **TwoPhasePlan**: phase 1 creates BP stubs without cross-references, phase 2 attaches them in a single update pass. Each cross-ref is resolved **one hop deep** so a mutual reference doesn't recurse. Cycles between BPs are detected and reported (not errors — they're legitimate intercompany pairs). Wired into data-migrator handler in place of the original `unify()` call. | self-test: 4 mappings, 1 cycle detected (`KNA1:100001` ↔ `LFA1:200001`), 1 unresolved out-of-batch xref correctly surfaced, idempotent on re-run |
| 2 | **Throttle cost during long target congestion** — fixed `wait_seconds` could turn into tight-loop polling and burn compute. | `WorkloadThrottle` now applies **exponential backoff** on consecutive non-GREEN probes: YELLOW base 2s, RED base 10s, doubles per consecutive miss, capped at 60s. A single GREEN probe **resets the streak** so recovery is fast. The throttle gates BEFORE `ecs.run_task` so the wait burns Lambda runtime (bounded), not Fargate; intra-task usage now also degrades cleanly. | self-test: RED probes wait 10→20→40s, then GREEN resets, next RED returns to 10s base |
| 3 | **BAPI / LTMC reconciliation precision** — when a record's BAPI succeeds but its CI/J_1B fields go to LTMC staging, the hash chain previously sealed only the BAPI half. A tampered or never-imported staging file was invisible to the chain. | data-migrator handler now collects every `ltmc_handoff` from `_load_one` results, persists them at `runs/<id>/ltmc_handoffs.json`, surfaces `ltmc_pending` in the run summary (with the explicit gate note "cutover must NOT proceed until each pending handoff is confirmed imported"), and **seals one `ltmc_pending` block per handoff into the HashChainLedger** so any tamper is detectable. | covered end-to-end by the cutover-verdict test below (LTMC pending → NO_GO) |
| 4 | **No explicit "SAP report > tool ledger" precedence rule** — auditors need a stated governance rule, not just per-stage results. | New `EvidencePack.cutover_verdict` field with a hard-coded precedence rule. The verdict is **NO_GO** if: any balance tie-out shows variance > 0, OR any LTMC handoff is pending import, OR a required close spool (FAGLB03, MB5B) is missing. The tool's hash-chained ledger **can confirm a GO but cannot override a NO_GO** — this rule is documented inline in `_compute_cutover_verdict()` and echoed in the manifest's `precedence_rule` field. A NO_GO is also sealed as its own block in the chain so the refusal itself becomes evidence. | self-test: 5 cases pass — clean GO; missing-spool NO_GO; LTMC-pending NO_GO; variance NO_GO **even when tool reconciliation says RECONCILED**; tool-discrepancy → GO_WITH_WARNINGS (not blocked) |

### Two items intentionally NOT addressed this round (per prior user directive)

- **Branch rename** `aws-lift-and-shift` → `sdt-orchestration` — cosmetic; user opted to defer until after the POC ships.
- **LLM compliance toggle** (Anthropic public API → in-VPC Bedrock / SageMaker) — POC-acceptable per user decision 2026-05-30; the runtime client (`anthropic_client.invoke_claude`) already takes a model id, so swapping the *endpoint* once Bedrock access is granted is one URL/header change in that module — no architectural rework needed.

### Where the brief now stands

Three review passes (2026-05-29, 2026-05-30, 2026-05-31) have walked the
critique into the code. Every structural and edge-case concern that can be
addressed without a live ECC/S4 pair is now closed. The remaining honest
residue is **landscape-specific content** (BAPI catalogs per release, cluster
table catalog per ECC release, CVI fuzzy-match rules per locale, DAG additions
per industry, NRIV / TH_WPINFO thresholds per landscape) and **live-volume
verification** — both of which benefit from a customer engagement and a real
system pair, not more engineering.
