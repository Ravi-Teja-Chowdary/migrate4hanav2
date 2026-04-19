locals {
  endpoints_subnet_id = var.endpoints_subnet_id != "" ? var.endpoints_subnet_id : var.subnet_id
}

resource "azurerm_cognitive_account" "openai" {
  name                  = "migrate4hana-openai-${var.environment}"
  location              = var.location
  resource_group_name   = var.resource_group_name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "migrate4hana-${var.environment}"

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = "Deny"

    virtual_network_rules {
      subnet_id = var.subnet_id
    }
  }

  tags = var.tags
}

resource "azurerm_cognitive_deployment" "model" {
  name                 = var.model_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "Standard"
    capacity = var.tokens_per_minute_capacity
  }
}

resource "azurerm_role_assignment" "openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = var.managed_identity_principal_id
}

resource "azurerm_private_endpoint" "openai" {
  name                = "migrate4hana-openai-pe-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = local.endpoints_subnet_id

  private_service_connection {
    name                           = "openai-psc"
    private_connection_resource_id = azurerm_cognitive_account.openai.id
    is_manual_connection           = false
    subresource_names              = ["account"]
  }

  tags = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "openai" {
  name                       = "migrate4hana-openai-diag-${var.environment}"
  target_resource_id         = azurerm_cognitive_account.openai.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}
