###############################################################################
# Step Functions Module — Migration Pipeline Orchestrator
# 17-stage, 5-phase SAP Activate pipeline
###############################################################################

variable "environment" { type = string }
variable "lambda_arns" { type = map(string) }
variable "pipeline_stages" { type = list(string) }

# ── IAM Role for Step Functions ──────────────
resource "aws_iam_role" "step_functions" {
  name = "migrate4hana-sfn-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "step_functions" {
  name = "migrate4hana-sfn-policy"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = values(var.lambda_arns)
      },
      {
        Effect   = "Allow"
        Action   = ["logs:*"]
        Resource = "*"
      }
    ]
  })
}

# ── State Machine Definition ─────────────────
resource "aws_sfn_state_machine" "migration_pipeline" {
  name     = "migrate4hana-pipeline-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn

  definition = jsonencode({
    Comment = "Migrate4HANA — 17-Stage SAP Activate Pipeline (5 Phases)"
    StartAt = "PreFlightChecks"
    States = {

      # ── Pre-flight validation ──
      PreFlightChecks = {
        Type    = "Pass"
        Comment = "Validate inputs and connectivity"
        Parameters = {
          "run_id.$"    = "States.UUID()"
          "timestamp.$" = "$$.Execution.StartTime"
          "input.$"     = "$"
        }
        ResultPath = "$.metadata"
        Next       = "Phase1_Prepare_Marker"
      }

      # ══════════════════════════════════════════════════════════════
      # PHASE 1: PREPARE — Assessment & Pre-Checks (Stages 1-4)
      # ══════════════════════════════════════════════════════════════

      Phase1_Prepare_Marker = {
        Type    = "Pass"
        Comment = "Phase 1: PREPARE — Assessment & Pre-Checks"
        Result  = { phase = 1, phase_name = "PREPARE", description = "Assessment & Pre-Checks" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage1_Discovery"
      }

      # ── Stage 1: Discovery & Landscape Analysis ──
      Stage1_Discovery = {
        Type     = "Task"
        Comment  = "Scan ECC: custom code, tables, org structure, roles, integrations"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "discovery-engine", "")
          Payload = {
            "stage"      = "discovery"
            "metadata.$" = "$.metadata"
            "input.$"    = "$.metadata.input"
          }
        }
        ResultPath = "$.discovery"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage1A_ProcessMining"
      }

      # ── Stage 1A: Process Mining ──
      Stage1A_ProcessMining = {
        Type     = "Task"
        Comment  = "Analyze ST03N workload data to map standard T-codes strictly to Fiori"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "process-miner", "")
          Payload = {
            "stage"       = "process-mining"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.process_mining"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "ReviewDiscovery"
      }

      # ── Decision: Review discovery results ──
      ReviewDiscovery = {
        Type    = "Choice"
        Comment = "Check if discovery found blocking issues"
        Choices = [{
          Variable           = "$.discovery.Payload.blocking_issues"
          NumericGreaterThan = 0
          Next               = "DiscoveryBlocker"
        }]
        Default = "Stage2_MaintenancePlanner"
      }

      DiscoveryBlocker = {
        Type  = "Fail"
        Error = "DiscoveryBlockingIssues"
        Cause = "Discovery found blocking issues that need manual resolution"
      }

      # ── Stage 2: Maintenance Planner Validation ──
      Stage2_MaintenancePlanner = {
        Type     = "Task"
        Comment  = "Validate SAP Maintenance Planner stack and upgrade path"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "maintenance-planner", "")
          Payload = {
            "stage"       = "maintenance-planner"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.maintenance_planner"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage3_ReadinessCheck"
      }

      # ── Stage 3: SAP Readiness Check ──
      Stage3_ReadinessCheck = {
        Type     = "Task"
        Comment  = "Run SAP Readiness Check for S/4HANA conversion compatibility"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "readiness-check", "")
          Payload = {
            "stage"       = "readiness-check"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.readiness_check"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage4_SimplificationCheck"
      }

      # ── Stage 4: Simplification Item Check ──
      Stage4_SimplificationCheck = {
        Type     = "Task"
        Comment  = "Analyze SAP Simplification Items for custom code impact"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "simplification-check", "")
          Payload = {
            "stage"       = "simplification-check"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.simplification_check"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Phase2_Explore_Marker"
      }

      # ══════════════════════════════════════════════════════════════
      # PHASE 2: EXPLORE — Application Preparation (Stages 5-8)
      # ══════════════════════════════════════════════════════════════

      Phase2_Explore_Marker = {
        Type    = "Pass"
        Comment = "Phase 2: EXPLORE — Application Preparation"
        Result  = { phase = 2, phase_name = "EXPLORE", description = "Application Preparation" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage5_CodeAnalysis"
      }

      # ── Stage 5: Code Analysis & Extraction ──
      Stage5_CodeAnalysis = {
        Type     = "Task"
        Comment  = "Extract AST from ABAP, scrub PII, prepare for LLM GenAI routing"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "code-analyzer", "")
          Payload = {
            "stage"       = "code-analysis"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.code_analysis"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Decision_LLMRoute"
      }

      # ── Decision: InfoSec LLM Routing (Air-Gapped vs Bedrock) ──
      Decision_LLMRoute = {
        Type    = "Choice"
        Comment = "Determine based on InfoSec compliance which GenAI path to traverse"
        Choices = [{
          Variable     = "$.metadata.input.llm_mode"
          StringEquals = "AIRGAPPED_LOCAL"
          Next         = "InvokeAirGappedLLM"
        }]
        Default = "InvokeBedrockLLM"
      }

      # ── LLM Remediation: Air-Gapped Local Models (e.g. Llama 3) ──
      InvokeAirGappedLLM = {
        Type     = "Task"
        Comment  = "Highly secure GPU/EC2 Local LLM for Banks & Defense"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "airgapped-llm-router", "")
          Payload = {
            "stage"           = "llm-remediation"
            "model"           = "local-g5-llama3"
            "metadata.$"      = "$.metadata"
            "code_analysis.$" = "$.code_analysis.Payload"
          }
        }
        ResultPath     = "$.remediated_code"
        TimeoutSeconds = 900
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage6_DataHygiene"
      }

      # ── LLM Remediation: Standard Bedrock (Anthropic/Titan) ──
      InvokeBedrockLLM = {
        Type     = "Task"
        Comment  = "Enterprise Scale Amazon Bedrock via PrivateLink"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "bedrock-llm-router", "")
          Payload = {
            "stage"           = "llm-remediation"
            "model"           = "bedrock-anthropic-claude"
            "metadata.$"      = "$.metadata"
            "code_analysis.$" = "$.code_analysis.Payload"
          }
        }
        ResultPath     = "$.remediated_code"
        TimeoutSeconds = 900
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage6_DataHygiene"
      }

      # ── Stage 6: Master Data Hygiene & Deduplication ──
      Stage6_DataHygiene = {
        Type     = "Task"
        Comment  = "Cleanses ERP dummy data and establishes unique BP mappings"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "data-hygiene", "")
          Payload = {
            "stage"       = "data-hygiene"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.data_hygiene"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage7_DataAssessment"
      }

      # ── Stage 7: Data Assessment & Migration Planning ──
      Stage7_DataAssessment = {
        Type     = "Task"
        Comment  = "Assess data: Finance->ACDOCA, Materials->MATDOC, BP conversion planning"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "data-migrator", "")
          Payload = {
            "stage"           = "data-assessment"
            "metadata.$"      = "$.metadata"
            "discovery.$"     = "$.discovery.Payload"
            "code_analysis.$" = "$.code_analysis.Payload"
          }
        }
        ResultPath     = "$.data_migration"
        TimeoutSeconds = 3600
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 60
          MaxAttempts     = 1
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage8_ConfigAssessment"
      }

      # ── Stage 8: Config, Role & Integration Assessment ──
      Stage8_ConfigAssessment = {
        Type     = "Task"
        Comment  = "Assess SPRO config, roles, and integration mapping for conversion"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "config-replicator", "")
          Payload = {
            "stage"       = "config-assessment"
            "metadata.$"  = "$.metadata"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.config"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "ConversionApprovalGate"
      }

      # ── Conversion Approval Gate ──
      # Critical decision: check all Phase 1-2 stages passed before Phase 3
      ConversionApprovalGate = {
        Type    = "Choice"
        Comment = "Verify all Phase 1-2 stages passed before allowing Phase 3 (SUM/DMO)"
        Choices = [{
          Variable      = "$.metadata.input.execute"
          BooleanEquals = true
          Next          = "Phase3_Realize_Marker"
        }]
        Default = "PlanningOnlyComplete"
      }

      PlanningOnlyComplete = {
        Type    = "Succeed"
        Comment = "Planning stages 1-8 completed. Execution not requested."
      }

      # ══════════════════════════════════════════════════════════════
      # PHASE 3: REALIZE — Technical System Conversion (Stages 9-10)
      # SUM/DMO Gate — SAP-managed database conversion
      # ══════════════════════════════════════════════════════════════

      Phase3_Realize_Marker = {
        Type    = "Pass"
        Comment = "Phase 3: REALIZE — Technical System Conversion (SUM/DMO)"
        Result  = { phase = 3, phase_name = "REALIZE", description = "Technical System Conversion" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage9_PreConversionGate"
      }

      # ── Stage 9: Pre-Conversion Cutover Gate ──
      Stage9_PreConversionGate = {
        Type     = "Task"
        Comment  = "Pre-cutover checks, source lock, checkpoint creation for SUM/DMO"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "cutover-orchestrator", "")
          Payload = {
            "stage"            = "pre-conversion-gate"
            "metadata.$"       = "$.metadata"
            "discovery.$"      = "$.discovery.Payload"
            "code_analysis.$"  = "$.code_analysis.Payload"
            "data_migration.$" = "$.data_migration.Payload"
            "config.$"         = "$.config.Payload"
          }
        }
        ResultPath = "$.cutover"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 30
          MaxAttempts     = 1
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "ReviewCutover"
      }

      # ── Decision: Cutover GO/NO-GO ──
      ReviewCutover = {
        Type    = "Choice"
        Comment = "Check cutover orchestrator result"
        Choices = [{
          Variable     = "$.cutover.Payload.go_no_go"
          StringEquals = "GO"
          Next         = "Stage10_SUM_DMO"
        }]
        Default = "CutoverBlocked"
      }

      CutoverBlocked = {
        Type  = "Fail"
        Error = "CutoverBlocked"
        Cause = "Pre-cutover checks failed — SUM/DMO execution blocked"
      }

      # ── Stage 10: SUM/DMO Orchestration & Monitoring ──
      Stage10_SUM_DMO = {
        Type     = "Task"
        Comment  = "Orchestrate and monitor SAP SUM/DMO database conversion"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "sum-orchestrator", "")
          Payload = {
            "stage"       = "sum-dmo"
            "metadata.$"  = "$.metadata"
            "cutover.$"   = "$.cutover.Payload"
          }
        }
        ResultPath     = "$.sum_dmo"
        TimeoutSeconds = 7200
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 120
          MaxAttempts     = 1
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Phase4_PostConversion_Marker"
      }

      # ══════════════════════════════════════════════════════════════
      # PHASE 4: POST-CONVERSION — Deploy & Validate (Stages 11-14)
      # ══════════════════════════════════════════════════════════════

      Phase4_PostConversion_Marker = {
        Type    = "Pass"
        Comment = "Phase 4: POST-CONVERSION — Deploy, Configure & Validate"
        Result  = { phase = 4, phase_name = "POST_CONVERSION", description = "Deploy, Configure & Validate" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage11_CodeDeploy"
      }

      # ── Stage 11: Code Deployer ──
      Stage11_CodeDeploy = {
        Type     = "Task"
        Comment  = "Deploy fixed ABAP programs to S/4HANA transport system"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "code-deployer", "")
          Payload = {
            "stage"           = "code-deployer"
            "metadata.$"      = "$.metadata"
            "code_analysis.$" = "$.code_analysis.Payload"
          }
        }
        ResultPath     = "$.code_deploy"
        TimeoutSeconds = 1800
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 60
          MaxAttempts     = 1
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage12_DataLoad"
      }

      # ── Stage 12: Data Loader ──
      Stage12_DataLoad = {
        Type     = "Task"
        Comment  = "Load transformed data into S/4HANA (ACDOCA, BUT000, MATDOC)"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "data-loader", "")
          Payload = {
            "stage"            = "data-loader"
            "metadata.$"       = "$.metadata"
            "data_migration.$" = "$.data_migration.Payload"
          }
        }
        ResultPath     = "$.data_load"
        TimeoutSeconds = 7200
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 120
          MaxAttempts     = 1
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage13_ConfigApply"
      }

      # ── Stage 13: Config Applier ──
      Stage13_ConfigApply = {
        Type     = "Task"
        Comment  = "Apply SPRO config, number ranges, Fiori settings to S/4HANA"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "config-applier", "")
          Payload = {
            "stage"      = "config-applier"
            "metadata.$" = "$.metadata"
            "config.$"   = "$.config.Payload"
          }
        }
        ResultPath = "$.config_apply"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage14_RoleProvision"
      }

      # ── Stage 14: Role Provisioner ──
      Stage14_RoleProvision = {
        Type     = "Task"
        Comment  = "Create PFCG roles, Fiori catalogs, user assignments in S/4HANA"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "role-provisioner", "")
          Payload = {
            "stage"       = "role-provisioner"
            "metadata.$"  = "$.metadata"
            "roles.$"     = "$.roles.Payload"
            "discovery.$" = "$.discovery.Payload"
          }
        }
        ResultPath = "$.role_provision"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Phase5_DeployAndRun_Marker"
      }

      # ══════════════════════════════════════════════════════════════
      # PHASE 5: DEPLOY & RUN — Go-Live (Stages 15-17)
      # ══════════════════════════════════════════════════════════════

      Phase5_DeployAndRun_Marker = {
        Type    = "Pass"
        Comment = "Phase 5: DEPLOY & RUN — Integration, Validation & Go-Live"
        Result  = { phase = 5, phase_name = "DEPLOY_AND_RUN", description = "Integration, Validation & Go-Live" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage15_IntegrationActivate"
      }

      # ── Stage 15: Integration Activator ──
      Stage15_IntegrationActivate = {
        Type     = "Task"
        Comment  = "Configure RFC destinations, IDoc partners, APIs in S/4HANA"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "integration-activator", "")
          Payload = {
            "stage"          = "integration-activator"
            "metadata.$"     = "$.metadata"
            "integrations.$" = "$.integrations.Payload"
          }
        }
        ResultPath = "$.integration_activate"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage16_MigrationValidation"
      }

      # ── Stage 16: Migration Validator ──
      Stage16_MigrationValidation = {
        Type     = "Task"
        Comment  = "End-to-end validation, reconciliation, GO-LIVE scorecard"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "migration-validator", "")
          Payload = {
            "stage"                  = "migration-validator"
            "metadata.$"             = "$.metadata"
            "data_migration.$"       = "$.data_migration.Payload"
            "code_deploy.$"          = "$.code_deploy.Payload"
            "data_load.$"            = "$.data_load.Payload"
            "config_apply.$"         = "$.config_apply.Payload"
            "role_provision.$"       = "$.role_provision.Payload"
            "integration_activate.$" = "$.integration_activate.Payload"
          }
        }
        ResultPath = "$.validation"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage17_DITLTestGeneration"
      }

      # ── Stage 17: DITL Test Script Generator ──
      Stage17_DITLTestGeneration = {
        Type     = "Task"
        Comment  = "Generates E2E Automation tests based on Process Mining mapping"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "test-generator", "")
          Payload = {
            "stage"            = "test-generator"
            "metadata.$"       = "$.metadata"
            "process_mining.$" = "$.process_mining.Payload"
          }
        }
        ResultPath = "$.tests"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "MigrationComplete"
      }

      # ── Success ──
      MigrationComplete = {
        Type    = "Succeed"
        Comment = "All 17 stages across 5 phases completed — SAP Activate pipeline done"
      }

      # ── Failure handlers & Rollback ──
      MigrationFailed = {
        Type  = "Fail"
        Error = "MigrationPlanningFailed"
        Cause = "Planning phase failed — check CloudWatch logs"
      }

      ExecutionFailed = {
        Type     = "Task"
        Comment  = "Execution failure caught. Initiating Automated Rollback Manager."
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "rollback-manager", "")
          Payload = {
            "stage"           = "rollback"
            "metadata.$"      = "$.metadata"
            "error_context.$" = "$.error"
          }
        }
        Next = "TerminalFailureState"
      }

      TerminalFailureState = {
        Type  = "Fail"
        Error = "MigrationExecutionFailed"
        Cause = "Execution phase failed. Automated Rollback was initiated."
      }
    }
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = { Name = "migrate4hana-pipeline-${var.environment}" }
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/stepfunctions/migrate4hana-${var.environment}"
  retention_in_days = 30
}

# ── Outputs ──────────────────────────────────
output "state_machine_arn" { value = aws_sfn_state_machine.migration_pipeline.arn }
output "state_machine_name" { value = aws_sfn_state_machine.migration_pipeline.name }
