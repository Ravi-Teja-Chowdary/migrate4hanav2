#!/bin/bash
###############################################################################
# Migrate4HANA — PyRFC Container Image Builder
#
# This script builds a Docker image containing:
# - PyRFC (Python SAP RFC library)
# - SAP NetWeaver RFC SDK (bundled in nwrfcsdk-linux/lib/)
#
# The resulting image is pushed to Azure Container Registry (ACR) and used by
# Azure Container Apps (heavy compute stages) and Azure Functions (serverless).
#
# PREREQUISITES:
# 1. Docker installed
# 2. Azure CLI installed and logged in (az login)
#
# The SAP NW RFC SDK Linux shared libraries are already bundled in the
# repository under nwrfcsdk-linux/lib/. No separate download is needed.
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================="
echo "  Migrate4HANA — PyRFC Image Builder"
echo "============================================="

# ── Step 1: Check prerequisites ──
echo ""
echo "Step 1: Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "  ✓ Docker found"

if ! command -v az &> /dev/null; then
    echo "ERROR: Azure CLI is not installed."
    echo "Install Azure CLI: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi
echo "  ✓ Azure CLI found"

# Verify Azure login
az account show > /dev/null 2>&1 || { echo "ERROR: Not logged in. Run 'az login' first."; exit 1; }
echo "  ✓ Azure CLI authenticated"

# Verify bundled Linux SDK
LINUX_SDK_DIR="${PROJECT_DIR}/nwrfcsdk-linux/lib"
if [ ! -d "$LINUX_SDK_DIR" ] || [ -z "$(ls -A "$LINUX_SDK_DIR" 2>/dev/null)" ]; then
    echo ""
    echo "ERROR: SAP NW RFC SDK Linux libraries not found at: ${LINUX_SDK_DIR}"
    echo "The nwrfcsdk-linux/lib/ directory should contain .so files."
    exit 1
fi
echo "  ✓ SAP NW RFC SDK found: ${LINUX_SDK_DIR}"
ls -1 "$LINUX_SDK_DIR" | sed 's/^/    /'

# ── Step 2: Build the container image ──
echo ""
echo "Step 2: Building container image (from project root)..."

cd "$PROJECT_DIR"
if ! docker build -f containers/Dockerfile -t migrate4hana-worker:latest .; then
    echo "ERROR: Docker build failed" >&2
    exit 1
fi
echo "  ✓ Image built: migrate4hana-worker:latest"

# ── Step 3: Validate the image ──
echo ""
echo "Step 3: Validating the image..."

docker run --rm migrate4hana-worker:latest \
    python3 -c "import pyrfc; print(f'  ✓ pyrfc {pyrfc.__version__} imported successfully')" 2>/dev/null || true

# ── Step 4: Push to Azure Container Registry ──
echo ""
echo "Step 4: Pushing to Azure Container Registry (ACR)..."

ACR_NAME="${ACR_NAME:-}"
if [ -z "$ACR_NAME" ]; then
    TFVARS="${PROJECT_DIR}/terraform/environments/dev/terraform.tfvars"
    if [ -f "$TFVARS" ]; then
        ACR_NAME=$(grep -oP 'acr_name\s*=\s*"\K[^"]+' "$TFVARS" 2>/dev/null || echo "")
    fi
fi

if [ -z "$ACR_NAME" ]; then
    echo "  ⚠ ACR_NAME not set — skipping push to Azure Container Registry."
    echo "  Set ACR_NAME environment variable or configure acr_name in terraform.tfvars"
    echo ""
    echo "  To push manually later:"
    echo "    export ACR_NAME=youracr.azurecr.io"
    echo "    az acr login --name \$ACR_NAME"
    echo "    docker tag migrate4hana-worker:latest \$ACR_NAME/migrate4hana/worker:latest"
    echo "    docker push \$ACR_NAME/migrate4hana/worker:latest"
else
    az acr login --name "$ACR_NAME"
    docker tag migrate4hana-worker:latest "${ACR_NAME}/migrate4hana/worker:latest"
    docker push "${ACR_NAME}/migrate4hana/worker:latest"
    echo "  ✓ Image pushed to ${ACR_NAME}/migrate4hana/worker:latest"
fi

echo ""
echo "============================================="
echo "  ✅ Container image ready!"
echo "============================================="
echo ""
echo "NEXT STEPS:"
echo "  1. The image 'migrate4hana-worker:latest' is available locally"
echo "  2. Container Apps stages (discovery-engine, code-analyzer, data-loader)"
echo "     will use this image via Azure Container Apps"
echo "  3. Deploy infrastructure: cd terraform/environments/dev && terraform apply"
echo ""
