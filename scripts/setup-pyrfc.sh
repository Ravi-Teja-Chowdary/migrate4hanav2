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

NWRFC_SDK_FILE=$(ls -1 "${SCRIPT_DIR}"/nwrfc750P_*.zip 2>/dev/null | head -1)
BUNDLED_SDK_DIR="${PROJECT_DIR}/nwrfcsdk-linux"
USE_BUNDLED_SDK=0
if [ -z "$NWRFC_SDK_FILE" ]; then
    if [ -f "${BUNDLED_SDK_DIR}/lib/libsapnwrfc.so" ]; then
        echo "  ✓ Using bundled SAP NW RFC SDK at ${BUNDLED_SDK_DIR}"
        USE_BUNDLED_SDK=1
    else
        echo ""
        echo "ERROR: SAP NW RFC SDK not found!"
        echo ""
        echo "You need to either:"
        echo "  (a) Place the bundled Linux SDK under ${BUNDLED_SDK_DIR}/"
        echo "      (must contain lib/libsapnwrfc.so), or"
        echo "  (b) Download the SAP NW RFC SDK zip from SAP:"
        echo "      1. Go to https://launchpad.support.sap.com/#/softwarecenter"
        echo "      2. Search for 'SAP NW RFC SDK 7.50'"
        echo "      3. Download the Linux x86_64 version"
        echo "      4. Place the zip file in: ${SCRIPT_DIR}/"
        echo ""
        echo "Note: You need an SAP S-user (support user) to download this."
        echo "If you don't have one, your SAP Basis admin can provide it."
        echo ""
        echo "The file will be named something like: nwrfc750P_12-70002752.zip"
        exit 1
    fi
else
    echo "  ✓ SAP NW RFC SDK found: ${NWRFC_SDK_FILE}"
fi

# ── Step 2: Set up build directory ──
echo ""
echo "Step 2: Setting up build directory..."
rm -rf "${BUILD_DIR}" "${OUTPUT_DIR}"
mkdir -p "${BUILD_DIR}/python" "${BUILD_DIR}/lib" "${OUTPUT_DIR}"

# Copy the SDK source — either the official zip or the bundled directory
if [ "${USE_BUNDLED_SDK}" -eq 1 ]; then
    cp -r "${BUNDLED_SDK_DIR}" "${BUILD_DIR}/nwrfcsdk-bundled"
else
    cp "${NWRFC_SDK_FILE}" "${BUILD_DIR}/"
fi

# ── Step 3: Build the layer using Docker ──
echo ""
echo "Step 3: Building Lambda layer in Docker (Amazon Linux 2)..."

cat > "${BUILD_DIR}/Dockerfile" << DOCKERFILE
FROM public.ecr.aws/lambda/python:3.11

# Install build dependencies
RUN yum install -y gcc gcc-c++ make unzip

# Copy SAP NW RFC SDK — either from the official zip or the pre-extracted
# directory bundled with the repo.
$(if [ "${USE_BUNDLED_SDK}" -eq 1 ]; then
    echo "COPY nwrfcsdk-bundled/ /opt/sap/"
else
    echo "COPY nwrfc750P_*.zip /tmp/"
    echo "RUN cd /tmp && unzip -o nwrfc750P_*.zip -d /opt/sap/ && \\"
    echo "    mv /opt/sap/nwrfcsdk/* /opt/sap/ 2>/dev/null || true"
fi)

# Set library path
ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:\$LD_LIBRARY_PATH

# Install PyRFC
RUN pip install pyrfc --target /opt/python/

