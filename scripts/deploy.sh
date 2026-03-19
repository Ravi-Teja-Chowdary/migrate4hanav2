#!/bin/bash
###############################################################################
# Migrate4HANA — Deployment Script
# Packages Lambda functions and deploys via Terraform
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="${PROJECT_DIR}/lambda"
TF_DIR="${PROJECT_DIR}/terraform/environments/dev"

echo "============================================="
echo "  Migrate4HANA — Deploy"
echo "============================================="

# Step 1: Package Lambda functions
echo ""
echo "Step 1: Packaging Lambda functions..."

FUNCTIONS=("discovery-engine" "process-miner" "code-analyzer" "data-hygiene" "data-migrator" "config-replicator" "role-migrator" "integration-mapper" "cutover-orchestrator" "code-deployer" "data-loader" "config-applier" "role-provisioner" "integration-activator" "migration-validator" "test-generator" "rollback-manager")

for func in "${FUNCTIONS[@]}"; do
    echo "  Packaging ${func}..."
    cd "${LAMBDA_DIR}/${func}"

    # Install dependencies if requirements.txt exists
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt -t . --quiet
    fi

    echo "  ✓ ${func} ready"
done

# Step 2: Build Frontend
echo ""
echo "Step 2: Building Frontend React Web App..."
cd "${PROJECT_DIR}/frontend"
npm ci
npm run build 

# Step 3: Terraform
echo ""
echo "Step 3: Running Terraform..."
cd "${TF_DIR}"

terraform init -input=false
terraform plan -out=tfplan
echo ""
read -p "Apply this plan? (yes/no): " CONFIRM
if [ "$CONFIRM" = "yes" ]; then
    terraform apply tfplan
    echo ""
    echo "============================================="
    echo "  Deployment Complete!"
    echo "============================================="
    terraform output
else
    echo "Deployment cancelled."
fi
