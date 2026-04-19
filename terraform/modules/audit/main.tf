data "azurerm_subscription" "current" {}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "migrate4hana-logs-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 365

  tags = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "activity_logs" {
  name                       = "migrate4hana-activity-diag-${var.environment}"
  target_resource_id         = data.azurerm_subscription.current.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  enabled_log {
    category = "Administrative"
  }

  enabled_log {
    category = "Security"
  }

  enabled_log {
    category = "Alert"
  }

  enabled_log {
    category = "Policy"
  }
}

resource "azurerm_monitor_action_group" "alerts" {
  name                = "migrate4hana-alerts-${var.environment}"
  resource_group_name = var.resource_group_name
  short_name          = "m4h-alerts"

  email_receiver {
    name          = "admin"
    email_address = var.alert_email
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "function_errors" {
  count               = var.monitored_function_app_id != "" ? 1 : 0
  name                = "migrate4hana-func-errors-${var.environment}"
  resource_group_name = var.resource_group_name
  scopes              = [var.monitored_function_app_id]
  description         = "Alert when Function App HTTP 5xx errors exceed threshold"
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Web/sites"
    metric_name      = "Http5xx"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 5
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts.id
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "function_duration" {
  count               = var.monitored_function_app_id != "" ? 1 : 0
  name                = "migrate4hana-func-duration-${var.environment}"
  resource_group_name = var.resource_group_name
  scopes              = [var.monitored_function_app_id]
  description         = "Alert when Function execution duration exceeds 15 minutes equivalent"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.Web/sites"
    metric_name      = "FunctionExecutionUnits"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 900000
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts.id
  }

  tags = var.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "unauthorized_access" {
  name                = "migrate4hana-unauth-access-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  description         = "Alert on suspicious Key Vault secret access patterns"
  severity            = 1
  enabled             = true

  scopes                    = [azurerm_log_analytics_workspace.this.id]
  evaluation_frequency      = "PT5M"
  window_duration           = "PT5M"
  target_resource_types     = ["Microsoft.OperationalInsights/workspaces"]

  criteria {
    query = <<-QUERY
      AzureActivity
      | where OperationNameValue contains "Microsoft.KeyVault/vaults/secrets"
      | summarize count() by bin(TimeGenerated, 5m)
      | where count_ > 10
    QUERY

    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.alerts.id]
  }

  tags = var.tags
}
