# Migrate4HANA — Detailed Review Brief

*Companion to `EXPERT_REVIEW_BRIEF.md`. The brief is the executive read; this
document is the engineering read: every claim backed by a file path, every
limitation named, every gap honestly graded. Written to be read end-to-end by
a Big-4-class peer reviewer, an SAP functional lead, and a cloud-security
architect in parallel.*

**Date:** 2026-05-31
**Branch:** `aws-lift-and-shift`
**Latest commit covered:** `2f33c3e`
**Repo:** GitHub `Ravi-Teja-Chowdary/migrate4hanav2`
**Stack maturity:** prototype, AWS prod stack applies/destroys cleanly (200 resources), in-AWS-only execution verified; **live ECC↔AWS connectivity deferred** until VPN/Direct Connect is configured.

---

## Reading guide

| If you are… | Read… |
|---|---|
| An exec / decision maker | §1 (positioning) + §3 (one-paragraph honest bottom line) + §24 (POC readiness) |
| An SAP functional lead | §1 + §6 (data lanes + objects) + §11 (live-proof matrix) + §13 (limitations) + §17 (CVI/DAG/cluster details) |
| A cloud / security architect | §2 (architecture) + §4 (AWS infra by module) + §18 (security posture) + §19 (audit / compliance) |
| A Big-4 SOX auditor | §19 (audit chain + evidence pack + cutover_verdict precedence) + §11 (live-proof) + §13 (limitations) |
| An engineer who will extend the code | §5 (repo layout) + §7-§10 (pipeline + state machine + modules) + §16 (extension points) |
| A SmartShift / Syniti / Natuvion competitor analyst | §14 (competitor-parity layers) + §15 (Gemini gap closures) |

---

## Table of contents

