###############################################################################
# Migrate4HANA  Dev Environment
# This is the main Terraform config. You deploy this.
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment for remote state (recommended)
  # backend "s3" {
  #   bucket         = "migrate4hana-tfstate"
  #   key            = "dev/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "migrate4hana-tflock"
  #   encrypt        = true
  # }
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

# 
# VPC  Network foundation for SAP workloads
# 
module "vpc" {
  source = "../../modules/vpc"

  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs

  # VPN to on-prem SAP ECC
  enable_vpn_gateway = var.enable_vpn_gateway
  on_prem_cidr       = var.on_prem_cidr
}

# 
# S3  Staging bucket for migration data
# 
module "s3_staging" {
  source = "../../modules/s3-staging"

  environment = var.environment
  bucket_name = var.s3_staging_bucket
}

# 
# Lambda  Migration engine functions
# 
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
  evidence_bucket_name       = module.evidence_ledger.evidence_bucket_name
  kms_key_arn                = module.evidence_ledger.kms_key_arn

  # WebSocket telemetry env vars for real-time UI streaming
  telemetry_ws_endpoint          = module.websocket_telemetry.management_endpoint
  telemetry_ws_connections_table = module.websocket_telemetry.connections_table_name
  telemetry_broadcast_policy_arn = module.websocket_telemetry.telemetry_broadcast_policy_arn

  # Entity Resolution — ML-powered BP deduplication
  entity_resolution_workflow_arn = module.entity_resolution.matching_workflow_arn

  # GenAI configuration - Anthropic API (Bedrock not in use; see prod/main.tf)
  ast_change_threshold = var.ast_change_threshold

  # GenAI routing (cloud / local / dual) and Ollama endpoint wiring
  llm_mode     = var.llm_mode
  ollama_model = var.ollama_model
  ollama_url   = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""

  lambda_functions = {
    # NOTE: discovery-engine removed — now runs on ECS Fargate (Stage 1)

    # ── Phase 1: PREPARE — Stages 2-4 ──
    maintenance-planner = {
      description = "Stage 2: SAP Maintenance Planner Validation"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/maintenance-planner"
      layers      = [var.pyrfc_layer_arn]
    }
    readiness-check = {
      description = "Stage 3: SAP Readiness Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/readiness-check"
      layers      = [var.pyrfc_layer_arn]
    }
    simplification-check = {
      description = "Stage 4: Simplification Item Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/simplification-check"
      layers      = [var.pyrfc_layer_arn]
    }

    # ── Phase 2: EXPLORE — Stages 5-8 ──
    # NOTE: code-analyzer removed — now runs on ECS Fargate (Stage 5)

    data-migrator = {
      description = "Stage 7: Assess & plan data migration"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/data-migrator"
      layers      = [var.pyrfc_layer_arn]
    }
    config-replicator = {
      description = "Stage 8: Assess SPRO config, roles & integrations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/config-replicator"
      layers      = [var.pyrfc_layer_arn]
    }
    role-migrator = {
      description = "Phase 2: Role assessment for migration planning"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/role-migrator"
      layers      = [var.pyrfc_layer_arn]
    }
    integration-mapper = {
      description = "Phase 2: Integration mapping & rewiring assessment"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/integration-mapper"
      layers      = [var.pyrfc_layer_arn]
    }

    # ── Phase 3: REALIZE — Stages 9-10 (SUM/DMO Conversion) ──
    cutover-orchestrator = {
      description = "Stage 9: Pre-conversion cutover gate & checkpoint"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/cutover-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }
    sum-orchestrator = {
      description = "Stage 10: SUM/DMO Orchestration & Monitoring"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900 # SUM monitoring can take a while
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/sum-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }

    # ── Phase 4: POST-CONVERSION — Stages 11-14 ──
    code-deployer = {
      description = "Stage 11: Deploy fixed ABAP to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/code-deployer"
      layers      = [var.pyrfc_layer_arn]
    }
    # NOTE: data-loader removed — now runs on ECS Fargate (Stage 12 & 12A)

    config-applier = {
      description = "Stage 13: Apply SPRO config to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/config-applier"
      layers      = [var.pyrfc_layer_arn]
    }
    role-provisioner = {
      description = "Stage 14: Create roles & user assignments"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/role-provisioner"
      layers      = [var.pyrfc_layer_arn]
    }

    # ── Phase 5: DEPLOY & RUN — Stages 15-17 ──
    integration-activator = {
      description = "Stage 15: Activate RFC/IDoc integrations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/integration-activator"
      layers      = [var.pyrfc_layer_arn]
    }
    migration-validator = {
      description = "Stage 16: Validate & generate GO-LIVE scorecard"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/migration-validator"
      layers      = [var.pyrfc_layer_arn]
    }

    #  Advanced Automated & LLM Features
    code-analyzer = {
      description = "ABAP code remediation: AST engine + Claude (Anthropic API) fail-safe"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/code-analyzer"
      layers      = []
    }
    rollback-manager = {
      description = "Automated SAP Rollback (BAPI_ACC_DOCUMENT_REVERSE, BAPI_CTREQUEST_DELETE)"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/rollback-manager"
      layers      = [var.pyrfc_layer_arn]
    }
    data-hygiene = {
      description = "Master Data Cleansing and Business Partner Deduplication"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/data-hygiene"
      layers      = []
    }
    process-miner = {
      description = "ST03N Workload and Process Data Mining"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/process-miner"
      layers      = []
    }
    test-generator = {
      description = "Generates DITL UI Automation scripts from Process Mining"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/test-generator"
      layers      = []
    }

    # ===========================================================================
    # LIFT-AND-SHIFT MODE (greenfield S/4HANA on AWS) — 12 new orchestrators
    # ===========================================================================
    object-router = {
      description = "Lift-and-shift: routes objects to MC/LTMOM/IDoc/Transport lanes"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/object-router"
      layers      = []
    }
    sizing-advisor = {
      description = "Lift-and-shift: target sizing recommendations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/sizing-advisor"
      layers      = []
    }
    target-provisioner = {
      description = "Lift-and-shift: stand-up greenfield S/4HANA via SSM"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/target-provisioner"
      layers      = []
    }
    basis-validator = {
      description = "Lift-and-shift: hard-gate readiness check on target system"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/basis-validator"
      layers      = [var.pyrfc_layer_arn]
    }
    bc-set-builder = {
      description = "Lift-and-shift: emit BC Set XML for customizing transport"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/bc-set-builder"
      layers      = []
    }
    transport-artifact-builder = {
      description = "Lift-and-shift: stage CTS+ transport artifacts to S3"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/transport-artifact-builder"
      layers      = []
    }
    transport-file-placer = {
      description = "Lift-and-shift: place cofiles/data on /usr/sap/trans via SSM"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/transport-file-placer"
      layers      = []
    }
    transport-import-executor = {
      description = "Lift-and-shift: invoke tp import via SSM on target host"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/transport-import-executor"
      layers      = [var.pyrfc_layer_arn]
    }
    transport-import-verifier = {
      description = "Lift-and-shift: verify transport import return codes"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 512
      source_dir  = "${path.root}/../../../lambda/transport-import-verifier"
      layers      = [var.pyrfc_layer_arn]
    }
    migration-cockpit-orchestrator = {
      description = "Lift-and-shift: drive SAP Migration Cockpit via REST"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/migration-cockpit-orchestrator"
      layers      = []
    }
    ltmom-orchestrator = {
      description = "Lift-and-shift: emit LTMOM project + monitor jobs"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/ltmom-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }
    idoc-orchestrator = {
      description = "Lift-and-shift: post IDoc XML inbound and track WE02"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/idoc-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }
    delta-extractor = {
      description = "Lift-and-shift: cutover delta capture from locked ECC"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/delta-extractor"
      layers      = [var.pyrfc_layer_arn]
    }
    manual-gate = {
      description = "Lift-and-shift: persist Step Functions task tokens for human approval"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 60
      memory      = 256
      source_dir  = "${path.root}/../../../lambda/manual-gate"
      layers      = []
    }
    # Wave 7 — Hash-chained evidence ledger (no SAP deps → ARM64)
    evidence-collector = {
      description   = "Wave 7: append hash-chained run events to DDB + WORM S3"
      handler       = "handler.lambda_handler"
      runtime       = "python3.11"
      timeout       = 120
      memory        = 512
      source_dir    = "${path.root}/../../../lambda/evidence-collector"
      layers        = []
      architectures = ["arm64"]
    }
    # Wave 8 — Reconciliation engine (no SAP deps → ARM64)
    reconciliation-engine = {
      description   = "Wave 8: count/key/balance/hash recon with tolerance policy"
      handler       = "handler.lambda_handler"
      runtime       = "python3.11"
      timeout       = 600
      memory        = 1024
      source_dir    = "${path.root}/../../../lambda/reconciliation-engine"
      layers        = []
      architectures = ["arm64"]
    }
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
  llm_mode           = var.llm_mode
  ollama_model       = var.ollama_model
  ollama_url         = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""
}

