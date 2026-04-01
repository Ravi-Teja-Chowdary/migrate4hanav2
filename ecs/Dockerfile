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

RUN dnf install -y python3.11 python3.11-pip python3.11-devel \
    gcc gcc-c++ make unzip && \
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

# Install Python dependencies
RUN python3.11 -m pip install --target /opt/python \
    pyrfc boto3

# ── Stage 2: Slim runtime image ─────────────
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y python3.11 && dnf clean all

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
COPY lambda/ /app/lambda/

# Copy the unified entrypoint
COPY ecs/entrypoint.py /app/entrypoint.py

# Non-root user for security
RUN useradd -r -s /bin/false appuser
USER appuser

ENTRYPOINT ["python3.11", "/app/entrypoint.py"]