1.  [What it is — and what it is NOT](#1-positioning)
2.  [Architecture in one diagram](#2-architecture-overview)
3.  [One-paragraph honest bottom line](#3-honest-bottom-line)
4.  [AWS infrastructure inventory](#4-aws-infrastructure-inventory)
5.  [Repository layout](#5-repository-layout)
6.  [Migration object catalog and lane assignment](#6-migration-object-catalog)
7.  [The pipeline spine (4 phases)](#7-the-pipeline-spine)
8.  [The lift-and-shift Step Functions state machine](#8-step-functions-state-machine)
9.  [Lambda inventory (37 functions)](#9-lambda-inventory)
10. [`lambda/utils/` shared modules (33 files)](#10-shared-modules)
11. [Live-proof matrix](#11-live-proof-matrix)
12. [End-to-end data flow walkthrough](#12-data-flow-walkthrough)
13. [Honest limitations (the §6 of the brief, expanded)](#13-honest-limitations)
14. [Competitor-parity layers (SmartShift / Syniti / Natuvion)](#14-competitor-parity)
15. [SAP-functional-depth gap closures (8 + 4 follow-up)](#15-gap-closures)
16. [Extension points + per-landscape content surfaces](#16-extension-points)
17. [Trust spine deep dive](#17-trust-spine)
18. [Security posture](#18-security-posture)
19. [Audit, compliance, evidence pack, cutover precedence](#19-audit-compliance)
20. [Cost model](#20-cost-model)
21. [Deployment runbook](#21-deployment-runbook)
22. [Operational observability](#22-observability)
23. [Branch-name + naming caveats](#23-naming-caveats)
24. [POC readiness](#24-poc-readiness)
25. [Reviewer's checklist — what to scrutinize](#25-reviewers-checklist)
26. [Glossary](#26-glossary)

---

## 1. Positioning

### What Migrate4HANA IS

A **support-clean, highly-automated ECC → S/4HANA data migration *orchestration
+ reconciliation* engine** for the **greenfield / selective-data-transition**
lane. It extracts master and transactional data from an ECC source and writes
it into an S/4HANA target **exclusively through SAP-released APIs**:

- Released BAPIs over RFC (via `pyrfc`).
- The released `API_BUSINESS_PARTNER` OData service for transaction-ready
  customer/supplier creation.
- LTMC / Migration Cockpit staging files for objects / fields the BAPIs cannot
  carry (Gemini gap #3 fix).

Around the load, it provides what the Migration Cockpit does NOT give you out
of the box:

- **Auto-discovery** of target config (company code, sales area, plants, recon
  accounts, charts, order types, etc.) so the loader adapts to the landscape
  it connects to.
- **Cross-run idempotent ledger** keyed by `(object, source_key)` so a re-run
  resumes and never duplicates.
- **Existence + value reconciliation** with a hard `RECONCILED` / `DISCREPANCY`
  verdict per object.
- **SHA-256 hash-chained audit ledger** so any record-level tamper is detectable.
- **Native SAP balance reports** (FAGLB03 / MB5B) captured into the evidence
  pack so auditors get SAP-standard binaries, not a Python ledger alone.
- **Two-phase BP unification** (CVI) for KNA1/LFA1 → BUT000 with intercompany
  cycle detection.
- **DAG-ordered execution** (masters before transactionals) with `KeyResolver`
  that translates legacy KUNNR → S/4 BP ID at runtime for dependent objects.
- **Target-side workload throttle** (TH_WPINFO + NRIV-lock probe) so parallel
  loads don't dump the target landscape.
- **Cluster-table-aware extraction** that refuses unsafe BSEG/RFBLG/PCL1 reads
  before they dump the source.
- **HMAC-signed cutover gate** with explicit precedence rule: SAP-standard
  spool reports outrank the tool's ledger; the tool can confirm GO but cannot
  override a NO_GO.

### What it is NOT

- **NOT a Brownfield in-place conversion.** It does not run, wrap, or bypass
  SUM / DMO / Maintenance Planner.
- **NOT a replacement for LTMC field-mapping UI.** It provides a programmatic
  `transformation_engine` with rule schema and DQ gates, but no business-user
  authoring UI.
- **NOT a turnkey customer product.** Framework-complete and self-tested; real
  customer engagements need landscape-specific content (BAPI field catalogs
  per release, cluster table catalog per release, CVI fuzzy-match rules per
  locale, DAG additions per industry).
- **NOT proven in customer production.** Live-tested on a single
  IDES-class ECC + SAP CAL S/4HANA appliance, modest volume.

### What lane Migrate4HANA plays in

The same lane as the **S/4HANA Migration Cockpit** (data load) with
substantially more automation wrapped around the load. In 2026 SAP shipped
Staging Tables for Direct Transfer in MC, which closes part of the
*extraction* gap we previously claimed. Our differentiator is now sharper and
narrower:

| What MC Direct Transfer does well | What we add that MC does not |
|---|---|
| Extraction via RFC | Auto-discovery of target config |
| Intermediate staging in HANA | Cross-run idempotent ledger with hash-chained audit |
| In-place data correction UI | Aggregate value-reconciliation with hard GO/NO-GO verdict |
| Native LTMC error handling | Governed cutover gate with HMAC-signed approval webhook |
|  | Selective carve-out ABAP generator |
|  | CVI / DAG / BAPI-coverage / cluster-aware preflight |

---

## 2. Architecture overview

```
                    ┌───────────────────────────────────────────────┐
                    │  AWS Step Functions (lift_and_shift state mc) │
                    │  + 4 waitForTaskToken human gates             │
                    └──────────────────┬────────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  Lambda (37 fns) │         │  ECS Fargate     │         │  EventBridge cron│
│  short-running   │         │  heavy compute   │         │  daily code-delta│
│  (≤15 min)       │◄────────┤  (Stages 1,5,12,│         │  TADIR snapshot  │
│                  │ dispatch│   12A; >15 min) │         │                  │
└────────┬─────────┘         └──────────────────┘         └──────────────────┘
         │
         │ uses
         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  lambda/utils/                                                              │
│  ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐│
│  │unified_loader│  │bapi_loader│ │bp_odata    │ │idoc_loader │ │key_map   ││
│  │ (dispatcher)│  │ (per-obj  │ │ (BP        │ │ (IDoc fall-│ │ (cross-  ││
│  │             │ │  BAPI calls)│ │  OData)   │ │  back lane)│ │  run     ││
│  └─────────────┘ └────────────┘ └────────────┘ └────────────┘ │  ledger) ││
│  ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ └──────────┘│
│  │reconciler   │ │transformation│ │bapi_coverage│ │cvi_mapper │            │
│  │ + HashChain │ │_engine + DQ │ │ +catalog  │ │ +xref/cycle│            │
│  │ + spool_cap │ │  gates      │ │  (25 objs)│ │  detection │            │
│  └─────────────┘ └────────────┘ └────────────┘ └────────────┘            │
│  ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐            │
│  │dependency_  │ │scaling +    │ │sap_workload│ │cluster_    │            │
│  │  dag +      │ │ ComputeDisp.│ │ throttle   │ │  table_    │            │
│  │ KeyResolver │ │  +ODataPager│ │ +backoff   │ │  awareness │            │
│  └─────────────┘ └────────────┘ └────────────┘ └────────────┘            │
│  ┌─────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐            │
│  │governance   │ │config_      │ │compliance  │ │code_delta  │            │
│  │  (HMAC gate)│ │  discovery  │ │            │ │            │            │
│  └─────────────┘ └────────────┘ └────────────┘ └────────────┘            │
└────────────────────────────────────────────────────────────────────────────┘
         │                                              │
         │ writes                                       │ reads
         ▼                                              ▼
┌────────────────────────┐                  ┌────────────────────────┐
│  DynamoDB              │                  │  Secrets Manager       │
│   ├ key-map (idemp.)   │                  │   ├ sap-credentials    │
│   ├ run_events ledger  │                  │   ├ s4hana-credentials │
│   ├ audit_ledger       │                  │   ├ gate-secret (HMAC) │
│   ├ recon_tolerance    │                  │   └ anthropic-api-key  │
│   ├ gates (TaskToken)  │                  └────────────────────────┘
│   └ mc-compat matrix   │
└────────────────────────┘
         │
         │ persisted via
         ▼
┌────────────────────────┐                  ┌────────────────────────┐
│  S3                    │                  │  KMS                   │
│   ├ staging bucket     │ encrypts (CMK)   │   alias/migrate4hana-* │
│   ├ evidence_app       │◄─────────────────┤   (rotated)            │
│   ├ audit-logs (WORM   │                  └────────────────────────┘
│   │   intentionally    │
│   │   off for testing) │
│   └ mapping matrix     │
└────────────────────────┘
                                                       │
                                                       │ alerts
                                                       ▼
                                            ┌────────────────────────┐
                                            │  SNS + email           │
                                            │   ├ alerts             │
                                            │   └ spine_gates (HMAC) │
                                            └────────────────────────┘
```

**External egress paths**:
- **NAT Gateway** → `api.anthropic.com` (TLS) for Claude code-remediation
  fallback. Pseudonymizer masks PII before egress. *Bedrock is not used on
  this account; see §18 + §23.*
- **NAT Gateway** → SAP Note RSS / SAP support APIs (informational only).

**Inbound paths**:
- API Gateway → WebSocket Lambda for real-time telemetry to the frontend.
- API Gateway → `/api/spine/approve` webhook (HMAC-signed) for the manual
  gates.

---

## 3. Honest bottom line

Migrate4HANA is a genuinely strong, support-clean, architecturally-
differentiated ECC→S/4 *data migration orchestration + reconciliation* engine.
It is **TRL ~6** on the data spine, **TRL ~5** on the embedded competitor-
parity layers, **deployable** end-to-end on AWS (apply→destroy idempotent at
200 resources), and **POC-ready** for a contained client engagement.

It is **NOT yet** a faithful, full-scope, mapping-complete, volume-proven,
pilot-validated migration product. The largest remaining work is exactly the
part real projects spend the most on: business mapping content,
landscape-specific BAPI / cluster-table / DAG addenda, and a live customer
pilot. The engineering is in place; the content + customer validation are not.

For an external reviewer, the recommended frame is: *"orchestration spine
with embedded SAP-functional-aware safety nets, ready to be filled with
customer-specific content during a paid engagement."*

---

## 4. AWS infrastructure inventory

Defined in `terraform/environments/prod/main.tf` (783 lines) and the modules
under `terraform/modules/`. 200 resources currently apply cleanly; full
end-to-end destroy is also clean.

### Modules

| Module | Path | What it provisions | Notes |
|---|---|---|---|
| **vpc** | `terraform/modules/vpc/` | VPC, public + private subnets, NAT, IGW, route tables | 3 AZs |
| **vpc-endpoints** | `terraform/modules/vpc-endpoints/` | (empty after Bedrock removal) | Bedrock PrivateLink endpoints intentionally removed (no account access); module shell kept |
| **s3-staging** | `terraform/modules/s3-staging/` | Migration staging bucket (versioned, KMS-encrypted, BPA) | |
| **lambda** | `terraform/modules/lambda/` | 37 Lambda functions in a `for_each` map | Shared IAM role, optional layers, env vars wired per pillar |
| **ecs** | `terraform/modules/ecs/` | ECS cluster + Fargate task def + ECR repo | Image push is manual via `scripts/push-fargate-image.ps1` |
| **step-functions** | `terraform/modules/step-functions/` | 2 state machines: `pipeline` (legacy 9-phase) + `lift_and_shift` (current) | 4 `waitForTaskToken` gates in lift-and-shift |
| **dynamodb** | `terraform/modules/dynamodb/` | Rules + state tables for the dispatcher | |
| **evidence-ledger** | `terraform/modules/evidence-ledger/` | KMS CMK + evidence S3 bucket + 3 ledger tables (run_events, recon_tolerance, mc_compat) | **Object Lock WORM intentionally off** for the test cycle; see §19 |
| **audit** | `terraform/modules/audit/` | CloudTrail + audit-logs bucket (Object Lock GOVERNANCE 2555d) + CW metric filters + alarms | SOX-compliance posture |
| **waf** | `terraform/modules/waf/` | WAFv2 WebACL (rate limit + AWS managed rule groups + IP reputation) | |
| **cloudwatch** | `terraform/modules/cloudwatch/` | Dashboard + SNS alerts + alarms | Region threaded into all 4 dashboard widgets |
| **target-system** | `terraform/modules/target-system/` | Target S/4HANA-side networking + SG + gates table | |
| **websocket-telemetry** | `terraform/modules/websocket-telemetry/` | API Gateway WebSocket + connections table for real-time UI updates | |
| **airgapped-llm** | `terraform/modules/airgapped-llm/` | Optional GPU EC2 + Ollama for on-prem LLM | **Off by default** (`enable_airgapped_llm=false`) |
| **dms** | `terraform/modules/dms/` | (currently excluded — DMS doesn't support `saphana` engine) | Module preserved for future use |
| **entity-resolution** | `terraform/modules/entity-resolution/` | (currently excluded — `aws_entityresolution_*` not in hashicorp/aws provider) | Module preserved; deterministic BP dedup runs in data-hygiene regardless |

### Top-level resources outside modules

Defined directly in `terraform/environments/prod/main.tf`:

- 4 Secrets Manager secrets (sap-credentials, s4hana-credentials, gate-secret,
  anthropic-api-key) — all with `recovery_window_in_days = 0` for clean destroy.
- 4 DynamoDB tables: `gates` (TaskToken store), `audit_ledger` (Pillar 4 hash
  chain), `key_map` (cross-run keymap), 1 reserved.
- 1 S3 bucket: `migrate4hana-evidence-prod-<account>` (tool-facing evidence,
  fixed name per 2026-05-30 directive).
- 1 SNS topic + email subscription for `spine_gates`.
- 1 random_password resource for the HMAC gate secret.
- EventBridge daily cron + Lambda permission for the code-delta-scheduler.

### Variables (`terraform/environments/prod/variables.tf`)

Key inputs the operator may override:

| Variable | Default | Purpose |
|---|---|---|
| `aws_region` | `us-east-1` | |
| `environment` | `prod` | |
| `vpc_cidr` | `10.50.0.0/16` | |
| `alert_email` | (required) | SNS subscription |
| `transform_rules` | `""` | Path/URI to transformation engine ruleset (no-op when empty) |
| `bedrock_model_id` | (removed) | Bedrock cleanup complete |
| `anthropic_api_key` | `""` (sensitive) | Loaded into Secrets Manager if non-empty |
| `anthropic_model_id` | `claude-sonnet-4-6` | Default Claude model |
| `anthropic_escalation_model` | `claude-opus-4-7` | Retry escalation |
| `ast_change_threshold` | `3` | Below this, GenAI escalation kicks in |
| `enable_airgapped_llm` | `false` | Provision GPU EC2 + Ollama |
| `waf_rate_limit` | `1000` | Per-5-min per-IP |
| `ecc_db_host` / etc. | `""` | Reserved for future DMS path |

---

## 5. Repository layout

```
migrate4hanav2/
├── lambda/
│   ├── utils/                 ← 33 shared modules (the actual engine)
│   ├── data-migrator/         ← the main extract + load + reconcile handler
│   ├── code-analyzer/         ← ABAP AST engine + Claude fallback (the SmartShift lane)
│   ├── code-delta-scheduler/  ← daily TADIR snapshot via EventBridge
│   ├── data-hygiene/          ← the Syniti lane (FK + self-heal + ledger)
│   ├── evidence-collector/    ← run-end evidence pack assembly
│   ├── manual-gate/           ← waitForTaskToken handler
│   ├── reconciliation-engine/ ← async recon worker
│   ├── transport-*/           ← 4 fns for code transport into S/4
│   ├── migration-cockpit-orchestrator/  ← LTMC lane orchestrator
│   ├── ltmom-orchestrator/    ← LTMOM lane
│   ├── idoc-orchestrator/     ← IDoc lane
│   ├── cutover-orchestrator/  ← runs the cutover runbook
│   ├── readiness-check/       ← SAP Readiness Check fetch + analyse
│   ├── simplification-check/  ← S/4HANA Simplification DB analyser
│   ├── basis-validator/       ← Basis-layer health checks
│   ├── sizing-advisor/        ← target sizing inputs
│   ├── object-router/         ← per-object dispatch (BAPI/OData/MC/IDoc)
│   ├── target-provisioner/    ← target landscape config probes
│   ├── role-provisioner/      ← target role + auth setup
│   ├── role-migrator/         ← role migration
│   ├── config-replicator/     ← config snapshot + reapply
│   ├── config-applier/        ← config push
│   ├── bc-set-builder/        ← BC-set artifact build
│   ├── delta-extractor/       ← CDC delta extract
│   ├── data-loader/           ← (deprecated alias)
│   ├── discovery-engine/      ← (planned; currently a stub)
│   ├── integration-mapper/    ← integration topology
│   ├── integration-activator/ ← post-cutover integration activation
│   ├── migration-validator/   ← post-load validator
│   ├── migration-completeness-analyzer/  ← (planned; currently a stub)
│   ├── process-miner/         ← optional process-mining input
│   ├── rollback-manager/      ← rollback via BAPI_ACC_DOCUMENT_REVERSE etc.
│   ├── code-deployer/         ← deployer for the remediated code
│   ├── test-generator/        ← test fixture generator
│   ├── ws-handler/            ← WebSocket telemetry handler
│   └── _deprecated/           ← legacy handlers kept for ref
│
├── pipeline_spine_master.py   ← 4-phase orchestrator (Natuvion / Syniti / SmartShift / Governance)
├── data_spine_orchestrator.py ← the Syniti-class data spine
├── run_local_pipeline.py      ← local-only runner (no AWS)
├── run_local_lift_and_shift.py← local lift-and-shift runner
├── audit_pipeline.py          ← run-end audit pack
├── api_server.py              ← FastAPI for /api/spine/* webhooks + UI backend
├── pdf_report_generator.py    ← unicode-safe report writer
├── multi_volume_report_generator.py
├── local_aws_shim.py          ← in-memory AWS service stubs for offline self-test
├── cutover.py                 ← cutover orchestration helpers
│
├── agent/
│   └── in_system_agent_generator.py  ← Natuvion-class carve-out ABAP generator
│
├── terraform/                  ← AWS infrastructure (see §4)
├── ecs/                        ← Fargate Dockerfile + entrypoint
├── layer-build/                ← pyrfc Lambda layer build scripts
├── scripts/                    ← PowerShell ops (push-fargate-image.ps1, etc.)
├── frontend/                   ← React UI (light fluidic theme, real-backend-driven)
├── docs/                       ← architecture docs
├── tests/                      ← test fixtures + integration helpers
│
└── (root-level docs)
    EXPERT_REVIEW_BRIEF.md          ← executive brief
    EXPERT_REVIEW_DETAILED.md       ← this document
    AUDIT_REPORT.md                 ← compliance audit narrative
    BATTLETEST.md                   ← stress + chaos report
    BREADTH_TRACKER.md              ← per-object live-proof tracker
    CAPABILITY_DOSSIER.md           ← capability narrative
    HOW-TO-RUN.md                   ← non-SAP-user runbook
    LIFT-AND-SHIFT-RUNBOOK.md       ← lift-and-shift runbook
    LIFT-AND-SHIFT-SETUP.md         ← landscape setup
    MIGRATE4HANAv2.md                ← v2 design notes
    PROJECT_STATUS.md                ← current status board
    PRODUCTION_READINESS_GUIDE.md    ← prod-readiness checklist
    ABAPGIT_SETUP.md                ← code import via abapgit
```

**File counts**: 151 Python files (excluding caches), 29 Terraform files
(excluding `.terraform/`).

---

## 6. Migration object catalog

Defined in `lambda/data-migrator/handler.py:DEFAULT_OBJECT_TABLES` (line 233).
The catalog covers **127 object types**. Distribution by lane:

| Lane | Count | Mechanism |
|---|---|---|
| **BAPI + OData (`unified_loader` direct lane)** | 25 | Released BAPI per object + API_BUSINESS_PARTNER OData for BP-led partners |
| **MC / LTMC staging emit** | 87 | Extract from ECC → emit Migration-Cockpit-shaped CSV; **actual import is operator-driven** in MC |
| **IDoc lane** | 15 | Standard IDoc messages (MATMAS, DEBMAS, KREDMAS, etc.) |

### The 25 loaded+reconciled objects

```
BusinessPartner, Customer, Vendor          (OData API_BUSINESS_PARTNER + RFC fallback)
Material, ExchangeRates                    (BAPI_MATERIAL_SAVEDATA / BAPI_EXCHANGERATE)
OpenPO, OpenAR, OpenAP                     (BAPI_PO_CREATE1 / BAPI_ACC_DOCUMENT_POST)
CostCenter, ProfitCenter                   (BAPI_COSTCENTER_CREATEMULTIPLE / BAPI_PROFITCENTER_CREATE)
CostElementGroup, ProfitCenterGroup        (BAPI_SET_CREATE family)
FixedAsset                                 (BAPI_FIXEDASSET_OVRTAKE_CREATE)
Bank                                       (BAPI_BANK_CREATE)
InternalOrder                              (BAPI_INTERNALORDER_CREATEMULTIPLE)
Equipment, FunctionalLocation              (BAPI_EQUI_CREATE / BAPI_FUNCLOC_CREATE)
Characteristic, Class                      (BAPI_CHARACT_CREATE / BAPI_CLASS_CREATE)
Project, WBS                               (BAPI_PROJECT_MAINTAIN)
PurchaseRequisition                        (BAPI_REQUISITION_CREATE)
PurchaseContract                           (BAPI_CONTRACT_CREATE)
SalesOrder                                 (BAPI_SALESORDER_CREATEFROMDAT2)
Batch                                      (BAPI_BATCH_CREATE)
InventoryBalance                           (BAPI_GOODSMVT_CREATE mvmt 561)
```

### Per-object BAPI field catalog

`lambda/utils/bapi_field_catalog.py` ships a hand-curated catalog of the
released-BAPI field set per object type. Used by `bapi_coverage` to detect
fields the BAPI cannot transport (CI_*, ZZ_*, J_1B*) and route them to LTMC
staging instead of silently dropping them.

**Current coverage**: 25 objects, 6-50 fields each (e.g. Customer: 50 fields,
FixedAsset: 28). Per-landscape addendum via `M4H_BAPI_FIELD_CATALOG_JSON` env
var. Authoritative source for a real project would be `DD_BAPI_PARAMETER_GET`
introspection against the target landscape.

---

## 7. The pipeline spine

`pipeline_spine_master.py` (584 lines) — the 4-phase orchestrator that runs
in any environment (local or AWS). Public entry: `MigrationSpineMaster().run(payload)`.

### Phase 1 — Natuvion (carve-out)

`_phase_natuvion()`. Generates org/time-filtered selective-transition ABAP
programs via `agent/in_system_agent_generator.py` for tables in
`payload["scope"]["carve_out"]`. With a live source connection, also deploys
and runs them.

**Key features:**
- Per-table elastic compute decision via `ComputeDispatcher`: if `est_rows >
  threshold`, route to Fargate; else inline/Lambda. Result includes
  `fargate_routed` count.
- **Target-side workload throttle** (Gemini gap #2): when `payload["_live_target_conn"]`
  is provided, builds a `WorkloadThrottle` bound to the target and passes it
  to the `ComputeDispatcher`. The dispatcher then probes TH_WPINFO + NRIV
  before launching each Fargate task; **exponential backoff** (Gemini follow-up
  #3) keeps polling costs bounded during sustained target congestion.

### Phase 2 — Syniti (data spine)

`_phase_syniti()`. Per object in `scope.entity_trees`:
- Run `DataSpineOrchestrator.process_tree(obj, tables)` from
  `data_spine_orchestrator.py`.
- FK-integrity check (BUT000/020/100 family), deterministic self-heal vs
  target reference data, SHA-256 idempotency ledger, orphan quarantine.

**Wired:**
- **DAG ordering** (Gemini gap #8): the requested `entity_trees` list is
  topologically sorted via `DependencyDAG.from_defaults()` so masters
  (Material, GLAccount, CostCenter, BusinessPartner) complete before
  transactionals (SalesOrder, OpenAR/AP). Per-object status
  (running/done/failed) tracked in `ExecutionState`; the phase summary
  carries a `dag_state` block with execution order, status, and a
  `downstream_blocked_by_failure` map.

### Phase 3 — SmartShift (code remediation)

`_phase_smartshift()`. Per ABAP program in `scope.code_objects`:
- Run the 6,400-line deterministic AST engine first
  (`lambda/code-analyzer/abap_ast_engine`).
- On parser crash or residual parse errors, escalate that program (only the
  localised fragment) to `llm_fallback_router.FallbackRouter`.
- The fallback router masks PII via `pseudonymize.Pseudonymizer`, calls Claude
  via `anthropic_client.invoke_claude()` (default `claude-sonnet-4-6`, retry
  escalates to `claude-opus-4-7`), restores PII byte-for-byte, runs a
  **mock-ATC** validator, and emits a transport `.data/.cofile` or quarantines.

### Phase 4 — Governance / ATC

`_phase_governance()`. Run the mock ATC validator + the UI progress tracker;
emit a final attestation; pass/fail per-program verdict.

### Per-phase invariants

- **Throttling**: every phase runs through `RFCThrottle` (anti-DoS rate
  limiter on the source RFC connection).
- **Progress tracking**: `ProgressTracker(run_dir, source, target)` writes
  state.json on every phase transition; the UI subscribes via WebSocket.
- **Atomic failure isolation**: `_guarded()` wrapper catches per-phase
  exceptions, records the failure in `state.phases[name]`, and lets the
  spine continue with the dependent phases skipped.

---

## 8. Step Functions state machine

`terraform/modules/step-functions/lift_and_shift_pipeline.asl.json`.

### Tasks (26 referenced Lambda handlers)

```
DiscoveryEngine  → SizingAdvisor → ObjectRouter → TargetProvisioner →
BasisValidator   → CodeAnalyzer  → TransportArtifactBuilder →
TransportFilePlacer → TransportImportExecutor → TransportImportVerifier →
ConfigReplicator → BCSetBuilder → DataMigrator → DataHygiene →
MigrationCockpitOrchestrator → LTMOMOrchestrator → IDocOrchestrator →
MigrationValidator → TestGenerator → MigrationCompletenessAnalyzer →
CutoverOrchestrator → DeltaExtractor → IntegrationActivator →
PdfReportGenerator → RollbackManager → ManualGateLambda
```

### 4 waitForTaskToken human gates

`arn:aws:states:::lambda:invoke.waitForTaskToken` at lines 43, 201, 240, 282
of the ASL — covering **ASSESS**, **DATA-PREP**, **VALIDATE**, and
**CUTOVER**. Each gate:
- Persists `taskToken` to `migrate4hana-gates-prod` DynamoDB.
- Sends an SNS notification with the full state payload to `spine_gates` topic.
- Blocks state-machine execution until `/api/spine/approve` is called with a
  matching HMAC-signed token.

### Lambda fallback resolution

Several ASL placeholders reference Lambdas not yet built (`discovery-engine`,
`migration-completeness-analyzer`, `pdf_report_generator`). The
`step-functions/main.tf:locals.ls_arns` block resolves each via:

```hcl
lookup(var.lambda_arns, "<name>", local.ls_fallback_arn)
```

Where `ls_fallback_arn` is the `manual-gate` ARN. **Result**: the state
machine validates and starts cleanly; tasks pointing at unbuilt Lambdas
no-op via the manual-gate handler (which returns success without any work).
Each placeholder needs its own handler before end-to-end execution against a
real source/target.

---

## 9. Lambda inventory

37 functions in the prod stack. Sized by `memory` + `timeout` in
`terraform/environments/prod/main.tf:lambda_functions` map.

### Production functions (deployed)

| Function | Memory | Timeout | Purpose | Status |
|---|---|---|---|---|
| `data-migrator` | 3008 | 15min | The main extract+load+reconcile orchestrator | Production-grade; ~1040 LOC |
| `data-hygiene` | 2048 | 15min | Syniti-class FK + self-heal | Wired into spine |
| `code-analyzer` | 2048 | 15min | AST + Claude fallback (formerly `bedrock-llm-router`) | Production-grade; pyrfc + anthropic_client |
| `evidence-collector` | 1024 | 5min | Run-end evidence pack assembly | Production-grade |
| `manual-gate` | 1024 | 5min | waitForTaskToken handler + DynamoDB persist | Production-grade |
| `reconciliation-engine` | 2048 | 15min | Async recon worker | Production-grade |
| `object-router` | 1024 | 5min | Per-object lane dispatch | Production-grade |
| `target-provisioner` | 2048 | 10min | Target landscape config probes | Production-grade |
| `migration-cockpit-orchestrator` | 2048 | 15min | LTMC lane orchestrator | Production-grade |
| `ltmom-orchestrator` | 2048 | 15min | LTMOM lane | Production-grade |
| `idoc-orchestrator` | 2048 | 15min | IDoc lane | Production-grade |
| `cutover-orchestrator` | 2048 | 15min | Cutover runbook | Production-grade |
| `delta-extractor` | 1024 | 10min | CDC delta extract | Production-grade |
| `readiness-check` | 3008 | 15min | SAP Readiness Check fetch + analyse | Production-grade |
| `simplification-check` | 2048 | 15min | S/4HANA Simplification DB analyser | Production-grade |
| `basis-validator` | 1024 | 5min | Basis health checks | Production-grade |
| `sizing-advisor` | 1024 | 5min | Target sizing inputs | Production-grade |
| `migration-validator` | 2048 | 15min | Post-load validator | Production-grade |
| `transport-artifact-builder` | 1024 | 5min | Build R+K cofiles | Production-grade |
| `transport-file-placer` | 1024 | 5min | Place cofiles into /usr/sap/trans | Production-grade |
| `transport-import-executor` | 1024 | 5min | tp import wrapper | Production-grade |
| `transport-import-verifier` | 1024 | 5min | tp post-import check | Production-grade |
| `config-replicator` | 1024 | 5min | Config snapshot+reapply | Production-grade |
| `config-applier` | 1024 | 5min | Config push | Production-grade |
| `bc-set-builder` | 1024 | 5min | BC-set artifact build | Production-grade |
| `process-miner` | 1024 | 5min | Process-mining input | Production-grade |
| `integration-mapper` | 1024 | 5min | Integration topology | Production-grade |
| `integration-activator` | 1024 | 5min | Post-cutover activation | Production-grade |
| `role-provisioner` | 1024 | 5min | Target role + auth setup | Production-grade |
| `role-migrator` | 1024 | 5min | Role migration | Production-grade |
| `rollback-manager` | 2048 | 10min | Rollback via reverse BAPIs | Production-grade |
| `test-generator` | 1024 | 5min | Test fixture generator | Production-grade |
| `code-deployer` | 1024 | 5min | Deploy remediated code | Production-grade |
| `code-delta-scheduler` | 1024 | 15min | **NEW**: daily TADIR snapshot + delta detection | Wired to EventBridge |
| `ws-handler` | 1024 | 5min | WebSocket telemetry | Production-grade |

### Referenced but NOT yet built (resolve to manual-gate fallback)

- `discovery-engine` — Stage 1 auto-discovery; today the `target-provisioner`
  partially covers this role.
- `migration-completeness-analyzer` — post-load completeness scoring.
- `pdf_report_generator` (as a separate Lambda) — `pdf_report_generator.py`
  exists as a module but is not wrapped as its own Lambda.

---

## 10. Shared modules

`lambda/utils/` — 33 modules. Listed in functional groups.

### Loading + dispatch

| Module | Purpose |
|---|---|
| `unified_loader.py` (659 LOC) | The dispatcher: `OBJECT_MECHANISM` (object → BAPI/OData/IDoc), `_load_one` branches, serial + pooled-parallel paths. Hosts `transformer`, `bapi_coverage_emitter`, `bapi_field_catalog`. |
| `bapi_loader.py` (1644 LOC) | One `create_<object>` per object type; discovery/validation/remap logic. **The file to scrutinise for SAP correctness.** |
| `bp_odata.py` | API_BUSINESS_PARTNER client (BP/Customer/Supplier OData create). |
| `idoc_loader.py` | IDoc fallback lane. |
| `meta_recipe.py` | Field-name and value resolution against discovered metadata. |
| `object_router` (in lambda dir) | Per-object lane decision. |

### Trust spine

| Module | Purpose |
|---|---|
| `key_map.py` | Cross-run idempotent ledger keyed by `(object, source_key)`. Includes thread-safe `TokenBucket` for DynamoDB write-capacity isolation (Pillar 1.3). |
| `reconciler.py` (685 LOC) | `Reconciler` (existence + value), `AggregateReconciler` (count + total + debit/credit tie-out), `HashChainLedger` (SHA-256 chain), `EvidencePack` (manifest + WORM-capable upload + `cutover_verdict` with precedence rule). |
| `config_discovery.py` | Landscape-agnostic target config probes (company code, sales area, plants, recon accounts, charts, order types, etc.). Probe-validated. |
| `compliance.py` | Per-run support-compliance attestation. |
| `governance.py` | `GateController` (HMAC-signed, file-backed, cross-process, no-double-pass) + schema-validated SNS alert payloads. |

### SAP-functional safety nets (Gemini gap closures)

| Module | Purpose | Gap closed |
|---|---|---|
| `cvi_mapper.py` (385 LOC) | KNA1/LFA1 → BUT000 unification: overlap detect, duplicate fold, conflict quarantine; `unify_with_xrefs()` adds two-phase resolution + cycle detection | #1 + follow-up #2 |
| `sap_workload.py` (267 LOC) | TH_WPINFO + NRIV-lock probe; `WorkloadThrottle.decide()` returns GREEN/YELLOW/RED with exponential backoff | #2 + follow-up #3 |
| `bapi_coverage.py` (270 LOC) | Field-coverage analysis vs `bapi_field_catalog`; routes to BAPI / BAPI+LTMC / LTMC-only | #3 |
| `bapi_field_catalog.py` (340 LOC) | Hand-curated released-BAPI field set per object; 25 objects, 6-50 fields each; env-override addendum | #3 |
| `spool_capture.py` (252 LOC) | JOB_OPEN → SUBMIT → CLOSE → poll → RSPO_RETURN_ABAP_SPOOLJOB → SHA-256 seal | #4 |
| `code_delta.py` (313 LOC) | TADIR/REPOSRC snapshot + diff + idempotent remediation queue | #5 |
| `transformation_engine.py` (475 LOC) | Rule schema (FIELD_MAP / VALUE_MAP / REGEX / CONST / TRIM / UPPER / PAD), DQ gates (MANDATORY / REGEX_VALID / MAX_LEN / ALLOWED / UNIQUE / **CROSS_FIELD_VALIDATE**), thread-safe UNIQUE state | Pillar 2 / #6 |
| `cluster_table_awareness.py` (200 LOC) | Pool/cluster table preflight; rewrites BSEG via BKPF 2-stage; refuses unsafe full-cluster scans | #7 |
| `dependency_dag.py` (273 LOC) | 28-node default DAG, topo sort, scope subset, failure propagation, `KeyResolver` for cross-object key lookup | #8 |

### Code-analyzer pipeline

| Module | Purpose |
|---|---|
| `anthropic_client.py` (in `lambda/code-analyzer/`) | stdlib urllib + Secrets Manager fetch + module-level caching for Anthropic API key. Returns None on failure (never raises). |
| `llm_fallback_router.py` (in `lambda/code-analyzer/`) | Deterministic-first AST + AI-fallback loop + mock ATC + transport packaging |
| `genai_router.py` (in `lambda/code-analyzer/`) | Backbone for AST → GenAI escalation routing |
| `bedrock_genai_engine.py` (in `lambda/code-analyzer/`) | Legacy filename; now routes through Anthropic API |
| `pseudonymize.py` (in `lambda/code-analyzer/`) | Reversible PII masking for outbound Claude prompts |
| `abap_ast_engine.py` (in `lambda/code-analyzer/`) | 6,400-line deterministic ABAP AST processor |

### Infrastructure helpers

| Module | Purpose |
|---|---|
| `scaling.py` (267 LOC) | `ComputeDispatcher` (Lambda/Fargate decision + ECS run_task) + `ODataPager` (`$top`/`$skiptoken`); now accepts `workload_throttle` |
| `rfc_pool.py` | pyrfc connection pool (releases GIL for parallel BAPI calls) |
| `logger.py` | Structured logger (JSON output for CloudWatch) |
| `sap_host_runner.py` | Run jobs on the SAP host via released wrappers |
| `sap_job_monitor.py` | Background job polling |
| `sap_log_collector.py` | Application-log harvester |
| `sap_number.py` | Number-range BAPI helpers |
| `sap_fields.py` | SAP field-name normalisation |
| `sap_prereq_checks.py` | Pre-flight checks against the source |
| `currency_config.py` | Currency-pair resolution |
| `odata_client.py` | OData client base |
| `validation.py` | Generic validators |
| `rule_router.py` | Routing rules for per-object DAG |

---

## 11. Live-proof matrix

Honest accounting of what's been exercised on real SAP systems vs what's
unit-tested-only. Live test environment: IDES-class ECC (SID Y01) + SAP CAL
S/4HANA appliance.

### Live-proven (real ECC + real S/4HANA APIs, real reconciliation)

| Capability | Where | Sample size | Notes |
|---|---|---|---|
| BAPI / OData load of 25 object types | `unified_loader._load_one` | Typically 5 records/object | Includes RECONCILED verdict, 0 missing |
| Auto-discovery of target config | `config_discovery.discover` | Each run on the live pair | Probe-validated (e.g. rolled-back test PO to confirm expense account) |
| Cross-run idempotency | `key_map.KeyMap` | Re-runs reused records, 0 duplicates | |
| Delta / CDC extract | `data-migrator/handler._cdc_delta` | Change-document-driven | Not just new-records |
| Value reconciliation | `reconciler.Reconciler` | FI amounts, factor-aware exchange rates | Caught a real MATNR collision |
| Parallel load via pyrfc pool | `rfc_pool.RFCPool` | ~936 FI documents in ~100s | All 936 reconciled |
| TESTRUN-validate-and-fallback | `bapi_loader.create_*` | Asset class, order type, contract-capable vendor | Per-object discovery+probe |
| Self-healing | Per-object handlers | Currency norm (DEM→target), MM posting-period auto-detection | |
| Cutover runbook | `cutover.py` | 1 dry-run | initial load → delta → reconcile → GO/NO-GO |
| Support-compliance attestation | `compliance.audit` | Every run | Machine-checkable JSON |

### Unit-tested + integrated (offline; not yet live-volume-proven)

| Capability | Module | Verified | Owed |
|---|---|---|---|
| CVI two-phase unification | `cvi_mapper.unify_with_xrefs` | 4-row test pair: cycle detected, 1 unresolved out-of-batch xref, deterministic re-run | Run against real customer KNA1/LFA1 at volume |
| Target-side TH_WPINFO/NRIV throttle | `sap_workload.WorkloadThrottle` | RED→GREEN exp backoff with streak reset | Live target landscape under sustained load |
| BAPI field coverage + LTMC routing | `bapi_coverage.decide_load_path` | 4 cases pass (BAPI / +LTMC delta / LTMC-only / staging emit) | Per-landscape BAPI catalog from `DD_BAPI_PARAMETER_GET` |
| FAGLB03 / MB5B spool capture | `spool_capture.SpoolCapture` | Full job lifecycle + SHA-256 seal into chain | Live target run with real `RSPO_RETURN_ABAP_SPOOLJOB` |
| Dual-maintenance code-delta | `code_delta.DeltaEngine` | Snapshot diff: ADDED/MODIFIED/DELETED detected; idempotent queue | Live TADIR snapshot at scale, real source-hash deep diff |
| Cross-field DQ | `transformation_engine.CROSS_FIELD_VALIDATE` | Conditional triggers, prefix/in/cmp ops, construction validation | DQ scorecards over time |
| Cluster-table aware extraction | `cluster_table_awareness.preflight` | 4 cases: transparent/cluster-keys/cluster-rewritten/PCL1-refused | Live BSEG extraction on customer non-HANA ECC |
| DAG dependency resolver + KeyResolver | `dependency_dag` | 28-node default, cycle detection, failure propagation, key resolve | Per-customer DAG additions, live cutover |
| Hash chain + tamper detection | `reconciler.HashChainLedger` | Detects single-block tamper | Live audit-window verification |
| Cutover precedence rule | `EvidencePack.cutover_verdict` | 5 cases: GO / NO_GO (missing spool / LTMC pending / variance-overrides-tool-RECONCILED) / GO_WITH_WARNINGS | Real auditor sign-off |
| AWS apply/destroy idempotency | `terraform/environments/prod/` | 200 resources, full cycle clean | (no live ECC connectivity yet — that's the next milestone) |

### Caveats a reviewer must weigh

- The live test environment is **non-production, non-customer data**, on a
  **single best-practice appliance**, at **small per-object sample sizes**
  (typically 5 records/object).
- It has **not** been run against a second landscape or customer-shaped data.
- The team's SAP functional/Basis depth is **engineering-led, not
  consultant-led** — please flag any non-idiomatic SAP usage you spot.

---

## 12. Data flow walkthrough

A single object load (e.g. `Customer`) walks this path:

```
1. data-migrator handler invoked (Step Functions / EventBridge / manual)
   │
2. _process_one_object():
   ├─ delta_watermark check (CDC mode)
   ├─ _read_table(KNA1, fields, where):
   │   ├─ cluster_table_awareness.preflight()  ← refuse NO_GO, cap PACKAGE SIZE
   │   ├─ RFC_READ_TABLE call
   │   └─ row dicts
   ├─ if Customer + Vendor both extracted in this batch:
   │   └─ cvi_mapper.unify_with_xrefs()  ← compute BP map + two-phase plan
   │
3. UnifiedLoader.load_records(obj, rows):
   ├─ Pool of parallel workers (pyrfc connections per worker)
   ├─ Each worker -> _load_one(obj, mech, row):
   │   ├─ transformation_engine.apply(obj, row)  ← rules + DQ gates
   │   │   └─ if DQ fail -> "DATA_QUALITY_REJECTION" -> dead-letter
   │   ├─ bapi_coverage.analyze_coverage() + decide_load_path()
   │   │   ├─ LTMC_ONLY -> LtmcStagingEmitter.emit() -> ltmc_handoff -> dead-letter
   │   │   ├─ BAPI_PLUS_LTMC_DELTA -> emit delta, continue to BAPI
   │   │   └─ BAPI -> continue
   │   ├─ key_map.lookup(obj, src_key)  ← already loaded? skip (idempotency)
   │   └─ bapi_loader.create_<obj>(...) or bp_odata.create_*(...)
   │       └─ TokenBucket gate on key_map writes
   │
4. Reconciler.reconcile(obj, created_keys):
   ├─ Read back via RFC_READ_TABLE / API_BUSINESS_PARTNER GET
   ├─ Existence check + value tie-out
   └─ RECONCILED | DISCREPANCY verdict
   │
5. Run-end:
   ├─ HashChainLedger blocks: data_load, key_map, reconciliation,
   │                          ltmc_pending (one per handoff), carve_out
   ├─ EvidencePack.build_manifest(captured_spools, ltmc_pending, ...):
   │   ├─ Seal each spool into the chain
   │   ├─ Compute cutover_verdict (precedence rule)
   │   └─ Seal NO_GO into the chain if applicable
   └─ Persist to S3: summary.json, ltmc_handoffs.json, cvi_map.json,
                     audit_chain.jsonl, evidence_pack_*.json
   │
6. If state machine in waitForTaskToken state:
   └─ governance.GateController.notify(SNS):
       └─ Human reviews payload, calls /api/spine/approve with HMAC-signed token
           └─ governance.verify + SendTaskSuccess -> state machine continues
```

Every step is **best-effort + structured-failure**: an exception in any sub-
component is captured into the result dict, never raised, so the pipeline
continues processing other records / objects while the failing one routes to
dead-letter or quarantine.

---

## 13. Honest limitations

These are the limitations that stand even after all of §14 / §15 closures. A
reviewer should test these claims rather than trust them.

### 13.1 Harmonization of dependent keys is a demonstration, not faithful migration (for now)

Several dependent / transactional objects currently **harmonize source
business keys to existing target-ready masters** rather than migrating them
1:1, because the source masters don't yet exist in the target appliance:

- **SalesOrder** sold-to and item material → an existing sales-ready
  customer/material in the target.
- **PurchaseContract** vendor → a TESTRUN-validated target vendor.
- **Batch** / **InventoryBalance** material+plant → a discovered
  batch-managed / stocked material.
- **FunctionalLocation** / **Project** labels → reformatted to the target mask.

This proves the **load + reconcile mechanism** for those object types, but
it is **not** a faithful migration of those specific records. In a real
project these objects depend on the prior faithful migration of their master
data.

**Mitigation in place**: `dependency_dag.DependencyDAG` + `KeyResolver` give
the staged-load + cross-run key-translation pattern needed. Integration into
the data-migrator stage loop is the remaining mechanical step (today the
modules are standalone-wired but the actual record-by-record key swap in
`_load_one` is not flipped on yet).

### 13.2 102 of the 127 catalog objects are extract-only

Of the 127-object catalog:
- **25** loaded+reconciled end-to-end via BAPI/OData spine.
- **87** routed to the MC/LTMC lane: the tool **extracts from ECC and emits
  Migration-Cockpit-staging templates** — the **actual MC import is operator-
  driven**, not done by this tool.
- **15** routed to the IDoc lane.

Of the 87 MC-lane extracts, 15 have been smoke-tested live; the other ~72
are source-table descriptors not yet extract-verified. Do not read "127" as
"127 migrated." The honest figure is **25 end-to-end + 87 extract-staged +
15 IDoc-staged**.

### 13.3 Functional coverage depth

Where loaded, objects use **minimal valid field sets** (the fields needed
for a consistent create), not the full business field complement. E.g. a
sales order is header + one item + schedule line; a contract is header +
one nominal item. Real records carry far more (partners, conditions, texts,
statuses, custom Z-fields).

**Mitigation in place**: `bapi_field_catalog` documents what each BAPI can
carry, and `bapi_coverage` routes anything beyond that to LTMC. So missing
fields are no longer **silently dropped** — they become visible LTMC delta
files. But the *content* of those LTMC files still needs the operator to
finalize the per-field mapping in the Migration Cockpit UI.

### 13.4 Scale

Volume proven once at ~1k documents. Real migrations are 10⁶-10⁸ records.
Throughput, restart at scale, ledger size, and reconciliation read-back cost
at volume are **unproven**.

**Mitigation in place**: `ComputeDispatcher` routes above-threshold work to
Fargate, `WorkloadThrottle` prevents target dumping at concurrency,
`TokenBucket` protects DynamoDB WCU, `ODataPager` streams large entity sets.
But none of these have been exercised at 10⁶-row scale on the deployed stack.

### 13.5 No customer pilot, no second landscape

TRL ~6 on the data spine. Not run outside the build appliance. The team's
SAP functional/Basis depth is **engineering-led, not consultant-led** —
please flag any non-idiomatic SAP usage you spot.

### 13.6 Mock ATC

The ATC gate in `llm_fallback_router.py` is a **mock**:
- Control-structure balance check
- Marker check (`M4H_SYNTAX_ERROR`)
- Native SQL flag
- `SELECT *` flag

Real ATC compliance requires checking against the target S/4HANA release's
SAP_BASIS and simplification database via the released ATC RFC
(`/SAP/ATC_INVOKE_TEST` family). This is on the roadmap but is an
engineering exercise, not a research problem.

### 13.7 Object Lock WORM intentionally off (regression vs original Pillar 4)

Per user directive 2026-05-30, the S3 Object Lock COMPLIANCE retention was
**removed** from the evidence and audit-logs buckets so `terraform destroy`
is clean during the inner-loop test cycle. The hash chain still detects
record-level tamper, but bucket-level immutability is OFF.

**Restore for production**: set `object_lock_enabled = true` on the bucket
at creation time (cannot toggle on later) + restore
`aws_s3_bucket_object_lock_configuration`. See `terraform/modules/
evidence-ledger/main.tf:64-77` for the exact change.

### 13.8 Anthropic public-API egress

Code-remediation LLM calls go to `api.anthropic.com` over the Lambda's NAT
egress because the user's AWS account does not have Bedrock model access.
Pseudonymizer masks PII (emails / IPs / passwords) but not business logic.
For regulated buyers (Aerospace / Defence / Pharma / Banking) this is a
likely compliance blocker; for the POC it's acceptable.

**Mitigation path**: `anthropic_client.invoke_claude()` already takes a
model id and is endpoint-agnostic; swapping to Bedrock once granted (or to
a private VPC LLM on SageMaker) is one URL/header change.

### 13.9 Live ECC ↔ AWS connectivity deferred

The current prod stack runs in-AWS-only. The user's local ECC system is
reachable from the workstation but **not** from VPC-attached Lambdas.
Site-to-site VPN or AWS Client VPN is needed before stages can actually
call ECC from AWS.

---

## 14. Competitor-parity layers

The 2026-05-29 commit added three "competitor-grade" engines that are now
embedded INSIDE the corresponding Migrate4HANA stages (not as separate
parallel spines).

| Competitor | Embedded into stage | Engine + what it does |
|---|---|---|
| **SmartShift** | `lambda/code-analyzer` | Deterministic 6,400-line AST first; on parser crash → localised AI fallback via Anthropic API → mock-ATC gate → transport `.data/.cofile` or quarantine. Plus daily code-delta engine via EventBridge (Gemini gap #5) for dual-maintenance code sync. |
| **Syniti** | `lambda/data-hygiene` | Entity-tree FK integrity (BUT000/020/100; orphans quarantined), deterministic org-attribute self-heal vs target reference data, SHA-256 idempotency ledger. Plus `CROSS_FIELD_VALIDATE` for multi-field business validation (Gemini gap #6). |
| **Natuvion** | `lambda/data-migrator` extract | Generates org(`BUKRS`) / time(`GJAHR`)-filtered, `OPEN CURSOR…PACKAGE SIZE`-streamed, dependency-aware (line→`BKPF`) in-system carve-out ABAP. Plus cluster-table-aware preflight (Gemini gap #7) to refuse unsafe BSEG/RFBLG full-cluster scans. |

### Head-to-head honest read (per competitor)

| Their speciality | Where we stand | To become competitive |
|---|---|---|
| **SmartShift** — automated custom-code remediation at scale, dual-maintenance | Real AST engine + 4-level fixers + deterministic-first/AI-fallback wired into stage + daily code-delta detection scheduled. | Real ATC integration (not mock); equivalence-test harness (before/after diff on a large custom-code base); expand simplification ruleset; CI over the fixer. |
| **Syniti** — DQ, mapping, governance, reconciliation | Strong reconciliation (existence+value, hard verdict) + cross-run idempotency ledger (SHA-256) + FK-integrity + deterministic self-heal + `CROSS_FIELD_VALIDATE`. | Build the business-user mapping/governance UI; DQ rule library + scorecards; data-owner workflow/sign-off. |
| **Natuvion** — SDT / carve-outs / consolidation | Carve-out ABAP generator (org+time filters, dependency-aware, streamed) + cluster-aware preflight + DAG dependency resolver. | Live carve-out at volume; selective company-code/time-slice split; harmonization rules for consolidation. |

---

## 15. Gap closures

Eight original gaps from the first peer-expert review (Gemini, 2026-05-31)
plus four follow-up concerns from the second pass. All twelve are addressed
in code with green self-tests.

### First pass (§14 in the brief)

| # | Gap | Module / call site | Verified |
|---|---|---|---|
| 1 | CVI overlapping number ranges + duplicate addresses | `cvi_mapper.unify` | Overlap, duplicate fold, conflict quarantine, deterministic |
| 2 | SAP-side backpressure (TH_WPINFO + NRIV) | `sap_workload.WorkloadThrottle` | GREEN/YELLOW/RED classification |
| 3 | BAPI field-coverage trap | `bapi_coverage` + `bapi_field_catalog` (25 objects) | BAPI / +LTMC delta / LTMC-only routing |
| 4 | FAGLB03 / MB5B spool capture | `spool_capture.SpoolCapture` | Job lifecycle + SHA-256 seal |
| 5 | Dual-maintenance code-sync engine | `code_delta.DeltaEngine` + scheduler Lambda + EventBridge cron | ADDED/MODIFIED/DELETED idempotent |
| 6 | Multi-field cross-validation DQ | `transformation_engine.CROSS_FIELD_VALIDATE` | Conditional triggers + ops + validation |
| 7 | Cluster-table aware extraction | `cluster_table_awareness.preflight` | Transparent/cluster/PCL1 cases |
| 8 | DAG dependency resolver | `dependency_dag` + `KeyResolver` | Topo sort, cycle, failure propagation |

### Second pass (§14.6 in the brief)

| # | Concern | Resolution | Verified |
|---|---|---|---|
| 1 (follow-up) | CVI cyclical references (KNA1.LIFNR ↔ LFA1.KUNNR) lock the loader | `cvi_mapper.unify_with_xrefs()` returns `TwoPhasePlan` (stub first, attach xrefs second); cycle detected, not error | 4-row test, 1 cycle, 1 unresolved out-of-batch xref |
| 2 (follow-up) | Throttle wait cost during long congestion | Exponential backoff (YELLOW 2s base, RED 10s base, doubles per consecutive non-GREEN, capped 60s, GREEN resets streak) | 7 probes: 10→20→40s then GREEN resets, next RED back to 10s |
| 3 (follow-up) | BAPI/LTMC chain precision (tampered LTMC file invisible) | `ltmc_pending` blocks sealed into `HashChainLedger`; one per handoff; `ltmc_pending` in run summary | Wired |
| 4 (follow-up) | No explicit "SAP report > tool ledger" precedence rule | `EvidencePack.cutover_verdict` + `_compute_cutover_verdict()`; precedence rule documented inline + echoed in manifest; NO_GO sealed into chain | 5 cases: GO / 3 distinct NO_GO scenarios / GO_WITH_WARNINGS |

### Intentionally NOT addressed (per user directive)

- **Branch rename** `aws-lift-and-shift` → `sdt-orchestration`: cosmetic;
  deferred until after POC ships.
- **LLM compliance toggle** (Anthropic public API → in-VPC Bedrock /
  SageMaker): POC-acceptable per user decision 2026-05-30; the runtime
  client already takes a model id, endpoint swap is trivial when Bedrock
  arrives.

---

## 16. Extension points + per-landscape content surfaces

These are the places a real customer engagement will need to extend. By
design — framework is in code, content is in config so it can ship
landscape-by-landscape without touching the engine.

| Surface | Where | How to extend |
|---|---|---|
| **BAPI field catalog per release** | `lambda/utils/bapi_field_catalog.py` baseline + `M4H_BAPI_FIELD_CATALOG_JSON` env var | Run `DD_BAPI_PARAMETER_GET` against target; write the result as JSON; set the env var; the loader picks it up at startup |
| **Cluster table catalog per release** | `lambda/utils/cluster_table_awareness.py:_CATALOG` | Add `TableInfo(name, kind, physical_table, header_table, join_keys)` rows for landscape-specific pool/cluster tables |
| **DAG additions per industry** | `lambda/utils/dependency_dag.py:from_defaults` | Call `dag.add_edge(dependent, requires)` after `DependencyDAG.from_defaults()` |
| **CVI fuzzy-match rules per locale** | `lambda/utils/cvi_mapper.py:_norm_*` | Currently only normalisation; locale-specific rules (street-abbreviation tables, edit-distance match) would extend `_build_partner_index` |
| **NRIV thresholds per landscape** | `lambda/utils/sap_workload.py:GREEN_FREE_RATIO` etc. | Constants today; trivial to lift into env vars |
| **Transformation rule sets** | `lambda/utils/transformation_engine.py` + `M4H_TRANSFORM_RULES` env var | JSON file with FIELD_MAP / VALUE_MAP / REGEX_CLEANSE / DQ rules per object |
| **S3 mapping matrix** | `M4H_MAPPING_S3` env var | Business-user-uploadable value translation table (cross-charts-of-accounts etc.) |
| **Per-object BAPI loader extensions** | `lambda/utils/bapi_loader.py` | One `create_<object>` method per object type |
| **Per-customer DAG additions** | EventBridge or runtime config | Today: env-loaded JSON; future: customer-portal-uploadable |

---

## 17. Trust spine deep dive

This is the architectural moat. Each layer is unusual on its own; together
they form a single auditable record per migration run.

### Auto-discovery (`lambda/utils/config_discovery.py`)

Probes the target landscape for:
- Company code → currency / chart of accounts / fiscal year variant
- Sales org / distribution channel / division
- Plants / storage locations
- Recon accounts (customer, vendor)
- Order types, structure indicators, coding masks
- Cost centers / profit centers / cost elements available

Each probe is **rollback-validated**: e.g., to confirm the expense account
for a test PO, it actually posts a tiny test PO, reads it back, and rolls
it back. This way the loader uses config that's *verified* against the
target, not just *assumed*.

### Idempotent cross-run ledger (`lambda/utils/key_map.py`)

Keyed by `(object, source_key) → target_key + status`. Persisted to
DynamoDB. On re-run, the loader skips any record whose key is already in
the ledger with status `created`. This way:
- A network hiccup mid-load doesn't create duplicates.
- A re-run picks up only what failed last time.
- A dependent object (OpenPO → Vendor) can look up the target Vendor key
  written by an earlier run.

`TokenBucket` (Pillar 1.3) limits ledger writes to a configurable rate
(default off; 50/s+50-burst when enabled) so high-concurrency loops can't
saturate DynamoDB WCU.

### Hash chain (`lambda/utils/reconciler.HashChainLedger`)

Append-only SHA-256-chained ledger. Each block:
```json
{
  "seq": 12,
  "ts": "2026-05-31T10:14:32Z",
  "run_id": "run-abc",
  "kind": "data_load" | "key_map" | "reconciliation" | "carve_out" |
          "ltmc_pending" | "captured_spool" | "cutover_no_go" | "evidence_pack",
  "payload_hash": "<sha256 of canonical payload>",
  "prev_hash": "<block_hash of block n-1>",
  "block_hash": "<sha256 of all the above>"
}
```

Persisted to S3 (`audit_chain.jsonl`) AND optionally to a `audit_ledger`
DynamoDB table. `verify()` walks the chain; any tampered block surfaces as
`{"ok": false, "broken_at": i, "reason": "prev_hash_mismatch"}`.

### Aggregate reconciliation (`reconciler.AggregateReconciler`)

For ledgers where row-level recon is too expensive (OpenAR, OpenAP,
InventoryBalance), runs aggregate tie-out: source count + total + debit/credit
split vs target. Surfaces `VARIANCE` when they don't match.

### Evidence pack (`reconciler.EvidencePack`)

Run-end manifest with:
- System config (auto-discovery result).
- Data quality summary.
- Target API success / failure responses.
- Balance tie-outs (aggregate reconciliation).
- Reconciliation verdict (row-level + aggregate).
- Captured spools (FAGLB03 / MB5B) sealed into the chain before the
  manifest hashes them.
- LTMC pending list (sealed into chain).
- **Cutover verdict** with precedence rule (see §19).
- Audit chain head hash + `verify()` result.
- Manifest SHA-256.
- Sealed-block-hash (the chain's head after the evidence_pack block is
  appended).

### Cutover gate (`lambda/utils/governance.GateController`)

HMAC-signed webhook gate. Workflow:
1. State machine hits `waitForTaskToken`.
2. `manual-gate` Lambda persists the token to DynamoDB + sends an SNS alert
   with the gate's full payload + a one-time HMAC-signed approval URL.
3. Authorised stakeholder receives the email, clicks the URL or hits
   `POST /api/spine/approve` with the signed token.
4. `governance.verify()` checks: signature valid, token not previously used,
   approver in the authorised list, gate not expired.
5. On verify success: `states.SendTaskSuccess` → state machine continues.
6. On verify failure: alert + state machine remains blocked.

---

## 18. Security posture

### IAM

- One Lambda execution role across all 37 functions (least-privilege within
  the role; further scoping per-function is on the roadmap).
- Permissions: logs:*, s3:* on staging bucket, secretsmanager:GetSecretValue
  on the named secrets only (sap, s4hana, gate, anthropic), ec2 ENI mgmt for
  VPC attachment, lambda:InvokeFunction on `migrate4hana-*` only, states:
  SendTaskSuccess/SendTaskFailure on this account/region only, ECS RunTask
  for Fargate dispatch.
- `bedrock:InvokeModel` **removed** (Bedrock not in use).

### Network

- All Lambdas in private subnets; egress via NAT.
- WAFv2 on the API Gateway: rate limit, AWS managed rule sets (CommonRules,
  SQLi, KnownBadInputs, IPReputation).
- WAF logs to CloudWatch + a `>100 blocked/5min` alarm.

### Encryption

- KMS CMK `alias/migrate4hana-prod` (rotated, in `evidence-ledger` module).
- All DynamoDB tables: SSE-KMS with the CMK.
- All S3 buckets: SSE-KMS + bucket-key-enabled.
- SNS topics: KMS-encrypted.
- TLS for all egress (anthropic API, SAP RFC over secure network).

### Secrets

- 4 secrets in Secrets Manager, all with `recovery_window_in_days = 0` for
  clean destroy:
  - `migrate4hana/prod/sap-credentials` (ECC RFC)
  - `migrate4hana/prod/s4hana-credentials` (S/4 RFC)
  - `migrate4hana/prod/gate-secret` (HMAC for governance gate; random 48
    chars, set by `random_password` resource)
  - `migrate4hana/prod/anthropic-api-key` (Anthropic API key; set via
    `aws secretsmanager put-secret-value`)

### Audit trail

- CloudTrail trail (`migrate4hana-audit-prod`) with multi-region: false (in
  prod, switch to true), log-file validation: on, log file: 7-year retention
  on the WORM-enabled audit-logs bucket.
- CloudTrail data events on **all Lambda invocations** in the account (bare
  `arn:aws:lambda` prefix) + the staging S3 bucket.
- 4 CloudWatch metric filters with alarms:
  - Unauthorized API calls
  - Secrets Manager access (every `GetSecretValue`)
  - IAM role/policy changes
  - Pipeline execution events

### Compliance posture

- **SOX**: 7-year retention on audit logs; hash-chained immutable ledger; all
  state-changing actions through released APIs; per-run signed attestation.
- **GxP**: same retention; manual gates with HMAC-signed approval webhook +
  approver identity in the chain.
- **Object Lock WORM**: intentionally off on evidence bucket for the test
  cycle (see §13.7); 7-year WORM is on the audit-logs bucket.

### Honest security limitations

- Lambda role is shared (not per-function least-privilege).
- Anthropic API egress is public (see §13.8).
- No private API Gateway endpoint; the spine approve webhook is
  internet-facing, protected by HMAC + WAF.
- No VPC peering / Direct Connect to ECC yet (see §13.9).

---

## 19. Audit, compliance, evidence pack

### The hash chain

See §17. Every state-changing action becomes a SHA-256-chained block. The
chain is persisted to S3 (`audit_chain.jsonl`) and optionally to the
`audit_ledger` DynamoDB table. `HashChainLedger.verify()` returns
`{"ok": True, "blocks": N, "head": "..."}` on a clean chain, or
`{"ok": False, "broken_at": i, "reason": "..."}` on a tamper.

### The cutover_verdict precedence rule

`reconciler._compute_cutover_verdict()` enforces:

> **SAP-standard spool reports outrank the tool's reconciliation ledger.**
> The tool's hash-chained ledger can confirm a GO but cannot override a NO_GO.

The verdict is **NO_GO** if any of:
- A balance tie-out shows `variance > 0` or status `VARIANCE / NO_MATCH / FAIL`.
- Any LTMC handoff is pending import (`ltmc_pending.pending_count > 0`).
- A required close spool is missing (`FAGLB03` or `MB5B` not in captured set).

The verdict is **GO_WITH_WARNINGS** if hard rules pass but the tool ledger
flags a discrepancy (e.g., `DISCREPANCY` from the row-level reconciler).

The verdict is **GO** if all hard rules pass and the tool ledger is clean.

On NO_GO: the verdict is itself sealed as a `cutover_no_go` block in the
chain, so the chain bears witness to the refusal.

### Object Lock status

| Bucket | Object Lock | Retention | Reason |
|---|---|---|---|
| `migrate4hana-audit-logs-prod` | **GOVERNANCE** | 2555d (7y) | SOX, applied at bucket creation |
| `migrate4hana-evidence-prod-<acct>` | **OFF** (intentional) | n/a | Per user directive 2026-05-30, for clean `terraform destroy` during inner-loop testing |

**To re-enable WORM on the evidence bucket**: set `object_lock_enabled = true`
on `aws_s3_bucket.evidence` AT creation (cannot toggle on later) + restore the
`aws_s3_bucket_object_lock_configuration` block. See `evidence-ledger/main.tf:64-77`.

### Per-auditor walkthrough

1. **Pull the audit chain**: `aws s3 cp s3://<staging-bucket>/runs/<run-id>/
   data-migrator/audit_chain.jsonl -`. Each line is one block.
2. **Verify chain integrity**: any Python (or even `jq`) script can recompute
   each block's hash and compare.
3. **Cross-check spool binaries**: each `captured_spool` block carries the
   SHA-256 of the spool file. Pull the file from
   `runs/<run-id>/spool/<report_code>/<job_name>.spool`, hash it, compare.
4. **Verify cutover verdict**: look for `cutover_no_go` blocks in the chain.
   If absent and `evidence_pack.cutover_verdict.verdict == "GO"`, the gate
   was clean.
5. **Cross-check FAGLB03 vs tool ledger**: the spool binary is the SAP-
   standard balance; the tool's `reconciliation` block is the tool's claim.
   Auditors should treat the spool as primary.

---

## 20. Cost model

Honest order-of-magnitude estimates for a 1M-record-load run on the deployed
stack. Real numbers depend on object mix, customer-side latency, and how
much of the load routes to Fargate vs Lambda.

### Per-run (1M records, typical mix)

| Component | Estimate | Notes |
|---|---|---|
| Lambda invocations | ~5,000 | Per-object handlers + reconciliation workers |
| Lambda compute (GB-s) | ~10,000 | Most handlers at 1-2GB, 1-60s each |
| Fargate (heavy stages) | ~5-20 task-hours | Stages 1/5/12/12A if >threshold |
| DynamoDB | ~$5-15 | key-map + audit-ledger writes |
| S3 (PUT + storage) | ~$2-5 | runs/, evidence/, audit_chain |
| KMS | ~$1-2 | Per-API-call cost |
| CloudWatch | ~$3-8 | Logs + metrics + dashboard |
| Anthropic API | ~$1-50 | Depends on % of code-remediation escalation. Sonnet 4.6 default at ~$3/M-input + $15/M-output |
| NAT data | ~$1-5 | Anthropic API egress + Lambda↔Internet |
| **Run total** | **~$30-150** | Excluding ECC / S/4 side costs |

### Always-on (monthly)

| Component | Estimate | Notes |
|---|---|---|
| VPC + NAT | ~$45 | NAT $0.045/h + GB |
| KMS | ~$1 | CMK monthly |
| Secrets Manager | ~$1.60 | 4 secrets × $0.40 |
| S3 storage (audit + evidence) | ~$5-20 | Grows with retention |
| DynamoDB on-demand | ~$2-10 | Idle cost |
| WAF | ~$5 | WebACL + rules |
| CloudWatch logs retention | ~$3-8 | 30-365d retention by group |
| **Monthly idle** | **~$60-100** | No active migrations |

### Cost levers

- Anthropic API cost scales with code-remediation escalation rate; the
  deterministic AST handles 90%+ of normal custom-code, so escalation should
  be the minority.
- Fargate cost scales with carve-out volume; the dispatcher routes only
  above-threshold work to Fargate, so small carve-outs stay on Lambda.
- WORM retention (when re-enabled) keeps audit-logs in STANDARD_IA →
  GLACIER after 90/365 days; 7-year SOX retention is what drives the
  long-tail storage cost.

---

## 21. Deployment runbook

### Prerequisites (one-time per machine)

```powershell
# 1. AWS CLI v2
aws --version
aws sts get-caller-identity   # confirm correct account

# 2. Terraform 1.5+
terraform version

# 3. Docker Desktop in Linux container mode (for Fargate image build)
docker info | Select-String "OSType"   # must show: OSType: linux

# 4. SAP NW RFC SDK (proprietary; from SAP Support Portal)
# Place nwrfc750P_*_linux64bit.zip in ecs/

# 5. pyrfc layer pre-built once
python layer-build/build_pyrfc_layer.py    # or .ps1
# Produces layer-build/pyrfc-layer.zip
```

### Apply the prod stack

```powershell
cd terraform\environments\prod
terraform init
terraform apply -auto-approve   # ~5-8 min, provisions 200 resources
```

### Push the Fargate worker image

```powershell
cd ..\..\..
.\scripts\push-fargate-image.ps1   # ~5-8 min first time, 30-60s cached
```

### Populate the Anthropic API key (after apply)

```powershell
aws secretsmanager put-secret-value `
  --secret-id migrate4hana/prod/anthropic-api-key `
  --secret-string '{\"api_key\":\"sk-ant-...\"}'
```

### Subscribe to the alert + gate SNS topics

The `aws_sns_topic_subscription` resources create pending subscriptions for
`var.alert_email`. Check your inbox and confirm the two subscriptions:
- `migrate4hana-alerts-prod`
- `migrate4hana-spine-gates-prod`

### Trigger a test run

```powershell
$STATE_MACHINE_ARN = aws stepfunctions list-state-machines `
    --query "stateMachines[?starts_with(name, 'migrate4hana-lift-and-shift')].stateMachineArn" `
    --output text

aws stepfunctions start-execution `
    --state-machine-arn $STATE_MACHINE_ARN `
    --input '{\"mode\":\"discovery\",\"ecc_client\":\"100\"}'
```

### Destroy the stack

```powershell
cd terraform\environments\prod
terraform destroy -auto-approve   # 200 resources, ~5-10 min
```

If destroy fails on the audit-logs bucket (non-empty), empty it first:

```powershell
python -c @"
import boto3
s3 = boto3.client('s3', region_name='us-east-1')
bucket = 'migrate4hana-audit-logs-prod-<account>'
paginator = s3.get_paginator('list_object_versions')
for page in paginator.paginate(Bucket=bucket):
    objs = [{'Key': v['Key'], 'VersionId': v['VersionId']}
            for v in (page.get('Versions') or []) + (page.get('DeleteMarkers') or [])]
    if objs:
        s3.delete_objects(Bucket=bucket, Delete={'Objects': objs, 'Quiet': True},
                          BypassGovernanceRetention=True)
"@
terraform destroy -auto-approve
```

---

## 22. Operational observability

### CloudWatch dashboard

`Migrate4HANA-prod`. Four widgets:
1. Lambda invocations by stage (all `migrate4hana-*` functions).
2. Lambda errors by stage.
3. Lambda duration by stage (average).
4. Step Functions executions (succeeded / failed / started).

### Alarms

- `migrate4hana-pipeline-failed-prod`: >0 Step Functions failures in 5min → SNS
- `migrate4hana-unauthorized-api-prod`: >5 unauthorized API calls in 5min → SNS
- `migrate4hana-iam-changes-prod`: any IAM role/policy change → SNS
- `migrate4hana-waf-blocked-prod`: >100 blocked requests in 5min → SNS

### Log groups

- `/aws/lambda/migrate4hana-*` per function, 14d retention.
- `/aws/stepfunctions/migrate4hana-*`, 30d retention.
- `/migrate4hana/audit/prod`, **365d retention** (audit trail).
- `aws-waf-logs-migrate4hana-prod`, 90d retention.

### WebSocket telemetry

`api/spine/ws` streams per-stage progress events to the React UI in real
time. Useful during long-running migrations for non-technical stakeholders.

### Run summary structure (S3)

After each `data-migrator` invocation, written to
`s3://<staging>/runs/<run-id>/data-migrator/summary.json`. Includes:

```
run_id, mode, object_count, ok_count, partial_count, error_count,
load_to_s4_enabled, objects_created_in_s4, cdc.{mode, watermark_used,
next_watermark, changed_rows_extracted}, idempotency.{newly_created,
reused_from_ledger}, discovered_config, reconciliation, support_compliance,
key_mapping, dead_letter, cvi.{overlap_count, legacy_keys_mapped, unique_bps,
merged_customer_vendor, conflicts_requiring_review, two_phase_plan,
artifact}, ltmc_pending.{pending_count, objects_with_pending, artifact,
note}, carve_out, audit_chain.{head_hash, blocks, verification}, results
```

---

## 23. Branch-name and naming caveats

The active branch is `aws-lift-and-shift`. This is **misleading** for the
product positioning (greenfield / SDT data migration via released APIs is
not a "lift and shift" in the SAP infrastructure sense, which usually means
in-place database migration).

**Recommended rename**: `sdt-orchestration` or `migrate4hana-greenfield`.
The rename is **one git command** but has blast radius (origin tracking,
any open PRs, CI configs). Deferred until after the POC ships per user
directive.

Other naming oddities a reviewer should be aware of:

- `lambda/code-analyzer/bedrock_genai_engine.py` — filename retained for
  callsite compatibility; the actual transport is now the Anthropic API.
  Documented at the top of the file.
- `lambda/code-analyzer/genai_router.py:_invoke_bedrock` — function name
  retained; routes through Anthropic API. Aliases `"anthropic"` and
  `"bedrock"` both accepted in `_dispatch()`.

---

## 24. POC readiness

For a contained client POC on **client ECC → client S/4HANA**:

### What works out of the box

- AWS prod stack provisions cleanly (200 resources, apply→destroy idempotent).
- Fargate image push is one PowerShell command.
- Anthropic API code-remediation path is live (just need the API key).
- All 25 load+reconcile object types work on the IDES/CAL test pair.
- All Gemini gap closures (12 of them) are wired and self-tested.

### What needs landscape work (client engagement scope)

- **Site-to-site VPN or Client VPN** from AWS to client ECC. Lambda
  currently has no path into the client's network. ~1-2 days of network
  setup.
- **Update `bapi_field_catalog`** from the client's release / SAP Notes
  via `DD_BAPI_PARAMETER_GET` introspection. ~½ day.
- **Update `cluster_table_awareness._CATALOG`** if the client has unusual
  cluster tables. ~½ day.
- **Tune `WorkloadThrottle` thresholds** to the client's WP topology.
  GREEN/YELLOW/RED ratios + NRIV object names. ~½ day.
- **DAG addendum** if the client has industry-specific object dependencies
  (utilities, banking, retail, etc.). ~1-2 days.
- **Run discovery on the client target** to verify `config_discovery`
  produces correct values. ~1 day.

### What is NOT POC-ready (clearly defer to a paid engagement)

- Full-volume validation (10⁶+ records).
- Real ATC integration (replace mock with `/SAP/ATC_INVOKE_TEST` RFC).
- Business-user mapping UI (today: JSON-only rule authoring).
- WORM re-enable on evidence bucket (one-line fix, but cancels easy destroy).
- Anthropic → private LLM for regulated buyers (one URL/header swap when
  Bedrock granted; currently API-public-egress).

### Recommended POC scope (per Gemini's suggestion)

A **like-for-like sandbox carve-out**:
- 3 master data objects: BP (CVI), Material, GLAccount
- 2 transactional objects: OpenPO, OpenAP
- Volume: 50,000 records per object
- Governance: dual-landscape test — Migrate4HANA into isolated target +
  standard Migration Cockpit into a peer target + `diff` on resulting target
  tables to prove equivalence.

---

## 25. Reviewer's checklist

Specific things to scrutinise during a peer review.

### SAP correctness (highest value)

- [ ] Verify each released BAPI used per object in `lambda/utils/bapi_loader.py`
      is in fact the supportable variant (BAPI / OData) for the target release.
- [ ] Verify calling conventions: `BAPI_TRANSACTION_COMMIT` placement in
      parallel loops; LUW boundary management; number range protection
      (now done via `sap_workload.WorkloadThrottle` NRIV probe).
- [ ] Verify per-object field mappings in `bapi_loader.create_*` match
      common SAP idioms (mandatory fields, currency / decimal handling,
      partner role assignments).
- [ ] Verify the BP-led CVI flow respects S/4 external numbering / number
      range customising.
- [ ] Verify reconciliation logic correctly accounts for posting periods,
      year-end carry-forward, and clearing rules.

### Engineering correctness

- [ ] Hash chain `verify()` returns clean on a normal run; flip one byte in
      a block payload and confirm `broken_at` surfaces.
- [ ] Cutover verdict precedence: confirm a variance > 0 in any balance
      tie-out produces NO_GO regardless of the row-level reconciler's
      claim.
- [ ] DAG topological sort: confirm `SalesOrder` cannot start until both
      `Customer` (which depends on `BusinessPartner`) and `Material` are
      `done`.
- [ ] CVI cycle handling: feed a fixture with intercompany cross-references
      and confirm the loader produces a two-phase plan + cycle entry.
- [ ] Cluster table preflight: attempt `RFC_READ_TABLE(PCL1, ...)` with no
      WHERE and confirm it raises BEFORE the RFC fires.
- [ ] Throttle backoff: feed a fixture that returns 5 consecutive RED
      probes and confirm wait times grow exponentially, capped at 60s,
      then a GREEN resets to base.

### Security / compliance

- [ ] All 4 secrets exist with `recovery_window_in_days = 0`.
- [ ] Lambda IAM has no `bedrock:*` permission.
- [ ] Audit-logs bucket has Object Lock GOVERNANCE 2555d.
- [ ] Evidence bucket has Object Lock OFF (intentional; confirm the
      `evidence-ledger/main.tf:64-77` comment explains the toggle).
- [ ] CloudTrail data events cover all Lambda invocations + staging bucket.
- [ ] WAFv2 rules attached to API Gateway.
- [ ] Pseudonymizer redacts PII before Anthropic API egress (read
      `lambda/code-analyzer/pseudonymize.py` and verify the regex set).

### Operational

- [ ] `terraform apply` produces 200 resources, zero changes on second apply.
- [ ] `terraform destroy` succeeds without manual cleanup (one exception:
      audit-logs bucket GOVERNANCE-locked objects need manual empty;
      documented in `EXPERT_REVIEW_BRIEF.md:§13`).
- [ ] `.\scripts\push-fargate-image.ps1` succeeds end-to-end.
- [ ] EventBridge `code-delta-scheduler` cron is wired and the Lambda has
      the pyrfc layer attached.
- [ ] Subscription to `migrate4hana-alerts-prod` SNS is confirmed.

---

## 26. Glossary

| Term | Definition |
|---|---|
| **BAPI** | Business Application Programming Interface — SAP-released RFC entry point for state-changing operations |
| **OData** | The HTTPS-based services SAP releases for modern integrations (e.g. API_BUSINESS_PARTNER) |
| **BP / Business Partner** | The unified S/4HANA partner entity that replaces ECC's separate Customer (KNA1) and Vendor (LFA1) |
| **CVI** | Customer-Vendor Integration — the mapping from KNA1/LFA1 to BUT000 with role assignments |
| **CDC** | Change Data Capture — delta extract driven by SAP change documents (CDHDR/CDPOS) |
| **DAG** | Directed Acyclic Graph — object dependency model (masters before transactionals) |
| **DQ** | Data Quality |
| **IDoc** | Intermediate Document — async messaging mechanism in SAP |
| **LTMC** | Legacy System Migration Cockpit — SAP's standard migration tool |
| **LTMOM** | Legacy Migration Object Modeler — LTMC's mapping editor |
| **LUW** | Logical Unit of Work — SAP's transactional boundary |
| **NRIV** | Number Range Internal Values — the SAP table that serialises number-range assignment |
| **RFC** | Remote Function Call — SAP's binary RPC protocol |
| **SDT** | Selective Data Transition — migrate only a subset (e.g. 3 years, one company code) |
| **SUM / DMO** | Software Update Manager / Database Migration Option — SAP's in-place upgrade/migration tool (NOT used by this product) |
| **SOX** | Sarbanes-Oxley Act — financial-reporting controls (7-year retention is one consequence) |
| **TADIR** | The SAP repository directory table — every Z/Y custom object is registered here |
| **TaskToken** | AWS Step Functions mechanism for human-in-the-loop wait states |
| **TH_WPINFO** | RFC function returning current work-process status on the target SAP system |
| **TRL** | Technology Readiness Level (1-9) — DARPA scale; TRL 6 = prototype demonstrated in relevant environment |
| **WORM** | Write-Once-Read-Many — immutable storage (S3 Object Lock COMPLIANCE/GOVERNANCE) |
| **WP** | Work Process — SAP's dialog/update/batch execution slot |

---

*End of detailed review brief. For executive summary, see `EXPERT_REVIEW_BRIEF.md`.
For operational runbooks, see `HOW-TO-RUN.md` and `LIFT-AND-SHIFT-RUNBOOK.md`.
For per-object live-proof trail, see `BREADTH_TRACKER.md`.*
