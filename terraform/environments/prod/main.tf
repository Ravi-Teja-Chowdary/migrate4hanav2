###############################################################################
# Migrate4HANA — Production Environment
# Hardened configuration: WAF, CloudTrail, Multi-AZ, VPN required
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # >= 5.40 gives us aws_entityresolution_* (added in 5.21) plus the latest
      # bug fixes, while staying inside the 5.x major. Bump up as needed.
      version = ">= 5.40, < 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.4"
    }
  }

  # Local state by design: `terraform init && terraform apply` with no pre-existing
  # backend bucket. For team/remote state, add an S3 backend block + bootstrap it
  # (see DEPLOY.md §"Remote state, optional").
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "Migrate4HANA"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ─────────────────────────────────────────────
# VPC — Network foundation for SAP workloads
# ─────────────────────────────────────────────
module "vpc" {
  source = "../../modules/vpc"

  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
  enable_vpn_gateway   = var.enable_vpn_gateway
  on_prem_cidr         = var.on_prem_cidr
}

# ─────────────────────────────────────────────
# S3 — Staging bucket for migration data
# ─────────────────────────────────────────────
module "s3_staging" {
  source = "../../modules/s3-staging"

  environment = var.environment
  bucket_name = var.s3_staging_bucket
}

# ─────────────────────────────────────────────
# pyrfc Lambda layer — auto-built from the in-repo SAP NW RFC SDK
# Build the zip once via `python layer-build/build_pyrfc_layer.py` (uses
# nwrfcsdk-linux/lib/* + the manylinux pyrfc wheel from PyPI). Terraform
# detects the file and publishes it; if absent, no layer is attached.
# ─────────────────────────────────────────────
locals {
  pyrfc_layer_zip    = "${path.module}/../../../layer-build/pyrfc-layer.zip"
  pyrfc_layer_exists = fileexists(local.pyrfc_layer_zip)
  pyrfc_layer_arn = (local.pyrfc_layer_exists
    ? aws_lambda_layer_version.pyrfc[0].arn
    : var.pyrfc_layer_arn)
}

resource "aws_lambda_layer_version" "pyrfc" {
  count                    = local.pyrfc_layer_exists ? 1 : 0
  layer_name               = "migrate4hana-pyrfc-${var.environment}"
  description              = "SAP NW RFC SDK 7.50 + pyrfc (auto-published from in-repo nwrfcsdk-linux/)"
  filename                 = local.pyrfc_layer_zip
  source_code_hash         = local.pyrfc_layer_exists ? filebase64sha256(local.pyrfc_layer_zip) : null
  compatible_runtimes      = ["python3.11"]
  compatible_architectures = ["x86_64"]
}

# ─────────────────────────────────────────────
# Lambda — Migration engine functions (prod memory)
# ─────────────────────────────────────────────
module "lambda" {
  source = "../../modules/lambda"

  environment        = var.environment
  s3_staging_bucket  = module.s3_staging.bucket_name
  s3_staging_arn     = module.s3_staging.bucket_arn
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  secrets_arn        = aws_secretsmanager_secret.sap_credentials.arn
  gates_table_name   = aws_dynamodb_table.gates.name

  # Wave 6/7/8 — evidence ledger plumbing
  events_table_name          = module.evidence_ledger.events_table_name
  recon_tolerance_table_name = module.evidence_ledger.recon_tolerance_table_name
  # Tool-facing evidence bucket (no Object Lock; explicit fixed name per
  # 2026-05-30 directive). Both Wave-7 S3_EVIDENCE_BUCKET and our pillar-4
  # M4H_EVIDENCE_BUCKET resolve to this same bucket.
  evidence_bucket_name = aws_s3_bucket.evidence_app.id
  kms_key_arn          = module.evidence_ledger.kms_key_arn

  telemetry_ws_endpoint          = module.websocket_telemetry.management_endpoint
  telemetry_ws_connections_table = module.websocket_telemetry.connections_table_name
  telemetry_broadcast_policy_arn = module.websocket_telemetry.telemetry_broadcast_policy_arn