# ─────────────────────────────────────────────
# Air-gapped LLM (Ollama + Gemma2 on GPU EC2)
# Disabled by default in dev; enable via -var='enable_airgapped_llm=true'
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

  # Pipeline stage order — 17 stages across 5 SAP Activate phases
  # Stages marked [ECS] run on Fargate, all others on Lambda
  pipeline_stages = [
    # Phase 1: PREPARE (Stages 1-4)
    "discovery-engine", # [ECS Fargate]
    "process-miner",
    "maintenance-planner",
    "readiness-check",
    "simplification-check",
    # Phase 2: EXPLORE (Stages 5-8)
    "code-analyzer", # [ECS Fargate]
    "data-hygiene",
    "data-migrator",
    "config-replicator",
    "role-migrator",
    "integration-mapper",
    # Phase 3: REALIZE (Stages 9-10)
    "cutover-orchestrator",
    "sum-orchestrator",
    # Phase 4: POST-CONVERSION (Stages 11-14)
    "code-deployer",
    "data-loader", # [ECS Fargate — 4x parallel + reconciliation]
    "config-applier",
    "role-provisioner",
    # Phase 5: DEPLOY & RUN (Stages 15-17)
    "integration-activator",
    "migration-validator",
    "test-generator",
  ]

  # Deploy the lift-and-shift state machine alongside the legacy in-place one.
  deploy_lift_and_shift = true
}

