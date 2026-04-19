###############################################################################
# Migrate4HANA — Azure Container Apps Worker Image
#
# Packages the Python handlers with the SAP NW RFC SDK so that
# Stages 1, 5, 12 and 12A can run without time limits.
#
# The Linux x86_64 SAP NW RFC SDK shared libraries are bundled in the
# repository under nwrfcsdk-linux/lib/.  No separate download is needed.
#
# BUILD (from project root — build context must be the repo root):
#   docker build -f containers/Dockerfile -t migrate4hana-worker:latest .
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
    gcc gcc-c++ make ca-certificates && \
    tdnf clean all

# Copy the bundled Linux x86_64 SAP NW RFC SDK shared libraries
COPY nwrfcsdk-linux/lib/ /opt/sap/lib/

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

# Copy ALL functions directories (handlers + utils + shared modules)
COPY --chown=1000:1000 functions/ /app/functions/

# Copy the unified entrypoint
COPY --chown=1000:1000 containers/entrypoint.py /app/entrypoint.py

# Non-root user for security
RUN useradd -r -u 1000 -s /bin/false appuser
USER appuser

ENTRYPOINT ["python3", "/app/entrypoint.py"]
