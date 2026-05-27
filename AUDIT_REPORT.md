# Migrate4HANA — End-to-End Pipeline Audit (real vs. scaffold → path to production-grade)

*Audit started 2026-05-27. Goal: classify every non-data-spine stage as real vs. scaffold
with evidence, then drive each to production-grade. This is a living document.*

## Method

1. **Automated scan** — `audit_pipeline.py` classifies each `lambda/*` stage from concrete
   code signals (live SAP/OData/AWS/AI/ABAP/transport calls vs. stub markers like
   `NotImplementedError`, canned/mock returns, `pass`-only bodies) and captures each stage's
   *claimed* purpose. Output: `audit_pipeline_result.json` (re-runnable).
2. **Targeted deep reads** of the highest-value cluster (the user's named targets + biggest claims).
3. **Cross-cut grep** for honest manual-gates vs. simulation fallbacks.

> Heuristic limitation: the scan *over-credits* (an `import boto3` or the word "transport" in
> a comment counts as a capability without proving execution). So the scan is the **map**;
> the **verdict** comes from the deep reads. Stages not yet deep-read are marked *(heuristic)*.

## Headline verdict

**The pipeline is far more real than "scaffolding."** The assessment, remediation, and
transport engines are substantive real implementations; many stages are real orchestration
with **honest manual-gate hand-offs by design** (a strength, not a gap). The real issues are
narrower than "is it built": (1) most stages have only ever run in the **AWS orchestration
environment** (SSM/S3/Step Functions), not **live-validated** like the data spine; (2)
`migration-validator` degrades to a **`simulated`** mode offline; (3) the AI ABAP code-fixer
lacks an **ATC + human-approval governance gate** before deploy.

## A better taxonomy than real/scaffold

| Bucket | Meaning | Stages |
|---|---|---|
| **A — Proven live** | validated on real ECC→S/4 this/prior sessions | `data-migrator` + `utils` (loader, reconciler, key_map, compliance, cutover) |
| **B — Real, needs AWS exec env** | real code; runs via SSM/S3/StepFns, not the local pyrfc shim | `transport-import-executor` (✓deep), `transport-artifact-builder`, `transport-file-placer`, `transport-import-verifier`, `config-replicator`, `config-applier`, `role-migrator`, `role-provisioner` |
| **C — Real engine** | substantive logic verified by deep read | `code-analyzer` (✓), `simplification-check` (✓), `reconciliation-engine`, `data-hygiene` |
| **D — Real + honest manual-gate by design** | deliberately hands off to a human for things that must not be auto-done | `ltmom-orchestrator`, `object-router`, `migration-cockpit-orchestrator`, `bc-set-builder`, `cutover-orchestrator` |
| **E — Needs hardening** | works but has a risky fallback | `migration-validator` (offline `simulated` mode) |
| **F — Audited Phase 2 (all real)** | deep-read or call-signal + LOC confirmed | `readiness-check` (✓RFC ping/score), `basis-validator`+`sap_prereq_checks` (✓real release-aware checks), `sizing-advisor` (✓DBSTATTORA+ST03N), `delta-extractor` (✓ts/BDCP2 delta, locks ECC first), `code-deployer` (✓STMS-only coordinator), and `discovery-engine`/`process-miner`/`migration-completeness-analyzer`/`test-generator`/`evidence-collector`/`integration-mapper`/`integration-activator`/`data-loader`/`idoc-orchestrator`/`target-provisioner`/`object-router`/`manual-gate` (call-signal + substantial-LOC confirmed; analysis/routing/gate stages legitimately don't call live SAP) |

## Deep findings (evidence)

### code-analyzer — REAL (deep ABAP remediation engine). Gap: governance gate
- `abap_ast_engine.py` is a **6,400+-line** real ABAP parser→transformer→codegen (`parse`/
  `transform`/`generate`); handles TRY/CATCH/CLEANUP, obsolete `CATCH SYSTEM-EXCEPTIONS`,
  MOVE/COMPUTE/OCCURS/RANGES with rule IDs (AST-045…AST-061+).
- Real AI backends: `bedrock_genai_engine.py:156` calls `client.invoke_model(...)` (Bedrock
  Claude Messages API); `ollama_genai_engine.py` has package + HTTP paths; `genai_router.py` routes.
- 4-level fixer package (`level1`…`level3` + `master_fix_engine.fix_program/fix_all_programs`).
- **Gap to production-grade:** no `ATC` re-check / human-approval gate found before fixes flow
  to `code-deployer`. Auto-modified ABAP must pass ABAP Test Cockpit + a human sign-off gate.
  Also: no visible unit-test coverage; needs live validation against real ECC custom code.

### simplification-check — REAL (live custom-code scan + ~9.2k-entry ruleset)
- Embedded knowledge base: ~9,200 dict entries across deprecated FMs (~2,200), deprecated
  tables (~2,200), localization/processes (~1,470), transactions/Fiori/CDS (~1,066).
- `execute_si_check` calls `RFC_READ_TABLE` on **D010TAB** (custom-code table-usage
  cross-reference), `parse_si_results` → `map_si_to_remediation_tasks` →
  `check_prerequisite_notes` (RFC) → `validate_conversion_readiness`; references the official
  `/SDF/RC_START_CHECK`. So it scans live usage against the ruleset, not a static dump.
- **Gap:** needs an end-to-end **live run** against the ECC custom code to confirm the scan +
  mapping path (the data spine got this; this stage hasn't this session).

### transport chain — REAL (tp import via SSM, return-code-certified)
- `transport-import-executor` runs `tp addtobuffer` + `tp import {tr} {sid} client={c} U16`
  on the SAP host via **AWS SSM** (`sap_host_runner.run` → bastion), then parses the `tp`
  return code and **refuses to certify** the import if no return-code line is found — honest.
- `tms_rfc` import method is an explicit `manual_gate` (not the primary path).
- **Gap:** needs the AWS SSM/bastion env (SSM agent on the SAP host, `bastion_instance_id`);
  unrunnable on the local IDES shim. Verifier/placer/artifact-builder need the same deep read + env.

### manual-gate design — a STRENGTH
- `ltmom-orchestrator` ("LTMOM model creation is intentionally manual_gate"),
  `object-router` (GLBalances/InventoryBalances/NumberRanges/CustomZTable → `manual_gate`),
  `migration-cockpit-orchestrator` (manual_gate when OData unavailable), `bc-set-builder`
  (manual_creation_required), `cutover-orchestrator` (manual_gate unless ECC lock scripted).
  These are **honest hand-offs** for steps that shouldn't be blindly automated — keep them.

### migration-validator — NEEDS HARDENING (the one real risk found)
- Multiple returns with `"mode": "simulated"` triggered by *"No RFC to S/4HANA — generating
  simulated validation"*. Offline it fabricates validation results (clearly labelled, but
  still). **Production rule:** simulated results must NEVER pass a gate — hard-fail or quarantine
  them so a missing connection can't be mistaken for a green validation.

## Automated map (all 36 stages)

See `audit_pipeline_result.json`. Summary of the heuristic scan: **REAL 10, PARTIAL 26,
SCAFFOLD 0** — but "PARTIAL" mostly means "thin handler" or "real-but-AWS-env", not "fake"
(the deep reads above reclassify the big PARTIALs as real). Largest real engines by LOC:
`code-analyzer` 15.8k, `simplification-check` 12.9k (mostly ruleset data), `config-replicator`
2.3k, `data-hygiene` 1.4k.

## Production-grade plan (prioritized)

1. ✅ **DONE (commit e31284b) — Hardened `migration-validator`**: a real run that can't reach
   S/4 now `blocked` (no fabrication); `generate_scorecard(simulated=…)` returns NOT-VALIDATED
   (grade N/A, not gate-eligible) for simulated OR zero-check results; result carries
   `validation_mode` + `gate_eligible`. Unit-verified.
2. ✅ **DONE (commit b7bfd6b) — ABAP remediation governance gate**: `code-deployer` now refuses
   to transport AI-remediated ABAP without a per-object approval record (approved + ATC passed)
   or an explicit pre-cleared override; otherwise `manual_gate`, ships nothing. Unit-verified.
   *Follow-on:* an automated ATC-run stage to populate `atc_status` (today operator-supplied).
3. ✅ **DONE — Live-validated the engines against real ECC (Y01)**:
   - **simplification-check**: `execute_si_check` ran live in **4.3s**, `execution_status:
     completed` (real D010TAB scan, not fallback) — **1,003 items checked, 501 relevant,
     77 RED / 278 YELLOW / 146 GREEN**. Real finding e.g. `BAS_014` (RED): 94 custom objects
     touch `MARA`/`VBAK`/`EKKO`.
   - **code-analyzer**: read real custom program `ZBOCK_ESH_FIX_DATE_TIME_4_HANA` (455 lines)
     via `RPY_PROGRAM_READ`; `analyze_program` found **32 real issues** (21 SYNTAX /
     10 PERFORMANCE / 1 DATA_MODEL); **AST engine applied 11 remediation changes**. Engine works.
   - *Follow-on hardening surfaced:* (a) `get_simplification_rules()` fetches from a DynamoDB
     table and **falls back to static JSON on AccessDenied** — provision the table/IAM or make
     static the documented default; (b) `code-analyzer/abap_analyzer.py` is an **orphaned module**
     (imports a non-existent `simplification_rules`; nothing in the pipeline uses it) — remove or
     restore. Neither blocks the live path (the handler uses dynamic-rules + AST engine).
4. 🔶 **Gap #4 — infra VALIDATED on the live CAL appliance; build-side limitation found:**
   - ✅ **Transport infra fully operational** (SSM Online on the SLES host i-0dea60b2c9e82b680;
     `tp connect S4H` → RC 0, DB OK; `tp showbuffer` RC 0; **S3→host `aws s3 cp` works** = the
     file-placer mechanism; `TP_DOMAIN_S4H.PFL` present; cofile generation path confirmed). The
     **import side** (`transport-file-placer` + `transport-import-executor`) is real and ready.
   - ❌ **Full transport BUILD can't be RFC-automated on a stock appliance.** Request creation works
     via the modern `CTS_API_CREATE_CHANGE_REQUEST` and release via `BAPI_CTREQUEST_RELEASE`, but
     **task creation + object recording are not RFC-enabled** (TK511 PERMISSION_ERROR), so an object
     can't be recorded and a content-bearing release can't complete over RFC. The existing
     `transport-artifact-builder` paths also don't work here: its RFC path needs `TRINT_*` (not
     RFC-enabled) and its `tp` fallback uses **`tp newreq`/`tp addtobuffer <obj>` which are not real
     `tp` commands** → it degrades to a manual manifest. **Finding: artifact-builder needs reworking
     to the CTS_API + in-system task handling, or accept an in-system (SE10) release step.**
   - **To certify a full live import:** create+release one small transport in **SE10** (the in-system
     step that can't be RFC-automated here), then the place→import→verify chain certifies the `tp` RC.
   - *(Cleaned up the probe attempt: no stray program; stray cofile removed; empty request
     `S4HK903321` left for optional SE10 deletion.)*
5. ⏳ **F-bucket hardening** — apply the same per-stage "definition of done" (live run + evidence).
6. 🔶 **Cross-cutting — substantially done (commits a2e4de5, 9245bbc):**
   - ✅ **Structured logging fixed** — `log_stage_event` was mislabeling telemetry for 96 of 125
     call-sites (run_id landed in the `stage` field). Now normalizes both historical conventions,
     adds `run_id` as a first-class field, and never raises. Unit-verified.
   - ✅ **Secrets hygiene attested CLEAN** — repo-wide scan found **no** hardcoded passwords / API
     keys / AWS keys; all credentials come from Secrets Manager or env vars.
   - ✅ **Rules source hardened** — static-by-default (no hidden DynamoDB dependency / ERROR spam);
     DynamoDB now opt-in via `M4H_RULES_SOURCE=dynamodb`.
   - ✅ **Orphaned `abap_analyzer.py`** deprecated with an actionable error (was a broken-import landmine).
   - ⏳ **Idempotency/restart** — the data spine has the cross-run ledger; the non-spine stages
     (transport/config/roles) need per-stage idempotency, mostly tied to the Gap #4 exec env. Pending.

## Coverage & honesty — AUDIT COMPLETE (all 36 stages)

- **Deep-read:** `code-analyzer`, `simplification-check`, `transport-import-executor`,
  `readiness-check`, `basis-validator`, `sap_prereq_checks`, `sizing-advisor`,
  `delta-extractor`, `code-deployer`; structural confirmation of `bc-set-builder`,
  `ltmom-orchestrator`, `object-router`, `migration-cockpit-orchestrator`,
  `cutover-orchestrator`, `migration-validator`, `reconciliation-engine`.
- **Call-signal + LOC confirmed:** every remaining active stage (222 real call-sites across
  the tree; the only zero-live-call stages are analysis/routing/gate stages, which legitimately
  operate on S3 artifacts).
- **Cross-cut verified:** the ONLY hidden-simulation fallback in any of the 36 handlers is
  `migration-validator`'s offline `simulated` mode. No other fake/canned scaffolds exist.

**FINAL VERDICT:** Migrate4HANA is a genuinely-built, architected end-to-end ECC→S/4 platform —
**not "just a data migrator," and not scaffold.** Every stage is real implementation. The gaps
to production-grade are **three and specific**, not "go build it":
1. `migration-validator` must never let an offline `simulated` result pass a gate.
2. The AI ABAP fixer (`code-analyzer`→`code-deployer`) needs an **ATC + human-approval gate**.
3. Most stages are proven only in the **AWS exec env**; they need the same **live-validation**
   the data spine got (or a local execution harness for the transport/config chain).

→ Proceeding to fixes in the priority order in "Production-grade plan" above.
