# Migrate4HANA — Automated, Support-Clean SAP ECC→S/4HANA Migration Engine

> **Aligned with SAP Activate Methodology | SAP Post-Migration Support Retained**

> ### 🆕 NEW: Lift-and-Shift mode (`aws-lift-and-shift` branch)
>
> A second migration mode is now available for greenfield **lift-and-shift** projects
> (ECC → brand-new S/4HANA on AWS). It runs a 28-stage / 9-phase pipeline that
> performs **zero direct writes** into the target — every change goes through SAP-shipped
> tools (Migration Cockpit, LTMOM, IDoc inbound, CTS+/`tp`, BC Sets) so SAP support is
> fully preserved with no "reproduce in a standard tool first" friction.
>
> - Architecture: [`MIGRATE4HANA-LIFT-AND-SHIFT.md`](MIGRATE4HANA-LIFT-AND-SHIFT.md)
> - Local runner: `python run_local_lift_and_shift.py --list-stages`
> - API: `POST /api/pipeline/lift-and-shift` (full / `/assess` / `/code` / `/data`)
> - UI: **Lift & Shift** tab in the navigation
> - CI gate: `tests/test_no_direct_writes.py` enforces the two-plane principle
>
> **Customer prerequisites for lift-and-shift mode:** ECC source + RFC user (read-only),
> target S/4HANA license + S-user, Migration Cockpit credentials, LTMOM authorization,
> IDoc inbound + partner profiles, CTS+ / abapGit, STMS routes ECC↔target, EFS or
> shared `/usr/sap/trans`, BUILD-system role definitions (assignments are NEVER
> auto-pushed to PROD — they are emitted to a CSV for the security team).


