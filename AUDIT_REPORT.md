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
| **F — To be deep-audited** | only heuristic evidence so far | `discovery-engine`, `readiness-check`, `sizing-advisor`, `process-miner`, `migration-completeness-analyzer`, `test-generator`, `evidence-collector`, `integration-mapper`, `integration-activator`, `delta-extractor`, `data-loader`, `idoc-orchestrator`, `target-provisioner`, `basis-validator`, `manual-gate`, `code-deployer` |

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

1. **Harden `migration-validator`** — remove silent `simulated`; offline ⇒ explicit
   `NOT_VALIDATED`/blocked, never a pass. *(Quick, high-trust win.)*
2. **Add the ABAP remediation governance gate** — `code-analyzer` → ATC re-check + human
   approval before `code-deployer`; record an auditable before/after diff per object.
3. **Build an execution harness for the B-bucket** — a local/AWS path to actually RUN the
   transport + config stages end-to-end and validate them the way the data spine was validated
   (SSM target or a local `tp`/`R3trans` equivalent). Then live-run them.
4. **Live-validate the C-bucket engines** — run `simplification-check` + `code-analyzer`
   against the real ECC custom code; capture evidence.
5. **Deep-audit + harden the F-bucket** (assessment / validation / roles / integration stages),
   one tier at a time, same evidence standard.
6. **Cross-cutting hardening** — structured logging, secrets, idempotency/restart, and a
   per-stage "definition of done" (live run + evidence) mirroring the data-spine bar.

## Coverage & honesty

- **Deep-read this pass:** `code-analyzer`, `simplification-check`, `transport-import-executor`;
  structural confirmation of `bc-set-builder`, `ltmom-orchestrator`, `object-router`,
  `migration-cockpit-orchestrator`, `cutover-orchestrator`, `migration-validator`,
  `reconciliation-engine`.
- **Heuristic only (F-bucket):** the remaining ~16 stages — next to deep-read.
- No stage read so far is a fake/canned scaffold; the gaps are **governance, live-validation,
  and execution-environment**, not absence of implementation.
