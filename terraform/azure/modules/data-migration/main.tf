###############################################################################
# Data Migration Module — Azure Data Factory replacing AWS DMS
# Full-load + CDC pipeline for SAP ECC → S/4HANA migration
###############################################################################

locals {
  default_tags = merge(var.tags, {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Module      = "data-migration"
  })
}

# -----------------------------------------------------------------------------
# Data Factory — managed VNet enabled
# -----------------------------------------------------------------------------
resource "azurerm_data_factory" "migrate4hana" {
  name                            = var.data_factory_name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  managed_virtual_network_enabled = true
  public_network_enabled          = false

  identity {
    type = "SystemAssigned"
  }

  tags = local.default_tags
}

# -----------------------------------------------------------------------------
# Key Vault Access — grant ADF identity read access to secrets
# -----------------------------------------------------------------------------
resource "azurerm_key_vault_access_policy" "adf" {
  key_vault_id = var.keyvault_id
  tenant_id    = azurerm_data_factory.migrate4hana.identity[0].tenant_id
  object_id    = azurerm_data_factory.migrate4hana.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}

# -----------------------------------------------------------------------------
# Integration Runtime — Azure managed, General purpose, 8 cores
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_integration_runtime_azure" "managed" {
  name                    = "managed-ir"
  data_factory_id         = azurerm_data_factory.migrate4hana.id
  location                = var.location
  compute_type            = "General"
  core_count              = 8
  virtual_network_enabled = true
}

# -----------------------------------------------------------------------------
# Managed Private Endpoint — SAP HANA target
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_managed_private_endpoint" "sap_hana" {
  name               = "sap-hana-mpe"
  data_factory_id    = azurerm_data_factory.migrate4hana.id
  target_resource_id = var.keyvault_id
  subresource_name   = "vault"
}

# -----------------------------------------------------------------------------
# Linked Service: Key Vault (for credential retrieval)
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_linked_service_key_vault" "keyvault" {
  name            = "ls-keyvault"
  data_factory_id = azurerm_data_factory.migrate4hana.id
  key_vault_id    = var.keyvault_id
}

# -----------------------------------------------------------------------------
# Linked Service: ECC Source (Oracle via ODBC)
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_linked_service_odbc" "ecc_source" {
  name            = "ls-ecc-oracle-source"
  data_factory_id = azurerm_data_factory.migrate4hana.id

  connection_string = "Driver={Oracle ODBC};Server=${var.ecc_db_host}:${var.ecc_db_port}/${var.ecc_db_name};"

  key_vault_password {
    linked_service_name = azurerm_data_factory_linked_service_key_vault.keyvault.name
    secret_name         = "ecc-db-password"
  }

  integration_runtime_name = azurerm_data_factory_integration_runtime_azure.managed.name
}

# -----------------------------------------------------------------------------
# Linked Service: S/4HANA Target (HANA via ODBC)
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_linked_service_odbc" "s4hana_target" {
  name            = "ls-s4hana-target"
  data_factory_id = azurerm_data_factory.migrate4hana.id

  connection_string = "Driver={HDBODBC};ServerNode=${var.s4_db_host}:${var.s4_db_port};DatabaseName=${var.s4_db_name};"

  key_vault_password {
    linked_service_name = azurerm_data_factory_linked_service_key_vault.keyvault.name
    secret_name         = "s4hana-db-password"
  }

  integration_runtime_name = azurerm_data_factory_integration_runtime_azure.managed.name
}

# -----------------------------------------------------------------------------
# Pipeline: sap-migration — Full-load + CDC with retry
# -----------------------------------------------------------------------------
resource "azurerm_data_factory_pipeline" "sap_migration" {
  name            = "sap-migration"
  data_factory_id = azurerm_data_factory.migrate4hana.id

  activities_json = jsonencode([
    {
      name = "CopyEccToHana"
      type = "Copy"
      policy = {
        retry                  = 5
        retryIntervalInSeconds = 30
        timeout                = "7.00:00:00"
        secureOutput           = false
        secureInput            = false
      }
      typeProperties = {
        source = {
          type = "OdbcSource"
          query = "SELECT * FROM SAP_MIGRATION_VIEW"
        }
        sink = {
          type         = "OdbcSink"
          writeBatchSize = 10000
          preCopyScript  = ""
        }
        enableStaging    = false
        parallelCopies   = 8
        dataIntegrationUnits = 8
      }
      linkedServiceName = {
        referenceName = azurerm_data_factory_linked_service_odbc.ecc_source.name
        type          = "LinkedServiceReference"
      }
      inputs  = []
      outputs = []
    },
    {
      name      = "CDCDeltaSync"
      type      = "Copy"
      dependsOn = [
        {
          activity             = "CopyEccToHana"
          dependencyConditions = ["Succeeded"]
        }
      ]
      policy = {
        retry                  = 5
        retryIntervalInSeconds = 60
        timeout                = "7.00:00:00"
        secureOutput           = false
        secureInput            = false
      }
      typeProperties = {
        source = {
          type = "OdbcSource"
          query = "SELECT * FROM SAP_CDC_CHANGE_LOG WHERE change_timestamp > '@{pipeline().parameters.lastCdcTimestamp}'"
        }
        sink = {
          type           = "OdbcSink"
          writeBatchSize = 5000
        }
        enableStaging    = false
        parallelCopies   = 8
        dataIntegrationUnits = 8
      }
      linkedServiceName = {
        referenceName = azurerm_data_factory_linked_service_odbc.ecc_source.name
        type          = "LinkedServiceReference"
      }
      inputs  = []
      outputs = []
    }
  ])

  parameters = {
    lastCdcTimestamp = "1970-01-01T00:00:00Z"
  }
}
