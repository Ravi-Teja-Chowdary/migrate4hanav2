###############################################################################
# Functions Module — Azure Functions Premium Plan
#
# Hosts ALL 18 migration stage functions in a single Linux Function App:
#   Stage 1A  process-miner          Stage 9   cutover-orchestrator
#   Stage 2   maintenance-planner    Stage 10  sum-orchestrator
#   Stage 3   readiness-check        Stage 11  code-deployer
#   Stage 4   simplification-check   Stage 13  config-applier
#   Stage 6   data-hygiene           Stage 14  role-provisioner
#   Stage 7   data-migrator          Stage 15  integration-activator
#   Stage 8   config-replicator      Stage 16  migration-validator
#   Stage 17  test-generator
#   Aux:      rollback-manager, integration-mapper,
#             migration-completeness-analyzer
###############################################################################

locals {
  app_name = "migrate4hana-func-${var.environment}"
  default_tags = merge(var.tags, {
    Component   = "MigrationEngine"
    Environment = var.environment
  })
}

# ── Application Insights ────────────────────────────────────────────────────
resource "azurerm_application_insights" "functions" {
  name                = "migrate4hana-ai-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  application_type    = "web"
  tags                = local.default_tags
}

# ── Storage account for Azure Functions runtime ─────────────────────────────
resource "azurerm_storage_account" "functions" {
  name                     = "m4hfunc${var.environment}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.default_tags
}

# ── Premium Elastic Plan ────────────────────────────────────────────────────
resource "azurerm_service_plan" "functions" {
  name                = "migrate4hana-plan-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = var.sku
  tags                = local.default_tags
}

# ── Linux Function App ──────────────────────────────────────────────────────
resource "azurerm_linux_function_app" "migrate4hana" {
  name                = local.app_name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = azurerm_service_plan.functions.id

  storage_account_name       = azurerm_storage_account.functions.name
  storage_account_access_key = azurerm_storage_account.functions.primary_access_key

  virtual_network_subnet_id = var.functions_subnet_id

  identity {
    type         = "UserAssigned"
    identity_ids = [var.managed_identity_id]
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.functions.connection_string

    application_stack {
      python_version = "3.11"
    }

    vnet_route_all_enabled = true
  }

  app_settings = {
    # Runtime
    FUNCTIONS_WORKER_RUNTIME       = "python"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"

    # Storage
    STORAGE_ACCOUNT_NAME = var.storage_account_name
    STORAGE_ACCOUNT_KEY  = var.storage_account_key

    # Cosmos DB
    COSMOSDB_ENDPOINT = var.cosmosdb_endpoint
    COSMOSDB_KEY      = var.cosmosdb_key

    # Key Vault
    KEYVAULT_URI = var.keyvault_uri

    # Real-time telemetry
    WEB_PUBSUB_CONNECTION_STRING = var.web_pubsub_connection_string

    # Anthropic Claude — key pulled from Key Vault reference
    ANTHROPIC_API_KEY = "@Microsoft.KeyVault(SecretUri=${var.anthropic_api_key_secret_uri})"

    # Air-gapped LLM — Ollama endpoint
    LOCAL_LLM_HOST  = var.local_llm_host
    LOCAL_LLM_MODEL = var.local_llm_model

    # AST → GenAI escalation threshold
    AST_CHANGE_THRESHOLD = tostring(var.ast_change_threshold)

    # Managed identity
    AZURE_CLIENT_ID = var.managed_identity_client_id

    # Monitoring
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.functions.connection_string
  }

  tags = local.default_tags
}
