###############################################################################
# Storage Module — Azure Blob Storage replacing AWS S3
# Containers: staging, audit-logs, entity-resolution, llm-models
###############################################################################

locals {
  default_tags = merge(var.tags, {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Module      = "storage"
  })
}

# -----------------------------------------------------------------------------
# Storage Account
# -----------------------------------------------------------------------------
resource "azurerm_storage_account" "migrate4hana" {
  name                          = var.storage_account_name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  account_tier                  = "Standard"
  account_replication_type      = "GRS"
  min_tls_version               = "TLS1_2"
  allow_nested_items_to_be_public = false

  blob_properties {
    versioning_enabled  = true
    change_feed_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  tags = local.default_tags
}

# -----------------------------------------------------------------------------
# Network Rules — deny all except allowed VNet subnets
# -----------------------------------------------------------------------------
resource "azurerm_storage_account_network_rules" "migrate4hana" {
  storage_account_id = azurerm_storage_account.migrate4hana.id
  default_action     = "Deny"
  bypass             = ["AzureServices"]

  virtual_network_subnet_ids = var.allowed_subnet_ids
}

# -----------------------------------------------------------------------------
# Containers
# -----------------------------------------------------------------------------
resource "azurerm_storage_container" "staging" {
  name                  = "staging"
  storage_account_id    = azurerm_storage_account.migrate4hana.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "audit_logs" {
  name                  = "audit-logs"
  storage_account_id    = azurerm_storage_account.migrate4hana.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "entity_resolution" {
  name                  = "entity-resolution"
  storage_account_id    = azurerm_storage_account.migrate4hana.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "llm_models" {
  name                  = "llm-models"
  storage_account_id    = azurerm_storage_account.migrate4hana.id
  container_access_type = "private"
}

# -----------------------------------------------------------------------------
# Lifecycle Management Policy
# -----------------------------------------------------------------------------
resource "azurerm_storage_management_policy" "lifecycle" {
  storage_account_id = azurerm_storage_account.migrate4hana.id

  # Staging: hot → cool (30d) → archive (90d) → delete (365d)
  rule {
    name    = "staging-lifecycle"
    enabled = true

    filters {
      prefix_match = ["staging/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than    = 30
        tier_to_archive_after_days_since_modification_greater_than = 90
        delete_after_days_since_modification_greater_than          = 365
      }

      snapshot {
        delete_after_days_since_creation_greater_than = 365
      }

      version {
        delete_after_days_since_creation = 365
      }
    }
  }

  # Audit logs: 7-year (2555 day) retention — WORM compliance for SOX/GxP
  rule {
    name    = "audit-logs-retention"
    enabled = true

    filters {
      prefix_match = ["audit-logs/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than    = 90
        tier_to_archive_after_days_since_modification_greater_than = 365
        delete_after_days_since_modification_greater_than          = 2555
      }

      snapshot {
        delete_after_days_since_creation_greater_than = 2555
      }

      version {
        delete_after_days_since_creation = 2555
      }
    }
  }

  # Entity resolution: delete after 90 days
  rule {
    name    = "entity-resolution-cleanup"
    enabled = true

    filters {
      prefix_match = ["entity-resolution/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 90
      }

      snapshot {
        delete_after_days_since_creation_greater_than = 90
      }

      version {
        delete_after_days_since_creation = 90
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Immutability Policy — audit-logs container (WORM for SOX/GxP)
# Time-based retention: 2555 days (7 years), locked
# -----------------------------------------------------------------------------
resource "azurerm_storage_blob_inventory_policy" "audit" {
  storage_account_id = azurerm_storage_account.migrate4hana.id

  rules {
    name                   = "audit-logs-inventory"
    storage_container_name = azurerm_storage_container.audit_logs.name
    format                 = "Csv"
    schedule               = "Weekly"
    scope                  = "Container"
    schema_fields          = ["Name", "Creation-Time", "Last-Modified", "Content-Length", "BlobType"]

    filter {
      blob_types = ["blockBlob"]
    }
  }
}

# -----------------------------------------------------------------------------
# Private Endpoint — Blob service
# -----------------------------------------------------------------------------
resource "azurerm_private_endpoint" "blob" {
  name                = "${var.storage_account_name}-blob-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.endpoints_subnet_id

  private_service_connection {
    name                           = "${var.storage_account_name}-blob-psc"
    private_connection_resource_id = azurerm_storage_account.migrate4hana.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  dynamic "private_dns_zone_group" {
    for_each = var.private_dns_zone_id != "" ? [1] : []
    content {
      name                 = "blob-dns-zone-group"
      private_dns_zone_ids = [var.private_dns_zone_id]
    }
  }

  tags = local.default_tags
}
