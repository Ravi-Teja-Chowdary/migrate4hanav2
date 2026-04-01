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

  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs

  # VPN to on-prem SAP ECC
  enable_vpn_gateway  = var.enable_vpn_gateway
  on_prem_cidr        = var.on_prem_cidr
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

  environment       = var.environment
  s3_staging_bucket = module.s3_staging.bucket_name
  s3_staging_arn    = module.s3_staging.bucket_arn
  vpc_id            = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  secrets_arn       = aws_secretsmanager_secret.sap_credentials.arn

  # WebSocket telemetry env vars for real-time UI streaming
  telemetry_ws_endpoint          = module.websocket_telemetry.management_endpoint
  telemetry_ws_connections_table = module.websocket_telemetry.connections_table_name
  telemetry_broadcast_policy_arn = module.websocket_telemetry.telemetry_broadcast_policy_arn

  # Entity Resolution — ML-powered BP deduplication
  entity_resolution_workflow_arn = module.entity_resolution.matching_workflow_arn

  # GenAI configuration — Bedrock + Air-Gapped LLM
  bedrock_model_id     = var.bedrock_model_id
  local_llm_endpoint   = var.local_llm_endpoint
  ast_change_threshold = var.ast_change_threshold

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
      timeout     = 900     # SUM monitoring can take a while
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
    airgapped-llm-router = {
      description = "Securely routes extracted AST syntax to Air-gapped Local LLM"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/code-analyzer" # Sharing code analyzer directory
      layers      = []
    }
    bedrock-llm-router = {
      description = "Routes standard AST syntax to Amazon Bedrock (Anthropic/Titan)"
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
  }
}

# ─────────────────────────────────────────────
# ECS — Fargate compute for heavy migration stages
# ─────────────────────────────────────────────
module "ecs" {
  source = "../../modules/ecs"

  environment       = var.environment
  aws_region        = var.aws_region
  vpc_id            = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  secrets_arn       = aws_secretsmanager_secret.sap_credentials.arn
  s3_staging_bucket = module.s3_staging.bucket_name
  s3_staging_arn    = module.s3_staging.bucket_arn
  bedrock_model_id  = var.bedrock_model_id
}

# ─────────────────────────────────────────────
# Step Functions — Pipeline orchestrator
# ─────────────────────────────────────────────
module "step_functions" {
  source = "../../modules/step-functions"

  environment  = var.environment
  lambda_arns  = module.lambda.function_arns

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
    "discovery-engine",       # [ECS Fargate]
    "process-miner",
    "maintenance-planner",
    "readiness-check",
    "simplification-check",
    # Phase 2: EXPLORE (Stages 5-8)
    "code-analyzer",          # [ECS Fargate]
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
    "data-loader",            # [ECS Fargate — 4x parallel + reconciliation]
    "config-applier",
    "role-provisioner",
    # Phase 5: DEPLOY & RUN (Stages 15-17)
    "integration-activator",
    "migration-validator",
    "test-generator",
  ]
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
  value = <<-EOT
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
  source = "../../modules/dynamodb"
  environment = var.environment
}

# ---------------------------------------------
# InfoSec: Bedrock PrivateLink (VPC Endpoints)
# ---------------------------------------------
module "vpc_endpoints" {
  source = "../../modules/vpc-endpoints"
  vpc_id = module.vpc.vpc_id
  region = var.aws_region
  private_subnet_ids = module.vpc.private_subnet_ids
  vpce_security_group_id = module.vpc.default_security_group_id
}

# ---------------------------------------------
# InfoSec: Air-Gapped Local LLM (Optional Feature)
# ---------------------------------------------
module "airgapped_llm" {
  source = "../../modules/airgapped-llm"
  vpc_id = module.vpc.vpc_id
  vpc_cidr = var.vpc_cidr
  lambda_private_subnets_cidr = var.private_subnet_cidrs
  isolated_subnet_id = module.vpc.private_subnet_ids[0]
  gpu_ami_id = var.gpu_ami_id
  model_s3_path   = var.llm_model_s3_path
  model_s3_bucket = var.llm_model_s3_bucket
}

# ---------------------------------------------
# AWS DMS (Database Migration Service)
# ---------------------------------------------
module "dms" {
  source = "../../modules/dms"
  private_subnet_ids = module.vpc.private_subnet_ids
  availability_zone  = var.availability_zones[0]
  security_group_id  = module.vpc.default_security_group_id
  ecc_db_host        = "10.10.1.100"
  ecc_db_port        = 3200
  ecc_db_name        = "ECC"
  ecc_db_user        = "SAPSR3"
  ecc_db_password    = "mock_password"
  s4_db_host         = "10.10.2.200"
  s4_db_port         = 30015
  s4_db_name         = "S4H"
  s4_db_user         = "SAPHANADB"
  s4_db_password     = "mock_password"
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
