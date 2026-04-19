###############################################################################
# Data Migration Module — Outputs
###############################################################################

output "data_factory_id" {
  description = "Resource ID of the Azure Data Factory"
  value       = azurerm_data_factory.migrate4hana.id
}

output "data_factory_name" {
  description = "Name of the Azure Data Factory"
  value       = azurerm_data_factory.migrate4hana.name
}

output "data_factory_identity_principal_id" {
  description = "Principal ID of the Data Factory managed identity"
  value       = azurerm_data_factory.migrate4hana.identity[0].principal_id
}

output "data_factory_identity_tenant_id" {
  description = "Tenant ID of the Data Factory managed identity"
  value       = azurerm_data_factory.migrate4hana.identity[0].tenant_id
}

output "integration_runtime_name" {
  description = "Name of the managed integration runtime"
  value       = azurerm_data_factory_integration_runtime_azure.managed.name
}

output "pipeline_name" {
  description = "Name of the SAP migration pipeline"
  value       = azurerm_data_factory_pipeline.sap_migration.name
}

output "ecc_linked_service_name" {
  description = "Name of the ECC source linked service"
  value       = azurerm_data_factory_linked_service_odbc.ecc_source.name
}

output "s4hana_linked_service_name" {
  description = "Name of the S/4HANA target linked service"
  value       = azurerm_data_factory_linked_service_odbc.s4hana_target.name
}