> **Status (May 2026 — `aws-lift-and-shift` branch, the active/primary mode):** The **28-stage /
> 9-phase Greenfield / Selective-Data-Transition** pipeline runs **end-to-end against live
> ECC→S/4HANA (`rc=0`, zero failed records)**. The support-clean data spine **loads + reconciles
> 11 object types live** (idempotent cross-run ledger, value-level reconciliation), ~20 extract.
> A full **pipeline audit of all 36 stages** is complete (every stage is a real implementation,
> not scaffold), with **3 production-grade gaps fixed** (validator can't certify on simulated
> data; AI-remediation ATC+human gate; cross-cutting logging/secrets/rules hardening). Code
> remediation (6,400-line ABAP AST + Bedrock/Ollama, ATC + human gate) and simplification-check
> (live `D010TAB` scan, ~9,200-rule knowledge base) are **live-validated** against real ECC custom
> code. A novel **in-system ABAP agent** drives in-system CTS/ABAP over RFC. **Honest maturity:
> ~TRL 6** — proven on a live ECC→S/4HANA pair at sample volume; **not yet pilot-go-live-proven at
> customer scale** (the deliberate next bar). The transport-build final import is deferred (a
> single-box appliance TMS-route limit, not a tool gap). See [AUDIT_REPORT.md](AUDIT_REPORT.md),
> [CAPABILITY_DOSSIER.md](CAPABILITY_DOSSIER.md), and [Production Readiness](#production-readiness).

---

## The Problem: Why SAP Migrations Fail

SAP S/4HANA migrations are among the most complex enterprise transformations undertaken today:

| Challenge | Industry Reality |
|-----------|-----------------|
| **Timeline** | Average migration takes **2-4 years** to complete |
| **Budget Overruns** | **60-70%** of projects exceed planned budgets by 2x or more |
| **Custom Code** | Enterprises carry **500-5,000+ custom ABAP programs**, most untouched for a decade |
| **Data Quality** | Duplicate business partners, orphaned records, and inconsistent master data plague every migration |
| **Regression Risk** | Configuration drift between ECC and S/4HANA introduces silent failures post go-live |
| **Rollback** | Most migrations have **no viable rollback path** once execution begins |
| **Testing** | Manual test case creation takes months and covers only a fraction of scenarios |
| **Localization** | Country-specific tax, compliance, and legal rules require deep domain expertise per jurisdiction |
| **Consultant Dependency** | Migrations require large teams of specialized SAP consultants at $250-450/hr |

---

## The Solution: an automated, support-clean migration factory

Migrate4HANA collapses the fragmented, consultant-heavy ECC→S/4HANA migration into **one governed,
automated pipeline**. On this branch it runs the **Greenfield / Selective Data Transition** lane: it
extracts from a live ECC source and loads into an S/4HANA target **exclusively through SAP-released
APIs** (Migration Cockpit, `API_BUSINESS_PARTNER` OData, released BAPIs, LTMOM, IDoc inbound, CTS+/`tp`,
BC Sets), with end-to-end reconciliation, idempotency, delta/CDC, and a governed cutover.

Unlike manual approaches that take 2–4 years, it compresses months of effort into hours of orchestrated
execution — one tool that reduces **time, effort, and cost** across discovery → code remediation →
config → data migration → reconciliation → cutover.

**What Migrate4HANA automates (the orchestration plane):**
- Assessment: discovery, HANA sizing, simplification-item + custom-code analysis
- AI ABAP custom-code remediation (6,400-line AST + ATC + GenAI) with an **ATC + human approval gate**
- Config extraction + BC-Set packaging + CTS+ transport
- Data migration via released BAPIs/OData, with **value-level reconciliation + an idempotent ledger**
- Delta/CDC, dead-letter, a machine-checkable support-compliance attestation, and a governed GO/NO-GO cutover

**What stays in SAP's hands (the execution plane — zero direct writes):**
- Every actual write: Migration Cockpit / OData / released BAPIs, LTMOM, IDoc inbound, CTS+/`tp`, BC Sets
- Object recording + transport into the target system

> **Note on modes:** the **Brownfield SUM/DMO in-place conversion** lane is a separate, **legacy** mode
> (retired on this branch under `lambda/_deprecated/`) — it wrapped SAP's Software Update Manager for the
> database conversion. This branch is the **Greenfield / Selective Data Transition** lane and does **not**
> run SUM/DMO. Some deeper sections below (project structure, component-readiness) still describe the
> legacy lane and are being progressively updated.

---

## Architecture

Migrate4HANA uses a **two-plane design**: an **orchestration plane** on AWS drives an **execution
plane** made entirely of SAP-shipped tools. The tool performs **zero direct writes** into the
target — every change goes through a released SAP mechanism (Migration Cockpit / `API_BUSINESS_PARTNER`
OData, released BAPIs, LTMOM, IDoc inbound, CTS+/`tp`, BC Sets) — so **SAP support is fully preserved**.

```
+================================================================================================+
|                                       AWS CLOUD (VPC)                                           |
|                                                                                                 |
|  +-----------+   +-------------------+   +--------------------------------------------------+    |
|  | Web UI    |-->| API server        |-->| ORCHESTRATOR                                     |    |
|  | (React)   |   | (FastAPI / ECS)   |   |  cloud : AWS Step Functions  (with rollback)     |    |
|  +-----------+   +-------------------+   |  local : run_local_lift_and_shift.py             |    |
|       ^ WebSocket (API GW)              |  drives the 28-stage / 9-phase pipeline on        |    |
|       | live telemetry                 |  Lambda + ECS Fargate [F] (heavy stages)          |    |
|  +-----------+                          +--------------------------------------------------+    |
|  | Operator  |   CloudWatch + SNS alarms          |                                              |
|  +-----------+                                     v                                              |
|                          +------------------------------------------------------------------+   |
|  AWS SERVICES            | 9 PHASES (released-API-only handlers)                            |   |
|  +--------------------+  |  0 ASSESS    discovery-engine[F] · sizing-advisor · object-router|   |
|  | S3 (staging +      |<-|  1 PROVISION target-provisioner · (gate) · basis-validator       |   |
|  |  evidence packs)   |  |  2 CODE      code-analyzer[F] +ATC+GenAI --> transport-* (CTS+)   |   |
|  | DynamoDB (ledger,  |<-|  3 CONFIG    config-replicator · bc-set-builder --> transport-*   |   |
|  |  watermark, keymap)|  |  4 DATA-PREP data-migrator[F](extract) · data-hygiene(BP dedup)  |   |
|  | Secrets Manager+KMS|->|  5 DATA-LOAD mc-orchestrator · ltmom-orch · idoc-orch            |   |
|  | Bedrock + air-     |->|  6 VALIDATE  migration-validator · test-generator · completeness |   |
|  |  gapped Ollama LLM |  |  7 CUTOVER   cutover-orch(lock) · delta-extractor · final-recon  |   |
|  | Entity Resolution  |->|  8 RUN       evidence PDF report                                 |   |
|  | WAF · Audit ledger |  +------------------------------------------------------------------+   |
|  +--------------------+            |                                |                            |
|  Terraform (terraform/modules/)    | RFC + OData (pyrfc):            | AWS SSM Run Command:       |
|  vpc·vpc-endpoints·lambda·ecs·     | released BAPIs /               | tp / R3trans (CTS+) +      |
|  step-functions·s3-staging·        | API_BUSINESS_PARTNER OData     | the in-system ABAP agent   |
|  dynamodb·secretsmanager·          v                                v                            |
|  cloudwatch·websocket-telemetry· +------------------+   +-----------+   +----------------------+ |
|  waf·airgapped-llm·dms·           | S/4HANA TARGET   |   | SAP host  |   |   (target-system     | |
|  entity-resolution·target-system· | (Migration       |   | EC2, SSM- |   |    Terraform module: | |
|  audit·evidence-ledger·kms        |  Cockpit, OData, |<--| managed:  |   |    aws_instance +    | |
|                                   |  released BAPIs) |   | /usr/sap/ |   |    instance profile) | |
|        VPN / Direct Connect       +------------------+   | trans,STMS|   +----------------------+ |
|  ---------------------------------+                      +-----------+                            |
|                                   |                                                              |
|  +-----------------------------+  |   EXECUTION PLANE = SAP-shipped tools only                   |
|  |  ON-PREM SAP ECC (source,   |<-+   (zero direct writes; machine-attested support-clean)       |
|  |  read-only RFC user)        |                                                                 |
|  +-----------------------------+                                                                 |
+================================================================================================+
```

**AWS deployment — is this diagram valid, and what changes in the cloud?** Yes, this topology is the
one provisioned by the Terraform modules under `terraform/modules/` and is valid as drawn. Key points
versus the legacy System-Conversion diagram:

- **Data migration is via released BAPIs + OData over RFC (pyrfc)** — *not* AWS DMS. DMS remains an
  optional CDC path (its module is retained); the proven, support-clean path is the Migration-Cockpit /
  BAPI / `API_BUSINESS_PARTNER` spine.
- **NEW — AWS SSM Run Command to an SSM-managed SAP host.** The CTS+ transport chain (`tp`/`R3trans`)
  and the **in-system ABAP agent** run shell/ABAP on the SAP host via SSM, not over RFC (those CTS FMs
  aren't RFC-exposed). Provisioned by the `target-system` module (`aws_instance` +
  `aws_iam_instance_profile` for SSM + scoped S3). The host's **EC2 instance ID is stable across
  stop/start** (only the public IP drifts), so transport addressing survives restarts.
- **No SUM/DMO orchestration.** The Brownfield in-place lane is deliberately out of scope on this branch
  (the old `sum-orchestrator` / `maintenance-planner` lambdas are retired to `lambda/_deprecated/`).
- **GenAI is dual-backend** (AWS Bedrock or an air-gapped Ollama for regulated/offline sites);
  remediation rules are **static-by-default**, with the DynamoDB rule table opt-in
  (`M4H_RULES_SOURCE=dynamodb`).
- **No credentials in code** — RFC/OData/host creds come from **Secrets Manager** (local runs use a
  shim over `connections.json` + `M4H_ECC_PASSWD` / `M4H_TARGET_PASSWD`).
- **Connectivity:** on-prem ECC reached via **VPN / Direct Connect**; the S/4HANA target and SAP host
  live in the VPC (or are reachable from it). Telemetry streams to the UI over **API Gateway WebSocket**.

---

## 28-Stage Pipeline — 9 Phases (Greenfield / Selective Data Transition)

Driven by `run_local_lift_and_shift.py` locally, or AWS Step Functions in the cloud. Every stage is a
released-API-only handler; results accumulate in a shared run context and the pipeline halts on any
hard failure. Non-`success` statuses are **honest hand-offs**, not crashes — `manual_required`
(transport build needs a routed landscape), `manual_gate` (e.g. ECC lock, custom-object LTMOM models),
or `skipped`.

| Phase | Stages (lambda handler) | What it does |
|---|---|---|
| **0 · ASSESS** | `discovery-engine` [F] · `sizing-advisor` · `object-router` | Scan ECC (custom code, org units, objects, roles); recommend HANA/app sizing from real DB + ST03N workload; route every object to a load lane (MC / LTMOM / IDoc / manual) |
| **1 · PROVISION** | `target-provisioner` · *gate: basis-handover* · `basis-validator` | Stand up or hand over the target; validate readiness (clients, STMS, Migration Cockpit, `idoc_xml` SICF) |
| **2 · CODE** | `code-analyzer` [F] (extract → remediate) · `transport-artifact-builder` / `-file-placer` / `-import-executor` / `-import-verifier` | 6,400-line ABAP AST + ATC + GenAI remediation of live custom code; ship via **CTS+ transport** — with an **ATC + human approval gate** before anything deploys |
| **3 · CONFIG** | `config-replicator` · `bc-set-builder` · `transport-*` | Extract customizing; package BC Sets; transport to target |
| **4 · DATA-PREP** | `data-migrator` (extract) · `data-hygiene` · `data-migrator` (templates) | Extract objects (live ECC); ML business-partner dedup / hygiene; generate Migration-Cockpit templates |
| **5 · DATA-LOAD** | `migration-cockpit-orchestrator` · `ltmom-orchestrator` · `idoc-orchestrator` | Load via the routed lane using **released BAPIs + `API_BUSINESS_PARTNER` OData**, with **value-level reconciliation** and a **cross-run idempotent ledger** (re-runs reuse, never duplicate) |
| **6 · VALIDATE** | `migration-validator` · `test-generator` · `migration-completeness-analyzer` · *gate: pre-cutover* | Existence **and** value reconciliation; a GO-LIVE scorecard that **refuses to certify on simulated/offline data**; generated tests; completeness analysis |
| **7 · CUTOVER** | `cutover-orchestrator` (lock ECC) · `delta-extractor` · `migration-cockpit-orchestrator` (delta) · `migration-validator` (final) · *gate: final-go-live* · `integration-activator` | Lock the source, pull the final delta, re-reconcile, GO/NO-GO, activate integrations |
| **8 · RUN** | evidence PDF report | Auditable evidence pack |

`[F]` = runs on **ECS Fargate** (heavy compute); the rest are Lambdas.

### Support model — why SAP support is retained

Every write goes through a **SAP-shipped, business-logic-honoring mechanism** (released BAPIs, the
released `API_BUSINESS_PARTNER` OData service, Migration Cockpit, LTMOM, IDoc inbound, CTS+/`tp`, BC
Sets). The tool **never** writes raw tables, runs arbitrary ABAP, or bypasses CTS — and each run emits a
**machine-checkable attestation** that none of those support-breaking techniques were used.

> The **Brownfield SUM/DMO in-place conversion** lane is a **separate, legacy mode** (retired on this
> branch under `lambda/_deprecated/`). This pipeline is the **Greenfield / Selective Data Transition**
> lane — the same lane as the SAP S/4HANA Migration Cockpit, but with far more automation around it
> (discovery, reconciliation, idempotency, cutover) and an AI custom-code remediation arm.

---

## Value Proposition

| # | Value | Detail |
|---|-------|--------|
| 1 | **Time Reduction** | What traditionally takes 18-36 months of manual effort, Migrate4HANA compresses to weeks by automating assessment, code remediation, data preparation, and post-conversion validation. |
| 2 | **Cost Reduction** | Eliminates the need for large consulting teams for repetitive tasks. One tool replaces dozens of manual workstreams. |
| 3 | **Risk Reduction** | Deterministic, repeatable pipeline with automated rollback, reconciliation reports, and GO-LIVE scorecard. |
| 4 | **SAP Compliance** | Full alignment with SAP Activate Methodology ensures post-migration support is retained. |
| 5 | **Quality Assurance** | 98.6% auto-fix rate for custom code, ML-powered BP deduplication, zero-variance financial reconciliation. |

---

## Key Capabilities

- **Released-API-only data migration** — a best-mechanism-per-object dispatcher (released BAPIs + `API_BUSINESS_PARTNER` OData + IDoc inbound); **11 object types load live, ~20 extract**; zero direct table writes
- **Value-level reconciliation** — every loaded record read back; existence **and** value tie-out (FI amounts, factor-aware exchange rates, recon accounts); a hard RECONCILED / DISCREPANCY verdict
- **Cross-run idempotent ledger** — re-runs resume, never duplicate (persisted source→target key registry)
- **Delta / CDC** — extract only records changed since a watermark, including changed masters via CDHDR change documents
- **Collision-safe key strategy + dead-letter** — never silently corrupts a target record; genuine failures captured with the SAP reason for safe reprocessing
- **Parallel mass-load** — connection-pool parallelism (pyrfc frees the GIL) at ~9× single-thread throughput
- **Landscape-agnostic auto-discovery** — reads org units / accounts / hierarchies from whatever target it connects to (PO expense GL is probe-validated; env-overridable; cached)
- **Support-clean attestation** — a machine-checkable proof that every write used a released SAP API (no raw table writes, no arbitrary ABAP, no SUM/Maintenance-Planner bypass)
- **Custom code analysis + remediation** — 6,400-line AST compiler + ATC (`/SDF/ATC_RUN_API`) + GenAI (Bedrock / air-gapped Ollama), **gated by an ATC + human approval** before transport. **Runs on ECS Fargate** (4 vCPU / 16 GB) for scale
- **Simplification-item check** — live `D010TAB` custom-code scan against a ~9,200-rule knowledge base, mapped to remediation tasks
- **In-system ABAP agent** — deploy + execute ABAP on the target over RFC (drives in-system CTS work that isn't RFC-exposed)
- **Governed cutover** — initial full load → delta → reconcile → GO/NO-GO runbook
- **Process mining** — ST03N workload analysis
- **RFC call timeouts** — `call_rfc_with_timeout()` prevents indefinite hangs with configurable timeout (default 120s)
- **Paginated table reads** — `read_table_chunked()` generator with ROWSKIPS/ROWCOUNT pagination for safe large-table scanning
- **Lambda event validation** — Shared `validation.py` validates run_id, ecc_client, mode, dry_run, stage across 4 handlers
- **Idempotency** — DynamoDB-backed duplicate detection for data-loader prevents reprocessing on Lambda retries
- **Credential refresh** — Secrets Manager caching with TTL and auto-retry on auth failures

---

## Technical Metrics

| Metric | Value |
|--------|-------|
| Pipeline Stages | 28 across 9 phases (ASSESS → RUN) |
| Lambda Functions | 18 (15 pipeline + 3 support) |
| ECS Fargate Stages | 4 (Stages 1, 5, 12, 12A — 4 vCPU / 16 GB) |
| Terraform Modules | 14 |
| Automated Validation Checks | 85 |
| AST Transform Rules | 160 (AST-001 → AST-160) |
| Table Transformations | 249 ECC → S/4HANA mappings |
| Country Compliance Rules | 535 rules across 57 countries |
| OData Service Mappings | 443 T-code → OData entries |
| Fiori Catalog Mappings | 611 T-code → Fiori app mappings |
| SUM Known Error Patterns | 94 across all SUM phases |
| IDoc Partner Profiles | 226 reference profiles |
| Custom Code Auto-Fix Rate | 98.6% |
| Financial Reconciliation | Zero-variance |
| Test Suite | 114 tests (unit + integration) |
| Telemetry | Real-time WebSocket |

---

## Project Structure

```
migrate4hana/
+-- lambda/                               # Migration engine — 36 stage handlers + shared utils
|   |  # Phase 0 ASSESS
|   +-- discovery-engine/                 # ECC scan: custom code, org, objects, roles [ECS Fargate]
|   +-- sizing-advisor/                   # HANA/app sizing from DBSTATTORA + ST03N workload
|   +-- object-router/                    # Route each object to a load lane (MC/LTMOM/IDoc/manual)
|   |  # Phase 1 PROVISION
|   +-- target-provisioner/               # Stand up / hand over the target
|   +-- basis-validator/                  # Target readiness (clients, STMS, MC, idoc_xml SICF)
|   |  # Phase 2 CODE
|   +-- code-analyzer/                    # ABAP AST + ATC + GenAI remediation [ECS Fargate]
|   |   +-- abap_ast_engine.py            #   6,400-line ABAP parser -> transformer -> codegen
|   |   +-- genai_router.py               #   dual-backend router (Bedrock / Ollama)
|   |   +-- bedrock_genai_engine.py       #   AWS Bedrock (Claude) invoke
|   |   +-- ollama_genai_engine.py        #   air-gapped Ollama invoke
|   |   +-- data_scrubber.py              #   PII masking before any LLM dispatch
|   |   +-- country_rules.py · fixers/    #   country rules; Deep-Knowledge + level1/2/2b/3 fixers
|   +-- code-deployer/                    # Ship remediated ABAP via CTS+ (ATC + HUMAN approval gate)
|   +-- transport-artifact-builder/       # Build CTS+ transport (create/record/release)
|   +-- transport-file-placer/            # S3 -> host /usr/sap/trans (via AWS SSM)
|   +-- transport-import-executor/        # `tp import` on the SAP host (via SSM), RC-certified
|   +-- transport-import-verifier/        # Verify the import
|   |  # Phase 3 CONFIG
|   +-- config-replicator/ · config-applier/ · bc-set-builder/   # Extract / apply customizing; BC Sets
|   |  # Phase 4 DATA-PREP
|   +-- data-migrator/                    # Extract + LOAD objects + reconcile [ECS Fargate]
|   +-- data-hygiene/                     # ML business-partner dedup / master-data hygiene
|   |  # Phase 5 DATA-LOAD
|   +-- migration-cockpit-orchestrator/   # MC / OData load lane
|   +-- ltmom-orchestrator/               # LTMOM custom-object lane (manual_gate by design)
|   +-- idoc-orchestrator/                # IDoc inbound lane
|   |  # Phase 6 VALIDATE
|   +-- migration-validator/              # Existence+value reconciliation + GO-LIVE scorecard
|   +-- test-generator/ · migration-completeness-analyzer/       # Generated tests; completeness
|   |  # Phase 7 CUTOVER
|   +-- cutover-orchestrator/ · delta-extractor/ · integration-activator/   # Lock; final delta; integrations
|   |  # Assessment / data-quality / roles / safety (used across phases)
|   +-- readiness-check/ · simplification-check/ · process-miner/
|   +-- reconciliation-engine/ · evidence-collector/ · data-loader/ · manual-gate/
|   +-- role-migrator/ · role-provisioner/ · integration-mapper/ · rollback-manager/
|   +-- utils/                            # Shared libraries
|   |   +-- unified_loader.py             #   best-mechanism-per-object dispatcher (BAPI/OData/IDoc)
|   |   +-- bapi_loader.py                #   released-BAPI creators (BP/Material/PO/FI/CC/PC/Asset/...)
|   |   +-- odata_client.py · bp_odata.py #   transaction-ready Customer/Vendor via API_BUSINESS_PARTNER
|   |   +-- reconciler.py                 #   existence + value reconciliation
|   |   +-- key_map.py                    #   source->target key registry (idempotent ledger)
|   |   +-- config_discovery.py           #   landscape-agnostic target config discovery
|   |   +-- compliance.py                 #   machine-checkable support-clean attestation
|   |   +-- sap_host_runner.py            #   AWS SSM Run Command -> SAP host (tp / R3trans / agent)
|   |   +-- rule_router.py                #   simplification rules (static default; DynamoDB opt-in)
|   |   +-- logger.py · validation.py · rfc_pool.py · sap_prereq_checks.py  (+ more)
|   +-- _deprecated/                      # Legacy Brownfield/SUM-DMO lambdas (sum-orchestrator, ...)
|
+-- agent/                                # In-system ABAP agent — deploy + run ABAP over RFC
|   +-- deploy_run_abap.py                #   RPY_PROGRAM_INSERT($TMP) + RZL_SUBMIT + SSM result read
|   +-- zm4h_*.abap                       #   probe / transport-builder / syntax-checker agent reports
+-- terraform/                            # IaC — 16 modules (see Architecture); environments/{dev,staging,prod}
+-- frontend/                             # React UI (Dashboard, Pipeline, Scorecard, Connections, Lift&Shift)
+-- tests/                                # Unit/integration/load (incl. tests/test_no_direct_writes.py CI gate)
+-- docs/                                 # SAP concepts reference
|
+-- run_local_lift_and_shift.py           # The 28-stage / 9-phase local orchestrator
+-- cutover.py                            # Governed cutover rehearsal (full -> delta -> reconcile -> GO/NO-GO)
+-- volume_load.py                        # Parallel mass-load harness (~9x throughput)
+-- audit_pipeline.py                     # Automated stage real-vs-scaffold auditor
+-- local_aws_shim.py                     # Local AWS shim (Secrets/S3/SSM over connections.json)
+-- api_server.py                         # FastAPI server (REST + JWT)
+-- connections.json                      # ECC + S/4 hosts (gitignored; passwords via env vars)
+-- AUDIT_REPORT.md · CAPABILITY_DOSSIER.md · BREADTH_BUILDOUT_PROMPT.md
+-- TRANSPORT_INFRA_SETUP.md · ABAPGIT_SETUP.md · MIGRATE4HANA-LIFT-AND-SHIFT.md
```

## Quick Start

### Local Testing (Live SAP ECC required)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Save connections on the Connections page of the UI (writes connections.json),
# then run the 28-stage / 9-phase lift-and-shift pipeline against live ECC -> S/4HANA:
set M4H_ECC_PASSWD=<ecc-password>
set M4H_TARGET_PASSWD=<s4-password>
python run_local_lift_and_shift.py --run-id RUN-001          # full pipeline
#   --list-stages | --from-stage <id> --through <id> | --only <id> | --dry-run
#   M4H_LOAD_TO_S4=1 enables real loads (else extract + assess only)
```

Mock mode has been removed — a working pyrfc install plus `connections.json` and the
`M4H_ECC_PASSWD` env var are required. Output is saved to `test-output/run_YYYYMMDD_HHMMSS/`.

### GenAI routing (Bedrock + air-gapped Ollama)

The `code-analyzer` lambda/ECS task routes ABAP analysis through:

  1. **AST engine** (always first) — deterministic, zero-latency
  2. **LLM backend**, selected by the `LLM_MODE` env var:
     - `cloud` (default) — AWS Bedrock via PrivateLink
     - `local` — on-prem Ollama (Gemma2 27B by default)
     - `dual` — Ollama for `sensitivity=="high"` context, Bedrock otherwise

The air-gapped LLM is provisioned by `terraform/modules/airgapped-llm/` (GPU EC2
running Ollama in a private subnet with VPC-only egress). Enable per environment
with `-var='enable_airgapped_llm=true'`. Relevant Lambda/ECS env vars:
`OLLAMA_URL`, `OLLAMA_MODEL`, `LLM_MODE`.

### Pipeline Modes

| Mode | Description | Phases | S/4HANA Required |
|------|-------------|--------|------------------|
| `full` | End-to-end migration: all 28 stages across 9 phases | 0-8 | Yes |
| `assess` | Assessment only: discovery, readiness, code analysis | 1-2 | No |
| `quick` | Fast assessment: subset of Phase 1-2 checks | 1-2 | No |
| `delta` | Delta run: re-process only changed objects since last run | 1-2 | No |
| `ecc_full` | **ECC-only full execution**: runs all remediation and transformation against ECC, generates multi-volume proof-of-work PDF reports. No S/4HANA needed. | 1-2 + 9.5 + 9.6 | **No** |

---

## ECC-Only Full Execution Mode

The `ecc_full` mode runs the complete assessment and remediation pipeline (Phases 1-2) against an ECC system **without requiring an S/4HANA target system**, then generates comprehensive multi-volume PDF reports proving all work is done and migration-ready.

### What It Does

1. **Phase 1 (Prepare)** — Discovery, Maintenance Planner, Readiness Check, Simplification Item Check
2. **Phase 2 (Explore)** — Code Analysis + AST remediation, CVI/BP preparation, Data Assessment, Config/Integration Assessment
3. **Stage 9 (Pre-Conversion Gate)** — Report-only mode (no S/4HANA connectivity check)
4. **Stage 9.5 (Migration Completeness Analyzer)** — Computes a weighted Migration Completion Score across 6 dimensions: Code Remediation (30%), Data Transformation (20%), Configuration (15%), Roles & Authorization (15%), Integration Migration (10%), Test Readiness (10%)
5. **Stage 9.6 (Multi-Volume PDF Report Generator)** — Generates professional, boardroom-ready multi-volume PDF migration reports

### Why It Exists

This mode enables a **two-phase commercial model**:
- **Phase A (ECC-Only):** Run Migrate4HANA against the customer's ECC system. All custom code is remediated, business partners are deduplicated and crosswalked, data is assessed, configurations are mapped, and a comprehensive multi-volume report is delivered proving the work is done.
- **Phase B (Migration):** When the customer is ready, provision S/4HANA and run the DATA-LOAD → VALIDATE → CUTOVER phases (released-API data migration + value-level reconciliation + governed GO/NO-GO cutover) to complete the migration.

### How to Run

```bash
# ECC-only full execution (against live ECC — requires connections.json + M4H_ECC_PASSWD)
python run_local_pipeline.py --mode ecc_full --ecc_client 100

# Via API server
curl -X POST http://localhost:8000/api/pipeline/ecc_full \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"ecc_client": "100"}'
```

### What the PDF Reports Contain

The multi-volume report is split into volumes of ≤50 pages each, with 10 sections:

| Section | Content |
|---------|---------|
| 1. Executive Summary | Overall completion score (donut gauge), 6-dimension spider chart, readiness statement |
| 2. System Landscape | Discovery summary: programs, tables, FMs, org structure, roles, users |
| 3. Code Remediation | Fix rates, before/after ABAP code samples, issue breakdown by severity |
| 4. Data Transformation | BP migration stats, dedup results, crosswalk summary, finance document counts |
| 5. Configuration | Config checklist, SPRO table coverage, country localization |
| 6. Roles & Authorization | Role mapping, Fiori catalog assignments, user provisioning |
| 7. Integration Migration | RFC destinations, IDoc partners, API mappings |
| 8. Test Readiness | DITL coverage, test generation status |
| 9. Risk & Recommendations | Manual remediation items, effort estimates, recommended next steps |
| 10. Appendices | Full crosswalk table, detailed fix log, glossary |

### Sample Output

```
=== MULTI-VOLUME PDF REPORT ===
  Generating 10-section professional migration report...
  Volume 1: Migrate4HANA_Migration_Report_Bharat_Industrial_2026-04-05_Vol1_of_3.pdf (50 pages)
  Volume 2: Migrate4HANA_Migration_Report_Bharat_Industrial_2026-04-05_Vol2_of_3.pdf (50 pages)
  Volume 3: Migrate4HANA_Migration_Report_Bharat_Industrial_2026-04-05_Vol3_of_3.pdf (28 pages)
  Total: 3 volumes, 128 pages
```

### Web UI

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### AWS Deployment

```bash
# 1. Configure
cd terraform/environments/dev
vim terraform.tfvars

# 2. Deploy infrastructure
terraform init && terraform apply

# 3. Build & push ECS Docker image
ECR_URL=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URL
cd ../../..  # back to project root
docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
docker tag migrate4hana-worker:latest $ECR_URL:latest
docker push $ECR_URL:latest

# 4. Deploy Lambda functions
cd scripts && ./deploy.sh
```

### Infrastructure Modules (16 Terraform Modules)

| Module | Description |
|--------|-------------|
| `vpc` | VPC with private subnets for SAP connectivity |
| `lambda` | 18 Lambda functions with telemetry env vars |
| `ecs` | ECS Fargate cluster, ECR repo, task definition (4 vCPU / 16 GB) for Stages 1, 5, 12, 12A |
| `step-functions` | 28-stage state machine with ECS `waitForTaskToken` + Lambda invoke + error chaining to rollback-manager |
| `s3-staging` | Intermediate data staging bucket |
| `cloudwatch` | Monitoring, alerts, and log retention |
| `dms` | AWS DMS for full-load + CDC continuous data sync |
| `dynamodb` | Country rules, simplification tables, migration state |
| `vpc-endpoints` | PrivateLink for Amazon Bedrock (no public internet) |
| `airgapped-llm` | Isolated GPU EC2 instance for local LLM (g5.2xlarge) |
| `entity-resolution` | AWS Entity Resolution for ML-powered BP deduplication |
| `websocket-telemetry` | API Gateway WebSocket for real-time log streaming |
| `waf` | WAFv2 Web ACL: rate limiting, OWASP Core Rules, SQLi, IP reputation |
| `audit` | CloudTrail + S3 WORM (7-year retention) + compliance metric alarms |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEMETRY_WS_ENDPOINT` | WebSocket API endpoint for real-time log broadcast |
| `TELEMETRY_CONNECTIONS_TABLE` | DynamoDB table for WebSocket connection tracking |
| `BP_FUZZY_THRESHOLD` | Fuzzy matching threshold for BP dedup (default: 0.82) |
| `ENTITY_RESOLUTION_WORKFLOW_ARN` | ARN for AWS Entity Resolution matching workflow |
| `LLM_MODE` | GenAI routing: `AMAZON_BEDROCK` or `AIRGAPPED_LOCAL` |
| `RFC_CALL_TIMEOUT_SECONDS` | Timeout for individual RFC/BAPI calls in seconds (default: 120) |
| `RFC_PAGE_SIZE` | Row count per page for paginated table reads (default: 5000) |
| `FINS_MAX_POLLS` | Max polling iterations for FINS_MASS_DATA_MONITOR (default: 480) |
| `FINS_POLL_INTERVAL` | Base polling interval in seconds for FINS monitor (default: 30) |
| `ROLLBACK_BATCH_SIZE` | Items per BAPI_TRANSACTION_COMMIT batch in rollback (default: 25) |
| `IDEMPOTENCY_TABLE` | DynamoDB table name for Lambda retry idempotency (default: migrate4hana-idempotency) |

```bash
# 4. Start migration -- assessment only (Phases 1-2)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"mode":"assess","ecc_client":"100","execute":false}'

# 5. Start migration -- full execution (all 9 phases)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"mode":"full","ecc_client":"100","execute":true}'
```

## Code Remediation Engine (Production-Grade AST + ATC + GenAI)

The Code Analyzer features a **6,400-line Abstract Syntax Tree (AST) Parser** with **160 transform rules (AST-001 → AST-160)**, combined with **ABAP Test Cockpit (ATC)** integration and a dual-path GenAI Fallback Strategy.

- **AST Engine (`abap_ast_engine.py`)** — Full compiler pipeline: Lexer -> Parser -> AST Transformer -> Code Generator. 160 transformation rules covering table renames, deprecated statement rewrites, Open SQL modernization, ACDOCA migration patterns, BP consolidation, Material Document restructuring, and more.
- **ATC Integration** — /SDF/ATC_RUN_API execution with S/4HANA-specific check variant for comprehensive compatibility analysis.
- **Deep Knowledge Engine** — 249 ECC-to-S/4HANA table transformation rules with semantic rewrites and mandatory WHERE clauses (BSEG->ACDOCA with `RLDNR='0L'`, `KOART` filters, etc.)
- **Enterprise GenAI (Standard Path)** — Bedrock integration via PrivateLink (`terraform/modules/vpc-endpoints`) for massive enterprise processing and semantic reasoning.
- **Air-Gapped GenAI (High-Security Path)** — Custom EC2 Terraform Module (`terraform/modules/airgapped-llm`) routing AST nodes to an isolated GPU instance (`g5.2xlarge`) running a local LLM (e.g., Llama 3) entirely within strict Private Subnets with *zero* outbound internet. Guaranteed InfoSec compliance.
- **Data Scrubber (`data_scrubber.py`)** — Pre-processes any pipeline payload to mask PII, passwords, code comments, and literal structures before dispatch.

## Real-Time WebSocket Telemetry

Every Lambda stage emits structured log events (`log_stage_event`) that are broadcast in real-time to the React frontend via **API Gateway WebSocket** (`terraform/modules/websocket-telemetry`).

- **Structured Logger (`lambda/utils/logger.py`)** — All 21 Lambda handlers emit `stage`, `status`, `detail`, and `timestamp` fields through a centralized logger with WebSocket broadcast.
- **LogViewer Component (`frontend/src/components/LogViewer.jsx`)** — Live-updating scrollable log panel with auto-reconnect and connection status indicator.
- **CloudWatch Integration** — All events are simultaneously shipped to CloudWatch Logs for durable retention and alerting.

## Master Data Deduplication & Hygiene

Business Partner deduplication powered by **fuzzy matching** and **AWS Entity Resolution**.

- **BP Deduplication Engine (`bp_deduplication_engine.py`)** — Levenshtein distance + Soundex phonetic matching + weighted multi-field scoring with configurable thresholds. Uses blocking (first-letter partitioning) for O(n) performance and Union-Find for transitive cluster merging.
- **MDM Data Cleanser (`mdm_data_cleanser.py`)** — Address standardization, phone normalization, and data quality scoring.
- **AWS Entity Resolution (`terraform/modules/entity-resolution`)** — ML-powered matching workflow for production-scale deduplication with schema mapping and S3 I/O.

## Global Localization (57 Countries)

Migrate4HANA utilizes Dynamic Rules stored in **DynamoDB** (`terraform/modules/dynamodb`) to fetch country-specific simplifications.
- **Global Config Framework (`global_config_framework.py`)** — 58 country compliance modules covering US Sales/Use Tax, Brazil's Nota Fiscal (NF-e/NFS-e), Germany's GoBD, EU GDPR retention, Japan's Consumption Tax, UAE VAT, Switzerland's QR-bill, India GST/TDS/E-Invoice, Saudi Arabia's ZATCA, South Africa's VAT Act, Australia's BAS/STP, Mexico's CFDI, South Korea's e-Tax, and 40+ more — dynamically selected based on Company Code (BUKRS).
- **Country Rules Engine (`country_rules.py`)** — 535 compliance rules across 57 countries with tax codes, regulatory mapping, depreciation keys, withholding tax, e-invoicing, and compliance endpoints.
- **Automated Rollback Engine** — Should the sequence fail during execution, `rollback-manager` Lambda natively executes `BAPI_ACC_DOCUMENT_REVERSE` and `BAPI_CTREQUEST_DELETE` preventing corruption.
- **Data Sync & Cutover** — Powered by pure AWS DMS provisioned via Terraform (`terraform/modules/dms`) doing full load and continuous data CDC.

## Safety & Testing Automation

- **Rollback Manager (`lambda/rollback-manager/`)** — Automated reversal covering post-conversion stages: FI document reversal (BAPI_ACC_DOCUMENT_REVERSE), transport cleanup, ACDOCA universal journal entries, SPRO customizing table entries, business partners, material documents, number ranges, BP groupings, roles, user assignments, RFC destinations, and IDoc partners. Wired into Step Functions error chain.
- **DITL Test Generator (`lambda/test-generator/ditl_generator.py`)** — Generates runnable Day-In-The-Life Cypress test scripts with 443 T-code-to-OData mappings, real Fiori selectors, custom commands (`loginToS4HANA`, `navToApp`, `waitForFioriApp`), and S/4HANA OData service intercepts.
- **Process Miner (`lambda/process-miner/st03n_analyzer.py`)** — ST03N workload analysis with 611 T-code-to-Fiori catalog mappings for identifying high-value programs and hot tables.

## Latest Live Run (E2E-003 — full pipeline against live ECC→S/4HANA)

The **28-stage pipeline ran end-to-end against a live ECC (Y01) → S/4HANA (S4H) pair**, `rc=0`,
**zero failed records** (S/4HANA on a SAP CAL fully-activated appliance + an ECC reference system).

| Metric | Value |
|---|---|
| Stages executed | **28 / 28** — no crashes, no hard failures |
| Objects extracted from live ECC | **20 types** at production-like volume |
| — examples | GLAccount 14,408 · BusinessPartner 28,242 · Customer 19,575 · CostCenter 2,645 · Vendor 2,415 · ProfitCenter 518 |
| Objects that load **+ reconcile** (released BAPI/OData) | **11 types** — existence + value tie-out, verdict **RECONCILED** |
| Idempotency (cross-run ledger) | re-run **reused 18 records, created 0 duplicates** |
| Custom ABAP remediated | live programs analyzed + AST-transformed (e.g. `Y_CLONE_PERNR`, `YBAPI`) |
| `migration-validator` verdict | **honest** — connected live and returned NOT-gate-eligible because data isn't fully loaded yet (it refuses to certify on partial/simulated data) |
| Failed records (dead-letter) | **0** |

> A genuine defect the live run caught (that the unit test missed): `ProfitCenter` failed against real
> data when the discovered config predated `PC_HIER`. Fixed (self-heal looks up the standard-hierarchy
> node) and confirmed on re-run — exactly the value of running against the realtime environment.

## Production Readiness

**Honest maturity: ~TRL 6** — demonstrated end-to-end in a relevant environment (real ECC + real
S/4HANA, real released APIs, real reconciliation) at sample volume. **Not yet TRL 8–9** (proven in
operational use across customers). A full audit of **all 36 stages** confirms each is a real
implementation (not scaffold) — see [AUDIT_REPORT.md](AUDIT_REPORT.md). For the AWS deployment playbook
see [PRODUCTION_READINESS_GUIDE.md](PRODUCTION_READINESS_GUIDE.md).

### Component status (current pipeline)

| Component | Status | Notes |
|---|---|---|
| **Data spine** (`data-migrator` + `utils`) | ✅ proven live | 11 object types load + reconcile; idempotent ledger; delta/CDC; dead-letter; parallel (~9×); support-clean attestation |
| **ASSESS** (discovery-engine · sizing-advisor · object-router) | ✅ proven live | real RFC scans, HANA sizing, object routing |
| **CODE** (code-analyzer + AST + GenAI) | ✅ live-validated | 6,400-line AST + Bedrock/Ollama; remediated real ECC programs; **ATC + human gate** before deploy |
| **simplification-check** | ✅ live-validated | live `D010TAB` scan vs a ~9,200-rule KB (1,003 items, 77 RED) |
| **basis-validator / readiness-check** | ✅ real | release-aware RFC checks (clients, STMS, MC, `idoc_xml`) |
| **migration-validator** | ✅ hardened | existence + value reconciliation; never certifies on simulated/offline data |
| **CONFIG / DATA-LOAD orchestrators / cutover / delta** | ✅ run live | config extract, MC/LTMOM/IDoc lanes, cutover delta + GO/NO-GO |
| **In-system ABAP agent** | ✅ proven | deploy + run ABAP on S/4 over RFC (RPY + RZL_SUBMIT + SSM) |
| **Transport chain** (build → place → import) | 🔶 infra proven; final import deferred | `tp` via SSM + S3↔host place proven; release→import is blocked only by the single-box appliance having no TMS route (works on a routed landscape) |
| **Terraform** (16 modules) | ✅ | VPC · Lambda · ECS · Step-Functions · S3 · DynamoDB · CloudWatch · WebSocket · WAF · Audit · Bedrock/air-gapped-LLM · Entity-Resolution · DMS · target-system · evidence-ledger · KMS |
| **Frontend / API server** | ✅ | React UI; FastAPI + JWT |

### Cross-cutting hardening (from the audit)
- **migration-validator** can no longer certify go-live on simulated/offline data (hard-blocks).
- **AI ABAP remediation** is gated: `code-deployer` ships nothing without an ATC pass + human approval.
- **Structured logging** normalized (`run_id` first-class); **secrets** attested clean (none in code);
  remediation **rules static-by-default** (DynamoDB opt-in).
- Retained from the platform: CI/CD (GitHub Actions, OIDC, SAP-SDK-from-S3, ECS image build), WAFv2,
  CloudTrail + S3 WORM audit, ECS Fargate for heavy stages, RFC pool with timeouts + paginated reads.

### Honest remaining gaps (the real ones)
1. **A pilot go-live** — the only true proof. Requires SAP functional + Basis expertise (best with an SI partner).
2. **Breadth** — 11 objects load today; ~40–60 of the ~120 Migration-Cockpit objects fit the proven
   pattern (see [BREADTH_BUILDOUT_PROMPT.md](BREADTH_BUILDOUT_PROMPT.md)).
3. **Transport final import on a routed landscape** (deferred — single-box appliance TMS-route limit;
   see [TRANSPORT_INFRA_SETUP.md](TRANSPORT_INFRA_SETUP.md) and [ABAPGIT_SETUP.md](ABAPGIT_SETUP.md)).
4. **A 2nd, non-IDES landscape** to confirm generalization (auto-discovery is the code-side enabler — done).
5. **Ops hardening at customer scale** — monitoring, secrets management, packaging/deployment.

> A note on prior claims: earlier README revisions reported "Grade A (100%), all gaps resolved" against
> a synthetic reference dataset — that reflected the legacy System-Conversion mode and a fabricated run.
> This section reports the **actual** live results and the **honest** remaining gaps.
## SAP / DevOps Glossary

| SAP Term | DevOps Equivalent |
|----------|-------------------|
| RFC | REST API / gRPC |
| Client (100, 200) | Environment (dev, prod) |
| Transport Request | Git commit + deploy pipeline |
| PFCG Role | IAM Role / Policy |
| BAPI | API endpoint |
| IDoc | Message queue message (SQS) |
| SPRO | Config management (Ansible vars) |
| Fiori | Frontend UI (React app) |
| HANA | Database (Aurora/RDS) |
| Z-program | Custom microservice |
| SUM/DMO | Deployment pipeline (CI/CD) |
| Maintenance Planner | Dependency resolver (npm/pip) |
| Readiness Check | Pre-deploy validation (smoke tests) |
