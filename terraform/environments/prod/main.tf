###############################################################################
# Migrate4HANA — Production Environment
# Hardened configuration: WAF, CloudTrail, Multi-AZ, VPN required
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "migrate4hana-tfstate"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "migrate4hana-tflock"
    encrypt        = true
  }
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

  telemetry_ws_endpoint          = module.websocket_telemetry.management_endpoint
  telemetry_ws_connections_table = module.websocket_telemetry.connections_table_name
  telemetry_broadcast_policy_arn = module.websocket_telemetry.telemetry_broadcast_policy_arn

  entity_resolution_workflow_arn = module.entity_resolution.matching_workflow_arn

  bedrock_model_id     = var.bedrock_model_id
  ast_change_threshold = var.ast_change_threshold

  # GenAI routing (cloud / local / dual) and Ollama endpoint wiring
  llm_mode     = var.llm_mode
  ollama_model = var.ollama_model
  ollama_url   = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""

  lambda_functions = {
    # NOTE: discovery-engine removed — now runs on ECS Fargate (Stage 1)

    maintenance-planner = {
      description = "Stage 2: SAP Maintenance Planner Validation"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/maintenance-planner"
      layers      = [var.pyrfc_layer_arn]
    }
    readiness-check = {
      description = "Stage 3: SAP Readiness Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/readiness-check"
      layers      = [var.pyrfc_layer_arn]
    }
    simplification-check = {
      description = "Stage 4: Simplification Item Check"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/simplification-check"
      layers      = [var.pyrfc_layer_arn]
    }
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
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/config-replicator"
      layers      = [var.pyrfc_layer_arn]
    }
    role-migrator = {
      description = "Phase 2: Role assessment for migration planning"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/role-migrator"
      layers      = [var.pyrfc_layer_arn]
    }
    integration-mapper = {
      description = "Phase 2: Integration mapping & rewiring assessment"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/integration-mapper"
      layers      = [var.pyrfc_layer_arn]
    }
    cutover-orchestrator = {
      description = "Stage 9: Pre-conversion cutover gate & checkpoint"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/cutover-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }
    sum-orchestrator = {
      description = "Stage 10: SUM/DMO Orchestration & Monitoring"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/sum-orchestrator"
      layers      = [var.pyrfc_layer_arn]
    }
    code-deployer = {
      description = "Stage 11: Deploy fixed ABAP to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/code-deployer"
      layers      = [var.pyrfc_layer_arn]
    }
    # NOTE: data-loader removed — now runs on ECS Fargate (Stage 12 & 12A)

    config-applier = {
      description = "Stage 13: Apply SPRO config to S/4HANA"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/config-applier"
      layers      = [var.pyrfc_layer_arn]
    }
    role-provisioner = {
      description = "Stage 14: Create roles & user assignments"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/role-provisioner"
      layers      = [var.pyrfc_layer_arn]
    }
    integration-activator = {
      description = "Stage 15: Activate RFC/IDoc integrations"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/integration-activator"
      layers      = [var.pyrfc_layer_arn]
    }
    migration-validator = {
      description = "Stage 16: Validate & generate GO-LIVE scorecard"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/migration-validator"
      layers      = [var.pyrfc_layer_arn]
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
      layers      = [var.pyrfc_layer_arn]
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
  }
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

  environment  = var.environment
  lambda_arns  = module.lambda.function_arns

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
}

# ─────────────────────────────────────────────
# Secrets Manager — DMS Database Credentials
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# DMS — Database Migration Service (production-grade)
# ─────────────────────────────────────────────
module "dms" {
  source             = "../../modules/dms"
  private_subnet_ids = module.vpc.private_subnet_ids
  availability_zone  = var.availability_zones[0]
  security_group_id  = module.vpc.default_security_group_id
  ecc_db_host        = var.ecc_db_host
  ecc_db_port        = var.ecc_db_port
  ecc_db_name        = var.ecc_db_name
  ecc_db_user        = var.ecc_db_user
  ecc_db_password    = jsondecode(data.aws_secretsmanager_secret_version.ecc_db_password.secret_string)["password"]
  s4_db_host         = var.s4_db_host
  s4_db_port         = var.s4_db_port
  s4_db_name         = var.s4_db_name
  s4_db_user         = var.s4_db_user
  s4_db_password     = jsondecode(data.aws_secretsmanager_secret_version.s4_db_password.secret_string)["password"]
}

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