# 
# CloudWatch  Monitoring & Alerts
# 
module "cloudwatch" {
  source = "../../modules/cloudwatch"

  environment       = var.environment
  lambda_arns       = module.lambda.function_arns
  state_machine_arn = module.step_functions.state_machine_arn
  alert_email       = var.alert_email
}

# 
# Secrets Manager  SAP credentials
# 
resource "aws_secretsmanager_secret" "sap_credentials" {
  name        = "migrate4hana/${var.environment}/sap-credentials"
  description = "SAP ECC RFC connection credentials"

  tags = {
    Component = "Security"
  }
}

# You'll populate this manually after deployment:
# aws secretsmanager put-secret-value \
#   --secret-id migrate4hana/dev/sap-credentials \
#   --secret-string '{"host":"...","sysnr":"00","client":"100","user":"...","passwd":"..."}'

resource "aws_secretsmanager_secret" "s4hana_credentials" {
  name        = "migrate4hana/${var.environment}/s4hana-credentials"
  description = "S/4HANA target system RFC connection credentials"

  tags = {
    Component = "Security"
  }
}

# Populate after deployment:
# aws secretsmanager put-secret-value \
#   --secret-id migrate4hana/dev/s4hana-credentials \
#   --secret-string '{"host":"...","sysnr":"00","client":"100","user":"...","passwd":"..."}'

# 
# EC2  SAP HANA (optional, for target system)
# Only enable when ready for actual data load
# 
# module "ec2_hana" {
#   source = "../../modules/ec2-hana"
#
#   environment     = var.environment
#   instance_type   = "x2idn.16xlarge"   # SAP certified
#   vpc_id          = module.vpc.vpc_id
#   subnet_id       = module.vpc.private_subnet_ids[0]
#   hana_volume_size = 500
#   hana_volume_iops = 64000
# }

# 
# Outputs
# 
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

output "start_migration_command" {
  value       = <<-EOT
    To start a migration, run:

    aws stepfunctions start-execution \
      --state-machine-arn ${module.step_functions.state_machine_arn} \
      --input '{"mode":"discovery","ecc_client":"100"}'
  EOT
  description = "CLI command to kick off migration"
}

# ---------------------------------------------
# DynamoDB - Rules Routing & State 
# ---------------------------------------------
module "dynamodb_rules" {
  source      = "../../modules/dynamodb"
  environment = var.environment
}

# ---------------------------------------------
# InfoSec: Bedrock PrivateLink (VPC Endpoints)
# ---------------------------------------------
module "vpc_endpoints" {
  source                 = "../../modules/vpc-endpoints"
  vpc_id                 = module.vpc.vpc_id
  region                 = var.aws_region
  private_subnet_ids     = module.vpc.private_subnet_ids
  vpce_security_group_id = module.vpc.default_security_group_id
}


