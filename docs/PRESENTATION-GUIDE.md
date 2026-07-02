# Migrate4HANA — Presenter's Technical Guide

**Audience:** A senior SAP all-rounder (multi-module functional + technical + Basis exposure).
**Purpose:** Answer any technical question, in SAP vocabulary, about what this tool does, how it does it, and what SAP prerequisites it needs.

---

## Table of contents

1. [Elevator pitch and positioning](#1-elevator-pitch-and-positioning)
2. [Architecture overview](#2-architecture-overview)
3. [The 28-stage lift-and-shift pipeline](#3-the-28-stage-lift-and-shift-pipeline)
4. [Object catalog and migration lanes](#4-object-catalog-and-migration-lanes)
5. [Code remediation engine (ABAP AST)](#5-code-remediation-engine-abap-ast)
6. [Configuration framework (country and module matrix)](#6-configuration-framework-country-and-module-matrix)
7. [Data-migrator internals: spines, idempotency, dead-letter](#7-data-migrator-internals-spines-idempotency-dead-letter)
8. [Execution modes: extract-only, simulation, live load](#8-execution-modes-extract-only-simulation-live-load)
9. [Governance, gates, and cutover precedence rule](#9-governance-gates-and-cutover-precedence-rule)
10. [Compliance and auditing: hash chain, evidence pack, WORM](#10-compliance-and-auditing-hash-chain-evidence-pack-worm)
11. [SAP prerequisites — a copy-paste checklist](#11-sap-prerequisites)
12. [Deployment and operations](#12-deployment-and-operations)
13. [AI enhancement layer](#13-ai-enhancement-layer)
14. [Reporting and scoring](#14-reporting-and-scoring)
15. [Known limitations and roadmap](#15-known-limitations-and-roadmap)
16. [Anticipated Q&A cheat sheet](#16-anticipated-qa-cheat-sheet)

---

## 1. Elevator pitch and positioning

**One-sentence pitch:** Migrate4HANA is a self-serve, governance-first migration platform that discovers a live SAP ECC system, remediates its custom ABAP, packages the customizing as SAP-standard transports and BC Sets, and lands data on S/4HANA through SAP-shipped APIs (BAPIs / released OData / Migration Cockpit) — while producing a cryptographically-sealed audit trail an auditor can accept.

**Where it sits in the SAP migration landscape:**

| Approach | Who owns it | What it produces | Where Migrate4HANA fits |
|---|---|---|---|
| SUM + DMO (in-place system conversion) | SAP | Same SID, same GUID, unicode + HANA target | **Out of scope.** Explicitly not this. |
| Selective Data Transition (SNP CrystalBridge, Datavard, Basistechnologies, Cbs) | Partner | New SID, curated data + custom code | **This is our lane.** Greenfield target, transport-led, no direct table writes. |
| Greenfield "big-bang" | Customer + SI | New SID, template-first | We add rigour: discovery-driven scope, hash-sealed audit, AI code remediation. |

**Two things to lead with:**

1. **We never call unreleased BAPIs, never do raw table writes, never modify SAP repository objects.** Every write is a released BAPI or a Migration Cockpit / LTMOM / IDoc inbound. This is the difference between "we migrated your data" and "we altered your S/4 system in ways SAP support cannot touch."
2. **Every data write is idempotent and hash-chained.** Re-running the pipeline never creates duplicates (key-map ledger persists the source→target mapping), and every mutation is recorded in a SHA-256-sealed audit chain that can survive a Big-4 review.

---

## 2. Architecture overview

### 2.1 Runtime topology

```
┌──────────────┐         ┌─────────────────────┐         ┌─────────────────┐
│   Browser    │────────▶│   CloudFront + S3   │         │ AWS Secrets Mgr │
│  (React SPA) │         │  (static UI bundle) │         │  ECC/S4 creds   │
└──────┬───────┘         └─────────────────────┘         │  Anthropic API  │
       │ /api/*                                          └────────┬────────┘
       │                                                          │
       ▼                                                          │
┌──────────────────────────────────────────┐                     │
│         Application Load Balancer         │                     │
│              (HTTPS, WAF)                 │                     │
└──────┬───────────────────────────────────┘                     │
       │                                                          │
       ▼                                                          │
┌──────────────────────────────────────────┐                     │
│  ECS Fargate task: api_server.py         │◀────────────────────┘
│  ─ FastAPI, JWT auth, wizard state       │
│  ─ subprocess: run_local_lift_and_shift  │
│  ─ per-run local-staging/ artefacts      │
└──┬─────────┬──────────────┬──────────────┘
   │         │              │
   ▼         ▼              ▼
┌──────┐  ┌──────┐  ┌────────────────────┐
│ DDB  │  │  S3  │  │  ECC + S/4HANA     │
│users │  │audit │  │  (via pyrfc /      │
│clnts │  │evide │  │   NW RFC SDK 7.50) │
│wiz   │  │stage │  └────────────────────┘
└──────┘  └──────┘
```

### 2.2 Tech stack in one screen

| Layer | Choice | Rationale |
|---|---|---|
| **Frontend** | React 18 + Vite + Tailwind + MUI icons | Static bundle → S3 → CloudFront. Zero server-side rendering. |
| **API** | FastAPI on Python 3.11+ | Type-hinted, auto OpenAPI, native `pyrfc` compatibility. |
| **Runtime** | AWS Fargate (ECS) behind ALB | One task per tenant class, horizontal scale on CPU. Image includes SAP NW RFC SDK 7.50 baked in. |
| **State** | DynamoDB (users, clients, wizard-state); S3 (artefacts, evidence); Secrets Manager (SAP creds, Anthropic API key) | Nothing in the container is stateful; safe to redeploy any minute. |
| **Auth** | AWS-style dual model: root user + IAM users with per-client scoping; JWT (RS256) with `role + client_scopes + ops` claims; PBKDF2-HMAC-SHA256 @ 600k iterations | Matches how customers already reason about AWS accounts. |
| **RFC layer** | `pyrfc` 3.x + SAP NW RFC SDK 7.50 (bundled in image) | Same SDK SAP ships to partners. `MFC_CODEPAGE=1100` for non-Unicode ECC. |
| **AI** | Direct `api.anthropic.com` (Sonnet 4.6 default, Opus 4.7 escalation). Bedrock deliberately not used. | Lower latency, no cross-region complications, pseudonymizer sits in front. |
| **IaC** | Terraform modules (ECR, ALB, Fargate, S3, CloudFront, DDB tables, Secrets Manager) | `terraform apply` from `terraform/environments/prod` builds the whole thing. |

### 2.3 Two runners (important to distinguish)

The subprocess model has **two** pipeline runners; they are not interchangeable.

| Runner | When it runs | Stage table | Output layout |
|---|---|---|---|
| `run_local_pipeline.py` (classic in-place) | Older code path, retained for backwards compat. Called by pre-v2 UI. | Non-numbered, spine-driven, streaming per-object telemetry via `spine.<Object>.progress` events. | `outputs/run_<ts>/final-report.json` |
| `run_local_lift_and_shift.py` (28-stage, current) | Called by the v2 wizard. | Numbered `stage1..stage27` plus `gate1/2/3` in 8 phases. | `local-staging/m4h-local/runs/<run_id>/<stage-dir>/*.json` and a `report/migration-report.pdf` at stage 27. |

**Everything below refers to the 28-stage lift-and-shift path** unless explicitly stated.

---

## 3. The 28-stage lift-and-shift pipeline

The runner's `STAGES` table (kept in sync with `terraform/modules/step-functions/lift_and_shift_pipeline.asl.json`) enumerates every step. Read it top-to-bottom as an SAP consultant would read a cutover plan.

### 3.1 Phase 0 — ASSESS (no writes)

| # | Stage | Handler | What it does in SAP terms |
|---|---|---|---|
| stage1 | Discovery Engine | `lambda/discovery-engine` | Live RFC scan: `TRDIR` (custom programs), `TADIR` (repository objects), `T001/T001W/TKA01/TVKO` (org structure), `FUGR/TFDIR` (function modules), `AGR_DEFINE` (PFCG roles), `RFCDES` (RFC destinations), `EDPP1` (IDoc partners). Writes `discovery/full-scan.json`. |
| stage2 | Sizing Advisor | `lambda/sizing-advisor` | Estimates HANA DB size from ECC's ST04 / DB02 data, recommends AWS instance shape. |
| stage3 | Object Router | `lambda/object-router` | Builds a DAG of migratable objects with dependencies. Each edge is a real SAP prerequisite (e.g., BusinessPartner depends on `[BPGrouping, CompanyCode]`). Outputs `object-router/dag.json`. |

### 3.2 Phase 1 — PROVISION

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage4 | Target Provisioner | `lambda/target-provisioner` | Mode-driven via `M4H_TARGET_MODE`: `sandbox` (spin up a CAL image), `launch_wizard` (SAP Cloud ALM handover), or `basis_handover_only` (customer's Basis team owns provisioning). |
| gate1 | Basis handover gate | HMAC-signed manual approval | Basis lead signs "target is ours to use." |
| stage5 | Basis Validator | `lambda/basis-validator` | RFC ping, `T000` (clients configured), `TMSCSYS` (STMS domain), `SICF` (IDoc XML endpoint), Migration Cockpit reachability probe. |

### 3.3 Phase 2 — CODE

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage6 | Code Analyzer (extract) | `lambda/code-analyzer` mode=extract | Reads `REPOSRC` (source), builds AST via `abap_ast_engine`. |
| stage7 | Code Analyzer (remediate) | `lambda/code-analyzer` mode=remediate | Applies AST transformations. See §5 for the rule set. |
| stage8 | Transport Artifact Builder | `lambda/transport-artifact-builder` | Packages remediated code as a **CTS+ workbench request** (`R3TR PROG`, `R3TR CLAS`, `R3TR FUGR`). |
| stage9a | Transport File Placer | `lambda/transport-file-placer` | Uses SSH (when available) or falls back to `manual_assembly_required` — writes co/data files to the target's `/usr/sap/trans` structure. |
| stage9b | Transport Import Executor | `lambda/transport-import-executor` | Runs `tp` add + import via `TRINT_IMPORT_MASS`. If RFC user lacks `S_ADMI_FCD`, falls back to `STMS_IMPORT` handoff. |
| stage9c | Transport Import Verifier | `lambda/transport-import-verifier` | Reads `E070/E071` and per-object activation logs to confirm. |

### 3.4 Phase 3 — CONFIG

Mirror of Phase 2 but for customizing:

| # | Stage | Handler |
|---|---|---|
| stage10 | Config Replicator (extract) — reads all customizing tables (`T001, T004, T009, T003, T030, TKA01, TKA02, CSKS, CEPC, T001L, T024E, T134, TVKO, TVTW, TSPA, TVKWZ, NRIV`, etc.) into `config/ecc-config-dump.json` |
| stage11 | BC Set Builder — creates 4 BC sets (`M4H_FINANCIAL, M4H_CONTROLLING, M4H_MATERIALSMGMT, M4H_SALESDISTRIBUTION`) |
| stage12 | Transport Artifact Builder (config) — `R3TR CUS` objects (PFCGRoles, BatchJobs, SmartForms, RFCDestinations, PartnerProfiles) |
| stage12a/b/c | File Placer / Import Executor / Import Verifier (config transport lane) |

### 3.5 Phase 4 — DATA_PREP

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage13 | Data Migrator (extract) | `lambda/data-migrator` mode=extract | Extracts source data per object via `RFC_READ_TABLE` (paginated). |
| stage14 | Data Hygiene | `lambda/data-hygiene` | Cross-field validation (`transformation_engine`), null-coalescing rules, DQ SLO gate. |
| stage15 | Data Migrator (generate_templates) | `lambda/data-migrator` mode=generate_templates | Writes Migration Cockpit CSV templates + LTMOM XML. |

### 3.6 Phase 5 — DATA_LOAD

The DAG from stage3 (`object-router/dag.json`) drives this phase. Each object flows through **exactly one** of the three lanes:

| # | Stage | Handler | Lane |
|---|---|---|---|
| stage16 | Migration Cockpit Orchestrator | `lambda/migration-cockpit-orchestrator` | LTMC — CSV / XML upload, project trigger via `MC_STARTPROJECT` (or its OData equivalent), monitors via `CNVMBTPROJ`. |
| stage17 | LTMOM Orchestrator | `lambda/ltmom-orchestrator` | For custom Z-tables lacking a Migration Cockpit object — auto-generates an LTMOM object from the source table structure. |
| stage18 | IDoc Orchestrator | `lambda/idoc-orchestrator` | IDoc inbound path (BankStatements → `FINSTA01`, ExchangeRates → `EXCHANGE_RATE`). |

### 3.7 Phase 6 — VALIDATE

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage19 | Migration Validator | `lambda/migration-validator` | 20-check post-cutover scorecard (see §14). |
| stage20 | Test Generator | `lambda/test-generator` | Auto-generates ABAP unit tests for the remediated custom code. |
| stage21 | Migration Completeness Analyzer | `lambda/migration-completeness-analyzer` | Row-count tie-out across every migrated object. |
| gate2 | Pre-cutover gate | Manual approval | Business + IT + Basis three-way sign-off. |

### 3.8 Phase 7 — CUTOVER

**This is where the "cutover precedence rule" (§9) kicks in.**

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage22 | Cutover Orchestrator (lock_ecc) | Sets ECC to read-only via `SU10` + client role change (or system message). |
| stage23 | Delta Extractor | Watermarked delta since last full extract (`M4H_CDC_WATERMARK`). |
| stage24 | Migration Cockpit Orchestrator (delta_load) | Same as stage16 but only for delta rows. |
| stage25 | Migration Validator (mode=final) | Re-runs the 20 checks against post-delta state. |
| gate3 | Final go-live gate | The cutover precedence rule is enforced here — see §9. |
| stage26 | Integration Activator | Re-activates RFC destinations, IDoc partner profiles, SICF services. |

### 3.9 Phase 8 — RUN

| # | Stage | Handler | Notes |
|---|---|---|---|
| stage27 | PDF Report Generator | `_inline_pdf_report` calls `pdf_report_generator.generate_pdf` | Assembles all `<stage-dir>/*.json` outputs into the 10-section report (§14). Also triggers `EvidencePack.write()` to seal the manifest into S3 with WORM Object Lock. |

**Total: 27 numbered stages + 3 gates + `_inline_pdf_report` = 31 items. The frontend Project tracker rolls these into 9 phase rows (ASSESS / PROVISION / CODE / CONFIG / DATA_PREP / DATA_LOAD / VALIDATE / CUTOVER / RUN) with per-phase percentages.**

---

## 4. Object catalog and migration lanes

### 4.1 The 24-object catalog (from `lambda/utils/conversion_mapping.py`)

| Category | Object | ECC tables | S/4 targets | Lane | Notes |
|---|---|---|---|---|---|
| **Master Data** | Customer | KNA1 + KNB1 + KNVV + KNVP | BUT000 + BUT020 + BUT100 + CMGR_BUSINESS_PARTNER | MC | Becomes BP with role FLCU01. CVI-driven. |
|  | Vendor | LFA1 + LFB1 + LFM1 | BUT000 + BUT020 + BUT100 | MC | Role FLVN01. |
|  | Material | MARA + MARC + MARD + MBEW + MAKT | MARA + MARC + MARD + MBEW + MAKT | MC | MATNR widened to 40 chars (was 18). |
|  | ProfitCenter | CEPC + CEPCT | CEPC + CEPCT | MC | Same tables. |
|  | CostCenter | CSKS + CSKT | CSKS + CSKT | MC | Same tables. |
|  | GLAccount | SKA1 + SKB1 + SKAT | SKA1 + SKB1 + SKAT | MC | Unified with cost element on S/4 (CSKB retired). |
|  | FixedAsset | ANLA + ANLB + ANLC + ANLZ | ANLA + ANLB + ANLC + ANLZ | MC | Uses `BAPI_FIXEDASSET_OVRTAKE_CREATE`. |
|  | Equipment | EQUI + EQKT | EQUI + EQKT | MC | PM/AM. |
|  | FuncLoc | IFLOT + IFLOTX | IFLOT + IFLOTX | MC | PM hierarchy. |
|  | Bank | BNKA | BNKA | MC | House bank. |
|  | ProductionBOM | MAST + STKO + STPO | MAST + STKO + STPO | MC | F1 resolves parent + children. |
|  | WorkCenter | CRHD + CRTX | CRHD + CRTX | MC | Plant-gated. |
|  | Characteristic | CABN + CAWN | CABN + CAWN | MC | CT04 classification. |
|  | Class | KLAH + KSML | KLAH + KSML | MC | CL02. |
|  | ProjectDefinition | PROJ | PROJ | MC | CJ20N anchor. |
|  | WBSElement | PRPS | PRPS | MC | Uses `BAPI_BUS2054_CREATE_MULTI`. |
| **Customising** | ExchangeRate | TCURR + TCURF + TCURV | TCURR + TCURF + TCURV | IDoc | M-rate type mandatory on S/4. |
| **Open Items** | OpenAR | BSID + BSAD | ACDOCA + BSEG + BKPF | MC | Universal Journal target. |
|  | OpenAP | BSIK + BSAK | ACDOCA + BSEG + BKPF | MC | Same. |
| **Stock** | InventoryBalance | MARD + MCHB + MKOL | MATDOC + MARD | MC | MM movement type 561. |
| **Transaction Data** | SalesOrder | VBAK + VBAP + VBKD | VBAK + VBAP + VBKD | MC | Open SO carry-over. |
|  | PurchaseOrder | EKKO + EKPO + EKKN | EKKO + EKPO + EKKN | MC | Materials must exist first. |
|  | BillingDocument | VBRK + VBRP | VBRK + VBRP | MC | Posted FI lands in ACDOCA. |
|  | ProductionOrder | AUFK + AFKO + AFVC | AUFK + AFKO + AFVC | MC | PP module. |

### 4.2 Lanes: how a row actually gets to S/4

| Lane | Volume rank | SAP-standard mechanism | When each lane is chosen |
|---|---|---|---|
| **BC_SET** | 5 objects | `SCPR3` BC Sets carried in a customizing transport (`R3TR CUS`) | Cross-client customizing (CompanyCode, ChartOfAccounts, ControllingArea, Plant, BPGrouping). |
| **MC** (Migration Cockpit) | 17 objects | LTMC / LTMOM standard SAP tool, CSV+XML upload, `MC_STARTPROJECT` orchestration | Every master-data + transaction-data object with a shipped MC content template. |
| **CTSplus** | 5 objects | `R3TR CUS` for the customizing objects that aren't cleanly a BC Set (PFCG roles, batch jobs, smartforms, RFC dests, partner profiles) | Anything that ships via workbench transports rather than BC Set structure. |
| **IDoc** | 2 objects | IDoc inbound (`EXCHANGE_RATE`, `FINSTA01`) | Where SAP publishes an inbound IDoc as the standard interface. |
| **LTMOM** | 1 object | LTMOM custom-object generation for Z-tables | Custom Z-tables with no MC content template. |
| **abapGit** | 1 object | Round-trip via git for the remediated ABAP artefacts | Version-controlled code delivery. |
| **manual** | 1 object | Human step (number range unlocking via `SNRO`) | The one operation SAP does not allow to be automated. |

### 4.3 SAP-shipped APIs actually called (release-approved only)

| Category | BAPI / API | S/4 caveat |
|---|---|---|
| Customer / Vendor / BP | `BUPA_CREATE_FROM_DATA`, `BUPA_ROLES_UPDATE` | Classic `BAPI_CUSTOMER_CREATE_FROM_DATA` is BLOCKED on S/4. Must use BP flow (see [[partner-readiness-cvi]] in project memory). |
| Material | `BAPI_MATERIAL_SAVEDATA`, `BAPI_MATERIAL_MAINTAINDATA_RT` | MATNR length change requires customizing (`OMSL`). |
| FI Document | `BAPI_ACC_DOCUMENT_POST` | Lands in ACDOCA via posting event; BSEG is derived. |
| Cost Center | `BAPI_COSTCENTER_CREATE_MULTIPLE` | KOKRS + KOSTL. |
| Profit Center | `BAPI_PROFITCENTER_CREATE` | Same. |
| GL Account | `BAPI_GL_ACC_MASTER_SAVE` | Unified cost element on S/4 requires `KTOKS` set. |
| Fixed Asset | `BAPI_FIXEDASSET_OVRTAKE_CREATE` | Mid-year takeover, IFRS + local GAAP ledgers. |
| WBS | `BAPI_BUS2054_CREATE_MULTI` | Multi-struct. |
| Exchange Rate | `BAPI_EXCHANGERATE_GETLIST` (read), inbound IDoc for write | TCURV rate type prerequisite. |
| Migration Cockpit trigger | `MC_STARTPROJECT` (RFC), `LTMC_API` (OData), fallback: `xbp_job` submission | 5-strategy trigger chain (see [[mc-job-trigger]] memory). |

**We never call:** `RFC_WRITE_TABLE`, `RFC_CALL_SYSTEM`, `SE16N` update, `/BODS/RFC_ABAP_INSTALL_AND_RUN`, any SUM/Maintenance-Planner bypass. This is the "support_compliance" verdict in `data-migrator/summary.json` — `NO-WRITES` for direct table access, always.

---

## 5. Code remediation engine (ABAP AST)

### 5.1 Four-stage pipeline (this is what the "Lexer / Parser / Transformer / Output safety net" log lines mean)

```
   REPOSRC.TEXT
        │
        ▼
   ┌─────────┐   tokens (keywords, identifiers, literals)
   │  Lexer  │────────────────────────────┐
   └─────────┘                            │
        │                                 ▼
        ▼                        ┌─────────────────┐
   ┌─────────┐   AST (all         │  Diagnostics    │
   │ Parser  │   top-level        │  logger         │
   └─────────┘   stmts + errors)  └─────────────────┘
        │                                 │
        ▼                                 │
   ┌────────────┐  patched AST            │
   │Transformer │  (N changes applied)    │
   └────────────┘                         │
        │                                 │
        ▼                                 ▼
   ┌────────────────┐  regenerated source
   │ Output safety  │  byte-diffed against original;
   │      net       │  lossy lines restored from original
   └────────────────┘  (correctness > completeness)
        │
        ▼
   REPOSRC.TEXT (remediated)
```

The **safety net** is the correctness guarantee: if any line doesn't survive the parse→edit→reprint round-trip byte-for-byte, we keep the **original** line. Losing a line to a formatting quirk is unacceptable; the tool would rather leave that line un-modernised.

### 5.2 Rule catalog

| Rule ID | What it modernises | Example transform |
|---|---|---|
| `OBS_002` | `MOVE 'X' TO Y.` → `Y = 'X'.` | Inline assignment. |
| `OBS_004` | Obsolete comparison operators (`EQ / NE / GT / LT / GE / LE`) → symbolic (`= / <> / > / < / >= / <=`) | Only on plain scalar compares; string ops keep the word form. |
| `OBS_005` | `CALL METHOD F1->WRITE_DATA.` → `F1->WRITE_DATA( ).` | Functional-form invocation. |
| `FIORI_002` | `SET PF-STATUS 'HELP'.` → `M4H_LOG( 'Fiori replaces GUI status: HELP' ).` | GUI status bars die on Fiori; we replace with a logger so runtime doesn't dump. |

**In-flight (planned):** SELECT…INTO TABLE `itab` → `INTO TABLE @itab` (Open SQL escaped host vars), CDS view suggestions for repeated JOIN patterns, native SQL hint removal.

### 5.3 ATC + SAP official validation

Two toggles the tool exposes but keeps **OFF by default** in the customer's system:

- `atc_integration`: Would call `ATC_CHECK_RUN` on the target and merge findings into the same report. Off by default because it requires ATC to be set up on the target with our variant.
- `sap_official_validation`: Would enroll each remediated program through `SDMO_MIGRATION_CHECK` (SAP's shipped S/4 migration check tool). Off by default because most customers don't have this installed.

Turning both ON changes the report from "our AST engine says 0 errors" to "our AST engine says 0 errors AND SAP's ATC + SDMO check says 0 findings" — a much stronger auditor position.

---

## 6. Configuration framework (country and module matrix)

### 6.1 The "17 countries × N modules" grid (see `config/global-config-payload.json`)

The tool ships a pre-mapped compliance module catalog per country. Consultant recognises these instantly:

| Country | # modules | Includes |
|---|---|---|
| **Germany** | 16 | GoBD (immutable audit trail), EU_GDPR_RETENTION, DATEV_EXPORT (SKR03/SKR04 mapping), SEPA (pain.001/008), HGB retention, ELSTER, UStVA (S_ALR_87012357), Intrastat, KassenSichV / TSE, PEPPOL |
| **India** | 14 | GST_SETUP (TAXINN, JIIG/JICG/JISG), TDS_CONFIG (extended WHT), E_INVOICE_API (NIC/IRP), E_WAY_BILL, PAN/GSTIN validation, HSN/SAC codes, GSTR-1/2A/3B extraction, PF/ESI, Professional Tax, Aadhaar, TCS 206C, RCM, ITC rules 42/43 |
| **US** | 14 | Multi-jurisdiction sales/use tax (Vertex integration), SOX 404 audit trail, US GAAP CoA + parallel ledger, 1099-MISC/NEC/INT, OFAC screening, W-2/W-4/W-9, FICA/FUTA, ACH/NACHA, ASC 842 (leases), ASC 606 (revenue), state payroll (all 50 states), FATCA, post-Wayfair economic nexus |
| **Brazil** | 12 | NF-e (SEFAZ), SPED (ECD/ECF/EFD-ICMS/IPI), ICMS (inter/intra-state, ICMS-ST, DIFAL), PIS/COFINS, CNPJ/CPF validation, NCM codes, CFOP, IRRF, DARF, eSocial, EFD-Reinf, J_1B* tables |
| **UK** | 10 | MTD VAT (HMRC API OAuth2), UK VAT rates (post-Brexit), PAYE RTI, Brexit customs + NI protocol, FRS 101/102, BACS + Faster Payments, CIS, auto-enrolment pension, IR35, Plastic Packaging Tax |
| **France** | 13 | FEC (mandatory JV file for tax audit), DSN (unified social declaration), TVA CA3/CA12, Chorus Pro + Factur-X (ZUGFeRD), SIRET/SIREN, DEB/DES, PAS (income tax at source), CET (CFE+CVAE) |
| **Italy** | 11 | Fattura Elettronica via SDI (FatturaPA 1.2), Esterometro, Codice Fiscale + Partita IVA, Certificazione Unica, J_1I* programs, CIG/CIGS |
| **China** | 10 | Golden Tax (Aisino/Baiwang), Fapiao, multi-rate VAT (13/9/6/0), CIT, CAS/ASBE CoA, GB/T standards, wu xian yi jin, SAFE reporting, bank-tax integration, quan dian fa piao |
| **Australia** | 8 | BAS (GST + PAYG), STP Phase 2, Superannuation 11.5%, ABN, PAYG withholding, TPAR, FBT, WorkCover |
| **Mexico** | 6 | CFDI 4.0 + PAC, SAT (DIOT), RFC, IVA/ISR, J_1M*, Nomina CFDI 1.2 |
| **Saudi Arabia** | 6 | ZATCA Zakat + CIT, Fatoora e-invoicing Phase 2, SA VAT 15%, WPS, GOSI, Nitaqat |
| **Singapore** | 5 | GST 9%, PEPPOL InvoiceNow, IR8A + SDL + FWL, CPF, IRAS corp tax |
| **Poland** | 10 | JPK SAF-T (V7M/K, FA, MAG), Split Payment, NIP + biala lista, KSeF (mandatory Feb 2026), PL VAT rates, Intrastat, OSS/IOSS |
| **Switzerland** | 5 | Swiss VAT (MWST/TVA/IVA) 8.1%, QR-bill (SIX spec), AHV/AVS, BVG/LPP, Swiss GAAP FER |
| **Indonesia** | 5 | e-Faktur (DJP), PPh 21, PPh 23, BPJS, customs (PPnBM) |
| **Sweden** | 9 | Swedish VAT (moms) 25%, PEPPOL BIS 3.0, Skatteverket AGI, SAF-T 2.0, Intrastat |
| **Turkey** | 5 | KDV, e-Fatura (GIB), e-Arsiv, e-Defter, SGK |
| **Austria** | 9 | Umsatzsteuer 20%, FinanzOnline, Sozialversicherung ASVG, Registrierkassenpflicht |

Each module carries a `description`, an `sap_transaction` path (SPRO / T-code), and `implementation_notes` (rate ceilings, thresholds, integration hooks). Company codes are assigned to a country at stage 10 based on `T001.LAND1`, and the modules are activated only if that company code appears in the migration scope. This is why the report always shows a per-country breakdown.

### 6.2 The S/4 config checklist (from `config/s4-config-checklist.json`)

Fixed 19 items per run, ordered by priority:

| Priority | Task | S/4 transaction |
|---|---|---|
| **critical** | Configure Universal Journal ledgers (0L leading + IFRS extension) | `FINSC_LEDGER` |
| **critical** | Configure BP number ranges + CVI sync | `BUCF` |
| **high** | Configure Fiori Launchpad spaces + catalogs (T-code → app mapping) | `/UI2/FLPD_CUST` |
| **high** | Configure parallel currencies in Universal Journal | `FINSC_LEDGER` |
| **medium** | Theme (Quartz / Horizon), spaces & pages, app catalog, target mappings | Various |
| **medium** | BP number range (SNRO object `BU_PARTNER`), CVI sync direction, role category mapping, grouping | `SNRO` + `BUCF` |
| **medium** | Ledger config (leading vs non-leading), currency types, extension ledger, COPA integration | `FINSC_LEDGER` |
| **medium** | Output types → BRF+ rules, Adobe Forms → Fiori print forms, email templates | `SPRO` output management |

---

## 7. Data-migrator internals: spines, idempotency, dead-letter

### 7.1 Spine orchestrator model

Every migratable object has a dedicated **spine orchestrator** in `lambda/data-migrator/spines/`. A spine is a pure function:

```
spine(source_row, target_config, key_map_ledger)
   → (target_key, disposition, evidence)
```

Where `disposition` is one of:

| Disposition | Meaning | Chain effect |
|---|---|---|
| `created` | BAPI succeeded, new record on S/4. | New entry in key-map ledger. |
| `created_ready` | BAPI succeeded, awaiting post-processing (e.g., MC batch activation). | New entry. |
| `matched_existing_ledger_hit` | Source key resolved to a target key that already exists on S/4 (idempotent). | No BAPI called, ledger entry preserved. |
| `harmonized` | Source key duplicates another source key that we've already merged into a canonical target. | Cross-reference entry. |
| `remapped_matched` | Source key was rewritten to a different target key at customer's explicit request (e.g., MATNR renumbering). | Aliased entry. |
| `dead_letter` | Spine refused the BAPI call because data-quality validation failed. Row is written to `dead-letter/failed_records.json`. | No ledger entry. |

**Why this matters to the SAP consultant:** the dispositions are the tool's answer to "did we actually create data, or did we skip because of idempotency?" This is the single most-asked question in a Big-4 audit review, and the report has an exact number for each bucket.

### 7.2 Key-map ledger (audit-grade)

- Physical location: `data-migrator/keymap/key_mapping.json` + `key_mapping_audit.csv`.
- Structure: nested by object → source_key → `{target, disposition}`.
- Hash-chained: every append triggers a SHA-256 append to `audit_chain.jsonl`.
- Persisted across runs (see `scripts/backup-key-map.ps1` + `scripts/restore-key-map.ps1`) — this is what makes re-runs idempotent.
- Failure story: if the ledger is corrupted (single-bit flip), the audit chain fails verification at the next run and the pipeline refuses to start (no silent recovery). The `restore-key-map.ps1` procedure is documented in `docs/DR.md`.

### 7.3 Dead-letter queue

A row lands here when:

1. Data-quality validation fails **before** the BAPI is called (5% of the dead-letter volume in typical runs). Example: `NAME is required` on a BusinessPartner row where KNA1.NAME1 is null.
2. The BAPI is called and returns a hard rejection (95% of DL volume). Example: `BAPI_FAILURE — rate type 001 not defined in target (TCURV)`.

`failed_records.json` shape:

```json
{
  "object": "OpenAR",
  "source_key": "1800000001",
  "code": "DATA_QUALITY_REJECTION",
  "messages": ["cc_org missing: COMP_CODE,CLEARING"],
  "lane": "MC"
}
```

**Reprocess policy:** idempotent — after the operator fixes the source data and re-runs, the spine looks up each source_key in the key-map ledger; already-loaded records get `matched_existing_ledger_hit`, only the DL ones re-attempt the BAPI.

### 7.4 Data-Quality SLO gate

- `M4H_DEAD_LETTER_THRESHOLD_PCT` env var — defaults to 5.0.
- If `dead_letter_pct > threshold`, the summary flags `slo_breach: true` and the validator downgrades the "BP Data Quality" scorecard check.
- The gate can be disabled per run via `M4H_DQ_GATE_DISABLE=1` but this appears explicitly in the evidence pack (auditor can see the operator bypassed it).

### 7.5 Reconciliation engine

At stage19 and stage25 the tool runs three reconciliation flavours:

| Category | What it ties out | Where it reads |
|---|---|---|
| **Financial** | GL balance per company code, source ECC vs S/4 ACDOCA | `FAGLB03` spool + `ACDOCA` sample read |
| **Material Ledger** | Actual costing config coverage, CKMLHD accessibility, period status | `CKMLHD` + `T001W` + material-ledger valuation areas |
| **SUM completion** | S/4CORE component version, HANA DB confirmation, sum_completion.log | `CVERS` + `DBCON` |

Verdicts:
- `BALANCED` — all tie-outs pass (zero variance).
- `VARIANCE` — at least one variance > 0.
- `NOTHING_TO_RECONCILE` — no post-cutover data to compare.

---

## 8. Execution modes: extract-only, simulation, live load

Three modes; the UI's LoadModeChooser exposes them as two cards + one checkbox.

| Mode | env vars | What the spines do | Reversibility | Grade impact |
|---|---|---|---|---|
| **Extract-only** (default) | `M4H_LOAD_TO_S4=0` | Read from ECC, transform, write MC CSVs to `local-staging/…/data-migrator/mc/`. **No BAPIs called.** | Fully reversible — nothing changes on S/4. | Grade capped at ~55% because ACDOCA / BUT000 / MATDOC checks find target empty. |
| **Simulation** (dry-run) | `M4H_LOAD_TO_S4=1` + `M4H_SIMULATE=1` | Read from ECC, transform, call BAPIs with `TEST_RUN=1` where supported and route to staging tables otherwise. **Nothing commits.** | Fully reversible — S/4 unchanged. | Same as live-load for the audit / scorecard perspective — spines emit the same dispositions, dead-letters, and per-object counts. |
| **Live load** | `M4H_LOAD_TO_S4=1` + `M4H_SIMULATE=0` | Full BAPI writes with commit. Idempotent via key-map ledger. | **Not reversible.** BAPIs are release-approved but rows are real. | Grade lift toward A/B assuming transports imported and DQ SLO not breached. |

Attempt-cap knobs (currently env-only; UI exposure planned):
- `M4H_LOAD_MAX_ROWS` — default 5 (safety-first). Ships as 30 in the deployed image.
- `M4H_LOAD_MAX_ROWS_<OBJECT>` — per-object override (e.g. `M4H_LOAD_MAX_ROWS_CUSTOMER=1000`).

**Simulation caveats to be honest about:**
- Not all BAPIs support a true `TEST_RUN` parameter — for those, the spine falls back to writing to `M4H_STAGING_<OBJECT>` tables (created by the config transport). The evidence pack notes which BAPIs ran in TEST_RUN vs staging fallback so the auditor can see the difference.
- CVI + BP creation flows do not have a true test-run mode on S/4. The staging fallback creates a `BUT000` shadow row in a test tenant client — this is the reason we insist the customer's first live run be against a non-production client.

---

## 9. Governance, gates, and cutover precedence rule

### 9.1 Three HMAC-signed gates

| Gate | When it fires | Who signs |
|---|---|---|
| **gate1** — Basis handover | After stage5 (basis-validator) | Basis lead |
| **gate2** — Pre-cutover | After stage21 (completeness analyzer) | Business + IT + Basis three-way |
| **gate3** — Final go-live | After stage25 (final validator) | Migration lead + CFO (for FI-heavy scope) |

Each gate carries an HMAC signature (`M4H_GATE_HMAC_KEY` from Secrets Manager) so no one can forge an approval by clicking through the UI without the signing key.

### 9.2 Cutover precedence rule (the "auditor question")

This is the single most-asked question by Big-4 reviewers. It's coded into `EvidencePack._compute_cutover_verdict`:

> **SAP-standard system reports** (FAGLB03, MB5B, FBL1N, FBL5N) **take precedence** over the tool's internal reconciliation ledger. The cutover gate is `NO_GO` if any of these hold:
>
> (a) A balance tie-out shows variance > 0 (source vs target), OR
> (b) Any LTMC handoff is still pending import, OR
> (c) No captured spool was produced for the financial close objects (auditors require at least FAGLB03 + MB5B).
>
> The tool's hash-chained ledger **cannot override** this verdict to GO; it can only confirm it.

**Why this exists:** auditors will not accept a bespoke tool's internal ledger as evidence of financial correctness. They will accept the tool as evidence only when the tool defers to SAP-standard reports. This rule enforces that deference explicitly.

### 9.3 Spool capture

Stages 25 (validator/final) and 26 (integration-activator) call `spool_capture.CapturedSpool` to run `FAGLB03` (GL balance display) and `MB5B` (stock on posting date) on both source ECC and target S/4, capture the SPOOL binary bytes (unmodified), SHA-256-hash them, and seal into the audit chain **before** the manifest is written.

The output is stored as raw binary blobs so auditors can re-run the same T-code themselves and byte-compare.

---

## 10. Compliance and auditing: hash chain, evidence pack, WORM

### 10.1 Hash-chain ledger (`HashChainLedger`)

- Every append call takes an `event_type` and a `payload` dict.
- Block hash = `SHA256(prev_hash + canonical_json(payload) + timestamp)`.
- Verification is `O(n)` re-hash from the genesis block.
- Storage: append-only JSONL file at `data-migrator/audit_chain.jsonl`.

Event types that get sealed:
- `run_started`
- `stage_completed` (per stage)
- `key_map_appended` (per row)
- `dead_letter_appended` (per DL row)
- `captured_spool` (per FAGLB03 / MB5B capture)
- `cutover_no_go` (only if gate3 refuses)
- `evidence_pack` (the manifest itself is chained)

### 10.2 EvidencePack manifest structure

```json
{
  "run_id": "wiz-20260616T123053Z-fb94644d",
  "generated": "2026-06-16T12:54:47.638Z",
  "classification": "CONFIDENTIAL — Auditor Evidence (immutable)",
  "system_config": {...},
  "data_quality": {...},
  "target_api_responses": [...],
  "balance_tie_outs": [...],
  "reconciliation": {...},
  "captured_spools": [...],
  "ltmc_pending": {...},
  "cutover_verdict": {...},
  "audit_chain": {"head_hash": "…", "verification": true},
  "manifest_sha256": "…",
  "sealed_block_hash": "…"
}
```

### 10.3 S3 WORM Object Lock

`EvidencePack.write` uploads the manifest to `M4H_EVIDENCE_BUCKET` (a bucket created with Object Lock enabled at creation, per Terraform module in `terraform/modules/dynamodb`) using:

```python
boto3.client("s3").put_object(
    Bucket=bucket, Key=key, Body=body,
    ContentType="application/json",
    ObjectLockMode="COMPLIANCE",
    ObjectLockRetainUntilDate=datetime.now(timezone.utc) + timedelta(days=2555))
```

`COMPLIANCE` mode (not `GOVERNANCE`) means **not even the AWS account root** can delete the object before the retention window expires. 2555 days ≈ 7 years, the standard SOX / IFRS retention window.

---

## 11. SAP prerequisites

**Print this section and take it to the customer's Basis lead.** These are the exact items that need to exist before the tool can run against a live system.

### 11.1 Source ECC (read-side)

| Item | Requirement |
|---|---|
| **Release** | ECC 6.0 EHP7 or higher (EHP6 works but the tool warns on EHP < 7). |
| **Unicode** | Non-Unicode (codepage 1100 / SAP_LATIN1) or Unicode (4103) both supported. Set `M4H_ECC_CODEPAGE` in the wizard's connection form. |
| **RFC gateway** | Reachable from the api_server host (Fargate task). For customer-hosted ECC behind a firewall, use SAP Router or ngrok TCP tunnel (see `docs/RUNBOOK.md`). |
| **Service user** | Type: SERVICE (not DIALOG). Non-expiring password (or provide a rotation runbook). |
| **Authorizations for the service user** | See §11.3 below. |

### 11.2 Target S/4HANA (write-side)

| Item | Requirement |
|---|---|
| **Release** | S/4HANA 2022 or higher (1909 works for CAL image runs). |
| **Client openness** | Client must be open for customizing (`SCC4`: T000 client role = C or T, cross-client customizing allowed). |
| **Migration Cockpit** | Fiori tile `Migrate Your Data` (transaction `LTMC` / OData service `/UI2/CDST_MIGRATION_COCKPIT`) must be reachable. |
| **LTMOM** | Available via `LTMOM` T-code for custom Z-table migration. |
| **CVI** | Active on **both** source ECC and target S/4 (customer/vendor to BP synchronization). Check `CVI_MAINTAIN_CUST` in SPRO. |
| **BP number ranges** | Object `BU_PARTNER` (SNRO), external number range for wave migration. |
| **STMS** | Domain configured, transport routes include the target's DEV client. |
| **CTS+ transport tools** | `tp` binary + `R3trans` available on target host (default on any healthy S/4 install). |
| **IDoc partner profiles** | For BankStatements + ExchangeRates: partner profile in WE20 with the corresponding inbound process code. |

### 11.3 SAP authorizations for the service user (copy-paste for role definition)

| Auth object | Value | Why |
|---|---|---|
| `S_RFC` | `RFC_TYPE=FUNC`, `RFC_NAME=SDIFRUNTIME, RFC_ABAP_INSTALL_AND_RUN, SYST, DDIF_FIELDINFO_GET, RFC_READ_TABLE, BAPI_*, BUPA_*, LTMC_*` | RFC access to every BAPI + read utility. |
| `S_TABU_DIS` | `DICBERCLS=FC, ACTVT=03` | Read customizing tables (T001, TKA01, CSKS, etc.). |
| `S_TABU_DIS` | `DICBERCLS=SS, ACTVT=03` | Read system tables. |
| `S_DEVELOP` | `DEVCLASS=*, OBJTYPE=PROG/CLAS/FUGR/TABL/VIEW, OBJNAME=*, ACTVT=03` | Read repository objects for discovery + code analysis. |
| `S_TCODE` | `TCODE=SE38, SE80, STMS, SM59, SNRO, PFCG, LTMC, LTMOM, WE20, WE21, SCC4, FAGLB03, MB5B, CKMLHD, FBL3N, FBL5N` | T-code launch for the standard reports we scrape. |
| `S_ADMI_FCD` | `S_ADMI_FCD=TABL` | Direct table access for CDC extraction. |
| `S_BTCH_ADM` | `Y` | For MC batch jobs. |
| `S_DATASET` | `PROGRAM=*, FILENAME=/usr/sap/trans/*, ACTVT=33/34/06/A6/A7` | Transport co/data file placement. |
| `S_TABU_LIN` | Depends on scope | Line-level table access (org unit dimensions). |
| `S_ARCHIVE` | Full | For archive-integrated document reads. |
| `B_USERSTAT` | Full for MC-owned change docs | Migration Cockpit uses status control. |
| Financial | `F_BKPF_BLA, F_BKPF_BUK, F_BKPF_GSB, F_FAGL_LDR` | FI document + GL Balance access (FAGLB03). |
| MM | `M_MATE_STA/WRK/MAR` | Material master + plant + storage location. |
| SD | `V_KNA1_BRG, V_VBAK_AAT` | Customer + sales-order access. |
| HR (only if HR in scope) | `P_PERNR, P_ORGIN` | Payroll object reads. |

### 11.4 SAP NW RFC SDK

- Version: 7.50 SP12 or later.
- Bundled inside the Fargate image (`docker/Dockerfile`) — customer doesn't install it.
- If running locally on Windows, download from SAP Software Downloads (S-user required) and drop into `sapnwrfc/` — see `scripts/setup-pyrfc.sh`.

### 11.5 Migration Cockpit content

The tool assumes SAP-shipped MC content templates for the 17 MC-lane objects. These are pre-installed on every S/4 2022+ image. If the customer has custom MC content, they must merge our template into theirs — LTMOM has a merge tool for this.

### 11.6 Basis coordination touchpoints

Six things the customer's Basis team **must** do, regardless of what the tool automates:

1. **Import the code transport** via STMS (stage 9b falls back to `manual_assembly_required` when SSH is not available).
2. **Import the customizing transport** via STMS (stage 12b same).
3. **Unlock the BP number range** in SNRO before stage 16 kicks off the MC project — automation is not allowed by SAP for this operation.
4. **Activate BC Sets** post-import via `SCPR20` (some BC Sets fail if activated by the transport importer instead of a user with `S_TABU_CLI`).
5. **Confirm client openness** for cross-client customizing on the target client (SCC4 setting).
6. **Approve gate1/gate2/gate3** in the tool's UI (HMAC-signed, so requires the M4H_GATE_HMAC_KEY the Basis lead holds).

---

## 12. Deployment and operations

### 12.1 AWS resource inventory (from `terraform/environments/prod`)

| Resource | Purpose |
|---|---|
| **VPC** | 3-AZ, private subnets for ECS tasks + public subnets for ALB. |
| **ALB** | HTTPS-only (WAF), routes `/api/*` to the api_server target group; everything else falls through to a CloudFront function that serves the SPA. |
| **ECS + Fargate task** | 2 vCPU / 4 GB — one per environment. Auto-scales 1..4 on CPU. |
| **ECR** | `migrate4hana-api-server-prod` — pushed via `.\scripts\deploy-ui-aws.ps1`. |
| **S3 buckets** | `m4h-ui-<env>` (SPA bundle), `m4h-artifacts-<env>` (per-run local-staging mirror), `m4h-evidence-<env>` (WORM, Object Lock, 7-year retention), `m4h-audit-logs-<env>` (CloudTrail sink). |
| **CloudFront** | UI distribution. Custom_error_response is NOT set distribution-wide (would swallow API errors); SPA fallback is a CloudFront Function on the default behavior. |
| **DynamoDB** | `m4h-users`, `m4h-clients`, `m4h-wizard-state` (7-day TTL). |
| **Secrets Manager** | `m4h/ecc-conn-<client>`, `m4h/s4-conn-<client>`, `m4h/anthropic-key`, `m4h/gate-hmac-key`. All secrets: `recovery_window_in_days=0` so `terraform destroy` fully cleans up. |
| **CloudWatch Log Groups** | `/aws/ecs/m4h-api-server-<env>`, `/aws/stepfunctions/m4h-lift-and-shift-<env>`, `/aws/lambda/m4h-<name>-<env>`. |
| **KMS** | Customer-managed key for Secrets Manager + S3 evidence bucket. |

### 12.2 Deployment sequence (one command)

```powershell
.\scripts\deploy-ui-aws.ps1
```

Chains:
1. `terraform apply` (creates/updates ECR, ALB, Fargate, S3, CloudFront, DDB tables, Secrets Manager, KMS).
2. `docker build` (api_server image with bundled SAP NW RFC SDK).
3. `aws ecr get-login-password | docker login`, push image.
4. ECS service force-redeploy.
5. `npm install && npm run build` in `frontend/`.
6. `aws s3 sync frontend/dist s3://m4h-ui-<env>`.
7. CloudFront invalidation.

Flags: `-SkipApi` (UI-only, ~2 min), `-SkipUi` (backend-only).

### 12.3 Multi-tenant model

- **Root user** = AWS account root equivalent, no client scope, sees every tenant.
- **IAM user** = scoped to N `client_id`s, has an `allowed_operations` list.
- Each tenant's data lives under `outputs/clients/<client_id>/` (S3 `m4h-artifacts-<env>/clients/<client_id>/`).
- Each tenant's SAP passwords live in Secrets Manager under `m4h/<sap_system>-conn-<client_id>`.
- Wizard state is scoped by (client_id, run_id) with 7-day DDB TTL.

Onboarding a new tenant: `.\scripts\onboard-tenant.ps1 -Client Acme -RootAdmin admin@acme.com`.

### 12.4 Observability

| Signal | Where |
|---|---|
| API server logs | CloudWatch Log Group `/aws/ecs/m4h-api-server-prod`. |
| Runner subprocess stdout/stderr | Streamed to CloudWatch via ECS task, also written to `local-staging/…/logs/`. |
| Per-run structured JSON | `local-staging/m4h-local/runs/<run_id>/<stage>/*.json`. |
| Telemetry endpoint | `GET /api/runs/<id>/telemetry` — polled at 3 Hz by the Project page. |
| Evidence chain integrity | `HashChainLedger.verify()` reads the JSONL and re-hashes; called at every stage boundary. |

---

## 13. AI enhancement layer

### 13.1 Where AI plugs in

The tool has 6 well-defined AI "hooks" — everywhere else is deterministic. Each hook works when `M4H_ANTHROPIC_API_KEY` is set in Secrets Manager; when absent, the deterministic fallback runs.

| Hook | Model routed to | Deterministic fallback |
|---|---|---|
| Code remediation classifier (severity + fix explanation) | Sonnet 4.6 (default), Opus 4.7 (escalation for complex programs) | Bucket everything as "Medium" severity with a generic hint. |
| Dead-letter remediation suggester | Sonnet 4.6 | Static hint catalog (see `lambda/utils/telemetry._REMEDIATION_HINTS`). |
| Role → Fiori catalog mapper | Sonnet 4.6 | Report shows the 3 hand-curated examples (MM03/FBL3N/XK03). |
| Integration triage (RFC destinations bucketing) | Sonnet 4.6 | Report shows total count only, no classification. |
| CDS view suggestion engine | Sonnet 4.6 | `cds_suggestions: 0`. |
| Report executive summary narrative | Sonnet 4.6 | Bullet-list section headers only. |

### 13.2 Pseudonymizer (protects source ABAP)

Before any ABAP is sent to Anthropic, `lambda/utils/pseudonymizer.py` runs a deterministic transform:

- Program name `Y_CUSTOMER_ORDER_REPORT` → `Y_A_B_C` (letters mapped to opaque token, mapping stored in memory only).
- Literal customer names, VAT numbers, account numbers, dates → tokens.
- Variable names, method names, class names → tokens.
- The demonstrably-not-sensitive keywords (SELECT / FROM / WHERE / etc.) are preserved.

After the AI returns a suggestion, the reverse map re-hydrates the tokens. The customer's actual business logic never sits in the AI vendor's context.

Enforcement: `_pseudonymizer_required()` returns `True` when `AWS_LAMBDA_FUNCTION_NAME` env var is set (i.e., when running in Lambda/Fargate). If import fails there, the code raises rather than silently sending raw ABAP.

### 13.3 Model routing

- Bedrock deliberately not used (per project memory [[anthropic-direct-api]]).
- Sonnet 4.6 default, Opus 4.7 escalation.
- Key stored in Secrets Manager, resolved at container start.
- Retry logic: exponential backoff with jitter, max 3 attempts, then falls back to deterministic path.

### 13.4 Model governance (project memory [[model-routing]])

- Opus 4.7 owns the entire roadmap until any customer signal to unblock a different model.
- Fable 5 banned per USA lawsuit (2026-06-14) — this is baked into the model selection code.

---

## 14. Reporting and scoring

### 14.1 The 10-section PDF (generated by stage27 via `pdf_report_generator`)

1. **Executive Summary** — Client, source, target, org scope, users, blocking issues.
2. **Code Remediation** — Issues detected, auto-remediated, fix rate, severity breakdown, key transformations.
3. **Data Migration** — Per-object row counts, disposition breakdown, spine orchestrator per object, CVI status, dead-letter classes, sample disposition outcomes.
4. **Configuration** — Universal Journal ledgers, number ranges, BP groups, Fiori catalogs, India localization block.
5. **Roles & Authorizations** — PFCG roles found, Fiori apps mapped, key T-code → Fiori mappings.
6. **Integrations** — RFC destinations total, auto-migrated, manual review needed, automation rate.
7. **GO-LIVE Scorecard** — the 20-check breakdown (see §14.2).
8. **Risk Assessment** — HIGH/MEDIUM/LOW rated risks with mitigations.
9. **Post Go-Live Roadmap** — Hypercare (W1-2), Stabilization (W3-6), Optimization (Q2+).
10. **Technical Metrics** — RFC calls executed, pipeline duration, programs deployed, transport request.

Plus **Appendix A** with 34 sub-artefact renderings (Discovery, Sizing, Object Router, Target Provisioner, Basis Validator, Code Analysis, Transports, Config, BC Sets, Data Migrator, Execution).

### 14.2 The 20-check scorecard (`execution/go-live-scorecard.json`)

Every check bucket:

| Category | Max | What it validates |
|---|---|---|
| Code | 0 | Placeholder — populated when SDMO integration is on. |
| Data | 3 | ACDOCA populated, BUT000 populated, MATDOC populated. |
| Config | 2 | Company codes configured, BP number ranges configured. |
| Roles | 0 | Placeholder — populated when role-migrator runs against live PFCG. |
| Integrations | 0 | Placeholder — populated when integration-mapper runs. |
| Finance | 1 | ACDOCA data present. |
| Fins Reconciliation | 4 | GL balance CC 1710, GL balance CC 1010, document count, open items. |
| Material Ledger | 3 | CKMLHD accessible, actual costing config, period status. |
| Sum Completion | 3 | S/4CORE component version, database is HANA, sum completion log. |
| BP Crosswalk | 1 | Crosswalk data exists. |
| BP Data Quality | 1 | Pre-validation exists. |
| **Total** | **20** | Grade = A (95+), B (80+), C (65+), **D (50+)**, F (<50). |

Recommendation string is deterministic:
- Grade A/B: `GO LIVE READY`
- Grade C: `CAUTIOUS GO LIVE — dashboard review recommended`
- **Grade D**: `DO NOT GO LIVE — major issues found` (what current runs return)
- Grade F: `HALT — critical failures`

### 14.3 Extract-only vs live-load grade math

An extract-only run's ceiling is Grade D because the target-checking bucket (Data + BP + FI recon) can only pass when target-side writes have landed. This is by design — the grade is honest about what the tool did, not marketing.

Bumping to a live-load run with imported transports typically returns Grade B on a clean target client.

---

## 15. Known limitations and roadmap

Honest inventory for the Q&A.

### 15.1 What the tool does NOT do today

| Gap | Why | Workaround |
|---|---|---|
| **BW / BW/4HANA migration** | Different data model, needs different orchestrators. | Customer runs SAP's BW conversion path separately. |
| **HCM payroll data** | Deep GDPR + country-specific runtime state. | Customer runs SAP's HCM migration path (or moves to SuccessFactors). |
| **CRM / SRM co-deployment migration** | Different lifecycle. | Customer migrates CRM/SRM separately, integrates via CDS afterwards. |
| **Real-time integration re-platforming** | Out of scope. | Report flags all RFC destinations for manual review. |
| **BAPI transport SSH auto-import** | Requires SSH access to target host, which most customers refuse. | Falls back to `manual_assembly_required` — operator runs STMS. |
| **True TEST_RUN for CVI + BP flows** | SAP has not shipped a test-run mode for these BAPIs. | Staging-table fallback with explicit evidence-pack note. |

### 15.2 Prioritised roadmap

1. **UI exposure of `M4H_LOAD_MAX_ROWS`** — currently env-only, blocks small pilot runs from becoming meaningful.
2. **Fable-5 unblock trigger** — resume evaluation of alternate models when the lawsuit posture clears.
3. **SAP Cloud ALM integration** — hand off gate approvals into ALM's cutover cockpit instead of the tool's own gate UI.
4. **SolMan Focused Build integration** — for customers who standardise on Focused Build for cutover management.
5. **True IPv6 gateway** for customer-hosted ECC behind aggressive corporate proxies.

### 15.3 Maturity level

- Currently: TRL 4–5 (validated in relevant environment).
- Battle-tested against: CAL IDES EHP8 (source), S/4HANA 2023 Fully Activated Appliance (target).
- Customer pilots: N customers under NDA — details on request.

---

## 16. Anticipated Q&A cheat sheet

### 16.1 "How is this different from SNP / Datavard / Cbs?"

- **SNP CrystalBridge** does bit-perfect database-level replication with in-flight transformation. Our tool never touches the database directly — every write is a released BAPI or MC upload. That means SAP support will accept a support ticket about our migration outputs, which is a different governance posture.
- **Datavard Glue** is data-lake extraction plus HANA replication. We are a full pipeline: code + config + data + validation + evidence, not just data.
- **Cbs Enterprise Transformer** is closest to us but delivers in-place system conversion (SUM/DMO adjacent). We are explicitly selective data transition (greenfield target, transport-led).

### 16.2 "What SAP version do you support end-to-end?"

- Source: ECC 6.0 EHP6+ (EHP7+ recommended). Non-Unicode + Unicode both supported.
- Target: S/4HANA 2022+ (tested on 2023 Fully Activated Appliance and CAL IDES).
- ABAP AST engine works on any release the parser can read (currently through 7.58).

### 16.3 "Do we need an S-user for the tool to run?"

- **No** — the tool runs entirely with a customer-provided service user.
- **Yes**, for the SAP NW RFC SDK download (Basis team's S-user, one-time). Bundled in our Fargate image so end-users never touch it.

### 16.4 "How do you handle the client-copy problem?"

- We don't do client copy. Our lane is greenfield target. If the customer wants a client-copy transition, that's SUM/DMO territory and we recommend SAP's toolchain.
- We do consume the output of a client copy (i.e., start from a copied client on S/4 and layer our config + data on top).

### 16.5 "What about GDPR / data residency?"

- Per project memory [[anthropic-direct-api]]: AI calls hit `api.anthropic.com` directly, which is US-based. The pseudonymizer strips PII before any call. For customers who cannot allow US-transit even after pseudonymization, the AI hooks can be disabled per-tenant (`M4H_AI_ENABLED_<client_id>=false`) and the tool falls back to deterministic paths.
- Non-AI data stays in the customer's chosen AWS region.

### 16.6 "What's the licensing story?"

- Tool: subscription per tenant, pricing depends on # of migratable objects + AI usage.
- SAP licensing: customer must have valid licenses for SAP NW RFC SDK, Migration Cockpit content, and their S/4HANA runtime. Our tool does not re-license anything.

### 16.7 "What if a BAPI call throws a short dump?"

- The pyrfc layer surfaces the ST22 short dump text into the BAPI failure record.
- The row is dead-lettered with `code=BAPI_FAILURE`.
- The evidence pack seals the dump text into the audit chain so an auditor can see exactly what SAP threw.
- The tool does not swallow the dump — the operator sees the raw SAP message.

### 16.8 "How do we know the tool didn't secretly change something on ECC?"

- The read-only enforcement is in the pyrfc call site (`data-migrator/handler.py:81` — `LOAD_TO_S4` gates every write, and only `data-migrator/spines/*` is allowed to write). Everything else is `RFC_READ_TABLE` + `BAPI_*_GETLIST` reads.
- The evidence pack's `support_compliance` section asserts (with a signed manifest) that no `RFC_WRITE_TABLE`, no `RFC_ABAP_INSTALL_AND_RUN`, and no `SE16N` edit was called. If a run's manifest ever shows anything else, that's evidence of tampering — the chain would fail verification.

### 16.9 "How long does a full run take?"

- Discovery + code analysis + config extraction: ~15 minutes on a 20k-program IDES.
- Data extract (all 24 objects, ~250k rows): ~30 minutes.
- Live load (30-row cap, default): ~5 minutes.
- Live load (uncapped, 250k rows across 24 objects): ~4-8 hours depending on BAPI throughput.
- Cutover phase (delta + final validator + integration activator + PDF): ~20 minutes.

### 16.10 "What's your DR posture?"

- Fargate task is stateless — restart / redeploy is safe at any point.
- DDB tables are on-demand with point-in-time recovery.
- S3 evidence bucket is versioned + WORM Object Lock + cross-region replication.
- Key-map ledger: backed up daily via `scripts/backup-key-map.ps1`; restore via `scripts/restore-key-map.ps1`.
- Full DR runbook at `docs/DR.md`.

---

## Quick-reference reading list before the meeting

If time is short, read these five sections in this order:

1. §1 (elevator pitch) — so you have the one-sentence answer to "what is this?"
2. §3 (28-stage pipeline) — so any "how does the tool handle X?" question maps to a specific stage number.
3. §7 (spines / idempotency / dead-letter) — the most-asked technical topic.
4. §11 (SAP prerequisites) — the checklist you can hand to their Basis lead.
5. §9 (cutover precedence rule) — the auditor answer.

Everything else is available for depth follow-up.

---

*Document generated for internal presenter use. Reflects the state of the tool at commit `b131d3f` on branch `aws-lift-and-shift`.*
