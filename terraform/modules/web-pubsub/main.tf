resource "azurerm_web_pubsub" "this" {
  name                = "migrate4hana-pubsub-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.sku
  capacity            = 1

  public_network_access_enabled = true

  live_trace {
    enabled                   = true
    messaging_logs_enabled    = true
    connectivity_logs_enabled = true
  }

  tags = var.tags
}

resource "azurerm_web_pubsub_hub" "telemetry" {
  name          = "telemetry"
  web_pubsub_id = azurerm_web_pubsub.this.id

  event_handler {
    url_template       = var.function_app_url
    system_events      = ["connect", "disconnected"]
    user_event_pattern = "*"
  }

  anonymous_connections_enabled = false
}

resource "azurerm_role_assignment" "pubsub_owner" {
  scope                = azurerm_web_pubsub.this.id
  role_definition_name = "Web PubSub Service Owner"
  principal_id         = var.managed_identity_principal_id
}
