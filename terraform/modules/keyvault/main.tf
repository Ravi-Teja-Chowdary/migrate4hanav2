# ──────────────────────────────────────────────────────────────
# Key Vault module — resources
# ──────────────────────────────────────────────────────────────

resource "azurerm_user_assigned_identity" "migrate4hana" {
  name                = "id-migrate4hana-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_key_vault" "main" {
  name                        = "kv-m4h-${var.environment}"
  location                    = var.location
  resource_group_name         = var.resource_group_name
  tenant_id                   = var.tenant_id
  sku_name                    = "standard"
  enable_rbac_authorization   = true
  soft_delete_retention_days  = 90
  purge_protection_enabled    = true
  tags                        = var.tags
}

# Grant the managed identity "Key Vault Secrets User" on the vault
resource "azurerm_role_assignment" "kv_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.migrate4hana.principal_id
}

# ── Placeholder secrets ──────────────────────────────────────

resource "azurerm_key_vault_secret" "sap_ecc_credentials" {
  name         = "sap-ecc-credentials"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_secrets_user]
}

resource "azurerm_key_vault_secret" "s4hana_credentials" {
  name         = "s4hana-credentials"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_secrets_user]
}

resource "azurerm_key_vault_secret" "ecc_db_password" {
  name         = "ecc-db-password"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_secrets_user]
}

resource "azurerm_key_vault_secret" "s4_db_password" {
  name         = "s4-db-password"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_secrets_user]
}
