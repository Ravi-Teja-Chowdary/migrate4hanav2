###############################################################################
# Durable Functions Module — Outputs
###############################################################################

output "orchestrator_id" {
  value       = azurerm_linux_function_app.orchestrator.id
  description = "Resource ID of the orchestrator function app"
}

output "orchestrator_name" {
  value       = azurerm_linux_function_app.orchestrator.name
  description = "Name of the orchestrator function app"
}

output "orchestrator_url" {
  value       = "https://${azurerm_linux_function_app.orchestrator.default_hostname}"
  description = "Default HTTPS URL of the orchestrator function app"
}

output "orchestrator_default_hostname" {
  value       = azurerm_linux_function_app.orchestrator.default_hostname
  description = "Default hostname of the orchestrator function app"
}

output "orchestrator_function_key" {
  value       = azurerm_linux_function_app.orchestrator.default_hostname
  sensitive   = true
  description = "Default host key — use azurerm_function_app_host_keys data source for the actual key"
}

output "storage_account_name" {
  value       = azurerm_storage_account.orchestrator.name
  description = "Name of the orchestrator's backing storage account"
}

output "service_plan_id" {
  value       = local.effective_plan_id
  description = "Resource ID of the service plan used by the orchestrator"
}
