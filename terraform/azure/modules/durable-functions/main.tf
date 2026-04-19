###############################################################################
# Durable Functions Module — 17-Stage Pipeline Orchestrator
#
# Replaces AWS Step Functions with Azure Durable Functions to coordinate
# the full SAP ECC → S/4HANA migration pipeline.
#
# Pipeline phases:
#   Phase 1 PREPARE:         Discovery[Container] → ProcessMining[Fn] →
#                            MaintenancePlanner → ReadinessCheck →
#                            SimplificationCheck
#   Phase 2 EXPLORE:         CodeAnalysis[Container] → LLM Decision Gate →
#                            DataHygiene → DataAssessment → ConfigAssessment
#   Phase 3 REALIZE:         PreConversionGate → ConversionApproval →
#                            SUMDMOOrchestration
#   Phase 4 POST-CONVERSION: CodeDeployer → DataLoader[Container,4-parallel] →
#                            Reconciliation[Container] → ConfigApplier →
#                            RoleProvisioner
#   Phase 5 DEPLOY & RUN:    IntegrationActivator → MigrationValidator →
#                            TestGenerator
#
# Error handling: retry 2 attempts, 60s first interval, backoff factor 2.0
#                 catch → RollbackManager
###############################################################################

locals {
  app_name = "migrate4hana-orch-${var.environment}"
  default_tags = merge(var.tags, {
    Component   = "Orchestrator"
    Environment = var.environment
  })
}

# ── Storage account for Durable Functions task hub ──────────────────────────
resource "azurerm_storage_account" "orchestrator" {
  name                     = "m4horch${var.environment}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.default_tags
}

# ── Service Plan (create only if not sharing with functions module) ─────────
resource "azurerm_service_plan" "orchestrator" {
  count               = var.service_plan_id == "" ? 1 : 0
  name                = "migrate4hana-orch-plan-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = var.sku
  tags                = local.default_tags
}

locals {
  effective_plan_id = var.service_plan_id != "" ? var.service_plan_id : azurerm_service_plan.orchestrator[0].id
}

# ── Orchestrator Function App ──────────────────────────────────────────────
resource "azurerm_linux_function_app" "orchestrator" {
  name                = local.app_name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = local.effective_plan_id

  storage_account_name       = azurerm_storage_account.orchestrator.name
  storage_account_access_key = azurerm_storage_account.orchestrator.primary_access_key

  virtual_network_subnet_id = var.functions_subnet_id

  identity {
    type         = "UserAssigned"
    identity_ids = [var.managed_identity_id]
  }

  site_config {
    application_insights_connection_string = var.application_insights_connection_string

    application_stack {
      python_version = "3.11"
    }

    vnet_route_all_enabled = true
  }

  app_settings = {
    # Durable Functions runtime
    FUNCTIONS_WORKER_RUNTIME = "python"
    AzureWebJobsStorage      = var.storage_connection_string

    # Concurrency tuning
    "AzureFunctionsJobHost__extensions__durableTask__maxConcurrentActivityFunctions"     = "10"
    "AzureFunctionsJobHost__extensions__durableTask__maxConcurrentOrchestratorFunctions" = "5"

    # Stage functions endpoint
    FUNCTION_APP_URL = var.function_app_url

    # Container Apps endpoints (JSON map)
    CONTAINER_APP_URLS = jsonencode(var.container_app_urls)

    # Key Vault for SAP credentials
    KEYVAULT_URI = var.keyvault_uri

    # Managed identity
    AZURE_CLIENT_ID = var.managed_identity_client_id

    # Monitoring
    APPLICATIONINSIGHTS_CONNECTION_STRING = var.application_insights_connection_string

    # ── Pipeline configuration ──────────────────────────────────────────
    # Retry policy: 2 attempts, 60s first interval, backoff 2.0×
    PIPELINE_RETRY_MAX_ATTEMPTS   = "2"
    PIPELINE_RETRY_FIRST_INTERVAL = "60"
    PIPELINE_RETRY_BACKOFF_FACTOR = "2.0"

    # Phase definitions (consumed by the orchestrator Python code)
    PIPELINE_PHASES = jsonencode({
      "phase1_prepare" = {
        order = 1
        name  = "PREPARE"
        stages = [
          { name = "Discovery", type = "container", target = "discovery-engine" },
          { name = "ProcessMining", type = "function", target = "process-miner" },
          { name = "MaintenancePlanner", type = "function", target = "maintenance-planner" },
          { name = "ReadinessCheck", type = "function", target = "readiness-check" },
          { name = "SimplificationCheck", type = "function", target = "simplification-check" }
        ]
      }
      "phase2_explore" = {
        order = 2
        name  = "EXPLORE"
        stages = [
          { name = "CodeAnalysis", type = "container", target = "code-analyzer" },
          { name = "LLMDecisionGate", type = "function", target = "integration-mapper" },
          { name = "DataHygiene", type = "function", target = "data-hygiene" },
          { name = "DataAssessment", type = "function", target = "data-migrator" },
          { name = "ConfigAssessment", type = "function", target = "config-replicator" }
        ]
      }
      "phase3_realize" = {
        order = 3
        name  = "REALIZE"
        stages = [
          { name = "PreConversionGate", type = "function", target = "migration-completeness-analyzer" },
          { name = "ConversionApproval", type = "function", target = "cutover-orchestrator" },
          { name = "SUMDMOOrchestration", type = "function", target = "sum-orchestrator" }
        ]
      }
      "phase4_post_conversion" = {
        order = 4
        name  = "POST-CONVERSION"
        stages = [
          { name = "CodeDeployer", type = "function", target = "code-deployer" },
          { name = "DataLoader", type = "container", target = "data-loader", parallel = 4 },
          { name = "Reconciliation", type = "container", target = "data-loader-reconcile" },
          { name = "ConfigApplier", type = "function", target = "config-applier" },
          { name = "RoleProvisioner", type = "function", target = "role-provisioner" }
        ]
      }
      "phase5_deploy_run" = {
        order = 5
        name  = "DEPLOY & RUN"
        stages = [
          { name = "IntegrationActivator", type = "function", target = "integration-activator" },
          { name = "MigrationValidator", type = "function", target = "migration-validator" },
          { name = "TestGenerator", type = "function", target = "test-generator" }
        ]
      }
      "error_handler" = {
        name   = "ERROR_HANDLER"
        target = "rollback-manager"
        type   = "function"
      }
    })
  }

  tags = local.default_tags
}
