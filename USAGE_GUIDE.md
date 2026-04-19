# Migrate4HANA — User Guide

Complete guide to using the **Migrate4HANA** Smart Orchestrator for SAP ECC to S/4HANA System Conversion, aligned with the SAP Activate Methodology.

> **Current Status (March 2026):** All 17 stages across 5 SAP Activate phases fully operational. Latest pipeline run: **Grade A (100%)** — 861 programs scanned, 98.6% auto-fix rate, 5,000 business partners migrated, 72.9-second end-to-end execution. 85 validation checks across 7 dimensions. 114-test suite passing. All 10 previously identified gaps resolved. See [README.md](README.md#production-readiness) for production deployment considerations.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Installation](#3-installation)
4. [Starting the Application](#4-starting-the-application)
5. [Using the Web Interface](#5-using-the-web-interface)
   - [Dashboard](#51-dashboard)
   - [Connections](#52-connections-page)
   - [Pipeline](#53-pipeline-page)
   - [Scorecard](#54-scorecard-page)
   - [Report](#55-report-page)
6. [Step-by-Step: ECC Assessment](#6-step-by-step-ecc-assessment)
7. [Step-by-Step: Full Migration](#7-step-by-step-full-migration)
8. [Downloading the PDF Report](#8-downloading-the-pdf-report)
9. [Running from Command Line (No UI)](#9-running-from-command-line-no-ui)
10. [API Reference](#10-api-reference)
11. [Azure Deployment (Production)](#11-azure-deployment-production)
12. [SAP Tool Requirements](#12-sap-tool-requirements)
13. [SUM/DMO Prerequisites](#13-sumdmo-prerequisites)
14. [LLM Setup & Data Privacy](#14-llm-setup--data-privacy)
15. [Real-Time Telemetry Setup](#15-real-time-telemetry-setup)
16. [Troubleshooting](#16-troubleshooting)
17. [Production Deployment Checklist](#17-production-deployment-checklist)

---

## 1. Overview

Migrate4HANA is a **17-stage Smart Orchestrator** that automates the pre-conversion, post-conversion, and validation phases of an SAP ECC to S/4HANA System Conversion, while wrapping around SAP's mandatory proprietary tools for the core technical conversion.

### Pipeline Stages — 5 SAP Activate Phases

| Phase | Stages | What Happens |
|-------|--------|-------------|
| **Phase 1: Prepare** (1–4) | System Discovery, Maintenance Planner Integration, SAP Readiness Check, Simplification Item Check | Scans ECC system, validates conversion path with SAP tools, generates readiness roadmap |
| **Phase 2: Explore** (5–8) | Code Analysis + ATC, CVI/BP Preparation, Data Assessment, Config/Integration Assessment | Analyzes custom code with 6,400-line AST + ATC + GenAI, prepares Business Partners, maps data and config scope |
| **Phase 3: Realize — Conversion** (9–10) | Pre-Conversion Gate, SUM/DMO Monitoring | GO/NO-GO validation, then orchestrates SAP's Software Update Manager for the core technical conversion |
| **Phase 4: Realize — Post-Conversion** (11–14) | SPAU/SPDD + Code Deploy, FINS Migration, Material Ledger + Config, Roles + Integrations | Post-conversion code deployment, finance migration, Material Ledger activation, role and integration provisioning |
| **Phase 5: Deploy & Run** (15–17) | Business Process Testing, Go-Live Cutover, Validation & Scorecard | Automated DITL testing, go-live cutover orchestration, 85-check validation with GO-LIVE scorecard |

Additionally, **4 support Functions** run alongside the pipeline:
- **rollback-manager** — Automated reversal on failure (full post-conversion rollback)
- **data-hygiene** — BP deduplication with fuzzy matching + ML (Azure Data Factory matching)
- **process-miner** — ST03N workload analysis
- **test-generator** — DITL test case generation

### Execution Modes

The tool supports four execution modes:

| Mode | Stages | API Endpoint | Description |
|------|--------|-------------|-------------|
| **Assessment Mode** | Phases 1–2 (stages 1–8) | `/api/pipeline/assess` | Safe, read-only. Gives you a full assessment of your ECC system including SAP readiness validation. |
| **Conversion Mode** | Phase 3 (stages 9–10) | `/api/pipeline/convert` | Orchestrates SAP SUM/DMO for the core technical conversion. Requires SUM prerequisites. |
| **Post-Conversion Mode** | Phases 4–5 (stages 11–17) | `/api/pipeline/complete` | Executes all post-conversion activities: code deployment, finance migration, testing, and validation. |
| **Full Migration** | All 5 phases (stages 1–17) | `/api/pipeline/full` | End-to-end orchestration across all 17 stages. |

---

## 2. Prerequisites

### For Local Demo (Mock Mode)
- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **Node.js 18+** — [Download](https://nodejs.org/)
- **pip** (comes with Python)

### For Real SAP Connectivity (Production)
Everything above, plus:
- **PyRFC** — SAP RFC connector for Python. Requires the SAP NW RFC SDK.
  ```
  pip install pyrfc
  ```
  See [scripts/setup-pyrfc.sh](scripts/setup-pyrfc.sh) for SAP NW RFC SDK installation.
- **Network access** to your ECC system (RFC port 33XX where XX = system number)
- **Network access** to your S/4HANA Cloud system (HTTPS for OData, or RFC)
- **SAP credentials** with read access on ECC and admin access on S/4HANA

> **Note:** If PyRFC is not installed, the tool automatically falls back to **Mock Mode** using realistic sample data from a fictional Indian company. This is perfect for demos and testing.

---

## 3. Installation

### Step 1: Clone the repository
```bash
git clone <repository-url>
cd migrate4hana
```

### Step 2: Install Python dependencies
```bash
pip install reportlab
```
> `reportlab` is needed for PDF report generation. All other Python code uses standard library modules.

### Step 3: Install frontend dependencies
```bash
cd frontend
npm install
cd ..
```

### Step 4: Verify installation
```bash
# Run the 114-test suite (should show "114 passed")
python -m pytest tests/ --ignore=tests/load_test.py -v

# Run the full 17-stage pipeline against mock data (no SAP required)
python run_local_pipeline.py
```

Expected output from the pipeline:
```
Pipeline completed — Grade A (100%)
Total duration: ~70 seconds
Results saved to: test-output/run_YYYYMMDD_HHMMSS/
```

> The test suite (114 tests) covers pipeline stages, rule router, ST03N analyzer, DITL generator, rollback manager, config applier, error handling, and 52 SAP integration tests (15 classes covering all 33 RFC/BAPI functions in dual-mode mock + live). The pipeline run validates all 17 stages end-to-end against realistic mock data.
>
> **Note:** `tests/load_test.py` requires the `locust` package and is excluded from default test runs. Install with `pip install locust` to run load tests separately.

---

## 4. Starting the Application

You need to start **two processes** — the API server and the frontend dev server.

### Terminal 1: Start the API Server
```bash
cd migrate4hana
python api_server.py
```
You should see:
```
  Migrate4HANA API Server
  =========================
  Listening on http://localhost:8000
  Endpoints:
    GET  /api/health             — Health check
    POST /api/connections/ecc     — Save ECC connection
    ...
```

### Terminal 2: Start the Frontend
```bash
cd migrate4hana/frontend
npm run dev
```
You should see:
```
  VITE v5.x.x  ready in XXX ms
  ➜  Local:   http://localhost:3000/
```

### Step 3: Open the Web UI
Open your browser and go to:
```
http://localhost:3000
```

---

## 5. Using the Web Interface

The sidebar has 5 pages:

### 5.1 Dashboard

The **landing page** shows an overview of the last migration run:
- Key metrics: total programs, tables, issues found, fix rate, GO-LIVE score
- 17-stage pipeline summary organized by SAP Activate phase with status indicators
- Click any stage card to see detailed results for that stage

### 5.2 Connections Page

**This is where you configure your SAP systems.** You must do this before running an assessment or migration.

#### Configuring ECC Connection

| Field | Description | Example |
|-------|-------------|---------|
| **Application Server** | ECC server hostname or IP | `ecc-prod.company.com` |
| **System Number** | SAP system number (00–99) | `00` |
| **Client** | SAP client number | `100` |
| **User** | SAP dialog user with RFC authorization | `MIGRATION_USER` |
| **Password** | Password for the user | `********` |
| **SAP Router** (optional) | SAP Router string if connecting through a firewall | `/H/saprouter.company.com/S/3299/H/` |

#### Configuring S/4HANA Connection

You have two connection types:

**RFC (On-Premise S/4HANA):**
Same fields as ECC — host, system number, client, user, password.

**OData (S/4HANA Cloud):**

| Field | Description | Example |
|-------|-------------|---------|
| **API Base URL** | S/4HANA Cloud API endpoint | `https://mycompany.s4hana.cloud.sap/sap/opu/odata/sap/` |
| **Host** | S/4HANA Cloud hostname | `mycompany.s4hana.cloud.sap` |
| **Communication User** | Technical user for API access | `COMM_USER_MIGRATION` |
| **Password** | Password | `********` |

#### Testing Connections

1. Fill in the connection details
2. Click **Test Connection** — the tool will attempt to connect and report success/failure
3. If successful, click **Save** to persist the configuration

> **Mock Mode:** If PyRFC is not installed, clicking "Test Connection" will show a "Connected (Mock Mode)" status. This means the tool will use realistic sample data instead of your real ECC system.

### 5.3 Pipeline Page

This is the **main action page** featuring a **5-phase pipeline view** that displays all 17 stages organized by SAP Activate phase. Three execution buttons control the pipeline progression:

#### "Run Assessment" Button (Blue)
- Runs **Phases 1–2** (stages 1–8, Assessment Mode) via `/api/pipeline/assess`
- **Read-only** — does NOT write anything to your SAP systems
- Phase 1 (Prepare): Validates conversion path with Maintenance Planner, Readiness Check, and SI-Check
- Phase 2 (Explore): Analyzes custom ABAP programs with AST + ATC + GenAI, prepares Business Partners, assesses data and config
- Result: Full assessment report showing migration readiness

#### SAP SUM/DMO Gate Warning
Between Phase 2 and Phase 3, the pipeline displays a **SAP SUM/DMO Gate warning** indicating that all SUM/DMO prerequisites must be met before proceeding. This gate ensures that:
- The SUM tool is installed and accessible on the application server
- The target HANA database is prepared and reachable
- All SI-Check RED items from Phase 1 have been resolved
- A source system backup has been completed
- The stack.xml from Maintenance Planner is available

The gate is visually distinguished in the pipeline view to reinforce that Phase 3 involves SAP's core technical conversion and cannot be reversed.

#### "Start Conversion" Button (Orange)
- Runs **Phase 3** (stages 9–10, Conversion Mode) via `/api/pipeline/convert`
- Requires SUM/DMO prerequisites to be met (see [Section 13](#13-sumdmo-prerequisites))
- Validates all Phase 1–2 results at the Pre-Conversion Gate (Stage 9)
- Orchestrates SAP's Software Update Manager (SUM) with Database Migration Option (DMO)
- Monitors SUM execution in real-time with log streaming

#### "Complete Migration" Button (Green)
- Runs **Phases 4–5** (stages 11–17, Post-Conversion Mode) via `/api/pipeline/complete`
- Deploys remediated code, executes FINS_MASS_DATA_MONITOR, activates Material Ledger
- Provisions roles, activates integrations, runs business process tests
- Ends with 85-check validation and GO-LIVE scorecard

#### During Execution
- The **5-phase pipeline view** shows all 17 stages with each stage lighting up in the visual timeline as it runs
- **Real-time WebSocket logs** stream live in the LogViewer panel (bottom of page)
- A progress bar shows overall completion across the active phases
- Phases not included in the current execution mode are grayed out with "NOT IN SCOPE" label
- The SUM/DMO Gate warning remains visible between Phase 2 and Phase 3 as a reminder
- Click **Stop** to abort, or **Reset** after completion to run again

### 5.4 Scorecard Page

Shows the **GO-LIVE Readiness Scorecard** with:
- Overall grade (A/B/C/D) and percentage score
- Circular gauge visualization
- Category breakdown across 7 dimensions: Code, Data, Finance, Config, Roles, Integrations, Business Processes
- Bar chart comparing category scores
- Each category shows pass/fail items from the 85 validation checks

### 5.5 Report Page

The **Post-Migration Report** — a comprehensive client-deliverable document with 11 sections:

1. **Executive Summary** — client name, source/target systems, migration approach, SAP Activate alignment, overall status
2. **Code Remediation** — issues found, fix rate, AST + ATC engine breakdown, auto-fixed vs manual review
3. **Data Migration** — business partner conversion, finance records, custom tables
4. **Configuration** — company codes, plants, sales orgs replicated
5. **Roles & Authorizations** — PFCG roles migrated, users assigned, Fiori catalog mappings
6. **Integrations** — RFC destinations, IDoc partners, India compliance endpoints
7. **GO-LIVE Scorecard** — grade, score, 7-dimension breakdown with 85 checks
8. **Risk Assessment** — identified risks with severity and mitigation steps
9. **Post Go-Live Roadmap** — recommended actions after migration
10. **Technical Metrics** — pipeline duration, stage timings, resource usage
11. **Appendix** — detailed findings and raw data

The **Download PDF** button (top-right) generates a professional branded PDF report.

---

## 6. Step-by-Step: ECC Assessment

This is the recommended first step — assess your ECC system without making any changes.

```
Step 1  →  Open http://localhost:3000
Step 2  →  Go to "Connections" in the sidebar
Step 3  →  Fill in your ECC connection details (host, system number, client, user, password)
Step 4  →  Click "Test Connection" — verify it shows "Connected"
Step 5  →  Click "Save" to persist the connection
Step 6  →  Go to "Pipeline" in the sidebar
Step 7  →  Click the blue "Run Assessment" button
Step 8  →  Watch the 8 stages execute across Phases 1–2 (takes 30–90 seconds with mock data)
           - Phase 1: System Discovery, Maintenance Planner, Readiness Check, SI-Check
           - Phase 2: Code Analysis, CVI/BP Prep, Data Assessment, Config Assessment
Step 9  →  Once complete, go to "Dashboard" to see the overview
Step 10 →  Go to "Scorecard" to see the GO-LIVE readiness grade
Step 11 →  Go to "Report" to see the full assessment
Step 12 →  Click "Download PDF" to get a client-deliverable PDF report
```

### What the Assessment Tells You

After running the assessment, you'll know:
- **SAP Readiness Check status** — conversion path validated by SAP's own tools
- **Simplification Item impact** — which items affect your system and what needs remediation
- **How many custom programs** need modification for S/4HANA
- **What percentage can be auto-fixed** (typically 95%+)
- **Which programs need manual review** and why
- **Business Partner readiness** — CVI pre-check results, deduplication analysis
- **How much data** needs to be migrated (tables, rows, finance documents)
- **What configurations** need to be replicated across 15+ country localizations
- **Which roles** exist and how they map to S/4HANA Fiori
- **What integrations** (RFC, IDoc, APIs) are in place
- **Overall migration complexity** and readiness score

---

## 7. Step-by-Step: Full Migration

> **Warning:** Full migration writes data to your S/4HANA target system. Only run this when you're ready.

```
Step 1  →  Complete the Assessment first (Section 6 above)
Step 2  →  Review the assessment report and address any HIGH severity risks
Step 3  →  Complete SUM/DMO prerequisites (see Section 13)
Step 4  →  Go to "Connections" and configure your S/4HANA target system
Step 5  →  Click "Test Connection" on the S/4HANA card — verify it connects
Step 6  →  Click "Save"

--- Phase 3: Technical Conversion ---
Step 7  →  Go to "Pipeline" and click the orange "Start Conversion" button
Step 8  →  Stage 9: Pre-Conversion Gate validates all readiness checks
Step 9  →  Stage 10: SUM/DMO is orchestrated — monitor progress in real-time
Step 10 →  Wait for SUM/DMO to complete (this is SAP's core conversion)

--- Phases 4–5: Post-Conversion & Go-Live ---
Step 11 →  Click the green "Complete Migration" button
Step 12 →  Phase 4 executes:
           - Stage 11: SPAU/SPDD adjustments + code deployment
           - Stage 12: FINS_MASS_DATA_MONITOR finance migration
           - Stage 13: Material Ledger activation + config application
           - Stage 14: Role provisioning + integration activation
Step 13 →  Phase 5 executes:
           - Stage 15: Automated business process testing
           - Stage 16: Go-live cutover orchestration
           - Stage 17: 85-check validation → GO-LIVE Scorecard
Step 14 →  Review the final report in the "Report" page
Step 15 →  Download the PDF for stakeholder review
```

---

## 8. Downloading the PDF Report

### From the Web UI
1. Go to the **Report** page
2. Click the **Download PDF** button (top-right, blue button with download icon)
3. A PDF file will download to your browser's default downloads folder

### From the API Directly
```bash
# Download the latest run's PDF
curl -o migration-report.pdf http://localhost:8000/api/runs/latest/pdf

# Download a specific run's PDF
curl -o migration-report.pdf http://localhost:8000/api/runs/run_20260306_162548/pdf
```

### From the Command Line
```bash
# Generate PDF from an existing report JSON
python pdf_report_generator.py test-output/run_20260306_162548/post-migration-report.json
```

The PDF includes a branded cover page, executive summary, all report sections with tables and metrics, and is suitable for presenting to stakeholders and management.

---

## 9. Running from Command Line (No UI)

You can run the entire pipeline without the web UI:

### Full Migration (All 17 Stages)
```bash
python run_local_pipeline.py
```

### Assessment Only (Phases 1–2, Stages 1–8)
```bash
python run_local_pipeline.py --assess-only
```

### What Happens
- Uses mock ECC data (or real PyRFC if installed)
- Prints colored terminal output showing each stage's progress by SAP Activate phase
- Saves all results to `test-output/run_YYYYMMDD_HHMMSS/`
- Generates a `final-report.json` and `post-migration-report.json`

### Output Directory Structure
```
test-output/run_20260306_162548/
├── final-report.json              ← Raw pipeline results (all stages)
├── post-migration-report.json     ← Formatted client report (11 sections)
├── post-migration-report.pdf      ← PDF version (if generated)
├── phase1-prepare/                ← Phase 1 outputs (discovery, readiness)
├── phase2-explore/                ← Phase 2 outputs (code analysis, BP prep)
├── phase3-conversion/             ← Phase 3 outputs (SUM/DMO logs)
├── phase4-post-conversion/        ← Phase 4 outputs (FINS, config, roles)
├── phase5-deploy/                 ← Phase 5 outputs (testing, validation)
└── scorecard/                     ← GO-LIVE scorecard and validation results
```

---

## 10. API Reference

The API server runs on `http://localhost:8000`. All responses are JSON unless noted.

### Health & Status

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check — returns `{"status": "ok"}` |
| `GET` | `/api/status` | Current pipeline status — `idle`, `running`, `completed`, or `failed` |

### Connection Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/connections` | Get saved connection configurations (passwords excluded) |
| `POST` | `/api/connections/ecc` | Save ECC connection config |
| `POST` | `/api/connections/s4hana` | Save S/4HANA connection config |
| `POST` | `/api/connections/ecc/test` | Test ECC connectivity |
| `POST` | `/api/connections/s4hana/test` | Test S/4HANA connectivity |

#### Example: Save ECC Connection
```bash
curl -X POST http://localhost:8000/api/connections/ecc \
  -H "Content-Type: application/json" \
  -d '{
    "ashost": "ecc-prod.company.com",
    "sysnr": "00",
    "client": "100",
    "user": "MIGRATION_USER",
    "passwd": "secret123"
  }'
```

#### Example: Test ECC Connection
```bash
curl -X POST http://localhost:8000/api/connections/ecc/test \
  -H "Content-Type: application/json" \
  -d '{
    "ashost": "ecc-prod.company.com",
    "sysnr": "00",
    "client": "100",
    "user": "MIGRATION_USER",
    "passwd": "secret123"
  }'
```

### Pipeline Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/pipeline/assess` | Start assessment — Phases 1–2 (stages 1–8) |
| `POST` | `/api/pipeline/convert` | Start conversion — Phase 3 (stages 9–10), orchestrates SUM/DMO |
| `POST` | `/api/pipeline/complete` | Start post-conversion — Phases 4–5 (stages 11–17) |
| `POST` | `/api/pipeline/full` | Start full migration — All 5 phases (stages 1–17) |

### Run Results

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/runs` | List all completed runs |
| `GET` | `/api/runs/{id}` | Get a specific run's results |
| `GET` | `/api/runs/{id}/pdf` | Download PDF report for a run |
| `GET` | `/api/runs/latest/pdf` | Download PDF report for the latest run |

---

## 11. Azure Deployment (Production)

Step-by-step instructions for deploying Migrate4HANA to Azure. No SAP or cloud expertise required — follow each step exactly.

### Prerequisites

You need:
- An **Azure subscription** with Contributor access
- **Azure CLI** installed and configured (`az login` to authenticate)
- **Terraform** v1.5+ installed — [Download](https://developer.hashicorp.com/terraform/install)
- **Git** installed — [Download](https://git-scm.com/downloads)
- **Python 3.10+** installed — [Download](https://www.python.org/downloads/)
- **Node.js 18+** installed — [Download](https://nodejs.org/)

### Architecture
```
  SAP ECC  ──RFC──▶  Azure Functions (21)  ──▶  S/4HANA
                          │
                   Durable Functions
                   (orchestrates 17 stages
                    across 5 SAP Activate phases)
                          │
                ┌─────────┼─────────┐
          Blob Storage  Cosmos DB  Application Insights
                          │            + Log Analytics
                ┌─────────┼─────────┐
         Azure Data Factory   Data Factory   Web PubSub
                     matching       Telemetry
```

### Step 1: Clone and Enter the Repository
```bash
git clone <repository-url>
cd migrate4hana
```

### Step 2: Configure Azure Credentials
```bash
# Check Azure CLI is installed
az --version

# Log in to Azure (opens a browser for authentication)
az login
```
After login:
- **Select subscription:** Use `az account set --subscription <subscription-id>` if you have multiple subscriptions
- **Default region:** Set via Terraform variables (e.g. `westeurope` — pick the region closest to your SAP systems)

### Step 3: Edit Terraform Variables
```bash
# Open the config file in any text editor
# Windows:
notepad terraform\environments\dev\terraform.tfvars

# Mac/Linux:
nano terraform/environments/dev/terraform.tfvars
```

Set these values in the file:
```hcl
# Azure region — pick the region closest to your SAP systems
azure_region = "westeurope"

# VNet network ranges (use defaults unless your network team specifies otherwise)
vnet_cidr            = "10.0.0.0/16"
private_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
public_subnet_cidrs  = ["10.0.101.0/24", "10.0.102.0/24"]

# SAP ECC connection (stored in Azure Key Vault — NOT in plaintext)
ecc_host          = "ecc-prod.company.com"
ecc_system_number = "00"
ecc_client        = "100"

# S/4HANA target connection
s4hana_host       = "s4hana.company.com"
s4hana_client     = "100"

# LLM mode: "CLAUDE_OPUS" (standard) or "AIRGAPPED_LOCAL" (banks/defense)
llm_mode = "CLAUDE_OPUS"

# Enable real-time log streaming to the frontend
enable_websocket_telemetry = true

# Enable ML-powered business partner deduplication
enable_entity_resolution = true
```
Save and close the file.

### Step 4: Deploy All Infrastructure
```bash
cd terraform/environments/dev

# Initialize Terraform (downloads required providers — one-time step)
terraform init

# Preview what will be created (review the output)
terraform plan

# Deploy everything (type "yes" when prompted)
terraform apply
```

This creates all 13 Azure modules:
- **VNet** with private subnets (for SAP connectivity)
- **21 Azure Functions** (17 pipeline stages + 4 support Functions, all with telemetry env vars)
- **Durable Functions** (17-stage orchestration across 5 SAP Activate phases with error chaining to rollback-manager)
- **Blob Storage container** (staging area for intermediate data)
- **Application Insights + Log Analytics** (monitoring, alerts, durable log retention)
- **Azure Database Migration Service** (full-load + CDC continuous data sync with checkpoint/retry)
- **Cosmos DB** (encrypted at rest — country rules, simplification tables, migration state, idempotency)
- **Private Endpoints** (Private Link for Anthropic Claude Opus 4.6 — no public internet)
- **Air-Gapped LLM** (isolated GPU VM for local LLM in high-security environments)
- **Azure Data Factory matching** (ML-powered BP deduplication with schema mapping)
- **Web PubSub Telemetry** (Azure Web PubSub for real-time log streaming)
- **WAF** (Azure Front Door WAF rate limiting, OWASP Core Rules, SQLi, IP reputation)
- **Audit** (Azure Activity Log + Blob Storage WORM 7-year retention + compliance metric alarms)

### Step 5: Deploy Function Code
```bash
# Return to project root
cd ../../..

# Package and deploy all Azure Functions
bash scripts/deploy.sh
```

### Step 6: Store SAP Credentials in Azure Key Vault
```bash
# Store ECC credentials (replace with real values)
az keyvault secret set \
  --vault-name migrate4hana-kv \
  --name ecc-credentials \
  --value '{"user":"MIGRATION_USER","passwd":"YOUR_PASSWORD"}'

# Store S/4HANA credentials (replace with real values)
az keyvault secret set \
  --vault-name migrate4hana-kv \
  --name s4hana-credentials \
  --value '{"user":"ADMIN_USER","passwd":"YOUR_PASSWORD"}'
```

### Step 7: Note the Outputs
After `terraform apply` completes, it prints important values. Save these:
```bash
# View outputs at any time
cd terraform/environments/dev
terraform output
```
Key outputs:
- `orchestrator_url` — needed to start migrations
- `web_pubsub_url` — Web PubSub endpoint for telemetry
- `dms_task_id` — Azure Database Migration Service task
- `blob_container_name` — staging data container

### Step 8: Run an Assessment (Phases 1–2, Read-Only)
```bash
# Start an assessment run (read-only, safe to run anytime)
az functionapp durable start-new \
  --resource-group migrate4hana-rg \
  --name migrate4hana-orchestrator \
  --function-name OrchestratorFunction \
  --input '{"mode":"assess","ecc_client":"100","execute":false}'
```

### Step 9: Run a Full Migration (When Ready)
```bash
# Start full execution (all 5 phases — WRITES to S/4HANA — back up first!)
az functionapp durable start-new \
  --resource-group migrate4hana-rg \
  --name migrate4hana-orchestrator \
  --function-name OrchestratorFunction \
  --input '{"mode":"full","ecc_client":"100","execute":true}'
```

### Step 10: Monitor in Azure Portal
1. Open **Azure Portal** → **Function Apps** → click your Durable Functions orchestrator
2. Click the running instance to see a live visual of each stage across all 5 phases
3. Open **Log Analytics** to see detailed Function output
4. If using the frontend, set `VITE_TELEMETRY_WS_URL` to the Web PubSub endpoint from Step 7

### Destroying the Infrastructure (When Done)
```bash
cd terraform/environments/dev
terraform destroy
# Type "yes" when prompted — this removes ALL Azure resources
```

---

## 12. SAP Tool Requirements

Migrate4HANA integrates with SAP's mandatory proprietary tools. The following must be available for a production conversion:

| SAP Tool | Requirement | How to Obtain |
|----------|-------------|---------------|
| **Maintenance Planner** | Access to SAP ONE Support Launchpad | SAP S-user with Maintenance Planner authorization on [SAP ONE Support Launchpad](https://launchpad.support.sap.com/) |
| **SAP Readiness Check** | Enabled in the source ECC system | SAP Note 2913617 — install latest READINESS_CHECK component. Requires SAP Readiness Check credentials for automated execution. |
| **Simplification Item Check** | /SDF/RC_START_CHECK available | SAP Note 2502552 — install Simplification Item Check add-on |
| **ABAP Test Cockpit (ATC)** | /SDF/ATC_RUN_API available | Part of SAP_BASIS 750+ — ensure latest SP applied |
| **CVI Cockpit** | CVI_UPGRADE_CHECK_RESOLVE available | Part of SAP_APPL — ensure CVI is activated |
| **SUM/DMO** | Software Update Manager installed on the SAP application server | Download from SAP Software Download Center. Must be extracted and configured on the application server hosting the source ECC system. |
| **HANA Database** | Target HANA database for the S/4HANA system | HANA database must be installed, sized, and accessible from the application server before Phase 3 conversion. |
| **FINS_MASS_DATA_MONITOR** | Available post-conversion | Part of S/4HANA — activated during conversion |

### Access Summary

- **Maintenance Planner access** — SAP ONE Support Launchpad with S-user authorization
- **SAP Readiness Check credentials** — System credentials with authorization for RC_COLLECT_ANALYSIS_DATA
- **SUM/DMO installed on app server** — Downloaded, extracted, and verified on the source application server
- **HANA database for target system** — Installed, configured, and network-accessible from the application server

> **For local demo/assessment:** None of these are required. Migrate4HANA automatically falls back to mock mode when SAP tools are not available.

---

## 13. SUM/DMO Prerequisites

Before running Phase 3 (Technical Conversion), ensure the following are prepared. The Pre-Conversion Gate (Stage 9) validates these prerequisites automatically, but they must be addressed before initiating conversion.

### System Prerequisites
- [ ] **SUM tool must be installed on the SAP application server** — Download the Software Update Manager from the SAP Software Download Center, extract it on the application server that hosts the source ECC system, and verify it launches correctly. SUM is SAP's proprietary tool that performs the actual database migration and cannot be substituted.
- [ ] **Target HANA database must be prepared and accessible** — The HANA database for the S/4HANA target system must be installed, properly sized for the migration workload, and network-accessible from the application server. Verify connectivity with `hdbuserstore` or HANA Studio.
- [ ] **All SI-Check RED items must be resolved** — Simplification Item Check (Phase 1, Stage 4) identifies incompatibilities. All items flagged as RED (critical) must be resolved before SUM/DMO can proceed. The Pre-Conversion Gate enforces this check.
- [ ] **Source system backup required** — A complete backup or snapshot of the SAP ECC system must be taken immediately before starting Phase 3. This is the last recovery point before the irreversible technical conversion.
- [ ] **stack.xml from Maintenance Planner required** — Generate the stack.xml file from SAP Maintenance Planner (Phase 1, Stage 2) that defines the target S/4HANA version, support packages, and add-on configuration. This file drives the SUM/DMO conversion process.
- [ ] **HANA database credentials** available for the target system

### Migrate4HANA Assessment Prerequisites
- [ ] **Phase 1 completed** — all SAP readiness checks passed (Maintenance Planner, Readiness Check, SI-Check)
- [ ] **Phase 2 completed** — code analysis, BP preparation, data assessment, and config assessment finished
- [ ] **Critical code issues resolved** — all critical ABAP incompatibilities auto-fixed or manually addressed
- [ ] **Business Partner preparation done** — CVI pre-checks passed, deduplication completed

### Network Prerequisites
- [ ] **Application server** accessible from Migrate4HANA (RFC or SSH for SUM CLI)
- [ ] **HANA database** accessible from the application server
- [ ] **SUM download directory** populated with the correct software packages

### Post-Conversion Readiness
- [ ] **SPAU/SPDD strategy defined** — decide which adjustments to accept, modify, or reset
- [ ] **Finance migration plan reviewed** — FINS_MASS_DATA_MONITOR parameters confirmed
- [ ] **Testing scope confirmed** — business process test scenarios validated

---

## 14. LLM Setup & Data Privacy

Because Migrate4HANA routes complex SAP codebase transformations (AST structures) through Generative AI, you must define the `llm_mode` upon execution.

### Option A: Standard Enterprise (Anthropic Claude Opus 4.6)
Set `llm_mode="CLAUDE_OPUS"`. Terraform will automatically provision Private Endpoints (`terraform/modules/private-endpoints`) so payload traffic never crosses the public internet. Uses Anthropic Claude Opus 4.6.

### Option B: "Air-Gapped" Local (Banks / Defense)
Set `llm_mode="AIRGAPPED_LOCAL"`. Deploy the `airgapped-llm` module in Terraform which spins up a generic GPU VM (`Standard_NC8as_T4_v3`) isolated within your private subnet.
- The `data_scrubber.py` Function will automatically strip ABAP comments and obfuscate PII from payloads before hitting the Local LLM (Llama 3/Mistral setup).

### Data Privacy Controls
- **Data Scrubber** — Automatically masks PII, passwords, code comments, and literal structures before any GenAI dispatch
- **Private Endpoints** — All Claude Opus traffic stays within Azure private network (no public internet)
- **Air-Gapped Isolation** — Zero outbound internet access for the local LLM instance
- **Azure Data Factory matching** — BP data processed within your Azure subscription, never exported

---

## 15. Real-Time Telemetry Setup

### WebSocket Configuration (Azure Deployment)
The `websocket-telemetry` Terraform module provisions an Azure Web PubSub service that streams live stage events to the frontend.

```bash
# In terraform.tfvars:
enable_websocket_telemetry = true
```

### Frontend Configuration
Set the WebSocket URL in your frontend environment:
```bash
# In frontend/.env.local:
VITE_TELEMETRY_WS_URL=wss://<web-pubsub-name>.webpubsub.azure.com/client/hubs/telemetry
```

### Local Development
For local development, the LogViewer operates in polling mode. Set up the environment variable to enable WebSocket mode:
```bash
VITE_TELEMETRY_WS_URL=ws://localhost:8000/ws
```

### Azure Data Factory Matching Configuration
For ML-powered BP deduplication in production:
```bash
# In terraform.tfvars:
enable_entity_resolution = true

# In Function App environment:
BP_FUZZY_THRESHOLD=0.82           # Fuzzy matching confidence threshold (0.0–1.0)
DATA_FACTORY_PIPELINE_ID=/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.DataFactory/factories/<factory>/pipelines/<pipeline>  # Set by Terraform output
```

---

## 16. Troubleshooting

### "Cannot reach API server"
- Make sure the API server is running: `python api_server.py`
- Check it's on port 8000: open `http://localhost:8000/api/health` in a browser
- If port 8000 is busy, kill the process using it and restart

### "Connected (Mock Mode)" instead of real SAP
- PyRFC is not installed. Install it with `pip install pyrfc`
- You also need the SAP NW RFC SDK library. See `scripts/setup-pyrfc.sh`
- Without PyRFC, the tool uses realistic sample data — this is fine for demos

### Frontend shows blank page
- Make sure `npm install` completed successfully in the `frontend/` directory
- Check the Vite dev server is running: `cd frontend && npm run dev`
- Check the browser console (F12) for JavaScript errors

### PDF download doesn't work
- Ensure the API server is running
- Try the direct URL: `http://localhost:8000/api/runs/latest/pdf`
- If no runs exist yet, run the pipeline first (at least an assessment)

### Pipeline fails at a stage
- Check the API server terminal output for error details
- Common issue: missing Python dependencies — run `pip install reportlab`
- Check `test-output/` for partial results from the failed run

### SUM/DMO Phase 3 issues
- Verify SUM tool is installed and accessible on the application server
- Check stack.xml is generated correctly from Maintenance Planner
- Ensure HANA database is accessible from the application server
- Review SUM logs in the WebSocket telemetry viewer for specific error messages

### Tests fail
```bash
# Run with verbose output to see details
python -m pytest tests/ -v --tb=long
```

### Port already in use
```bash
# Find and kill the process on port 8000 (Windows)
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Find and kill the process on port 3000 (Windows)
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

---

## Quick Reference Card

```
┌──────────────────────────────────────────────────────────────┐
│                    MIGRATE4HANA — Quick Start                │
│           Smart Orchestrator — SAP Activate Aligned          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Start API:    python api_server.py                       │
│  2. Start UI:     cd frontend && npm run dev                 │
│  3. Open:         http://localhost:3000                      │
│                                                              │
│  WORKFLOW (SAP Activate Phases):                             │
│  Connections → Configure SAP systems                         │
│  Pipeline    → Click "Run Assessment" (Phases 1-2, read-only)│
│  Scorecard   → Review GO-LIVE readiness grade                │
│  Report      → Full report + Download PDF                    │
│  Pipeline    → Click "Start Conversion" (Phase 3, SUM/DMO)  │
│  Pipeline    → Click "Complete Migration" (Phases 4-5)       │
│                                                              │
│  CLI ONLY:                                                   │
│  python run_local_pipeline.py               (all 17 stages)  │
│  python run_local_pipeline.py --assess-only (phases 1-2)     │
│                                                              │
│  API ENDPOINTS:                                              │
│  POST /api/pipeline/assess   → Phases 1-2 (stages 1-8)      │
│  POST /api/pipeline/convert  → Phase 3 (stages 9-10)        │
│  POST /api/pipeline/complete → Phases 4-5 (stages 11-17)    │
│  POST /api/pipeline/full     → All phases (stages 1-17)     │
│                                                              │
│  PDF:                                                        │
│  python pdf_report_generator.py <report.json>                │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 17. Production Deployment Checklist

Before deploying Migrate4HANA against a real SAP ECC → S/4HANA conversion:

### Completed (Pre-Configured)
- [x] **API authentication** — JWT + API key auth implemented in `api_server.py`.
- [x] **Cosmos DB encryption-at-rest** — encryption enabled by default in `terraform/modules/cosmosdb/main.tf`.
- [x] **Azure Data Factory matching workflow** — `azurerm_data_factory_pipeline` fully provisioned with ML matching in Terraform.
- [x] **Cosmos DB fallback rules** — 30 static rules across 8 categories in `rule_router.py`.
- [x] **Config applier error handling** — Structured error collection + dry_run validation.
- [x] **Rollback coverage** — Full post-conversion rollback: FI docs, transports, ACDOCA, SPRO, BPs, materials, roles, users, RFC, IDoc. Batch commits (25/batch) with BAPI_TRANSACTION_COMMIT.
- [x] **Test suite** — 114 tests covering pipeline stages, rule router, ST03N analyzer, DITL generator, rollback manager, config applier, error handling, and 52 SAP integration tests.
- [x] **RFC call timeouts** — `call_rfc_with_timeout()` prevents indefinite hangs (default 120s, configurable via `RFC_CALL_TIMEOUT_SECONDS`).
- [x] **Paginated table reads** — `read_table_chunked()` generator with ROWSKIPS/ROWCOUNT pagination (default 5000 rows/page via `RFC_PAGE_SIZE`).
- [x] **Input validation** — Shared `lambda/utils/validation.py` validates Function events (run_id, ecc_client, mode, dry_run, stage) across 4 handlers.
- [x] **Idempotency** — Cosmos DB-backed duplicate detection for data-loader prevents reprocessing on Function retries (7-day TTL).
- [x] **Credential refresh** — Key Vault credential caching with 300s TTL + auth-failure auto-retry in RFC pool.
- [x] **Source system locking** — SCCR_LOCK_CLIENT + BAPI_USER_LOCK (cutover) / SCCR_UNLOCK_CLIENT + BAPI_USER_UNLOCK (rollback).
- [x] **FINS configurable polling** — `FINS_MAX_POLLS` (480) × `FINS_POLL_INTERVAL` (30s) with adaptive backoff.
- [x] **Azure Database Migration Service CDC checkpoint/retry** — CDC error behavior, batch apply, stream buffer, full-load settings configured in Terraform.
- [x] **DITL test scripts** — Runnable Cypress scripts with real Fiori selectors and OData intercepts.

### Must Complete (Environment-Specific)
- [ ] **Install PyRFC + SAP NW RFC SDK** — Required for real SAP connectivity. See `scripts/setup-pyrfc.sh`.
- [ ] **Configure Azure Key Vault** — Store SAP credentials securely (never in plaintext config files).
- [ ] **Restrict CORS** — Change wildcard CORS (`*`) in `api_server.py` to your specific frontend domain.
- [ ] **Set Terraform variables** — Edit `terraform/environments/dev/terraform.tfvars` with your Azure region, VNet CIDRs, SAP connection details.
- [ ] **Choose LLM mode** — Set `llm_mode` to `CLAUDE_OPUS` (standard) or `AIRGAPPED_LOCAL` (high-security).
- [ ] **Create idempotency Cosmos DB container** — `migrate4hana-idempotency` with pk/sk string keys and TTL on `ttl` attribute (see PRODUCTION_READINESS_GUIDE.md).
- [ ] **Configure new environment variables** — Set `RFC_CALL_TIMEOUT_SECONDS`, `RFC_PAGE_SIZE`, `FINS_MAX_POLLS`, `FINS_POLL_INTERVAL`, `ROLLBACK_BATCH_SIZE`, `IDEMPOTENCY_TABLE` as needed (all have sensible defaults).

### SAP Tool Prerequisites
- [ ] **Maintenance Planner access** — SAP S-user with authorization on SAP ONE Support Launchpad.
- [ ] **SAP Readiness Check installed** — SAP Note 2913617 applied on source ECC system. Credentials configured.
- [ ] **Simplification Item Check installed** — SAP Note 2502552 applied on source ECC system.
- [ ] **SUM/DMO downloaded** — Software Update Manager installed on application server.
- [ ] **HANA database prepared** — Target HANA database installed and accessible.
- [ ] **stack.xml generated** — From Maintenance Planner for the target S/4HANA version.

### SUM/DMO Prerequisites (Before Phase 3)
- [ ] **SUM tool installed on SAP application server** — Extracted and verified on the source system.
- [ ] **Target HANA database prepared and accessible** — Sized, configured, and network-reachable from the app server.
- [ ] **All SI-Check RED items resolved** — No critical simplification item incompatibilities remaining.
- [ ] **Source system backup completed** — Full backup or snapshot taken immediately before conversion.
- [ ] **stack.xml from Maintenance Planner available** — Generated and validated for the target S/4HANA version.
- [ ] **SPAU/SPDD strategy defined** — Adjustment approach decided for post-conversion code reconciliation.
- [ ] **FINS_MASS_DATA_MONITOR parameters confirmed** — Finance migration scope and parameters reviewed.

### Verify Before Each Migration Run
- [ ] ECC connection tested and confirmed
- [ ] S/4HANA target connection tested and confirmed
- [ ] Run assessment (Phases 1–2) first to review findings
- [ ] Review all SAP readiness check results
- [ ] Review GO-LIVE scorecard before proceeding to conversion
- [ ] Confirm Azure Database Migration Service CDC latency is within threshold
- [ ] SUM/DMO prerequisites met (see Section 13)
- [ ] Take SAP ECC system snapshot/backup before Phase 3
