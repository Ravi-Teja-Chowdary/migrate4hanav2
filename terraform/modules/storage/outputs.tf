###############################################################################
# Storage Module — Outputs
###############################################################################

output "storage_account_id" {
  description = "Resource ID of the storage account"
  value       = azurerm_storage_account.migrate4hana.id
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.migrate4hana.name
}

output "primary_blob_endpoint" {
  description = "Primary blob service endpoint URL"
  value       = azurerm_storage_account.migrate4hana.primary_blob_endpoint
}

output "primary_access_key" {
  description = "Primary access key for the storage account"
  value       = azurerm_storage_account.migrate4hana.primary_access_key
  sensitive   = true
}

output "primary_connection_string" {
  description = "Primary connection string for the storage account"
  value       = azurerm_storage_account.migrate4hana.primary_connection_string
  sensitive   = true
}

output "staging_container_name" {
  description = "Name of the staging container"
  value       = azurerm_storage_container.staging.name
}

output "audit_logs_container_name" {
  description = "Name of the audit-logs container"
  value       = azurerm_storage_container.audit_logs.name
}

output "entity_resolution_container_name" {
  description = "Name of the entity-resolution container"
  value       = azurerm_storage_container.entity_resolution.name
}

output "llm_models_container_name" {
  description = "Name of the llm-models container"
  value       = azurerm_storage_container.llm_models.name
}

output "private_endpoint_ip" {
  description = "Private IP address of the blob private endpoint"
  value       = azurerm_private_endpoint.blob.private_service_connection[0].private_ip_address
}
