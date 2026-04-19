# Migrate4HANA

**Automated SAP ECC → S/4HANA Migration Platform on Microsoft Azure**

[![Azure](https://img.shields.io/badge/cloud-Microsoft%20Azure-0078D4?logo=microsoftazure&logoColor=white)](#azure-services)
[![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](#prerequisites)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform&logoColor=white)](#azure-deployment)
[![SAP](https://img.shields.io/badge/SAP-ECC%20→%20S%2F4HANA-0FAAFF?logo=sap&logoColor=white)](#17-stage-pipeline)
[![License](https://img.shields.io/badge/license-Proprietary-red)](#license)

> Aligned with **SAP Activate Methodology** — 17-stage, 5-phase fully automated migration pipeline with dual-path GenAI code remediation.

---

## Table of Contents

- [Overview](#overview)
- [Azure Services](#azure-services)
- [17-Stage Pipeline](#17-stage-pipeline)
- [Dual-Path GenAI Architecture](#dual-path-genai-architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Azure Deployment](#azure-deployment)
- [Environment Variables](#environment-variables)
- [License](#license)

---

## Overview

Migrate4HANA is a fully Azure-native platform that automates SAP ECC to S/4HANA system conversions. The platform orchestrates **17 migration stages** across the **5 SAP Activate phases** (Discover → Prepare → Explore → Realize → Deploy), replacing months of manual effort with a deterministic, auditable pipeline.

Key capabilities:

- **End-to-end automation** — from ECC system discovery through final cutover validation
- **GenAI-powered code remediation** — dual-path architecture supporting both cloud (Anthropic Claude Opus 4.6) and air-gapped (self-hosted LLM) inference
- **Real-time telemetry** — live progress streaming via Azure Web PubSub
- **Compliance-first** — 7-year WORM audit trail, immutable logging, WAF protection
- **Offline mode** — full local execution with mock SAP data for development and demos

---

## Azure Services

| Component | Azure Service |
|---|---|
| Serverless Functions (18 handlers) | Azure Functions (Premium Plan, Python 3.11) |
| Heavy Compute (4 tasks) | Azure Container Apps (4 vCPU / 16 GiB) |
| Orchestration | Azure Durable Functions (17-stage pipeline) |
| API Gateway | Azure API Management (APIM) |
| GenAI Path A (Cloud) | Anthropic Claude Opus 4.6 (direct API via `anthropic` SDK) |
| GenAI Path B (Air-Gapped) | Azure NC-series GPU VM (Ollama serving Gemma 4 26B, NSG blocks internet) |
| Database | Azure Cosmos DB (NoSQL API) |
| Object Storage | Azure Blob Storage (4 containers, 7-year WORM for audit) |
| Secrets | Azure Key Vault + User-Assigned Managed Identity |
| Real-Time Telemetry | Azure Web PubSub |
| WAF | Azure Front Door WAF (OWASP + rate limiting) |
| Monitoring & Audit | Azure Monitor + Log Analytics + Immutable Blob Storage |
| Data Migration (CDC) | Azure Data Factory |
| Networking | Azure VNet (5 subnets), NSGs for SAP ports |
| Container Registry | Azure Container Registry (ACR) |
| IaC | Terraform (`azurerm` provider) |

---

## 17-Stage Pipeline

The pipeline follows the **SAP Activate methodology**, organized into five phases:

### Phase 1 — Discover

| Stage | Name | Runtime | Description |
|-------|------|---------|-------------|
| 1 | Discovery Engine | Container App | SAP ECC system scan via RFC |
| 1A | SUM Orchestrator | Function | Software Update Manager coordination |

### Phase 2 — Prepare

| Stage | Name | Runtime | Description |
|-------|------|---------|-------------|
| 2 | Simplification Check | Function | S/4HANA simplification item analysis |
| 3 | Data Hygiene | Function | BP deduplication, data cleansing |
| 4 | Config Replicator | Function | Extract ECC configuration for S/4HANA |
| 5 | Code Analyzer | Container App | ABAP code analysis with AST + GenAI |

### Phase 3 — Explore

| Stage | Name | Runtime | Description |
|-------|------|---------|-------------|
| 6 | Readiness Check | Function | Pre-migration validation |
| 7 | Integration Mapper | Function | Interface / RFC / IDoc mapping |
| 8 | Config Applier | Function | Apply configuration to S/4HANA |
| 9 | Role Migrator | Function | Authorization role migration |

### Phase 4 — Realize

| Stage | Name | Runtime | Description |
|-------|------|---------|-------------|
| 10 | Role Provisioner | Function | Assign roles in S/4HANA |
| 11 | Code Deployer | Function | Deploy fixed ABAP code |
| 12 | Data Loader | Container App | Mass data migration |
| 12A | Data Loader Reconcile | Container App | Data validation and reconciliation |
| 13 | Integration Activator | Function | Activate interfaces |

### Phase 5 — Deploy

| Stage | Name | Runtime | Description |
|-------|------|---------|-------------|
| 14 | Cutover Orchestrator | Function | Final cutover execution |
| 15 | Migration Validator | Function | Post-migration validation |
| 16 | Maintenance Planner | Function | Update planning |
| 17 | Migration Completeness Analyzer | Function | Final scorecard + PDF report |

---

## Dual-Path GenAI Architecture

The **Code Analyzer** (Stage 5) uses a dual-path strategy for ABAP code remediation:

```
                    ┌──────────────────────────────────┐
                    │        genai_router.py            │
                    │   LLM_MODE: auto│cloud│airgapped  │
                    └────────┬─────────────┬───────────┘
                             │             │
                    ┌────────▼──────┐ ┌────▼───────────────┐
                    │   Path A      │ │   Path B            │
                    │   Cloud       │ │   Air-Gapped        │
                    │               │ │                     │
                    │ Claude Opus   │ │ Gemma 4 26B via     │
                    │ 4.6 via       │ │ Ollama on Azure     │
                    │ anthropic SDK │ │ NC-series GPU VM    │
                    │               │ │ NSG: no internet    │
                    └───────────────┘ └─────────────────────┘
```

- **Path A (Cloud):** Anthropic Claude Opus 4.6 via the `anthropic` Python SDK. API key stored in Azure Key Vault. Exponential backoff for rate limits.
- **Path B (Air-Gapped):** Gemma 4 26B served by Ollama on an Azure NC-series GPU VM inside an isolated subnet. NSG denies all internet outbound traffic — zero data exfiltration. Uses the `ollama` Python SDK for inference.
- **Routing:** Controlled by the `LLM_MODE` environment variable (`auto`, `cloud`, `airgapped`). In `auto` mode, sensitive AST nodes are automatically routed to the air-gapped path.
- **PII Masking:** `data_scrubber.py` strips personally identifiable information before any GenAI dispatch.

---

## Project Structure

```
migrate4hanav2/
├── functions/                              # Azure Function handlers (18 stages)
│   ├── discovery-engine/                # Stage 1: ECC system scan
│   ├── sum-orchestrator/                # Stage 1A: SUM coordination
│   ├── simplification-check/            # Stage 2: S/4HANA simplification analysis
│   ├── data-hygiene/                    # Stage 3: BP dedup, data cleansing
│   ├── config-replicator/               # Stage 4: Config extraction
│   ├── code-analyzer/                   # Stage 5: ABAP code analysis + GenAI
│   │   ├── handler.py
│   │   ├── claude_engine.py             #   Anthropic Claude Opus 4.6 engine
│   │   ├── genai_router.py              #   Dual-path routing logic
│   │   └── data_scrubber.py             #   PII masking before GenAI dispatch
│   ├── readiness-check/                 # Stage 6
│   ├── integration-mapper/              # Stage 7
│   ├── config-applier/                  # Stage 8
│   ├── role-migrator/                   # Stage 9
│   ├── role-provisioner/                # Stage 10
│   ├── code-deployer/                   # Stage 11
│   ├── data-loader/                     # Stage 12
│   ├── data-migrator/                   # Stage 12A
│   ├── integration-activator/           # Stage 13
│   ├── cutover-orchestrator/            # Stage 14
│   ├── migration-validator/             # Stage 15
│   ├── maintenance-planner/             # Stage 16
│   ├── migration-completeness-analyzer/ # Stage 17: PDF scorecard
│   ├── process-miner/                   # ST03N workload analysis
│   ├── test-generator/                  # DITL test generation
│   ├── rollback-manager/                # Automated rollback on failure
│   └── utils/                           # Shared utilities
│       ├── storage_client.py            #   Azure Blob Storage wrapper
│       ├── secrets_client.py            #   Azure Key Vault wrapper
│       ├── db_client.py                 #   Azure Cosmos DB wrapper
│       ├── logger.py                    #   Web PubSub telemetry broadcaster
│       ├── rfc_pool.py                  #   Thread-safe SAP RFC connection pool
│       ├── rule_router.py               #   Simplification rules engine
│       └── validation.py               #   Input validation
├── containers/                                 # Container Apps worker image
│   ├── Dockerfile                       #   CBL-Mariner based, PyRFC + SAP NW RFC SDK
│   └── entrypoint.py                    #   Durable Functions callback integration
├── frontend/                            # React + Vite + Tailwind UI
│   └── src/
├── terraform/                           # Infrastructure as Code
│   ├── main.tf                          # Root module wiring 14 Azure modules
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars.example
│   ├── modules/                         # 14 Terraform modules
│   │   ├── vnet/                        #   VNet + 5 subnets + NSGs
│   │   ├── keyvault/                    #   Key Vault + Managed Identity
│   │   ├── storage/                     #   Blob Storage (4 containers, WORM)
│   │   ├── cosmosdb/                    #   Cosmos DB (NoSQL API, 3 containers)
│   │   ├── functions/                   #   Azure Functions Premium Plan
│   │   ├── container-apps/              #   Container Apps (4 vCPU / 16 GiB)
│   │   ├── durable-functions/           #   Orchestrator (17-stage state machine)
│   │   ├── apim/                        #   API Management
│   │   ├── genai/                       #   Anthropic API key in Key Vault
│   │   ├── gpu-vm/                      #   NC-series GPU VM (air-gapped LLM)
│   │   ├── web-pubsub/                  #   Real-time telemetry
│   │   ├── waf/                         #   Front Door WAF
│   │   ├── audit/                       #   Monitor + Log Analytics + Immutable Blob
│   │   └── data-migration/              #   Data Factory (CDC pipelines)
│   └── environments/                    # Per-environment configs
│       ├── dev/
│       ├── staging/
│       └── prod/
├── scripts/
│   ├── deploy.sh                        # Azure deployment script
│   └── setup-pyrfc.sh                   # PyRFC container image builder
├── sapnwrfc/                            # SAP NW RFC SDK (Windows DLLs)
│   ├── __init__.py                      #   Auto-registers DLL path for pyrfc
│   └── lib/                             #   sapnwrfc.dll, ICU libraries
├── tests/                               # Test suite
├── api_server.py                        # Local FastAPI dev server
├── run_local_pipeline.py                # Local CLI runner (offline mode)
├── run_10x_evaluation.py                # Batch evaluation runner
├── multi_volume_report_generator.py     # PDF report generator
├── pdf_report_generator.py              # Single-volume PDF generator
├── requirements.txt                     # Python dependencies
├── .env.example                         # Environment variable template
├── DEPLOY.md                            # Step-by-step deployment guide
└── README.md                            # This file
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Azure subscription | Contributor access |
| Azure CLI | v2.50+ |
| Terraform | v1.5+ |
| Docker | Latest stable |
| Node.js | 18+ |
| Python | 3.11 |
| SAP NW RFC SDK | 7.50 *(Windows DLLs bundled in `sapnwrfc/lib/`; Linux SDK needed for Docker builds)* |

---

## Quick Start (Local Development)

```bash
# 1. Clone and install
git clone https://github.com/Ravi-Teja-Chowdary/migrate4hanav2.git
cd migrate4hanav2
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Azure credentials and SAP connection details

# 3. Run locally (offline mode with mock SAP data)
python run_local_pipeline.py --mode mock

# 4. Run with live SAP ECC connection
python run_local_pipeline.py --mode ecc --host 192.168.0.6 --sysnr 41 --client 800

# 5. Start the API server
python api_server.py

# 6. Start the frontend
cd frontend && npm install && npm run dev
```

---

## Azure Deployment

> See **[DEPLOY.md](DEPLOY.md)** for the full step-by-step deployment guide.

```bash
# 1. Login to Azure
az login

# 2. Configure Terraform
cd terraform/environments/dev
cp ../../terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your subscription and resource details

# 3. Deploy infrastructure
terraform init && terraform apply

# 4. Build and push container images
az acr login --name <your-acr>
docker build -f containers/Dockerfile -t <your-acr>.azurecr.io/migrate4hana/worker:latest .
docker push <your-acr>.azurecr.io/migrate4hana/worker:latest

# 5. Deploy Azure Functions
func azure functionapp publish <your-func-app> --python
```

---

## Environment Variables

Key environment variables (see [`.env.example`](.env.example) for the full list):

| Variable | Description |
|---|---|
| `AZURE_STORAGE_ACCOUNT_NAME` | Azure Blob Storage account name |
| `AZURE_COSMOSDB_ENDPOINT` | Cosmos DB endpoint URL |
| `AZURE_KEYVAULT_URI` | Key Vault URI |
| `AZURE_WEB_PUBSUB_CONNECTION_STRING` | Web PubSub connection string |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `ANTHROPIC_MODEL` | Claude model ID (default: `claude-opus-4-6-20250219`) |
| `LOCAL_LLM_HOST` | Ollama endpoint on GPU VM (e.g., `http://10.0.5.4:11434`) |
| `LOCAL_LLM_MODEL` | Ollama model name (default: `gemma4:26b`) |
| `LLM_MODE` | GenAI routing: `auto`, `cloud`, or `airgapped` |
| `AST_CHANGE_THRESHOLD` | Threshold for GenAI escalation (default: `3`) |

---

## License

Proprietary. All rights reserved.
