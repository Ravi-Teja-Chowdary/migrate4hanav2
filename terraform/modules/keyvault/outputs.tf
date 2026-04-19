# ──────────────────────────────────────────────────────────────
# Key Vault module — outputs
# ──────────────────────────────────────────────────────────────

output "vault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

output "vault_id" {
  description = "Resource ID of the Key Vault"
  value       = azurerm_key_vault.main.id
}

output "managed_identity_id" {
  description = "Resource ID of the user-assigned managed identity"
  value       = azurerm_user_assigned_identity.migrate4hana.id
}

output "managed_identity_principal_id" {
  description = "Principal (object) ID of the managed identity"
  value       = azurerm_user_assigned_identity.migrate4hana.principal_id
}

output "managed_identity_client_id" {
  description = "Client ID of the managed identity"
  value       = azurerm_user_assigned_identity.migrate4hana.client_id
}
