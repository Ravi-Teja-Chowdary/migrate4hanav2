###############################################################################
# APIM Module — Outputs
###############################################################################

output "apim_id" {
  value       = azurerm_api_management.migrate4hana.id
  description = "Resource ID of the API Management instance"
}

output "apim_name" {
  value       = azurerm_api_management.migrate4hana.name
  description = "Name of the API Management instance"
}

output "gateway_url" {
  value       = azurerm_api_management.migrate4hana.gateway_url
  description = "Gateway URL for the API Management instance"
}

output "api_id" {
  value       = azurerm_api_management_api.migrate4hana.id
  description = "Resource ID of the Migrate4HANA API"
}

output "developer_portal_url" {
  value       = azurerm_api_management.migrate4hana.developer_portal_url
  description = "Developer portal URL"
}
