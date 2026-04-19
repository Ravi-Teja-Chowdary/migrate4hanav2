#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────
# Migrate4HANA — Azure Deployment Script
# ──────────────────────────────────────────────────────────────

ENVIRONMENT="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════════"
echo " Migrate4HANA — Deploying to Azure ($ENVIRONMENT)"
echo "═══════════════════════════════════════════════════════"

# 1. Verify Azure CLI login
echo "▶ Verifying Azure CLI authentication..."
az account show > /dev/null 2>&1 || { echo "ERROR: Not logged in. Run 'az login' first."; exit 1; }

# 2. Terraform — provision infrastructure
echo "▶ Provisioning Azure infrastructure via Terraform..."
cd "$PROJECT_ROOT/terraform/environments/$ENVIRONMENT"
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan

# Capture outputs
RG_NAME=$(terraform output -raw resource_group)
FUNC_APP_NAME=$(terraform output -raw function_app_url | sed 's|https://||' | sed 's|\.azurewebsites\.net.*||')
ACR_NAME=$(az acr list --resource-group "$RG_NAME" --query "[0].loginServer" -o tsv)

# 3. Build & push container images
echo "▶ Building container images..."
cd "$PROJECT_ROOT"
az acr login --name "$ACR_NAME"

for STAGE in discovery-engine code-analyzer data-loader data-loader-reconcile; do
    echo "  → Building $STAGE..."
    docker build -t "$ACR_NAME/$STAGE:latest" -f ecs/Dockerfile --build-arg STAGE_TARGET="$STAGE" .
    docker push "$ACR_NAME/$STAGE:latest"
done

# 4. Deploy Azure Functions
echo "▶ Deploying Azure Functions..."
cd "$PROJECT_ROOT"
func azure functionapp publish "$FUNC_APP_NAME" --python

# 5. Build & deploy frontend
echo "▶ Building frontend..."
cd "$PROJECT_ROOT/frontend"
npm ci
npm run build

# Deploy to Azure Static Web Apps or Blob Storage static site
STORAGE_ACCOUNT=$(cd "$PROJECT_ROOT/terraform/environments/$ENVIRONMENT" && terraform output -raw storage_account_name 2>/dev/null || echo "")
if [ -n "$STORAGE_ACCOUNT" ]; then
    echo "  → Deploying frontend to Azure Blob Storage static site..."
    az storage blob upload-batch -d '$web' -s dist --account-name "$STORAGE_ACCOUNT" --overwrite
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo " ✅ Deployment complete!"
echo "═══════════════════════════════════════════════════════"
