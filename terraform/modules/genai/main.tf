# ──────────────────────────────────────────────────────────────
# GenAI module — stores Anthropic API key in Key Vault
# ──────────────────────────────────────────────────────────────

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "anthropic-api-key"
  value        = var.anthropic_api_key
  key_vault_id = var.keyvault_id
}
