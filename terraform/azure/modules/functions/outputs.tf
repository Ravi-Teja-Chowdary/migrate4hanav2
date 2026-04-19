###############################################################################
# Functions Module — Outputs
###############################################################################

output "function_app_id" {
  value       = azurerm_linux_function_app.migrate4hana.id
  description = "Resource ID of the function app"
}

output "function_app_name" {
  value       = azurerm_linux_function_app.migrate4hana.name
  description = "Name of the function app"
}

output "function_app_url" {
  value       = "https://${azurerm_linux_function_app.migrate4hana.default_hostname}"
  description = "Default HTTPS URL of the function app"
}

output "function_app_default_hostname" {
  value       = azurerm_linux_function_app.migrate4hana.default_hostname
  description = "Default hostname of the function app"
}

output "service_plan_id" {
  value       = azurerm_service_plan.functions.id
  description = "Resource ID of the App Service Plan (can be shared with durable-functions)"
}

output "application_insights_connection_string" {
  value       = azurerm_application_insights.functions.connection_string
  sensitive   = true
  description = "Application Insights connection string"
}

output "application_insights_instrumentation_key" {
  value       = azurerm_application_insights.functions.instrumentation_key
  sensitive   = true
  description = "Application Insights instrumentation key"
}

output "storage_account_name" {
  value       = azurerm_storage_account.functions.name
  description = "Name of the function app's backing storage account"
}
