output "hostname" {
  description = "Web PubSub service hostname"
  value       = azurerm_web_pubsub.this.hostname
}

output "connection_string" {
  description = "Web PubSub primary connection string"
  value       = azurerm_web_pubsub.this.primary_connection_string
  sensitive   = true
}

output "primary_access_key" {
  description = "Web PubSub primary access key"
  value       = azurerm_web_pubsub.this.primary_access_key
  sensitive   = true
}

output "hub_name" {
  description = "Name of the telemetry hub"
  value       = azurerm_web_pubsub_hub.telemetry.name
}
