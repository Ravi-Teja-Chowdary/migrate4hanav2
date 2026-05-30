###############################################################################
# Migrate4HANA — Fargate Worker Image
#
# Packages the Python handlers with the SAP NW RFC SDK so that
# Stages 1, 5, 12 and 12A can run without Lambda's 15-min limit.
#
# BUILD PREREQUISITES:
#   Place the SAP NW RFC SDK zip in the ecs/ directory before building:
#     ecs/nwrfc750P_*.zip        (Linux x86_64, from SAP Support Portal)
#
# BUILD (from project root — build context must be the repo root):
#   docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
#
# PUSH (after ECR login):
#   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
#   REGION=us-east-1
#   aws ecr get-login-password --region $REGION | \
#       docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
#   docker tag  migrate4hana-worker:latest $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/migrate4hana/worker:latest
#   docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/migrate4hana/worker:latest
###############################################################################

# ── Stage 1: Build PyRFC + SAP NW RFC SDK ────
FROM public.ecr.aws/amazonlinux/amazonlinux:2023 AS builder

RUN dnf install -y python3.11 python3.11-pip unzip tar gzip && \
    dnf clean all

# Copy and extract SAP NW RFC SDK (from ecs/ directory in build context)
COPY ecs/nwrfc750P_*.zip /tmp/
RUN cd /tmp && unzip -o nwrfc750P_*.zip -d /opt/sap/ && \
    # The SDK extracts into nwrfcsdk/ — flatten if needed
    if [ -d /opt/sap/nwrfcsdk ]; then \
        cp -r /opt/sap/nwrfcsdk/* /opt/sap/ ; \
    fi

ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Install Python dependencies. pyrfc is fetched from SAP's GitHub release (the
# PyPI release has no Linux wheel — only macOS-arm64 + Windows); the wheel is
# precompiled cp311 linux_x86_64, no compilation needed.
ARG PYRFC_VERSION=3.3.1
# pip is strict about PEP-427 wheel filenames, so we keep the original whl name.
RUN WHL="pyrfc-${PYRFC_VERSION}-cp311-cp311-linux_x86_64.whl" && \
    curl -fsSL "https://github.com/SAP/PyRFC/releases/download/v${PYRFC_VERSION}/${WHL}" -o "/tmp/${WHL}" && \
    python3.11 -m pip install --no-cache-dir --target /opt/python "/tmp/${WHL}" boto3 && \
    rm -f "/tmp/${WHL}" && \
    test -d /opt/python/pyrfc && echo "pyrfc installed OK"

# ── Stage 2: Slim runtime image ─────────────
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y python3.11 shadow-utils && dnf clean all

# SAP NW RFC SDK shared libraries
COPY --from=builder /opt/sap/lib /opt/sap/lib
ENV SAPNWRFC_HOME=/opt/sap
ENV LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH

# Python packages (pyrfc, boto3)
COPY --from=builder /opt/python /opt/python
ENV PYTHONPATH=/opt/python:$PYTHONPATH

# ── Application code ─────────────────────────
WORKDIR /app

# Copy ALL lambda directories (handlers + utils + shared modules)
# Build context is project root, so lambda/ is directly accessible
COPY --chown=1000:1000 lambda/ /app/lambda/

# Copy the unified entrypoint
COPY --chown=1000:1000 ecs/entrypoint.py /app/entrypoint.py

# Non-root user for security
RUN useradd -r -u 1000 -s /bin/false appuser
USER appuser

ENTRYPOINT ["python3.11", "/app/entrypoint.py"]
