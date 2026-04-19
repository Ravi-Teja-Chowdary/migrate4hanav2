output "secret_id" {
  description = "Versioned URI of the Anthropic API key secret in Key Vault"
  value       = azurerm_key_vault_secret.anthropic_api_key.id
}

output "secret_name" {
  description = "Name of the Anthropic API key secret in Key Vault"
  value       = azurerm_key_vault_secret.anthropic_api_key.name
}
