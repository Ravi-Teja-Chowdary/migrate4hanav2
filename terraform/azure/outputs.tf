# ──────────────────────────────────────────────────────────────
# Migrate4HANA — root outputs
# ──────────────────────────────────────────────────────────────

output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "vnet_id" {
  description = "Resource ID of the Migrate4HANA VNet"
  value       = module.vnet.vnet_id
}

output "function_app_url" {
  description = "URL of the Azure Functions app"
  value       = module.functions.function_app_url
}

output "container_app_urls" {
  description = "URLs of deployed Container Apps"
  value       = module.container_apps.container_app_urls
}

output "cosmosdb_endpoint" {
  description = "Cosmos DB account endpoint"
  value       = module.cosmosdb.cosmosdb_endpoint
}

output "storage_account_name" {
  description = "Name of the shared storage account"
  value       = module.storage.storage_account_name
}

output "keyvault_uri" {
  description = "URI of the Key Vault"
  value       = module.keyvault.vault_uri
}

output "web_pubsub_hostname" {
  description = "Azure Web PubSub hostname"
  value       = module.web_pubsub.hostname
}

output "apim_gateway_url" {
  description = "API Management gateway URL"
  value       = module.apim.gateway_url
}

output "openai_endpoint" {
  description = "Azure OpenAI service endpoint"
  value       = module.openai.endpoint
}

output "gpu_vm_private_ip" {
  description = "Private IP of the GPU VM (empty when GPU is disabled)"
  value       = var.enable_gpu_vm ? module.gpu_vm[0].private_ip_address : ""
}

output "orchestrator_url" {
  description = "Durable Functions orchestrator URL"
  value       = module.durable_functions.orchestrator_url
}

output "data_factory_name" {
  description = "Azure Data Factory name"
  value       = module.data_migration.data_factory_name
}

output "waf_frontend_endpoint" {
  description = "WAF frontend endpoint (empty when WAF is disabled)"
  value       = var.enable_waf ? module.waf[0].frontend_endpoint : ""
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID for diagnostics"
  value       = module.audit.log_analytics_workspace_id
}

output "managed_identity_client_id" {
  description = "Client ID of the User-Assigned Managed Identity"
  value       = module.keyvault.managed_identity_client_id
}
