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

  ast_change_threshold = var.ast_change_threshold

  # Direct Anthropic API path (replaces Bedrock when the AWS account does not
  # have model access). The code-analyzer Lambda fetches the key at runtime
  # from this Secrets Manager secret via M4H_ANTHROPIC_SECRET_ARN.
  anthropic_secret_arn       = aws_secretsmanager_secret.anthropic_api_key.arn
  anthropic_model_id         = var.anthropic_model_id
  anthropic_escalation_model = var.anthropic_escalation_model

  # ── PROD-hardening pillars wired into every function (no-op when empty) ──
  transform_rules    = var.transform_rules
  mapping_s3         = "s3://${aws_s3_bucket.mapping.id}/mappings/matrix.json"
  gate_sns_topic     = aws_sns_topic.spine_gates.arn
  gate_secret_arn    = aws_secretsmanager_secret.gate_secret.arn
  audit_ledger_table = aws_dynamodb_table.audit_ledger.name
  key_map_table      = aws_dynamodb_table.key_map.name
  evidence_bucket    = aws_s3_bucket.evidence_app.id # exposed to code as M4H_EVIDENCE_BUCKET
  fargate_cluster    = module.ecs.cluster_arn
  fargate_taskdef    = module.ecs.task_definition_arn
  fargate_sgs        = module.ecs.security_group_id

  # GenAI routing (cloud / local / dual) and Ollama endpoint wiring
  llm_mode     = var.llm_mode
  ollama_model = var.ollama_model
  ollama_url   = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""

  lambda_functions = {
    # Stage 1 — discovery-engine. Previously routed to Fargate (heavier scans),
    # but the lift-and-shift pipeline expects a Lambda binding so the SFN can
    # call it directly. Re-added 2026-06-10 after a prod run showed the SFN
    # was falling back to manual-gate-prod for Stage 1.
    discovery-engine = {
      description = "Stage 1: Discover custom ABAP, tables, FMs, org units, RFC dests"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 3008
      source_dir  = "${path.root}/../../../lambda/discovery-engine"
      layers      = [local.pyrfc_layer_arn]
    }
    # Stage 21 — migration-completeness-analyzer. Added 2026-06-10 (same
    # reason as discovery-engine: SFN was binding to fallback).
    migration-completeness-analyzer = {
      description = "Stage 21: Completeness scoring + go-live recommendation"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 300
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/migration-completeness-analyzer"
      layers      = []
    }
    # Stage 27 — pdf-report-generator. Bundles reportlab; emits the
    # client-deliverable PDF + the aggregated report_input.json to S3
    # under runs/<run_id>/report/. Source lives at repo root so the lambda
    # zip is built from a small wrapper dir under .deploy-tmp/ at apply time;
    # see DEPLOY-NOTES.md for the layout.
    pdf-report-generator = {
      description = "Stage 27: Aggregate per-stage artifacts and render client-deliverable PDF"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 600
      memory      = 2048
      source_dir  = "${path.root}/../../../lambda/pdf-report-generator"
      layers      = []
    }

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
    code-analyzer = {
      description = "ABAP code remediation: AST engine + Claude (Anthropic API) fail-safe"
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
    code-delta-scheduler = {
      description = "Daily TADIR snapshot + delta detection (dual-maintenance code sync)"
      handler     = "handler.lambda_handler"
      runtime     = "python3.11"
      timeout     = 900
      memory      = 1024
      source_dir  = "${path.root}/../../../lambda/code-delta-scheduler"
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
  llm_mode           = var.llm_mode
  ollama_model       = var.ollama_model
  ollama_url         = var.enable_airgapped_llm ? "http://${module.airgapped_llm[0].private_ip}:11434" : ""
  # Direct Anthropic API path for heavy-compute stages on Fargate
  anthropic_secret_arn       = aws_secretsmanager_secret.anthropic_api_key.arn
  anthropic_model_id         = var.anthropic_model_id
  anthropic_escalation_model = var.anthropic_escalation_model
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
  region            = var.aws_region
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
  # Purge immediately on destroy so the same name can be re-created without the
  # 7-30 day "scheduled for deletion" lockout. Real prod runs should raise this.
  recovery_window_in_days = 0
  tags                    = { Component = "Security" }
}

resource "aws_secretsmanager_secret" "s4hana_credentials" {
  name                    = "migrate4hana/${var.environment}/s4hana-credentials"
  description             = "S/4HANA target system RFC connection credentials"
  recovery_window_in_days = 0
  tags                    = { Component = "Security" }
}

# ─────────────────────────────────────────────
# Route 53 private hosted zone — so Lambdas in the VPC can resolve SAP CAL
# hostnames (`vhcals4hci.dummy.nodomain`, `vhcalerphci.dummy.nodomain`, etc.)
# which would otherwise only exist in the user's local hosts file. A-record
# values are the CAL appliances' CURRENT public IPs; update when CAL drifts.
# Zone is created if EITHER s4_public_ip OR cal_ecc_public_ip is non-empty.
# ─────────────────────────────────────────────
resource "aws_route53_zone" "s4_cal" {
  count = (var.s4_public_ip != "" || var.cal_ecc_public_ip != "") ? 1 : 0
  name  = "dummy.nodomain"
  vpc {
    vpc_id = module.vpc.vpc_id
  }
  comment = "Private zone for SAP CAL hostname resolution from Lambda (S/4 + ECC)"
  tags    = { Component = "ConnectivityDNS" }
}

resource "aws_route53_record" "s4_vhcals4hci" {
  count   = var.s4_public_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.s4_cal[0].zone_id
  name    = "vhcals4hci.dummy.nodomain"
  type    = "A"
  ttl     = 60
  records = [var.s4_public_ip]
}

resource "aws_route53_record" "s4_vhcals4hcs" {
  count   = var.s4_public_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.s4_cal[0].zone_id
  name    = "vhcals4hcs.dummy.nodomain"
  type    = "A"
  ttl     = 60
  records = [var.s4_public_ip]
}

# CAL ECC IDES — kernel back-verify uses the internal hostname (var.cal_ecc_hostname);
# we publish A records for both the "ci" (central instance) and "cs" (central service)
# aliases since the kernel may use either depending on operation.
resource "aws_route53_record" "cal_ecc_ci" {
  count   = var.cal_ecc_public_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.s4_cal[0].zone_id
  name    = "${var.cal_ecc_hostname}.dummy.nodomain"
  type    = "A"
  ttl     = 60
  records = [var.cal_ecc_public_ip]
}

resource "aws_route53_record" "cal_ecc_cs" {
  count   = var.cal_ecc_public_ip != "" ? 1 : 0
  zone_id = aws_route53_zone.s4_cal[0].zone_id
  name    = "${replace(var.cal_ecc_hostname, "ci", "cs")}.dummy.nodomain"
  type    = "A"
  ttl     = 60
  records = [var.cal_ecc_public_ip]
}

# Anthropic API key - used by code-analyzer Lambda for Claude remediation in
# accounts without Bedrock access. The secret resource is always created; the
# value is only set when var.anthropic_api_key is non-empty (so an empty value
# does not break the apply for users who haven't supplied a key yet).
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "migrate4hana/${var.environment}/anthropic-api-key"
  description             = "Anthropic API key for Claude (Sonnet 4.6 / Opus 4.7) code remediation"
  recovery_window_in_days = 0
  tags                    = { Component = "Security", Purpose = "ClaudeAPI" }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  count         = var.anthropic_api_key != "" ? 1 : 0
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = jsonencode({ api_key = var.anthropic_api_key })
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
# Bastion — reverse-SSH tunnel target so Lambdas in the private subnets can
# reach the user's laptop ECC at 192.168.100.129. Only created when the
# operator names an existing AWS key pair via bastion_key_pair_name
# (count=0 otherwise).
# ─────────────────────────────────────────────
module "bastion" {
  count  = var.bastion_key_pair_name != "" ? 1 : 0
  source = "../../modules/bastion"

  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  public_subnet_id   = module.vpc.public_subnet_ids[0]
  private_subnet_ids = module.vpc.private_subnet_ids
  key_pair_name      = var.bastion_key_pair_name
  # By default allow SSH from anywhere; tighten via -var=ssh_allowed_cidrs='["YOUR_IP/32"]'
  ssh_allowed_cidrs = var.ssh_allowed_cidrs
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

  # F6 governance toggles. Defaults preserve current prod posture:
  #   object_lock_enabled = true   -> WORM retention (SOX-defensible)
  #   audit_retention_days = 2555  -> 7 years (SOX requirement)
  #   kms_key_arn = ""             -> AWS-managed s3 key (set to CMK ARN later)
  # Overridable in terraform.tfvars per environment.
  object_lock_enabled  = var.object_lock_enabled
  audit_retention_days = var.audit_retention_days
  kms_key_arn          = var.audit_kms_key_arn
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



# ─────────────────────────────────────────────
# Customer-facing UI hosting (added 2026-06-11)
# api-server (Fargate behind ALB) + ui-hosting (S3 behind CloudFront).
# Customers reach a single CloudFront URL; CF routes /api/* to the ALB
# and the rest to the S3-hosted React build.
# Deploy with: scripts/deploy-ui-aws.ps1
# ─────────────────────────────────────────────
module "api_server" {
  source = "../../modules/api-server"

  environment          = var.environment
  vpc_id               = module.vpc.vpc_id
  private_subnet_ids   = module.vpc.private_subnet_ids
  public_subnet_ids    = module.vpc.public_subnet_ids
  ecs_cluster_arn      = module.ecs.cluster_arn
  staging_bucket       = module.s3_staging.bucket_name
  key_map_table        = aws_dynamodb_table.key_map.name
  anthropic_secret_arn = aws_secretsmanager_secret.anthropic_api_key.arn
}

module "ui_hosting" {
  source = "../../modules/ui-hosting"

  environment            = var.environment
  alb_dns_name           = module.api_server.alb_dns_name
  custom_domain          = var.ui_custom_domain
  acm_cert_arn_us_east_1 = var.ui_acm_cert_arn_us_east_1
}

output "ui_url" {
  description = "Customer-facing UI URL. Open this in a browser."
  value       = module.ui_hosting.ui_url
}

output "ui_bucket_name" {
  description = "S3 bucket the deploy script syncs frontend/dist/ to."
  value       = module.ui_hosting.bucket_name
}

output "ui_cloudfront_distribution_id" {
  description = "CloudFront distribution id (for invalidations)."
  value       = module.ui_hosting.cloudfront_distribution_id
}

output "api_server_ecr_url" {
  description = "ECR repo the deploy script docker-pushes the api-server image to."
  value       = module.api_server.ecr_repository_url
}

output "api_server_alb_dns" {
  value = module.api_server.alb_dns_name
}

output "api_server_ecs_service" {
  value = module.api_server.service_name
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
  name                    = "migrate4hana/${var.environment}/gate-secret"
  description             = "HMAC secret for spine approval gates (M4H_GATE_SECRET)"
  recovery_window_in_days = 0
  tags                    = { Component = "Governance", Pillar = "3" }
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

# ─────────────────────────────────────────────
# EventBridge schedule for the code-delta scheduler Lambda
# (Gemini gap #5 - dual-maintenance / continuous code sync).
# Fires once daily; the Lambda snapshots ECC custom-code, diffs against the
# prior baseline, and enqueues remediation tasks for any ADDED/MODIFIED objects.
# ─────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "code_delta_daily" {
  name                = "migrate4hana-code-delta-daily-${var.environment}"
  description         = "Daily TADIR snapshot + code-delta detection"
  schedule_expression = "cron(0 6 ? * MON-FRI *)" # 06:00 UTC business days
  tags                = { Component = "DualMaintenance" }
}

resource "aws_cloudwatch_event_target" "code_delta_daily" {
  rule      = aws_cloudwatch_event_rule.code_delta_daily.name
  target_id = "code-delta-scheduler"
  arn       = module.lambda.function_arns["code-delta-scheduler"]
}

resource "aws_lambda_permission" "code_delta_scheduler_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = "migrate4hana-code-delta-scheduler-${var.environment}"
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.code_delta_daily.arn
}

# ─────────────────────────────────────────────
# Bastion outputs (only meaningful when ssh_public_key is set)
# ─────────────────────────────────────────────
output "bastion_public_ip" {
  value       = length(module.bastion) > 0 ? module.bastion[0].public_ip : ""
  description = "Public IP of the reverse-SSH tunnel bastion (empty if not provisioned)"
}

output "bastion_private_ip" {
  value       = length(module.bastion) > 0 ? module.bastion[0].private_ip : ""
  description = "Private IP - Lambda reaches the laptop ECC at <this>:3341 via the reverse tunnel"
}

output "bastion_ssh_hint" {
  value       = length(module.bastion) > 0 ? module.bastion[0].ssh_command_hint : ""
  description = "Copy-paste SSH command for the laptop-side reverse tunnel"
}

# ─────────────────────────────────────────────
# S/4HANA + NAT outputs (used by helper scripts)
# ─────────────────────────────────────────────
output "nat_gateway_public_ip" {
  value       = module.vpc.nat_gateway_public_ip
  description = "Lambda's outbound source IP. Add to S/4HANA SG to allow Lambda -> S/4 RFC/OData."
}

output "s4_public_ip" {
  value       = var.s4_public_ip
  description = "Echoes the s4_public_ip variable so helper scripts can read it."
}
