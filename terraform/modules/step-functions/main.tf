###############################################################################
# Step Functions Module — Migration Pipeline Orchestrator
# 17-stage, 5-phase SAP Activate pipeline
###############################################################################

variable "environment" { type = string }
variable "lambda_arns" { type = map(string) }
variable "pipeline_stages" { type = list(string) }

# Lift-and-shift state machine — set to false on legacy stacks that do not
# yet have the new orchestrator Lambdas deployed.
variable "deploy_lift_and_shift" {
  type    = bool
  default = false
}

# BAPI / in-place state machine — opt-in. Deploys an INDEPENDENT state machine
# that drives the data-migrator lambda's UnifiedLoader + 25-spine roster path.
# Set to true for customer landscapes running BAPI/in-place mode (not
# lift-and-shift). Default false to preserve current prod posture; flipping to
# true adds exactly 3 net-new resources (sfn state machine + log group +
# output).
variable "deploy_bapi_inplace" {
  type    = bool
  default = false
}

# ── ECS / Fargate variables (heavy-compute stages) ──
variable "ecs_cluster_arn" {
  type        = string
  description = "ARN of the ECS cluster for Fargate tasks"
}
variable "ecs_task_definition_arn" {
  type        = string
  description = "ARN of the Fargate task definition (4 vCPU / 16 GB)"
}
variable "ecs_security_group_id" {
  type        = string
  description = "Security group for Fargate ENIs"
}
variable "private_subnet_ids" {
  type        = list(string)
  description = "VPC subnets for Fargate tasks (same as Lambda)"
}
variable "ecs_task_role_arn" {
  type        = string
  description = "Task role ARN (for iam:PassRole)"
}
variable "ecs_execution_role_arn" {
  type        = string
  description = "Execution role ARN (for iam:PassRole)"
}

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
      # Step Functions vended-logs delivery to CloudWatch. These specific
      # actions are what the service principal needs; `logs:*` is far too
      # broad and would let the state machine read arbitrary log groups in
      # the account.
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups",
        ]
        Resource = "*"
      },
      # Manual-gate human-approval pattern (lambda:invoke.waitForTaskToken).
      # SendTaskSuccess / SendTaskFailure / SendTaskHeartbeat are token-keyed
      # but AWS does not surface resource-level ARNs for them, so the action
      # itself is the boundary (the caller still needs the live task token).
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
        Resource = "*"
      },
      # ── ECS Fargate permissions (Stages 1, 5, 12, 12A) ──
      # Scoped via cluster + task-definition ARN conditions so this role can
      # only RunTask against the migrate4hana cluster and its task defs.
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = "arn:aws:ecs:*:*:task-definition/migrate4hana-*:*"
        Condition = {
          ArnEquals = {
            "ecs:cluster" = var.ecs_cluster_arn
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:StopTask", "ecs:DescribeTasks"]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "ecs:cluster" = var.ecs_cluster_arn
          }
        }
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          var.ecs_task_role_arn,
          var.ecs_execution_role_arn
        ]
      },
      # EventBridge — required for .sync and .waitForTaskToken ECS integration
      {
        Effect = "Allow"
        Action = [
          "events:PutTargets",
          "events:PutRule",
          "events:DescribeRule"
        ]
        Resource = "arn:aws:events:*:*:rule/StepFunctionsGetEventsForECSTaskRule"
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
        Type       = "Pass"
        Comment    = "Phase 1: PREPARE — Assessment & Pre-Checks"
        Result     = { phase = 1, phase_name = "PREPARE", description = "Assessment & Pre-Checks" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage1_Discovery_Prep"
      }

      # ── Stage 1: Discovery & Landscape Analysis  [ECS Fargate] ──
      # Prep state constructs the handler payload so it can be
      # serialised into the SFN_INPUT environment variable.
      Stage1_Discovery_Prep = {
        Type    = "Pass"
        Comment = "Construct discovery payload for ECS container"
        Parameters = {
          "stage"      = "discovery"
          "metadata.$" = "$.metadata"
          "input.$"    = "$.metadata.input"
        }
        ResultPath = "$.stage_payload"
        Next       = "Stage1_Discovery"
      }

      Stage1_Discovery = {
        Type     = "Task"
        Comment  = "ECS Fargate — Scan ECC: custom code, tables, org structure, roles"
        Resource = "arn:aws:states:::ecs:runTask.waitForTaskToken"
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = var.ecs_cluster_arn
          TaskDefinition = var.ecs_task_definition_arn
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = var.private_subnet_ids
              SecurityGroups = [var.ecs_security_group_id]
              AssignPublicIp = "DISABLED"
            }
          }
          Overrides = {
            ContainerOverrides = [{
              Name = "migration-worker"
              Environment = [
                { Name = "STAGE_TARGET", Value = "discovery-engine" },
                { "Name" = "SFN_TASK_TOKEN", "Value.$" = "$$.Task.Token" },
                { "Name" = "SFN_INPUT", "Value.$" = "States.JsonToString($.stage_payload)" },
              ]
            }]
          }
        }
        HeartbeatSeconds = 300
        TimeoutSeconds   = 3600
        ResultPath       = "$.discovery"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 60
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
        Type       = "Pass"
        Comment    = "Phase 2: EXPLORE — Application Preparation"
        Result     = { phase = 2, phase_name = "EXPLORE", description = "Application Preparation" }
        ResultPath = "$.phase_telemetry"
        Next       = "Stage5_CodeAnalysis_Prep"
      }

      # ── Stage 5: Code Analysis & Extraction  [ECS Fargate] ──
      Stage5_CodeAnalysis_Prep = {
        Type    = "Pass"
        Comment = "Construct code-analysis payload for ECS container"
        Parameters = {
          "stage"       = "code-analysis"
          "metadata.$"  = "$.metadata"
          "discovery.$" = "$.discovery.Payload"
        }
        ResultPath = "$.stage_payload"
        Next       = "Stage5_CodeAnalysis"
      }

      Stage5_CodeAnalysis = {
        Type     = "Task"
        Comment  = "ECS Fargate — AST extraction, PII scrub, GenAI prep (15 K+ programs)"
        Resource = "arn:aws:states:::ecs:runTask.waitForTaskToken"
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = var.ecs_cluster_arn
          TaskDefinition = var.ecs_task_definition_arn
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = var.private_subnet_ids
              SecurityGroups = [var.ecs_security_group_id]
              AssignPublicIp = "DISABLED"
            }
          }
          Overrides = {
            ContainerOverrides = [{
              Name = "migration-worker"
              Environment = [
                { Name = "STAGE_TARGET", Value = "code-analyzer" },
                { "Name" = "SFN_TASK_TOKEN", "Value.$" = "$$.Task.Token" },
                { "Name" = "SFN_INPUT", "Value.$" = "States.JsonToString($.stage_payload)" },
              ]
            }]
          }
        }
        HeartbeatSeconds = 300
        TimeoutSeconds   = 7200
        ResultPath       = "$.code_analysis"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 60
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "MigrationFailed"
          ResultPath  = "$.error"
        }]
        Next = "InvokeBedrockLLM"
      }

      # ── LLM Remediation: Bedrock (Anthropic Claude) ──
      InvokeBedrockLLM = {
        Type     = "Task"
        Comment  = "LLM remediation via Claude (direct Anthropic API, NAT egress)"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = lookup(var.lambda_arns, "code-analyzer", "")
          Payload = {
            "stage"           = "llm-remediation"
            "model"           = "anthropic-claude-sonnet-4-6"
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
        Type       = "Pass"
        Comment    = "Phase 3: REALIZE — Technical System Conversion (SUM/DMO)"
        Result     = { phase = 3, phase_name = "REALIZE", description = "Technical System Conversion" }
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
            "stage"      = "sum-dmo"
            "metadata.$" = "$.metadata"
            "cutover.$"  = "$.cutover.Payload"
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
        Type       = "Pass"
        Comment    = "Phase 4: POST-CONVERSION — Deploy, Configure & Validate"
        Result     = { phase = 4, phase_name = "POST_CONVERSION", description = "Deploy, Configure & Validate" }
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
        Next = "Stage12_DataLoad_Prepare"
      }

      # ── Stage 12: Data Loader — Distributed Map  [ECS Fargate] ──
      # SAP databases can be terabytes. Each of the 4 data streams
      # fans out into its own Fargate container (no 15-min limit).
      Stage12_DataLoad_Prepare = {
        Type    = "Pass"
        Comment = "Fan-out: prepare data load chunks for parallel ECS processing"
        Parameters = {
          "data_streams" = [
            { "stream_type" = "finance", "description" = "ACDOCA via BAPI_ACC_DOCUMENT_POST" },
            { "stream_type" = "business_partner", "description" = "BUT000 via BAPI_BUPA_CREATE_FROM_DATA" },
            { "stream_type" = "material_documents", "description" = "MATDOC via BAPI_GOODSMVT_CREATE" },
            { "stream_type" = "custom_tables", "description" = "Z-tables via RFC_WRITE_TABLE" },
          ]
          "metadata.$"       = "$.metadata"
          "data_migration.$" = "$.data_migration.Payload"
        }
        ResultPath = "$.data_load_input"
        Next       = "Stage12_DataLoad_DistributedMap"
      }

      Stage12_DataLoad_DistributedMap = {
        Type           = "Map"
        Comment        = "Parallel data loading — 4 concurrent Fargate tasks"
        ItemsPath      = "$.data_load_input.data_streams"
        MaxConcurrency = 4
        Parameters = {
          "stream_type.$"    = "$$.Map.Item.Value.stream_type"
          "description.$"    = "$$.Map.Item.Value.description"
          "stage"            = "data-loader"
          "metadata.$"       = "$.data_load_input.metadata"
          "data_migration.$" = "$.data_load_input.data_migration"
        }
        Iterator = {
          StartAt = "PrepDataStreamPayload"
          States = {
            # Capture the full map-item input so we can stringify it for SFN_INPUT
            PrepDataStreamPayload = {
              Type = "Pass"
              Parameters = {
                "stream_type.$"    = "$.stream_type"
                "description.$"    = "$.description"
                "stage.$"          = "$.stage"
                "metadata.$"       = "$.metadata"
                "data_migration.$" = "$.data_migration"
              }
              ResultPath = "$.sfn_payload"
              Next       = "LoadDataStreamECS"
            }
            LoadDataStreamECS = {
              Type     = "Task"
              Comment  = "ECS Fargate — load one data stream into S/4HANA"
              Resource = "arn:aws:states:::ecs:runTask.waitForTaskToken"
              Parameters = {
                LaunchType     = "FARGATE"
                Cluster        = var.ecs_cluster_arn
                TaskDefinition = var.ecs_task_definition_arn
                NetworkConfiguration = {
                  AwsvpcConfiguration = {
                    Subnets        = var.private_subnet_ids
                    SecurityGroups = [var.ecs_security_group_id]
                    AssignPublicIp = "DISABLED"
                  }
                }
                Overrides = {
                  ContainerOverrides = [{
                    Name = "migration-worker"
                    Environment = [
                      { Name = "STAGE_TARGET", Value = "data-loader" },
                      { "Name" = "SFN_TASK_TOKEN", "Value.$" = "$$.Task.Token" },
                      { "Name" = "SFN_INPUT", "Value.$" = "States.JsonToString($.sfn_payload)" },
                    ]
                  }]
                }
              }
              HeartbeatSeconds = 300
              TimeoutSeconds   = 14400
              Retry = [{
                ErrorEquals     = ["States.TaskFailed"]
                IntervalSeconds = 60
                MaxAttempts     = 2
                BackoffRate     = 2.0
              }]
              End = true
            }
          }
        }
        ResultPath = "$.data_load_streams"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "ExecutionFailed"
          ResultPath  = "$.error"
        }]
        Next = "Stage12_DataLoad_Aggregate"
      }

      # Aggregate parallel results into a single data_load result
      Stage12_DataLoad_Aggregate = {
        Type    = "Pass"
        Comment = "Consolidate parallel data load results + trigger reconciliation"
        Parameters = {
          "Payload" = {
            "status"     = "success"
            "parallel"   = true
            "streams.$"  = "$.data_load_streams"
            "metadata.$" = "$.data_load_input.metadata"
          }
        }
        ResultPath = "$.data_load"
        Next       = "Stage12A_Reconciliation_Prep"
      }

      # ── Stage 12A: Penny-Perfect Financial Reconciliation  [ECS Fargate] ──
      Stage12A_Reconciliation_Prep = {
        Type    = "Pass"
        Comment = "Construct reconciliation payload for ECS container"
        Parameters = {
          "stage"            = "reconciliation"
          "metadata.$"       = "$.metadata"
          "data_migration.$" = "$.data_migration.Payload"
          "data_load.$"      = "$.data_load.Payload"
        }
        ResultPath = "$.stage_payload"
        Next       = "Stage12A_Reconciliation"
      }

      Stage12A_Reconciliation = {
        Type     = "Task"
        Comment  = "ECS Fargate — post-load reconciliation: ECC GL vs S/4HANA ACDOCA"
        Resource = "arn:aws:states:::ecs:runTask.waitForTaskToken"
        Parameters = {
          LaunchType     = "FARGATE"
          Cluster        = var.ecs_cluster_arn
          TaskDefinition = var.ecs_task_definition_arn
          NetworkConfiguration = {
            AwsvpcConfiguration = {
              Subnets        = var.private_subnet_ids
              SecurityGroups = [var.ecs_security_group_id]
              AssignPublicIp = "DISABLED"
            }
          }
          Overrides = {
            ContainerOverrides = [{
              Name = "migration-worker"
              Environment = [
                { Name = "STAGE_TARGET", Value = "data-loader" },
                { "Name" = "SFN_TASK_TOKEN", "Value.$" = "$$.Task.Token" },
                { "Name" = "SFN_INPUT", "Value.$" = "States.JsonToString($.stage_payload)" },
              ]
            }]
          }
        }
        HeartbeatSeconds = 300
        TimeoutSeconds   = 7200
        ResultPath       = "$.reconciliation"
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
        Type       = "Pass"
        Comment    = "Phase 5: DEPLOY & RUN — Integration, Validation & Go-Live"
        Result     = { phase = 5, phase_name = "DEPLOY_AND_RUN", description = "Integration, Validation & Go-Live" }
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


# =============================================================================
# LIFT-AND-SHIFT STATE MACHINE (greenfield S/4HANA pipeline)
#
# Deployed when var.deploy_lift_and_shift = true. Renders
# lift_and_shift_pipeline.asl.json with placeholder substitution: each
# ${XxxArn} is replaced with the corresponding entry from var.lambda_arns.
# =============================================================================
locals {
  # Step Functions schema requires every Task's Resource to be a valid ARN at
  # creation time. If a Lambda role hasn't been deployed yet, fall back to the
  # manual-gate Lambda (always present) so the state machine validates. Replace
  # the fallback with the real Lambda once it's deployed.
  ls_fallback_arn = lookup(var.lambda_arns, "manual-gate", "")

  ls_arns = {
    DiscoveryEngineArn               = lookup(var.lambda_arns, "discovery-engine", local.ls_fallback_arn)
    SizingAdvisorArn                 = lookup(var.lambda_arns, "sizing-advisor", local.ls_fallback_arn)
    ObjectRouterArn                  = lookup(var.lambda_arns, "object-router", local.ls_fallback_arn)
    TargetProvisionerArn             = lookup(var.lambda_arns, "target-provisioner", local.ls_fallback_arn)
    BasisValidatorArn                = lookup(var.lambda_arns, "basis-validator", local.ls_fallback_arn)
    CodeAnalyzerArn                  = lookup(var.lambda_arns, "code-analyzer", local.ls_fallback_arn)
    TransportArtifactBuilderArn      = lookup(var.lambda_arns, "transport-artifact-builder", local.ls_fallback_arn)
    TransportFilePlacerArn           = lookup(var.lambda_arns, "transport-file-placer", local.ls_fallback_arn)
    TransportImportExecutorArn       = lookup(var.lambda_arns, "transport-import-executor", local.ls_fallback_arn)
    TransportImportVerifierArn       = lookup(var.lambda_arns, "transport-import-verifier", local.ls_fallback_arn)
    ConfigReplicatorArn              = lookup(var.lambda_arns, "config-replicator", local.ls_fallback_arn)
    BCSetBuilderArn                  = lookup(var.lambda_arns, "bc-set-builder", local.ls_fallback_arn)
    DataMigratorArn                  = lookup(var.lambda_arns, "data-migrator", local.ls_fallback_arn)
    DataHygieneArn                   = lookup(var.lambda_arns, "data-hygiene", local.ls_fallback_arn)
    MigrationCockpitOrchestratorArn  = lookup(var.lambda_arns, "migration-cockpit-orchestrator", local.ls_fallback_arn)
    LTMOMOrchestratorArn             = lookup(var.lambda_arns, "ltmom-orchestrator", local.ls_fallback_arn)
    IDocOrchestratorArn              = lookup(var.lambda_arns, "idoc-orchestrator", local.ls_fallback_arn)
    MigrationValidatorArn            = lookup(var.lambda_arns, "migration-validator", local.ls_fallback_arn)
    TestGeneratorArn                 = lookup(var.lambda_arns, "test-generator", local.ls_fallback_arn)
    MigrationCompletenessAnalyzerArn = lookup(var.lambda_arns, "migration-completeness-analyzer", local.ls_fallback_arn)
    CutoverOrchestratorArn           = lookup(var.lambda_arns, "cutover-orchestrator", local.ls_fallback_arn)
    DeltaExtractorArn                = lookup(var.lambda_arns, "delta-extractor", local.ls_fallback_arn)
    IntegrationActivatorArn          = lookup(var.lambda_arns, "integration-activator", local.ls_fallback_arn)
    # NOTE: key MUST match the lambda module's each.key (kebab-case, not snake).
    # 2026-06-10: was previously "pdf_report_generator" (snake), causing a silent
    # fallback to manual-gate-prod even when the Lambda was deployed.
    PdfReportGeneratorArn = lookup(var.lambda_arns, "pdf-report-generator", local.ls_fallback_arn)
    RollbackManagerArn    = lookup(var.lambda_arns, "rollback-manager", local.ls_fallback_arn)
    ManualGateLambdaArn   = lookup(var.lambda_arns, "manual-gate", local.ls_fallback_arn)
  }
}

resource "aws_sfn_state_machine" "lift_and_shift" {
  count    = var.deploy_lift_and_shift ? 1 : 0
  name     = "migrate4hana-lift-and-shift-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn

  # Manual placeholder substitution — we cannot use templatefile() because the
  # ASL JSON contains $$.Task.Token references and templatefile would mangle
  # the $$ escape. Each replace() swaps one ${PlaceholderArn} for the actual
  # Lambda ARN.
  definition = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
    file("${path.module}/lift_and_shift_pipeline.asl.json"),
    "$${DiscoveryEngineArn}", local.ls_arns.DiscoveryEngineArn),
    "$${SizingAdvisorArn}", local.ls_arns.SizingAdvisorArn),
    "$${ObjectRouterArn}", local.ls_arns.ObjectRouterArn),
    "$${TargetProvisionerArn}", local.ls_arns.TargetProvisionerArn),
    "$${BasisValidatorArn}", local.ls_arns.BasisValidatorArn),
    "$${CodeAnalyzerArn}", local.ls_arns.CodeAnalyzerArn),
    "$${TransportArtifactBuilderArn}", local.ls_arns.TransportArtifactBuilderArn),
    "$${TransportFilePlacerArn}", local.ls_arns.TransportFilePlacerArn),
    "$${TransportImportExecutorArn}", local.ls_arns.TransportImportExecutorArn),
    "$${TransportImportVerifierArn}", local.ls_arns.TransportImportVerifierArn),
    "$${ConfigReplicatorArn}", local.ls_arns.ConfigReplicatorArn),
    "$${BCSetBuilderArn}", local.ls_arns.BCSetBuilderArn),
    "$${DataMigratorArn}", local.ls_arns.DataMigratorArn),
    "$${DataHygieneArn}", local.ls_arns.DataHygieneArn),
    "$${MigrationCockpitOrchestratorArn}", local.ls_arns.MigrationCockpitOrchestratorArn),
    "$${LTMOMOrchestratorArn}", local.ls_arns.LTMOMOrchestratorArn),
    "$${IDocOrchestratorArn}", local.ls_arns.IDocOrchestratorArn),
    "$${MigrationValidatorArn}", local.ls_arns.MigrationValidatorArn),
    "$${TestGeneratorArn}", local.ls_arns.TestGeneratorArn),
    "$${MigrationCompletenessAnalyzerArn}", local.ls_arns.MigrationCompletenessAnalyzerArn),
    "$${CutoverOrchestratorArn}", local.ls_arns.CutoverOrchestratorArn),
    "$${DeltaExtractorArn}", local.ls_arns.DeltaExtractorArn),
    "$${IntegrationActivatorArn}", local.ls_arns.IntegrationActivatorArn),
    "$${PdfReportGeneratorArn}", local.ls_arns.PdfReportGeneratorArn),
    "$${RollbackManagerArn}", local.ls_arns.RollbackManagerArn),
  "$${ManualGateLambdaArn}", local.ls_arns.ManualGateLambdaArn)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_ls[0].arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = { Name = "migrate4hana-lift-and-shift-${var.environment}", Pipeline = "lift-and-shift" }
}