  # Entity Resolution module excluded: aws_entityresolution_* resources are NOT
  # in the hashicorp/aws provider (verified against v5.100.0). The service is
  # only available via the hashicorp/awscc provider (Cloud Control / CloudFormation
  # backed). Deterministic BP dedup runs alongside this regardless.
  entity_resolution_workflow_arn = ""

  bedrock_model_id     = var.bedrock_model_id
  ast_change_threshold = var.ast_change_threshold

  # ── PROD-hardening pillars wired into every function (no-op when empty) ──
  transform_rules    = var.transform_rules
  mapping_s3         = "s3://${aws_s3_bucket.mapping.id}/mappings/matrix.json"
  gate_sns_topic     = aws_sns_topic.spine_gates.arn
  gate_secret_arn    = aws_secretsmanager_secret.gate_secret.arn
  audit_ledger_table = aws_dynamodb_table.audit_ledger.name
  key_map_table      = aws_dynamodb_table.key_map.name
  evidence_bucket    = aws_s3_bucket.evidence_app.id   # exposed to code as M4H_EVIDENCE_BUCKET
  fargate_cluster    = module.ecs.cluster_arn
  fargate_taskdef    = module.ecs.task_definition_arn
  fargate_sgs        = module.ecs.security_group_id

  # GenAI routing (cloud / local / dual) and Ollama endpoint wiring
  llm_mode     = var.llm_mode
  ollama_model = var.ollama_model
  ollama_url   = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""

