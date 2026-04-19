#!/bin/bash
###############################################################################
# Migrate4HANA — PyRFC Container Image Builder
#
# This script builds a Docker image containing:
# - PyRFC (Python SAP RFC library)
# - SAP NetWeaver RFC SDK (you must download this from SAP)
#
# The resulting image is pushed to Azure Container Registry (ACR) and used by
# Azure Container Apps (heavy compute stages) and Azure Functions (serverless).
#
# PREREQUISITES:
# 1. Docker installed
# 2. Azure CLI installed and logged in (az login)
# 3. SAP NetWeaver RFC SDK downloaded from SAP (requires S-user)
#    Download from: https://launchpad.support.sap.com/#/softwarecenter
#    Search for: SAP NW RFC SDK 7.50
#    Download: Linux x86_64 version
#
# WHY THIS IS NEEDED:
# PyRFC is a Python wrapper around SAP's C library (nwrfcsdk).
# It lets Python code call SAP function modules just like ABAP can.
# Think of it like a database driver — you need the native driver
# to connect to the database.
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_DIR}/pyrfc-build"
OUTPUT_DIR="${BUILD_DIR}/output"

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

NWRFC_SDK_FILE=$(ls -1 "${SCRIPT_DIR}"/nwrfc750P_*.zip 2>/dev/null | head -1)
if [ -z "$NWRFC_SDK_FILE" ]; then
    echo ""
    echo "ERROR: SAP NW RFC SDK not found!"
    echo ""
    echo "You need to download the SAP NW RFC SDK:"
    echo "  1. Go to https://launchpad.support.sap.com/#/softwarecenter"
    echo "  2. Search for 'SAP NW RFC SDK 7.50'"
    echo "  3. Download the Linux x86_64 version"
    echo "  4. Place the zip file in: ${SCRIPT_DIR}/"
    echo ""
    echo "Note: You need an SAP S-user (support user) to download this."
    echo "If you don't have one, your SAP Basis admin can provide it."
    echo ""
    echo "The file will be named something like: nwrfc750P_12-70002752.zip"
    exit 1
fi
echo "  ✓ SAP NW RFC SDK found: ${NWRFC_SDK_FILE}"

# ── Step 2: Set up build directory ──
echo ""
echo "Step 2: Setting up build directory..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}" "${OUTPUT_DIR}"

# Copy the SDK zip
cp "${NWRFC_SDK_FILE}" "${BUILD_DIR}/"

# ── Step 3: Build the PyRFC base image ──
echo ""
echo "Step 3: Building PyRFC base image in Docker (CBL-Mariner)..."

cat > "${BUILD_DIR}/Dockerfile" << 'DOCKERFILE'
FROM mcr.microsoft.com/cbl-mariner/base/python:3.11

RUN tdnf install -y gcc gcc-c++ make unzip ca-certificates && tdnf clean all

# Copy and extract SAP NW RFC SDK
COPY nwrfc750P_*.zip /tmp/
RUN cd /tmp && unzip -o nwrfc750P_*.zip -d /opt/sap/ && \
    mv /opt/sap/nwrfcsdk/* /opt/sap/ 2>/dev/null || true

# Set library path
ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Install PyRFC and Azure SDK dependencies
RUN pip install --no-cache-dir pyrfc

# Validate installation
RUN python3 -c "import pyrfc; print(f'pyrfc {pyrfc.__version__} OK')"

CMD ["python3", "-c", "import pyrfc; print('PyRFC ready')"]
DOCKERFILE

cd "${BUILD_DIR}"
if ! docker build -t migrate4hana-pyrfc-base .; then
    echo "ERROR: Docker build failed" >&2
    exit 1
fi

echo "  ✓ Base image built: migrate4hana-pyrfc-base"

# ── Step 4: Validate the image ──
echo ""
echo "Step 4: Validating the image..."

docker run --rm migrate4hana-pyrfc-base \
    python3 -c "import pyrfc; print(f'  ✓ pyrfc {pyrfc.__version__} imported successfully')"

if [ $? -eq 0 ]; then
    echo "  ✓ Image validation passed — pyrfc imports successfully"
else
    echo "  ✗ Image validation FAILED — pyrfc cannot import"
    echo "  Check that the SAP NW RFC SDK .so libraries are correctly installed"
    exit 1
fi

# ── Step 5: Push to Azure Container Registry ──
echo ""
echo "Step 5: Pushing to Azure Container Registry (ACR)..."

# Get ACR name from terraform or environment
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
    echo "    docker tag migrate4hana-pyrfc-base \$ACR_NAME/migrate4hana-pyrfc-base:latest"
    echo "    docker push \$ACR_NAME/migrate4hana-pyrfc-base:latest"
else
    az acr login --name "$ACR_NAME"
    docker tag migrate4hana-pyrfc-base "${ACR_NAME}/migrate4hana-pyrfc-base:latest"
    docker push "${ACR_NAME}/migrate4hana-pyrfc-base:latest"
    echo "  ✓ Image pushed to ${ACR_NAME}/migrate4hana-pyrfc-base:latest"
fi

echo ""
echo "============================================="
echo "  ✅ PyRFC base image ready!"
echo "============================================="
echo ""
echo "NEXT STEPS:"
echo "  1. The base image 'migrate4hana-pyrfc-base' is available locally"
echo "  2. Container Apps stages (discovery-engine, code-analyzer, data-loader)"
echo "     will use this as their base image via the ecs/Dockerfile"
echo "  3. Deploy infrastructure: cd terraform/environments/dev && terraform apply"
echo ""

# ── Cleanup ──
rm -rf "${BUILD_DIR}"
echo "Build files cleaned up. Done!"
