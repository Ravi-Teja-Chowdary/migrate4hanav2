###############################################################################
# CosmosDB Module — Outputs
###############################################################################

output "cosmosdb_account_id" {
  description = "Resource ID of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.id
}

output "cosmosdb_account_name" {
  description = "Name of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.name
}

output "cosmosdb_endpoint" {
  description = "Endpoint URL of the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.endpoint
}

output "cosmosdb_primary_key" {
  description = "Primary master key for the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.primary_key
  sensitive   = true
}

output "cosmosdb_primary_readonly_key" {
  description = "Primary read-only key for the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.primary_readonly_key
  sensitive   = true
}

output "cosmosdb_connection_strings" {
  description = "Connection strings for the Cosmos DB account"
  value       = azurerm_cosmosdb_account.migrate4hana.connection_strings
  sensitive   = true
}

output "database_name" {
  description = "Name of the SQL database"
  value       = azurerm_cosmosdb_sql_database.migrate4hana.name
}

output "simplification_rules_container_name" {
  description = "Name of the simplification-rules container"
  value       = azurerm_cosmosdb_sql_container.simplification_rules.name
}

output "ws_connections_container_name" {
  description = "Name of the ws-connections container"
  value       = azurerm_cosmosdb_sql_container.ws_connections.name
}

output "idempotency_container_name" {
  description = "Name of the idempotency container"
  value       = azurerm_cosmosdb_sql_container.idempotency.name
}

output "private_endpoint_ip" {
  description = "Private IP address of the Cosmos DB private endpoint"
  value       = azurerm_private_endpoint.cosmosdb.private_service_connection[0].private_ip_address
}
