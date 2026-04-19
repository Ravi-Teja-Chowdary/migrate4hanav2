###############################################################################
# Migrate4HANA — Azure Container Apps Worker Image
#
# Packages the Python handlers with the SAP NW RFC SDK so that
# Stages 1, 5, 12 and 12A can run without time limits.
#
# BUILD PREREQUISITES:
#   Place the SAP NW RFC SDK zip in the ecs/ directory before building:
#     ecs/nwrfc750P_*.zip        (Linux x86_64, from SAP Support Portal)
#
# BUILD (from project root — build context must be the repo root):
#   docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
#
# PUSH (after ACR login):
#   ACR_NAME=<your-acr>.azurecr.io
#   az acr login --name "$ACR_NAME"
#   docker tag  migrate4hana-worker:latest $ACR_NAME/migrate4hana/worker:latest
#   docker push $ACR_NAME/migrate4hana/worker:latest
###############################################################################

# ── Stage 1: Build PyRFC + SAP NW RFC SDK ────
FROM mcr.microsoft.com/cbl-mariner/base/core:2.0 AS builder

RUN tdnf install -y python3 python3-pip python3-devel \
    gcc gcc-c++ make unzip ca-certificates && \
    tdnf clean all

# Copy and extract SAP NW RFC SDK (from ecs/ directory in build context)
# NOTE: You must provide the SAP NW RFC SDK zip (nwrfc750P_*.zip) in the ecs/
# directory before building. Download from SAP Support Portal (SAP Note 2573790).
# The SDK is required for live RFC connections to SAP ECC/S4HANA.
COPY ecs/nwrfc750P_*.zip /tmp/
RUN cd /tmp && unzip -o nwrfc750P_*.zip -d /opt/sap/ && \
    if [ -d /opt/sap/nwrfcsdk ]; then \
        cp -r /opt/sap/nwrfcsdk/* /opt/sap/ ; \
    fi

ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Install Python dependencies (requests replaces boto3)
RUN python3 -m pip install --target /opt/python \
    pyrfc requests

# ── Stage 2: Slim runtime image ─────────────
FROM mcr.microsoft.com/cbl-mariner/base/core:2.0

RUN tdnf install -y python3 ca-certificates && tdnf clean all

# SAP NW RFC SDK shared libraries
COPY --from=builder /opt/sap/lib /opt/sap/lib
ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Python packages (pyrfc, requests)
COPY --from=builder /opt/python /opt/python
ENV PYTHONPATH=/opt/python:$PYTHONPATH

# ── Application code ─────────────────────────
WORKDIR /app

# Copy ALL lambda directories (handlers + utils + shared modules)
COPY --chown=1000:1000 lambda/ /app/lambda/

# Copy the unified entrypoint
COPY --chown=1000:1000 ecs/entrypoint.py /app/entrypoint.py

# Non-root user for security
RUN useradd -r -u 1000 -s /bin/false appuser
USER appuser

ENTRYPOINT ["python3", "/app/entrypoint.py"]
