###############################################################################
# CosmosDB Module — Azure Cosmos DB replacing DynamoDB
# Containers: simplification-rules, ws-connections, idempotency
###############################################################################

locals {
  default_tags = merge(var.tags, {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Module      = "cosmosdb"
  })
}

# -----------------------------------------------------------------------------
# Cosmos DB Account — Serverless (pay-per-request), Session consistency
# -----------------------------------------------------------------------------
resource "azurerm_cosmosdb_account" "migrate4hana" {
  name                = var.cosmosdb_account_name
  location            = var.location
  resource_group_name = var.resource_group_name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  automatic_failover_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }

  tags = local.default_tags
}

# -----------------------------------------------------------------------------
# SQL Database
# -----------------------------------------------------------------------------
resource "azurerm_cosmosdb_sql_database" "migrate4hana" {
  name                = "migrate4hana"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.migrate4hana.name
}

# -----------------------------------------------------------------------------
# Container: simplification-rules
# Stores SAP S/4HANA simplification rules
# Partition key: /category, unique key: /rule_id
# -----------------------------------------------------------------------------
resource "azurerm_cosmosdb_sql_container" "simplification_rules" {
  name                = "simplification-rules"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.migrate4hana.name
  database_name       = azurerm_cosmosdb_sql_database.migrate4hana.name
  partition_key_paths = ["/category"]

  unique_key {
    paths = ["/rule_id"]
  }

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }
  }
}

# -----------------------------------------------------------------------------
# Container: ws-connections
# Web PubSub connection tracking — 24h TTL
# Partition key: /connectionId
# -----------------------------------------------------------------------------
resource "azurerm_cosmosdb_sql_container" "ws_connections" {
  name                = "ws-connections"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.migrate4hana.name
  database_name       = azurerm_cosmosdb_sql_database.migrate4hana.name
  partition_key_paths = ["/connectionId"]
  default_ttl         = 86400 # 24 hours

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }
  }
}

# -----------------------------------------------------------------------------
# Container: idempotency
# Data-loader retry deduplication — 7d TTL
# Partition key: /pk, unique key: /sk
# -----------------------------------------------------------------------------
resource "azurerm_cosmosdb_sql_container" "idempotency" {
  name                = "idempotency"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.migrate4hana.name
  database_name       = azurerm_cosmosdb_sql_database.migrate4hana.name
  partition_key_paths = ["/pk"]
  default_ttl         = 604800 # 7 days

  unique_key {
    paths = ["/sk"]
  }

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }
  }
}

# -----------------------------------------------------------------------------
# Private Endpoint
# -----------------------------------------------------------------------------
resource "azurerm_private_endpoint" "cosmosdb" {
  name                = "${var.cosmosdb_account_name}-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.endpoints_subnet_id

  private_service_connection {
    name                           = "${var.cosmosdb_account_name}-psc"
    private_connection_resource_id = azurerm_cosmosdb_account.migrate4hana.id
    subresource_names              = ["Sql"]
    is_manual_connection           = false
  }

  tags = local.default_tags
}

# -----------------------------------------------------------------------------
# Diagnostic Settings → Log Analytics
# -----------------------------------------------------------------------------
resource "azurerm_monitor_diagnostic_setting" "cosmosdb" {
  name                       = "${var.cosmosdb_account_name}-diag"
  target_resource_id         = azurerm_cosmosdb_account.migrate4hana.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "DataPlaneRequests"
  }

  enabled_log {
    category = "QueryRuntimeStatistics"
  }

  enabled_log {
    category = "PartitionKeyStatistics"
  }

  enabled_log {
    category = "PartitionKeyRUConsumption"
  }

  metric {
    category = "Requests"
    enabled  = true
  }
}
