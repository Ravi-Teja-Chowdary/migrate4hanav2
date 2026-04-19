# Migrate4HANA — Azure Deployment Guide

A complete, step-by-step guide to deploy the Migrate4HANA platform on Microsoft Azure. This guide assumes **zero prior Azure experience** and walks through every step from creating an Azure account to running your first SAP ECC-to-S/4HANA migration.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Azure Account Setup](#2-azure-account-setup)
3. [Install Required Tools](#3-install-required-tools)
4. [Clone the Repository](#4-clone-the-repository)
5. [Configure Azure Authentication](#5-configure-azure-authentication)
6. [Configure Terraform Variables](#6-configure-terraform-variables)
7. [Deploy Azure Infrastructure](#7-deploy-azure-infrastructure)
8. [Build and Push Container Images](#8-build-and-push-container-images)
9. [Deploy Azure Functions](#9-deploy-azure-functions)
10. [Deploy the Frontend](#10-deploy-the-frontend)
11. [Configure SAP Connectivity](#11-configure-sap-connectivity)
12. [Configure GenAI (Claude Opus 4.6)](#12-configure-genai-claude-opus-46)
13. [Run Your First Migration](#13-run-your-first-migration)
14. [Verify the Deployment](#14-verify-the-deployment)
15. [Monitoring and Troubleshooting](#15-monitoring-and-troubleshooting)
16. [Cost Estimation](#16-cost-estimation)
17. [Tear Down (Cleanup)](#17-tear-down-cleanup)
18. [Appendix A — Environment Variables Reference](#appendix-a--environment-variables-reference)
19. [Appendix B — Terraform Outputs Reference](#appendix-b--terraform-outputs-reference)
20. [Appendix C — Networking and Ports](#appendix-c--networking-and-ports)

---

## 1. Prerequisites

Before starting, make sure you have the following:

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Azure Subscription | Any (Pay-As-You-Go or Enterprise) | Hosts all cloud resources |
| Azure CLI | v2.50 or later | Manage Azure resources from terminal |
| Terraform | v1.5 or later | Infrastructure as Code deployment |
| Docker | v20+ | Build container images for heavy-compute stages |
| Python | 3.11 | Runtime for Azure Functions and local dev |
| Node.js | 18+ | Build the React frontend |
| Git | Any | Clone the repository |
| Azure Functions Core Tools | v4 | Deploy Azure Functions locally and to cloud |

**Optional (for live SAP connectivity):**
| Requirement | Purpose |
|-------------|---------|
| SAP NW RFC SDK 7.50 | Native SAP RFC connectivity — **both Windows and Linux SDKs are bundled** in the repository (`sapnwrfc/lib/` and `nwrfcsdk-linux/lib/`) |
| SAP S-user account | Not needed (SDK is pre-bundled) |
| Network access to SAP ECC | RFC port 3300 connectivity to your SAP system |
| Network access to SAP S/4HANA | RFC port 3300 + OData port 443 |

---

## 2. Azure Account Setup

If you don't already have an Azure subscription:

### 2.1 Create an Azure Account

1. Go to [https://azure.microsoft.com/free/](https://azure.microsoft.com/free/)
2. Click **"Start free"** — you get $200 in credits for 30 days
3. Sign in with your Microsoft account (or create one)
4. Complete the registration with your payment method
5. Once complete, go to the [Azure Portal](https://portal.azure.com)

### 2.2 Verify Your Subscription

```bash
# After installing Azure CLI (next section), verify your subscription
az account show --query "{Name:name, ID:id, State:state}" -o table
```

You should see your subscription listed with `State: Enabled`.

### 2.3 Required Resource Providers

Azure requires registering resource providers before using certain services. Register all providers needed by Migrate4HANA:

```bash
# Register all required providers
az provider register --namespace Microsoft.Web              # Azure Functions
az provider register --namespace Microsoft.App              # Container Apps
az provider register --namespace Microsoft.ContainerRegistry # ACR
az provider register --namespace Microsoft.DocumentDB       # Cosmos DB
az provider register --namespace Microsoft.Storage          # Blob Storage
az provider register --namespace Microsoft.KeyVault         # Key Vault
az provider register --namespace Microsoft.SignalRService   # Web PubSub
az provider register --namespace Microsoft.ApiManagement    # APIM
az provider register --namespace Microsoft.Cdn              # Front Door WAF
az provider register --namespace Microsoft.DataFactory      # Data Factory
az provider register --namespace Microsoft.Compute          # VMs (GPU)
az provider register --namespace Microsoft.Network          # VNet, NSG
az provider register --namespace Microsoft.OperationalInsights # Log Analytics

# Check registration status (all should say "Registered")
az provider list --query "[?registrationState=='Registered'].namespace" -o table
```

> **Note:** Provider registration can take a few minutes. Wait until all show as "Registered" before proceeding.

---

## 3. Install Required Tools

### 3.1 Azure CLI

**Windows (PowerShell):**
```powershell
# Using winget (recommended)
winget install Microsoft.AzureCLI

# Or download the MSI installer from:
# https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows
```

**macOS:**
```bash
brew install azure-cli
```

**Linux (Ubuntu/Debian):**
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

Verify: `az version` — should show 2.50+

### 3.2 Terraform

**Windows (PowerShell):**
```powershell
winget install HashiCorp.Terraform

# Or download from: https://developer.hashicorp.com/terraform/downloads
```

**macOS:**
```bash
brew install terraform
```

**Linux:**
```bash
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | \
  sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
  https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install terraform
```

Verify: `terraform version` — should show 1.5+

### 3.3 Docker

Download and install from [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

Verify: `docker --version`

### 3.4 Python 3.11

Download from [https://www.python.org/downloads/](https://www.python.org/downloads/)

> **Important:** Select Python **3.11.x** specifically. Azure Functions Premium Plan uses Python 3.11.

Verify: `python --version` or `python3 --version`

### 3.5 Node.js 18+

Download from [https://nodejs.org/](https://nodejs.org/) (LTS version recommended)

Verify: `node --version`

### 3.6 Azure Functions Core Tools

**Windows:**
```powershell
winget install Microsoft.Azure.FunctionsCoreTools
```

**macOS:**
```bash
brew tap azure/functions
brew install azure-functions-core-tools@4
```

**Linux:**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/microsoft-ubuntu-$(lsb_release -cs)-prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/dotnetdev.list'
sudo apt-get update && sudo apt-get install azure-functions-core-tools-4
```

Verify: `func --version` — should show 4.x

---

## 4. Clone the Repository

```bash
git clone https://github.com/Ravi-Teja-Chowdary/migrate4hanav2.git
cd migrate4hanav2

# Switch to the azure-setup branch
git checkout azure-setup

# Install Python dependencies
pip install -r requirements.txt
```

---

## 5. Configure Azure Authentication

### 5.1 Login to Azure

```bash
# Interactive login (opens browser)
az login

# If you have multiple subscriptions, set the correct one:
az account list -o table
az account set --subscription "<your-subscription-id>"
```

### 5.2 Create a Service Principal (for Terraform)

Terraform needs credentials to manage Azure resources. Create a service principal:

```bash
# Create service principal with Contributor role
az ad sp create-for-rbac \
  --name "migrate4hana-terraform" \
  --role Contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)
```

This outputs:
```json
{
  "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "displayName": "migrate4hana-terraform",
  "password": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

### 5.3 Set Environment Variables

Set these environment variables so Terraform can authenticate:

**Windows (PowerShell):**
```powershell
$env:ARM_CLIENT_ID = "<appId from above>"
$env:ARM_CLIENT_SECRET = "<password from above>"
$env:ARM_TENANT_ID = "<tenant from above>"
$env:ARM_SUBSCRIPTION_ID = (az account show --query id -o tsv)
```

**Linux/macOS (Bash):**
```bash
export ARM_CLIENT_ID="<appId from above>"
export ARM_CLIENT_SECRET="<password from above>"
export ARM_TENANT_ID="<tenant from above>"
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

> **Tip:** Add these to your shell profile (`.bashrc`, `.zshrc`, or PowerShell `$PROFILE`) so you don't have to set them every time.

---

## 6. Configure Terraform Variables

### 6.1 Create Your Variables File

```bash
cd terraform/environments/dev
cp ../../terraform.tfvars.example terraform.tfvars
```

### 6.2 Edit terraform.tfvars

Open `terraform/environments/dev/terraform.tfvars` in your editor and configure:

```hcl
# ──────────────────────────────────────────────────────────
# REQUIRED — You must fill these in
# ──────────────────────────────────────────────────────────

environment = "dev"
location    = "southindia"         # Azure South India region
alert_email = "your-email@example.com"  # Receives monitoring alerts

# ──────────────────────────────────────────────────────────
# GenAI — Anthropic Claude API Key
# ──────────────────────────────────────────────────────────
# Get your API key from: https://console.anthropic.com/settings/keys
anthropic_api_key = "sk-ant-api03-..."
anthropic_model   = "claude-opus-4-6-20250219"

# ──────────────────────────────────────────────────────────
# OPTIONAL — Defaults work for dev environments
# ──────────────────────────────────────────────────────────

# GPU VM for air-gapped LLM (costs ~$2/hr — disable for dev)
enable_gpu_vm  = false
gpu_vm_size    = "Standard_NC6s_v3"
ssh_public_key = ""    # Set if enable_gpu_vm = true

# WAF (costs ~$50/month — disable for dev)
enable_waf = false

# SAP connectivity
pyrfc_enabled = false             # Set true when SAP NW RFC SDK is available
sap_rfc_cidr  = "172.16.0.0/12"  # Your SAP network CIDR
s4hana_vm_ip  = ""                # IP of S/4HANA target (if available)

# Database Migration (fill in if using Azure Data Factory)
ecc_db_host = ""
ecc_db_name = ""
s4_db_host  = ""
s4_db_name  = ""

# Compute sizing (defaults are good for dev)
function_app_sku     = "EP1"      # Elastic Premium 1 (~$150/month)
container_app_cpu    = 4.0        # 4 vCPU for Container Apps
container_app_memory = "16Gi"     # 16 GiB for Container Apps
```

### 6.3 Understanding Key Decisions

| Setting | `false` (Default) | `true` |
|---------|-------------------|--------|
| `enable_gpu_vm` | GenAI uses only Claude API (cloud) | Provisions NC-series GPU VM (~$2/hr) with Ollama + Gemma 4 26B for air-gapped LLM |
| `enable_waf` | API exposed directly via APIM | Azure Front Door WAF in front of APIM (OWASP protection) |
| `pyrfc_enabled` | Uses mock/offline SAP data | Enables live RFC connections to SAP ECC/S/4HANA |

---

## 7. Deploy Azure Infrastructure

### 7.1 Initialize Terraform

```bash
cd terraform/environments/dev

# Initialize Terraform (downloads Azure provider plugins)
terraform init
```

You should see: `Terraform has been successfully initialized!`

### 7.2 Preview the Deployment

```bash
# See what Terraform will create (no changes made yet)
terraform plan
```

Review the plan. You'll see ~40-60 resources being created including:
- 1 Resource Group
- 1 VNet with 5 subnets and NSGs
- 1 Key Vault + Managed Identity
- 1 Storage Account (4 containers)
- 1 Cosmos DB Account (3 containers)
- 1 Azure Functions App (Premium Plan)
- 1 Container Apps Environment (4 container apps)
- 1 Durable Functions Orchestrator
- 1 API Management instance
- 1 Web PubSub service
- 1 Log Analytics workspace
- 1 Data Factory

### 7.3 Apply the Deployment

```bash
# Deploy all resources (type 'yes' when prompted)
terraform apply
```

> **This takes 15-30 minutes** — API Management alone takes ~15 minutes to provision.

### 7.4 Save the Outputs

After deployment completes, save the important outputs:

```bash
# View all outputs
terraform output

# Key outputs you'll need:
terraform output function_app_url
terraform output storage_account_name
terraform output cosmosdb_endpoint
terraform output keyvault_uri
terraform output apim_gateway_url
terraform output orchestrator_url
```

---

## 8. Build and Push Container Images

The heavy-compute stages (Discovery Engine, Code Analyzer, Data Loader, Data Loader Reconcile) run as Azure Container Apps. You need to build and push their Docker image.

### 8.1 Create an Azure Container Registry (ACR)

If Terraform didn't create one, create it manually:

```bash
# Get the resource group name
RG_NAME=$(cd terraform/environments/dev && terraform output -raw resource_group_name)

# Create ACR (name must be globally unique, lowercase, no hyphens)
az acr create \
  --resource-group "$RG_NAME" \
  --name migrate4hanadev \
  --sku Basic

# Enable admin access (needed for Container Apps to pull images)
az acr update --name migrate4hanadev --admin-enabled true
```

### 8.2 Login to ACR

```bash
az acr login --name migrate4hanadev
```

### 8.3 Build and Push the Worker Image

```bash
cd /path/to/migrate4hanav2

# Build the container image (from project root)
docker build -f containers/Dockerfile -t migrate4hanadev.azurecr.io/migrate4hana/worker:latest .

# Push to ACR
docker push migrate4hanadev.azurecr.io/migrate4hana/worker:latest
```

> **Note about SAP NW RFC SDK:** The Linux x86_64 shared libraries are bundled in `nwrfcsdk-linux/lib/`. The Dockerfile copies them directly — **no separate download is needed**.

### 8.5 SAP NW RFC SDK — Local Development (Windows)

The project bundles the **Windows x64 SAP NW RFC SDK 7.50 DLLs** in `sapnwrfc/lib/` for local development:

```
sapnwrfc/
├── __init__.py          # Auto-registers DLL path on import
└── lib/
    ├── sapnwrfc.dll     # Core RFC library
    ├── icudt50.dll      # ICU data
    ├── icuin50.dll      # ICU internationalization
    ├── icuuc50.dll      # ICU common
    ├── libicudecnumber.dll
    ├── libsapucum.dll   # SAP Unicode library
    └── ...
```

### 8.6 SAP NW RFC SDK — Linux / Docker Builds

The Linux x86_64 shared libraries are bundled in `nwrfcsdk-linux/lib/`:

```
nwrfcsdk-linux/
├── lib/
│   ├── libsapnwrfc.so      # Core RFC library
│   ├── libicudata.so.50     # ICU data
│   ├── libicui18n.so.50     # ICU internationalization
│   ├── libicuuc.so.50       # ICU common
│   ├── libicudecnumber.so
│   └── libsapucum.so        # SAP Unicode library
└── doc/
    └── licenses.txt          # SDK license information
```

**How it works:**
- The `sapnwrfc/__init__.py` module detects the platform at import time.
  - **Windows:** Registers `sapnwrfc/lib/` via `os.add_dll_directory()`.
  - **Linux (local):** Sets `LD_LIBRARY_PATH` to `nwrfcsdk-linux/lib/`.
  - **Linux (Docker):** Prefers `/opt/sap/lib` (copied by Dockerfile).
- Entry-point files (`api_server.py`, `run_local_pipeline.py`, `real_rfc_connection.py`) import `sapnwrfc` **before** importing `pyrfc`.
- No manual `PATH` or `LD_LIBRARY_PATH` manipulation is needed.

### 8.4 Verify the Image

```bash
# List images in your ACR
az acr repository list --name migrate4hanadev -o table

# Show tags
az acr repository show-tags --name migrate4hanadev --repository migrate4hana/worker -o table
```

---

## 9. Deploy Azure Functions

### 9.1 Get the Function App Name

```bash
cd terraform/environments/dev
FUNC_APP_URL=$(terraform output -raw function_app_url)
FUNC_APP_NAME=$(echo $FUNC_APP_URL | sed 's|https://||' | sed 's|\.azurewebsites\.net.*||')
echo "Function App: $FUNC_APP_NAME"
```

### 9.2 Deploy the Functions

```bash
cd /path/to/migrate4hanav2

# Deploy all function handlers to Azure
func azure functionapp publish "$FUNC_APP_NAME" --python
```

### 9.3 Verify Functions

```bash
# List deployed functions
az functionapp function list \
  --name "$FUNC_APP_NAME" \
  --resource-group "$RG_NAME" \
  -o table
```

---

## 10. Deploy the Frontend

### 10.1 Build the Frontend

```bash
cd frontend

# Install dependencies
npm ci

# Set the API base URL (use the APIM gateway URL from Terraform output)
# Create a .env.production file
echo "VITE_API_BASE_URL=https://<your-apim-gateway-url>" > .env.production

# Build for production
npm run build
```

### 10.2 Deploy to Azure Blob Storage Static Website

```bash
STORAGE_ACCOUNT=$(cd ../terraform/environments/dev && terraform output -raw storage_account_name)

# Enable static website hosting
az storage blob service-properties update \
  --account-name "$STORAGE_ACCOUNT" \
  --static-website \
  --404-document index.html \
  --index-document index.html

# Upload the built frontend
az storage blob upload-batch \
  -d '$web' \
  -s dist \
  --account-name "$STORAGE_ACCOUNT" \
  --overwrite

# Get the frontend URL
az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --query "primaryEndpoints.web" -o tsv
```

---

## 11. Configure SAP Connectivity

### 11.1 Store SAP Credentials in Key Vault

```bash
KEYVAULT_NAME=$(cd terraform/environments/dev && terraform output -raw keyvault_uri | sed 's|https://||' | sed 's|\.vault\.azure\.net.*||')

# Store ECC credentials
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
  --name "sap-ecc-credentials" \
  --value '{
    "ashost": "192.168.0.6",
    "sysnr": "00",
    "client": "100",
    "user": "SAPUSER",
    "passwd": "your-password"
  }'

# Store S/4HANA credentials (if available)
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
  --name "s4hana-credentials" \
  --value '{
    "ashost": "10.10.4.10",
    "sysnr": "00",
    "client": "100",
    "user": "S4USER",
    "passwd": "your-password"
  }'
```

### 11.2 Network Connectivity

Your Azure VNet needs connectivity to your SAP systems. Options:

| Method | Best For | Setup |
|--------|----------|-------|
| **Azure VPN Gateway** | Dev/Test | [Create VPN Gateway](https://learn.microsoft.com/en-us/azure/vpn-gateway/tutorial-create-gateway-portal) |
| **Azure ExpressRoute** | Production | Work with your network team — dedicated private connection |
| **Azure VNet Peering** | SAP on Azure | If S/4HANA is already in Azure, peer the VNets |

**Required ports (configured in NSGs by Terraform):**
| Port | Protocol | Purpose |
|------|----------|---------|
| 3300 | TCP | SAP RFC (Remote Function Call) |
| 3200 | TCP | SAP GUI |
| 44300 | TCP | SAP HTTPS (OData/ICF) |

---

## 12. Configure GenAI (Claude Opus 4.6)

### 12.1 Get an Anthropic API Key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign up or log in
3. Navigate to **Settings** → **API Keys**
4. Click **Create Key**
5. Copy the key (starts with `sk-ant-api03-...`)

### 12.2 Store the API Key in Key Vault

If you already set `anthropic_api_key` in `terraform.tfvars`, Terraform stored it automatically. Otherwise:

```bash
az keyvault secret set --vault-name "$KEYVAULT_NAME" \
  --name "anthropic-api-key" \
  --value "sk-ant-api03-your-key-here"
```

### 12.3 (Optional) Air-Gapped GPU VM Setup

If you enabled `enable_gpu_vm = true` in Terraform:

1. SSH into the GPU VM:
```bash
GPU_IP=$(cd terraform/environments/dev && terraform output -raw gpu_vm_private_ip)
ssh azureuser@$GPU_IP
```

2. Verify Ollama is running and Gemma 4 is available (cloud-init auto-installs both):
```bash
# On the GPU VM — check Ollama service status
sudo systemctl status ollama

# Verify Gemma 4 model is loaded
ollama list
# Should show: gemma4:26b
```

If the model isn't present (e.g., internet was blocked before cloud-init finished):
```bash
# Temporarily allow internet to pull the model
# Then re-apply air-gap by revoking the AllowInitialSetupHTTPS NSG rule
ollama pull gemma4:26b
```

3. Set the local LLM host in your function app:
```bash
az functionapp config appsettings set \
  --name "$FUNC_APP_NAME" \
  --resource-group "$RG_NAME" \
  --settings LOCAL_LLM_HOST="http://$GPU_IP:11434" \
             LOCAL_LLM_MODEL="gemma4:26b"
```

4. **Lock down the air-gap** — after the model is downloaded, remove the temporary internet rule:
```bash
az network nsg rule delete \
  --resource-group "$RG_NAME" \
  --nsg-name "nsg-migrate4hana-dev-gpu" \
  --name "AllowInitialSetupHTTPS"
```

> **Security Note:** The GPU VM's NSG blocks all internet outbound traffic after lockdown. This ensures zero data exfiltration for sensitive ABAP code analysis. The Ollama API (port 11434) is only accessible from the functions and containers subnets.

---

## 13. Run Your First Migration

### 13.1 Option A — Local Pipeline (Offline/Mock Mode)

The fastest way to test is running locally with mock data:

```bash
cd /path/to/migrate4hanav2

# Configure local environment
cp .env.example .env
# Edit .env with your Azure credentials

# Run with mock SAP data (no SAP system needed)
python run_local_pipeline.py --mode mock
```

This runs all 17 stages locally using simulated SAP data and generates a PDF report in the `output/` directory.

### 13.2 Option B — Local Pipeline (Live SAP ECC)

```bash
# Run with live SAP ECC connection
python run_local_pipeline.py \
  --mode ecc \
  --host 192.168.0.6 \
  --sysnr 41 \
  --client 800 \
  --user SAPUSER
```

### 13.3 Option C — Cloud Pipeline (Full Azure Deployment)

Trigger the Durable Functions orchestrator:

```bash
ORCHESTRATOR_URL=$(cd terraform/environments/dev && terraform output -raw orchestrator_url)

# Start a migration run
curl -X POST "$ORCHESTRATOR_URL/api/orchestrators/migrate4hana" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "ecc_full",
    "ecc_secret_name": "sap-ecc-credentials",
    "s4_secret_name": "s4hana-credentials",
    "stages": "all"
  }'
```

This returns a status URL. Poll it to monitor progress:

```bash
# Check orchestration status
curl "$ORCHESTRATOR_URL/api/orchestrators/<instance-id>"
```

### 13.4 Option D — Via the Web UI

1. Open the frontend URL in your browser
2. Go to **Connections** → Configure your SAP ECC and S/4HANA connections
3. Go to **Pipeline** → Click **Start Migration**
4. Monitor progress in real-time via the **Log Viewer**

---

## 14. Verify the Deployment

Run through this checklist to confirm everything is working:

### 14.1 Infrastructure Health

```bash
RG_NAME=$(cd terraform/environments/dev && terraform output -raw resource_group_name)

# Check all resources in the resource group
az resource list --resource-group "$RG_NAME" -o table

# Check Azure Functions are running
az functionapp show --name "$FUNC_APP_NAME" --resource-group "$RG_NAME" \
  --query "state" -o tsv
# Expected: Running

# Check Container Apps are provisioned
az containerapp list --resource-group "$RG_NAME" -o table

# Check Cosmos DB is accessible
az cosmosdb show --name "cosmos-migrate4hana-dev" --resource-group "$RG_NAME" \
  --query "documentEndpoint" -o tsv
```

### 14.2 GenAI Connectivity

```bash
# Test Claude API access (from your local machine)
python -c "
import anthropic
client = anthropic.Anthropic(api_key='your-key-here')
response = client.messages.create(
    model='claude-opus-4-6-20250219',
    max_tokens=100,
    messages=[{'role': 'user', 'content': 'Say hello'}]
)
print(response.content[0].text)
"
```

### 14.3 End-to-End Smoke Test

```bash
# Run in mock mode to test the full pipeline
python run_local_pipeline.py --mode mock --stages "1,2,5,17"
```

This runs a subset of stages and generates a PDF report — confirming the pipeline works.

---

## 15. Monitoring and Troubleshooting

### 15.1 View Logs

```bash
# Azure Functions logs (real-time)
az webapp log tail --name "$FUNC_APP_NAME" --resource-group "$RG_NAME"

# Container Apps logs
az containerapp logs show \
  --name "ca-discovery-engine-dev" \
  --resource-group "$RG_NAME" \
  --follow

# Query Log Analytics (last 1 hour errors)
az monitor log-analytics query \
  --workspace "$(terraform output -raw log_analytics_workspace_id)" \
  --analytics-query "AppExceptions | where TimeGenerated > ago(1h) | project TimeGenerated, ExceptionType, OuterMessage" \
  -o table
```

### 15.2 Azure Portal Dashboards

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your Resource Group (`rg-migrate4hana-dev`)
3. Key dashboards:
   - **Application Insights** → Live Metrics, Failures, Performance
   - **Cosmos DB** → Metrics, Data Explorer
   - **Azure Functions** → Monitor, Invocations
   - **Log Analytics** → Logs (KQL queries)

### 15.3 Common Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `DefaultAzureCredential` error | Missing Azure auth | Run `az login` or set `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` |
| Cosmos DB 403 Forbidden | Missing permissions | Check Managed Identity role assignment in Key Vault |
| Claude 429 Rate Limit | Too many API calls | Built-in exponential backoff handles this; wait and retry |
| Container App CrashLoopBackOff | Missing env vars or image | Check Container App logs; verify ACR image exists |
| RFC connection timeout | Network/firewall issue | Verify VPN/ExpressRoute and NSG rules (port 3300) |
| `pyrfc` import error | Missing SAP NW RFC SDK | **Local/Windows:** Bundled in `sapnwrfc/lib/` — ensure `import sapnwrfc` runs before pyrfc. **Docker:** Bundled in `nwrfcsdk-linux/lib/` — Dockerfile copies automatically. **Linux (local):** `sapnwrfc/__init__.py` sets `LD_LIBRARY_PATH` to `nwrfcsdk-linux/lib/` |
| Functions cold start | Premium Plan scaling | First invocation takes 5-10s; subsequent calls are fast |
| APIM 502 Bad Gateway | Functions not deployed | Re-deploy with `func azure functionapp publish` |

---

## 16. Cost Estimation

### 16.1 Development Environment (Minimal)

With `enable_gpu_vm = false` and `enable_waf = false`:

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Azure Functions (EP1) | ~$150 |
| Container Apps | ~$50 (scales to zero when idle) |
| Cosmos DB (400 RU/s) | ~$25 |
| Blob Storage | ~$5 |
| Key Vault | ~$1 |
| Web PubSub (Free tier) | $0 |
| API Management (Developer) | ~$50 |
| Log Analytics | ~$5 |
| VNet + NSGs | $0 |
| **Total (dev)** | **~$286/month** |

### 16.2 Production Environment

With `enable_gpu_vm = true` and `enable_waf = true`:

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Azure Functions (EP2/EP3) | ~$300-600 |
| Container Apps (4 vCPU) | ~$150 |
| GPU VM (NC6s_v3) | ~$1,400 (on-demand) |
| Cosmos DB (auto-scale) | ~$100 |
| Blob Storage (with WORM) | ~$20 |
| Front Door WAF | ~$50 |
| API Management (Standard) | ~$300 |
| ExpressRoute | ~$300+ |
| **Total (prod)** | **~$2,620+/month** |

### 16.3 Cost-Saving Tips

- **GPU VM**: Use `az vm deallocate` when not running GenAI analysis — only pays for storage when stopped
- **Container Apps**: Automatically scales to zero when idle (pay per use)
- **Dev environment**: Use `enable_gpu_vm = false` and `enable_waf = false`
- **Reserved Instances**: Save 30-50% on Functions and VMs with 1-year reservations
- **Anthropic API**: Most programs are handled by the AST engine (~90%) — Claude costs are typically under $20 per migration run

---

## 17. Tear Down (Cleanup)

To remove all Azure resources and stop incurring charges:

```bash
cd terraform/environments/dev

# Destroy all resources (type 'yes' when prompted)
terraform destroy
```

> **Warning:** This permanently deletes ALL resources including Cosmos DB data, Key Vault secrets, and storage. Export any data you need first.

To delete just the resource group (nuclear option):
```bash
az group delete --name rg-migrate4hana-dev --yes --no-wait
```

---

## Appendix A — Environment Variables Reference

Full list of environment variables used by Migrate4HANA:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_TENANT_ID` | Cloud only | (from MI) | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Cloud only | (from MI) | Managed Identity client ID |
| `AZURE_STORAGE_ACCOUNT_NAME` | Yes | — | Blob Storage account name |
| `AZURE_STORAGE_CONTAINER` | No | `staging` | Default blob container |
| `AZURE_COSMOSDB_ENDPOINT` | Yes | — | Cosmos DB endpoint URL |
| `AZURE_COSMOSDB_KEY` | Yes | — | Cosmos DB primary key |
| `AZURE_KEYVAULT_URI` | Yes | — | Key Vault URI |
| `AZURE_WEB_PUBSUB_CONNECTION_STRING` | No | — | Web PubSub connection string |
| `AZURE_WEB_PUBSUB_HUB` | No | `telemetry` | Web PubSub hub name |
| `ANTHROPIC_API_KEY` | For GenAI | — | Anthropic Claude API key |
| `ANTHROPIC_MODEL` | No | `claude-opus-4-6-20250219` | Claude model identifier |
| `LLM_MODE` | No | `auto` | `auto`, `cloud`, or `airgapped` |
| `LOCAL_LLM_HOST` | For air-gap | — | Ollama endpoint on GPU VM (e.g., `http://10.0.5.4:11434`) |
| `LOCAL_LLM_MODEL` | For air-gap | `gemma4:26b` | Ollama model name |
| `ECC_SECRET_NAME` | No | `sap-ecc-credentials` | Key Vault secret for ECC |
| `S4_SECRET_NAME` | No | `s4hana-credentials` | Key Vault secret for S/4HANA |
| `AST_CHANGE_THRESHOLD` | No | `3` | GenAI escalation threshold |
| `RULES_TABLE_NAME` | No | `simplification-rules` | Cosmos DB container for rules |
| `IDEMPOTENCY_TABLE` | No | `idempotency` | Cosmos DB container for idempotency |

---

## Appendix B — Terraform Outputs Reference

After `terraform apply`, these outputs are available:

| Output | Description |
|--------|-------------|
| `resource_group_name` | Name of the Azure Resource Group |
| `vnet_id` | VNet resource ID |
| `function_app_url` | Azure Functions app URL |
| `container_app_urls` | Map of Container App URLs |
| `cosmosdb_endpoint` | Cosmos DB endpoint |
| `storage_account_name` | Blob Storage account name |
| `keyvault_uri` | Key Vault URI |
| `web_pubsub_hostname` | Web PubSub hostname |
| `apim_gateway_url` | API Management gateway URL |
| `anthropic_secret_name` | Key Vault secret name for Claude API key |
| `gpu_vm_private_ip` | GPU VM private IP (empty if disabled) |
| `orchestrator_url` | Durable Functions orchestrator URL |
| `data_factory_name` | Data Factory name |
| `waf_frontend_endpoint` | WAF endpoint (empty if disabled) |
| `log_analytics_workspace_id` | Log Analytics workspace ID |
| `managed_identity_client_id` | Managed Identity client ID |

---

## Appendix C — Networking and Ports

### VNet Architecture

```
Azure VNet: 10.10.0.0/16
├── functions-subnet:  10.10.1.0/24  (Azure Functions)
├── containers-subnet: 10.10.2.0/24  (Container Apps)
├── gpu-subnet:        10.10.3.0/24  (GPU VM — air-gapped)
├── sap-subnet:        10.10.4.0/24  (SAP connectivity)
└── endpoints-subnet:  10.10.5.0/24  (Private Endpoints)
```

### NSG Rules

| Rule | Direction | Port | Source | Destination | Purpose |
|------|-----------|------|--------|-------------|---------|
| SAP RFC | Outbound | 3300 | functions, containers | SAP CIDR | RFC calls to SAP ECC/S4 |
| SAP GUI | Outbound | 3200 | functions, containers | SAP CIDR | SAP GUI connections |
| SAP HTTPS | Outbound | 44300 | functions, containers | SAP CIDR | OData/ICF services |
| GPU Deny Internet | Outbound | All | gpu-subnet | Internet | Air-gap enforcement |
| HTTPS | Inbound | 443 | Internet | APIM | API access |

### Private Endpoints

All data services are accessed via Private Endpoints (no public internet):
- Cosmos DB → endpoints-subnet
- Blob Storage → endpoints-subnet
- Key Vault → endpoints-subnet

---

*Last updated: 2025*