# ---------------------------------------------
# Secrets Manager — DMS Database Credentials
# Store passwords via CLI, NOT in Terraform/Git:
#   aws secretsmanager put-secret-value \
#     --secret-id migrate4hana/dev/ecc-db-password \
#     --secret-string '{"password":"<REAL_PASSWORD>"}'
# ---------------------------------------------
resource "aws_secretsmanager_secret" "ecc_db_password" {
  name        = "migrate4hana/${var.environment}/ecc-db-password"
  description = "ECC source database password for DMS replication"
  tags        = { Component = "DMS" }
}

resource "aws_secretsmanager_secret" "s4_db_password" {
  name        = "migrate4hana/${var.environment}/s4-db-password"
  description = "S/4HANA target database password for DMS replication"
  tags        = { Component = "DMS" }
}

data "aws_secretsmanager_secret_version" "ecc_db_password" {
  secret_id = aws_secretsmanager_secret.ecc_db_password.id
}

data "aws_secretsmanager_secret_version" "s4_db_password" {
  secret_id = aws_secretsmanager_secret.s4_db_password.id
}

# ---------------------------------------------
# AWS DMS (Database Migration Service)
# ---------------------------------------------
module "dms" {
  source             = "../../modules/dms"
  private_subnet_ids = module.vpc.private_subnet_ids
  availability_zone  = var.availability_zones[0]
  security_group_id  = module.vpc.default_security_group_id
  ecc_db_host        = "10.10.1.100"
  ecc_db_port        = 3200
  ecc_db_name        = "ECC"
  ecc_db_user        = "SAPSR3"
  ecc_db_password    = jsondecode(data.aws_secretsmanager_secret_version.ecc_db_password.secret_string)["password"]
  s4_db_host         = "10.10.2.200"
  s4_db_port         = 30015
  s4_db_name         = "S4H"
  s4_db_user         = "SAPHANADB"
  s4_db_password     = jsondecode(data.aws_secretsmanager_secret_version.s4_db_password.secret_string)["password"]
}

# ─────────────────────────────────────────────
# Entity Resolution — ML-powered BP Deduplication
# ─────────────────────────────────────────────
module "entity_resolution" {
  source      = "../../modules/entity-resolution"
  environment = var.environment
  region      = var.aws_region
}

# ─────────────────────────────────────────────
# WebSocket Telemetry — Real-time pipeline streaming
# ─────────────────────────────────────────────
module "websocket_telemetry" {
  source      = "../../modules/websocket-telemetry"
  environment = var.environment
  region      = var.aws_region
}


# =============================================================================
# Lift-and-Shift: target-system module (greenfield S/4HANA infrastructure)
# =============================================================================
module "target_system" {
  source = "../../modules/target-system"

  name_prefix        = "migrate4hana-${var.environment}"
  vpc_id             = module.vpc.vpc_id
  private_subnets    = module.vpc.private_subnet_ids
  build_sid          = "BLD"
  target_sid         = "S4H"
  staging_bucket_arn = module.s3_staging.bucket_arn
  tags = {
    Component = "TargetSystem"
    Pipeline  = "lift-and-shift"
  }
}

# =============================================================================
# Lift-and-Shift: DynamoDB table for manual-gate task tokens
# =============================================================================
resource "aws_dynamodb_table" "gates" {
  name         = "migrate4hana-gates-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "gate_id"

  attribute {
    name = "gate_id"
    type = "S"
  }

  tags = {
    Component = "ManualGate"
    Pipeline  = "lift-and-shift"
  }
}

output "lift_and_shift_state_machine_arn" {
  value       = module.step_functions.lift_and_shift_state_machine_arn
  description = "ARN of the lift-and-shift state machine"
}

output "target_system" {
  value = {
    sap_host_role_arn         = module.target_system.sap_host_iam_role_arn
    sap_host_instance_profile = module.target_system.sap_host_instance_profile
    hana_security_group_id    = module.target_system.hana_security_group_id
    app_security_group_id     = module.target_system.app_security_group_id
    trans_efs_id              = module.target_system.trans_efs_id
  }
  description = "Lift-and-shift target system outputs"
}

output "gates_table_name" {
  value       = aws_dynamodb_table.gates.name
  description = "DynamoDB table for manual-gate task tokens"
}
