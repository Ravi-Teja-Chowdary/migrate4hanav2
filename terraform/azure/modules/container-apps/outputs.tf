###############################################################################
# Container Apps Module — Outputs
###############################################################################

output "environment_id" {
  value       = azurerm_container_app_environment.migrate4hana.id
  description = "Resource ID of the Container App Environment"
}

output "environment_default_domain" {
  value       = azurerm_container_app_environment.migrate4hana.default_domain
  description = "Default domain of the Container App Environment"
}

output "container_app_urls" {
  value = {
    for k, app in azurerm_container_app.workers :
    k => "https://${app.ingress[0].fqdn}"
  }
  description = "Map of container app name to internal FQDN URL"
}

output "container_app_ids" {
  value = {
    for k, app in azurerm_container_app.workers :
    k => app.id
  }
  description = "Map of container app name to resource ID"
}

output "acr_login_server" {
  value       = azurerm_container_registry.migrate4hana.login_server
  description = "Login server URL for the Azure Container Registry"
}

output "acr_id" {
  value       = azurerm_container_registry.migrate4hana.id
  description = "Resource ID of the Azure Container Registry"
}

output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.containers.id
  description = "Resource ID of the Log Analytics workspace"
}