  lambda_functions = {
    # NOTE: discovery-engine removed — now runs on ECS Fargate (Stage 1)

    # NOTE: maintenance-planner not in repo — Stage 2 is handled in-pipeline via
    # the SAP Maintenance Planner web UI (manual gate) rather than a Lambda.
    readiness-check = {
      description = "Stage 3: SAP Readiness Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/readiness-check"
      layers      = [local.pyrfc_layer_arn]
    }
    simplification-check = {
      description = "Stage 4: Simplification Item Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/simplification-check"
      layers      = [local.pyrfc_layer_arn]
    }
    # NOTE: code-analyzer removed — now runs on ECS Fargate (Stage 5)

    data-migrator = {
      description = "Stage 7: Assess & plan data migration"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/data-migrator"
      layers      = [local.pyrfc_layer_arn]
    }
    config-replicator = {
      description = "Stage 8: Assess SPRO config, roles & integrations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/config-replicator"
      layers      = [local.pyrfc_layer_arn]
    }
    role-migrator = {
      description = "Phase 2: Role assessment for migration planning"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/role-migrator"
      layers      = [local.pyrfc_layer_arn]
    }
    integration-mapper = {
      description = "Phase 2: Integration mapping & rewiring assessment"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/integration-mapper"
      layers      = [local.pyrfc_layer_arn]
    }
    cutover-orchestrator = {
      description = "Stage 9: Pre-conversion cutover gate & checkpoint"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/cutover-orchestrator"
      layers      = [local.pyrfc_layer_arn]
    }
    # NOTE: sum-orchestrator not in repo — SUM/DMO is SAP-proprietary and runs
    # outside our pipeline (handed off to SAP Basis); the cutover-orchestrator
    # handles the pre-conversion gate and resume-after-SUM checkpoints.
    code-deployer = {
      description = "Stage 11: Deploy fixed ABAP to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/code-deployer"
      layers      = [local.pyrfc_layer_arn]
    }
    # NOTE: data-loader removed — now runs on ECS Fargate (Stage 12 & 12A)

    config-applier = {
      description = "Stage 13: Apply SPRO config to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/config-applier"
      layers      = [local.pyrfc_layer_arn]
    }
    role-provisioner = {
      description = "Stage 14: Create roles & user assignments"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/role-provisioner"
      layers      = [local.pyrfc_layer_arn]
    }
    integration-activator = {
      description = "Stage 15: Activate RFC/IDoc integrations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/integration-activator"
      layers      = [local.pyrfc_layer_arn]
    }
    migration-validator = {
      description = "Stage 16: Validate & generate GO-LIVE scorecard"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/migration-validator"
      layers      = [local.pyrfc_layer_arn]
    }
    bedrock-llm-router = {
      description = "Routes standard AST syntax to Amazon Bedrock (Anthropic/Titan)"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/code-analyzer"
      layers      = []
    }
    rollback-manager = {
      description = "Automated SAP Rollback (BAPI_ACC_DOCUMENT_REVERSE, BAPI_CTREQUEST_DELETE)"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/rollback-manager"
      layers      = [local.pyrfc_layer_arn]
    }
    data-hygiene = {
      description = "Master Data Cleansing and Business Partner Deduplication"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/data-hygiene"
      layers      = []
    }
    process-miner = {
      description = "ST03N Workload and Process Data Mining"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/process-miner"
      layers      = []
    }
    test-generator = {
      description = "Generates DITL UI Automation scripts from Process Mining"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/test-generator"
      layers      = []
    }

    # Lift-and-shift orchestrators
    object-router                  = { description = "LS: object lane router", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 300, memory = 1024, source_dir = "${path.root}/../../../lambda/object-router", layers = [] }
    sizing-advisor                 = { description = "LS: target sizing advisor", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 300, memory = 512, source_dir = "${path.root}/../../../lambda/sizing-advisor", layers = [] }
    target-provisioner             = { description = "LS: greenfield S/4 stand-up", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/target-provisioner", layers = [] }
    basis-validator                = { description = "LS: target readiness gate", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 300, memory = 512, source_dir = "${path.root}/../../../lambda/basis-validator", layers = [local.pyrfc_layer_arn] }
    bc-set-builder                 = { description = "LS: BC Set builder", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 300, memory = 512, source_dir = "${path.root}/../../../lambda/bc-set-builder", layers = [] }
    transport-artifact-builder     = { description = "LS: stage CTS+ artifacts", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 600, memory = 1024, source_dir = "${path.root}/../../../lambda/transport-artifact-builder", layers = [] }
    transport-file-placer          = { description = "LS: place tp files via SSM", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 600, memory = 512, source_dir = "${path.root}/../../../lambda/transport-file-placer", layers = [] }
    transport-import-executor      = { description = "LS: invoke tp import via SSM", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/transport-import-executor", layers = [local.pyrfc_layer_arn] }
    transport-import-verifier      = { description = "LS: verify transport return", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 300, memory = 512, source_dir = "${path.root}/../../../lambda/transport-import-verifier", layers = [local.pyrfc_layer_arn] }
    migration-cockpit-orchestrator = { description = "LS: drive Migration Cockpit", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/migration-cockpit-orchestrator", layers = [] }
    ltmom-orchestrator             = { description = "LS: LTMOM project + monitor", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/ltmom-orchestrator", layers = [local.pyrfc_layer_arn] }
    idoc-orchestrator              = { description = "LS: IDoc XML inbound + WE02", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/idoc-orchestrator", layers = [local.pyrfc_layer_arn] }
    delta-extractor                = { description = "LS: cutover delta capture", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 900, memory = 1024, source_dir = "${path.root}/../../../lambda/delta-extractor", layers = [local.pyrfc_layer_arn] }
    manual-gate                    = { description = "LS: persist SFN task tokens", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 60, memory = 256, source_dir = "${path.root}/../../../lambda/manual-gate", layers = [] }
    evidence-collector             = { description = "Wave 7: hash-chained event ledger", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 120, memory = 1024, source_dir = "${path.root}/../../../lambda/evidence-collector", layers = [], architectures = ["arm64"] }
    reconciliation-engine          = { description = "Wave 8: count/key/balance/hash recon", handler = "handler.lambda_handler", runtime = "python3.11", timeout = 600, memory = 2048, source_dir = "${path.root}/../../../lambda/reconciliation-engine", layers = [], architectures = ["arm64"] }
  }
}

# Wave 6/7/8 — Evidence ledger (KMS CMK + Object Lock S3 + DDB)
module "evidence_ledger" {
  source          = "../../modules/evidence-ledger"
  environment     = var.environment
  retention_years = 7
}

# ─────────────────────────────────────────────
# ECS — Fargate compute for heavy migration stages
# ─────────────────────────────────────────────
module "ecs" {
  source = "../../modules/ecs"

  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  secrets_arn        = aws_secretsmanager_secret.sap_credentials.arn
  s3_staging_bucket  = module.s3_staging.bucket_name
  s3_staging_arn     = module.s3_staging.bucket_arn
  bedrock_model_id   = var.bedrock_model_id
  llm_mode           = var.llm_mode
  ollama_model       = var.ollama_model
  ollama_url         = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""
}

# ─────────────────────────────────────────────
# Air-gapped LLM (Ollama + Gemma2 on GPU EC2)
# Enabled by default in prod — set enable_airgapped_llm=false to skip.
# ─────────────────────────────────────────────
module "airgapped_llm" {
  source = "../../modules/airgapped-llm"
  count  = var.enable_airgapped_llm ? 1 : 0

  environment                = var.environment
  vpc_id                     = module.vpc.vpc_id
  vpc_cidr                   = var.vpc_cidr
  private_subnet_id          = module.vpc.private_subnet_ids[0]
  consumer_security_group_id = module.lambda.security_group_id
  gpu_ami_id                 = var.gpu_ami_id
  ollama_model               = var.ollama_model
}

# ─────────────────────────────────────────────
# Step Functions — Pipeline orchestrator
# ─────────────────────────────────────────────
module "step_functions" {
  source = "../../modules/step-functions"

  environment = var.environment
  lambda_arns = module.lambda.function_arns

  # ECS Fargate — heavy-compute stages (1, 5, 12, 12A)
  ecs_cluster_arn         = module.ecs.cluster_arn
  ecs_task_definition_arn = module.ecs.task_definition_arn
  ecs_security_group_id   = module.ecs.security_group_id
  private_subnet_ids      = module.vpc.private_subnet_ids
  ecs_task_role_arn       = module.ecs.task_role_arn
  ecs_execution_role_arn  = module.ecs.execution_role_arn

  pipeline_stages = [
    "discovery-engine", "process-miner", "maintenance-planner",
    "readiness-check", "simplification-check",
    "code-analyzer", "data-hygiene", "data-migrator",
    "config-replicator", "role-migrator", "integration-mapper",
    "cutover-orchestrator", "sum-orchestrator",
    "code-deployer", "data-loader", "config-applier", "role-provisioner",
    "integration-activator", "migration-validator", "test-generator",
  ]

  deploy_lift_and_shift = true
}

# ─────────────────────────────────────────────
# DMS REMOVED (2026-05-29): AWS DMS does not support a "saphana" engine, and
# raw DB-level replication of the SAP database would violate the support-clean,
# application-layer-only posture (released BAPIs / OData / Migration Cockpit).
# All data movement flows through the API/MC lanes — not DMS.
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# CloudWatch — Monitoring & Alerts
# ─────────────────────────────────────────────
module "cloudwatch" {
  source = "../../modules/cloudwatch"

  environment       = var.environment
  lambda_arns       = module.lambda.function_arns
  state_machine_arn = module.step_functions.state_machine_arn
  alert_email       = var.alert_email
}

# ─────────────────────────────────────────────
# Secrets Manager — SAP credentials (with rotation)
# ─────────────────────────────────────────────
resource "aws_secretsmanager_secret" "sap_credentials" {
  name        = "migrate4hana/${var.environment}/sap-credentials"
  description = "SAP ECC RFC connection credentials"
  tags        = { Component = "Security" }
}

resource "aws_secretsmanager_secret" "s4hana_credentials" {
  name        = "migrate4hana/${var.environment}/s4hana-credentials"
  description = "S/4HANA target system RFC connection credentials"
  tags        = { Component = "Security" }
}

# ─────────────────────────────────────────────
# DynamoDB — Rules Routing & State
# ─────────────────────────────────────────────
module "dynamodb_rules" {
  source      = "../../modules/dynamodb"
  environment = var.environment
}

# ─────────────────────────────────────────────
# VPC Endpoints — Bedrock PrivateLink
# ─────────────────────────────────────────────
module "vpc_endpoints" {
  source                 = "../../modules/vpc-endpoints"
  vpc_id                 = module.vpc.vpc_id
  region                 = var.aws_region
  private_subnet_ids     = module.vpc.private_subnet_ids
  vpce_security_group_id = module.vpc.default_security_group_id
}


# ─────────────────────────────────────────────
# Entity Resolution — ML-powered BP dedup (NOT IN hashicorp/aws PROVIDER)
# Verified against aws v5.100.0: aws_entityresolution_* resources are not
# shipped. To re-enable, switch the entity-resolution module to use the
# hashicorp/awscc provider (Cloud Control), or manage the workflow via CLI.
# Deterministic BP dedup runs in the data-hygiene stage regardless.
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# WebSocket Telemetry — Real-time pipeline streaming
# ─────────────────────────────────────────────
module "websocket_telemetry" {
  source      = "../../modules/websocket-telemetry"
  environment = var.environment
  region      = var.aws_region
}

# ─────────────────────────────────────────────
# WAF — Web Application Firewall (mandatory for prod)
# ─────────────────────────────────────────────
module "waf" {
  source      = "../../modules/waf"
  environment = var.environment
  rate_limit  = var.waf_rate_limit
}

# ─────────────────────────────────────────────
# Audit Trail — CloudTrail for SOX/GxP compliance
# ─────────────────────────────────────────────
module "audit" {
  source      = "../../modules/audit"
  environment = var.environment
  region      = var.aws_region
}

# ─────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────
output "state_machine_arn" {
  value       = module.step_functions.state_machine_arn
  description = "ARN of the migration pipeline state machine"
}

output "s3_staging_bucket" {
  value       = module.s3_staging.bucket_name
  description = "S3 bucket for migration staging data"
}

output "lambda_functions" {
  value       = module.lambda.function_arns
  description = "Map of Lambda function ARNs"
}

output "ecs_cluster_arn" {
  value       = module.ecs.cluster_arn
  description = "ECS cluster for Fargate migration tasks"
}

output "ecr_repository_url" {
  value       = module.ecs.ecr_repository_url
  description = "ECR repo — push the Fargate worker image here"
}

output "waf_web_acl_arn" {
  value       = module.waf.web_acl_arn
  description = "WAF WebACL ARN for ALB attachment"
}

output "audit_trail_arn" {
  value       = module.audit.cloudtrail_arn
  description = "CloudTrail ARN for audit logging"
}

output "start_migration_command" {
  value = <<-EOT
    aws stepfunctions start-execution \
      --state-machine-arn ${module.step_functions.state_machine_arn} \
      --input '{"mode":"discovery","ecc_client":"100"}'
  EOT
}



# Lift-and-Shift: target-system + gates table
module "target_system" {
  source             = "../../modules/target-system"
  name_prefix        = "migrate4hana-${var.environment}"
  vpc_id             = module.vpc.vpc_id
  private_subnets    = module.vpc.private_subnet_ids
  subnet_count       = length(var.availability_zones) # statically known (default 3)
  staging_bucket_arn = module.s3_staging.bucket_arn
  tags               = { Component = "TargetSystem", Pipeline = "lift-and-shift" }
}

resource "aws_dynamodb_table" "gates" {
  name         = "migrate4hana-gates-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "gate_id"
  attribute {
    name = "gate_id"
    type = "S"
  }
  tags = { Component = "ManualGate", Pipeline = "lift-and-shift" }
}

# ═════════════════════════════════════════════════════════════════════════════
# PROD-hardening resources (Pillars 2/3/4) — folded into the single root so the
# whole platform is one `terraform apply`. See AUDIT_REPORT/EXPERT_REVIEW_BRIEF.
# ═════════════════════════════════════════════════════════════════════════════

# Pillar 4 — DynamoDB audit hash-chain vault (HashChainLedger)
resource "aws_dynamodb_table" "audit_ledger" {
  name         = "migrate4hana-audit-ledger-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "seq"
  attribute {
    name = "run_id"
    type = "S"
  }
  attribute {
    name = "seq"
    type = "N"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags = { Component = "CryptoAudit", Pillar = "4" }
}

# Pillar 4 / ledger — cross-run key-map DynamoDB table
resource "aws_dynamodb_table" "key_map" {
  name         = "migrate4hana-key-map-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "object"
  range_key    = "source_key"
  attribute {
    name = "object"
    type = "S"
  }
  attribute {
    name = "source_key"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags = { Component = "KeyMapLedger", Pillar = "4" }
}

# Pillar 3 — governance gate HMAC secret
resource "random_password" "gate_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "gate_secret" {
  name        = "migrate4hana/${var.environment}/gate-secret"
  description = "HMAC secret for spine approval gates (M4H_GATE_SECRET)"
  tags        = { Component = "Governance", Pillar = "3" }
}

resource "aws_secretsmanager_secret_version" "gate_secret" {
  secret_id     = aws_secretsmanager_secret.gate_secret.id
  secret_string = random_password.gate_secret.result
}

# Pillar 3 — governance gate SNS topic + email subscription
resource "aws_sns_topic" "spine_gates" {
  name              = "migrate4hana-spine-gates-${var.environment}"
  kms_master_key_id = "alias/aws/sns"
  tags              = { Component = "Governance", Pillar = "3" }
}

resource "aws_sns_topic_subscription" "spine_gates_email" {
  topic_arn = aws_sns_topic.spine_gates.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Tool-facing evidence bucket — explicit, fixed name per 2026-05-30 directive.
# No Object Lock, versioning + encryption + public-access block on. This is the
# bucket the application writes evidence packs to (M4H_EVIDENCE_BUCKET +
# S3_EVIDENCE_BUCKET both point here). The evidence-ledger module's bucket
# remains for KMS-encrypted artifacts but is no longer the tool's target.
resource "aws_s3_bucket" "evidence_app" {
  bucket        = "migrate4hana-evidence-bucket"
  force_destroy = true # allow `terraform destroy` to empty non-WORM objects
  tags = {
    Component   = "EvidenceBucket"
    Environment = var.environment
    Purpose     = "tool-facing evidence pack target"
  }
}

resource "aws_s3_bucket_versioning" "evidence_app" {
  bucket = aws_s3_bucket.evidence_app.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence_app" {
  bucket = aws_s3_bucket.evidence_app.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence_app" {
  bucket                  = aws_s3_bucket.evidence_app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Pillar 2 — value-map matrix bucket (business users upload the mapping JSON)
resource "aws_s3_bucket" "mapping" {
  bucket = "migrate4hana-mapping-${var.environment}-${data.aws_caller_identity.current.account_id}"
  tags   = { Component = "Transformation", Pillar = "2" }
}

resource "aws_s3_bucket_versioning" "mapping" {
  bucket = aws_s3_bucket.mapping.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "mapping" {
  bucket                  = aws_s3_bucket.mapping.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}

output "audit_ledger_table" {
  value = aws_dynamodb_table.audit_ledger.name
}

output "gate_sns_topic_arn" {
  value = aws_sns_topic.spine_gates.arn
}

output "gate_secret_arn" {
  value = aws_secretsmanager_secret.gate_secret.arn
}

output "mapping_bucket" {
  value = aws_s3_bucket.mapping.id
}

output "lift_and_shift_state_machine_arn" {
  value = module.step_functions.lift_and_shift_state_machine_arn
}

output "gates_table_name" {
  value = aws_dynamodb_table.gates.name
}
