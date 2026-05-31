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
# BUILD + PUSH (one command, after `terraform apply` creates the ECR repo):
#   .\scripts\push-fargate-image.ps1
#
# The script handles pre-flight checks, ECR login, build (context = repo root),
# tag, push, verify, and warns about any running Fargate tasks that would not
# auto-pull the new image. See script header for parameters (-Tag, -Region,
# -RepoName, -SkipBuild).
#
# Manual build, if needed (e.g., to inspect layers):
#   docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
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
# faker is the synthetic-data generator for the battletest harness.
ARG PYRFC_VERSION=3.3.1
# pip is strict about PEP-427 wheel filenames, so we keep the original whl name.
RUN WHL="pyrfc-${PYRFC_VERSION}-cp311-cp311-linux_x86_64.whl" && \
    curl -fsSL "https://github.com/SAP/PyRFC/releases/download/v${PYRFC_VERSION}/${WHL}" -o "/tmp/${WHL}" && \
    python3.11 -m pip install --no-cache-dir --target /opt/python "/tmp/${WHL}" boto3 faker && \
    rm -f "/tmp/${WHL}" && \
    test -d /opt/python/pyrfc && \
    test -d /opt/python/faker && echo "pyrfc + faker installed OK"

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

# Copy the battletest harness so the Fargate task can run the standalone
# proof-run mode (entrypoint.py:run_battletest_mode). Only the .py files;
# the gitignored fixtures/abap-suite/results dirs are NOT in the image.
# (faker is already installed into /opt/python by the builder stage.)
COPY --chown=1000:1000 tests/battletest/*.py /app/battletest/

# Non-root user for security
RUN useradd -r -u 1000 -s /bin/false appuser
USER appuser

ENTRYPOINT ["python3.11", "/app/entrypoint.py"]
