###############################################################################
# Container Apps Module — Azure Container Apps for Heavy Migration Stages
#
# Replaces AWS ECS Fargate for tasks that exceed Function timeout/memory:
#   1. discovery-engine     (Stage 1 — full SAP system scan)
#   2. code-analyzer        (Stage 5 — GenAI code analysis)
#   3. data-loader          (Stage 12 — parallel data migration streams)
#   4. data-loader-reconcile (Stage 12A — post-load reconciliation)
###############################################################################

locals {
  default_tags = merge(var.tags, {
    Component   = "MigrationEngine-Heavy"
    Environment = var.environment
  })

  container_apps = {
    "discovery-engine" = {
      stage_target = "discovery"
      min_replicas = 0
      max_replicas = 1
    }
    "code-analyzer" = {
      stage_target = "code-analysis"
      min_replicas = 0
      max_replicas = 1
    }
    "data-loader" = {
      stage_target = "data-load"
      min_replicas = 0
      max_replicas = 4
    }
    "data-loader-reconcile" = {
      stage_target = "data-reconcile"
      min_replicas = 0
      max_replicas = 1
    }
  }
}

# ── Azure Container Registry ───────────────────────────────────────────────
resource "azurerm_container_registry" "migrate4hana" {
  name                = "m4hacr${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = local.default_tags
}

# ── Log Analytics Workspace ────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "containers" {
  name                = "migrate4hana-ca-logs-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.default_tags
}

# ── Container App Environment ──────────────────────────────────────────────
resource "azurerm_container_app_environment" "migrate4hana" {
  name                           = "migrate4hana-cae-${var.environment}"
  location                       = var.location
  resource_group_name            = var.resource_group_name
  infrastructure_subnet_id       = var.containers_subnet_id
  internal_load_balancer_enabled = true
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.containers.id
  tags                           = local.default_tags
}

# ── Container Apps (one per heavy stage) ───────────────────────────────────
resource "azurerm_container_app" "workers" {
  for_each = local.container_apps

  name                         = "m4h-${each.key}-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.migrate4hana.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  tags                         = local.default_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.managed_identity_id]
  }

  registry {
    server   = azurerm_container_registry.migrate4hana.login_server
    identity = var.managed_identity_id
  }

  ingress {
    external_enabled = false
    target_port      = 8080

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = each.value.min_replicas
    max_replicas = each.value.max_replicas

    container {
      name   = each.key
      image  = "${azurerm_container_registry.migrate4hana.login_server}/migrate4hana/worker:${var.image_tag}"
      cpu    = 4.0
      memory = "16Gi"

      env {
        name  = "STAGE_TARGET"
        value = each.value.stage_target
      }
      env {
        name  = "KEYVAULT_URI"
        value = var.keyvault_uri
      }
      env {
        name  = "STORAGE_ACCOUNT_NAME"
        value = var.storage_account_name
      }
      env {
        name  = "COSMOSDB_ENDPOINT"
        value = var.cosmosdb_endpoint
      }
      env {
        name  = "WEB_PUBSUB_CONNECTION_STRING"
        value = var.web_pubsub_connection_string
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = var.managed_identity_client_id
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
    }
  }
}