# Copy SDK libraries to layer
RUN mkdir -p /opt/lib && \\
    cp /opt/sap/lib/*.so* /opt/lib/ 2>/dev/null || true

# Package the layer
RUN cd /opt && zip -r /tmp/pyrfc-layer.zip python/ lib/

CMD ["echo", "Layer built successfully"]
DOCKERFILE

cd "${BUILD_DIR}"
if ! docker build -t migrate4hana-pyrfc-builder .; then
    echo "ERROR: Docker build failed" >&2
    exit 1
fi
if ! docker run --rm -v "${OUTPUT_DIR}:/output" migrate4hana-pyrfc-builder \
    sh -c "cp /tmp/pyrfc-layer.zip /output/"; then
    echo "ERROR: Docker run failed" >&2
    exit 1
fi

if [ ! -f "${OUTPUT_DIR}/pyrfc-layer.zip" ]; then
    echo "ERROR: Layer zip not created" >&2
    exit 1
fi

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
echo "  Layer ARN: ${LAYER_ARN}"

# ── Step 5: Validate the layer ──
echo ""
echo "Step 5: Validating the layer..."

# Check layer size (Lambda limit = 250 MB unzipped)
LAYER_SIZE=$(stat -f%z "${OUTPUT_DIR}/pyrfc-layer.zip" 2>/dev/null || stat -c%s "${OUTPUT_DIR}/pyrfc-layer.zip")
LAYER_SIZE_MB=$((LAYER_SIZE / 1024 / 1024))
echo "  Layer size: ${LAYER_SIZE_MB} MB"

if [ ${LAYER_SIZE_MB} -gt 200 ]; then
    echo "  ⚠ WARNING: Layer is ${LAYER_SIZE_MB} MB — close to Lambda's 250 MB limit"
    echo "  Consider stripping debug symbols: strip lib/*.so"
fi

# Functional test: verify pyrfc can import inside a Lambda-like container
echo "  Running import validation in Lambda container..."
docker run --rm \
    -v "${OUTPUT_DIR}/pyrfc-layer.zip:/tmp/layer.zip" \
    public.ecr.aws/lambda/python:3.11 \
    sh -c "cd /opt && unzip -q /tmp/layer.zip && \
           export LD_LIBRARY_PATH=/opt/lib:\$LD_LIBRARY_PATH && \
           python3 -c 'import pyrfc; print(f\"  ✓ pyrfc {pyrfc.__version__} imported successfully\")' 2>&1"

if [ $? -eq 0 ]; then
    echo "  ✓ Layer validation passed — pyrfc imports successfully"
else
    echo "  ✗ Layer validation FAILED — pyrfc cannot import"
    echo "  Check that the SAP NW RFC SDK .so libraries are included in lib/"
    exit 1
fi

# ── Step 6: Update Terraform variables ──
echo ""
echo "Step 6: Updating Terraform configuration..."

TFVARS="${PROJECT_DIR}/terraform/environments/dev/terraform.tfvars"
if [ -f "${TFVARS}" ]; then
    # Update or add pyrfc_layer_arn
    if grep -q "pyrfc_layer_arn" "${TFVARS}"; then
        sed -i "s|pyrfc_layer_arn.*=.*|pyrfc_layer_arn = \"${LAYER_ARN}\"|" "${TFVARS}"
        echo "  ✓ Updated pyrfc_layer_arn in terraform.tfvars"
    else
        echo "pyrfc_layer_arn = \"${LAYER_ARN}\"" >> "${TFVARS}"
        echo "  ✓ Added pyrfc_layer_arn to terraform.tfvars"
    fi
else
    mkdir -p "$(dirname ${TFVARS})"
    echo "pyrfc_layer_arn = \"${LAYER_ARN}\"" > "${TFVARS}"
    echo "  ✓ Created terraform.tfvars with pyrfc_layer_arn"
fi
echo "============================================="
echo "  Layer ARN: ${LAYER_ARN}"
echo "============================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Verify the layer ARN above is correct"
echo "  2. terraform.tfvars has been auto-updated with pyrfc_layer_arn"
echo "  3. Run: cd terraform/environments/dev && terraform plan && terraform apply"
echo ""

# ── Cleanup ──
rm -rf "${BUILD_DIR}"
echo "Build files cleaned up. Done!"