resource "aws_cloudwatch_log_group" "sfn_ls" {
  count             = var.deploy_lift_and_shift ? 1 : 0
  name              = "/aws/stepfunctions/migrate4hana-lift-and-shift-${var.environment}"
  retention_in_days = 30
}

output "lift_and_shift_state_machine_arn" {
  value       = var.deploy_lift_and_shift ? aws_sfn_state_machine.lift_and_shift[0].arn : ""
  description = "ARN of the lift-and-shift state machine (empty if not deployed)"
}

###############################################################################
# BAPI / in-place pipeline (NEW 2026-06-09)
###############################################################################
#
# Parallel-to-lift-and-shift state machine for customers running the
# BAPI/in-place migration mode (data-migrator lambda's UnifiedLoader -> 25-
# spine roster). Independent state machine, independent log group, opt-in via
# var.deploy_bapi_inplace (default false), so deploying this module does NOT
# disturb the existing lift-and-shift or main migration_pipeline state
# machines for current customers.
#
# Per-object fan-out invokes data-migrator with mode
# `phase_b_validate_production_path` -- the same code path proven against
# live S/4 on 2026-06-09 (UnifiedLoader -> spine -> Reconciler, RECONCILED on
# Material + BusinessPartner). Each per-object result already carries the
# reconciler verdict and verify_key tie-out, so the state machine just
# orchestrates and gates.
#
# To enable for a customer landscape: set deploy_bapi_inplace=true in the
# environment tfvars and `terraform apply`. Plan should show exactly 3 net-
# new resources (sfn state machine + log group + this output).
#
resource "aws_sfn_state_machine" "bapi_inplace" {
  count    = var.deploy_bapi_inplace ? 1 : 0
  name     = "migrate4hana-bapi-inplace-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn

  definition = replace(
    file("${path.module}/bapi_inplace_pipeline.asl.json"),
    "$${DataMigratorArn}",
    local.ls_arns.DataMigratorArn,
  )

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_bapi[0].arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = {
    Name     = "migrate4hana-bapi-inplace-${var.environment}"
    Pipeline = "bapi-inplace"
  }
}

resource "aws_cloudwatch_log_group" "sfn_bapi" {
  count             = var.deploy_bapi_inplace ? 1 : 0
  name              = "/aws/stepfunctions/migrate4hana-bapi-inplace-${var.environment}"
  retention_in_days = 30
}

output "bapi_inplace_state_machine_arn" {
  value       = var.deploy_bapi_inplace ? aws_sfn_state_machine.bapi_inplace[0].arn : ""
  description = "ARN of the BAPI/in-place state machine (empty if not deployed)"
}
