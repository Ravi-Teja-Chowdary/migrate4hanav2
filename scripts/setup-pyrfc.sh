#!/bin/bash
###############################################################################
# Migrate4HANA — PyRFC Lambda Layer Builder
#
# This script builds a Lambda layer containing:
# - PyRFC (Python SAP RFC library)
# - SAP NetWeaver RFC SDK (you must download this from SAP)
#
# PREREQUISITES:
# 1. Docker installed (for building the layer in Amazon Linux 2)
# 2. SAP NetWeaver RFC SDK downloaded from SAP (requires S-user)
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
LAYER_DIR="${PROJECT_DIR}/lambda-layers/pyrfc"
BUILD_DIR="${LAYER_DIR}/build"
OUTPUT_DIR="${LAYER_DIR}/output"

echo "============================================="
echo "  Migrate4HANA — PyRFC Layer Builder"
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

NWRFC_SDK_PATH="${SCRIPT_DIR}/nwrfc750P_*.zip"
if ! ls ${NWRFC_SDK_PATH} 1> /dev/null 2>&1; then
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
echo "  ✓ SAP NW RFC SDK found"

# ── Step 2: Set up build directory ──
echo ""
echo "Step 2: Setting up build directory..."
rm -rf "${BUILD_DIR}" "${OUTPUT_DIR}"
mkdir -p "${BUILD_DIR}/python" "${BUILD_DIR}/lib" "${OUTPUT_DIR}"

# Copy the SDK zip
cp ${NWRFC_SDK_PATH} "${BUILD_DIR}/"

# ── Step 3: Build the layer using Docker ──
echo ""
echo "Step 3: Building Lambda layer in Docker (Amazon Linux 2)..."

cat > "${BUILD_DIR}/Dockerfile" << 'DOCKERFILE'
FROM public.ecr.aws/lambda/python:3.11

# Install build dependencies
RUN yum install -y gcc gcc-c++ make unzip

# Copy and extract SAP NW RFC SDK
COPY nwrfc750P_*.zip /tmp/
RUN cd /tmp && unzip -o nwrfc750P_*.zip -d /opt/sap/ && \
    mv /opt/sap/nwrfcsdk/* /opt/sap/ 2>/dev/null || true

# Set library path
ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Install PyRFC
RUN pip install pyrfc --target /opt/python/

# Copy SDK libraries to layer
RUN mkdir -p /opt/lib && \
    cp /opt/sap/lib/*.so* /opt/lib/ 2>/dev/null || true

# Package the layer
RUN cd /opt && zip -r /tmp/pyrfc-layer.zip python/ lib/

CMD ["echo", "Layer built successfully"]
DOCKERFILE

cd "${BUILD_DIR}"
docker build -t migrate4hana-pyrfc-builder .
docker run --rm -v "${OUTPUT_DIR}:/output" migrate4hana-pyrfc-builder \
    sh -c "cp /tmp/pyrfc-layer.zip /output/"

echo "  ✓ Layer built: ${OUTPUT_DIR}/pyrfc-layer.zip"

# ── Step 4: Publish to AWS ──
echo ""
echo "Step 4: Publishing Lambda layer to AWS..."

LAYER_ARN=$(aws lambda publish-layer-version \
    --layer-name "migrate4hana-pyrfc" \
    --description "PyRFC + SAP NW RFC SDK for SAP connectivity" \
    --zip-file "fileb://${OUTPUT_DIR}/pyrfc-layer.zip" \
    --compatible-runtimes python3.11 \
    --query 'LayerVersionArn' \
    --output text)

echo "  ✓ Layer published!"
echo ""
echo "============================================="
echo "  Layer ARN: ${LAYER_ARN}"
echo "============================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Copy the Layer ARN above"
echo "  2. Paste it into terraform.tfvars as pyrfc_layer_arn"
echo "  3. Run: terraform plan && terraform apply"
echo ""
echo "  pyrfc_layer_arn = \"${LAYER_ARN}\""
echo ""

# ── Cleanup ──
rm -rf "${BUILD_DIR}"
echo "Build files cleaned up. Done!"
