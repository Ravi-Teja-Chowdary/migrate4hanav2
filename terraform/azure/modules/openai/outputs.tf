output "endpoint" {
  description = "Azure OpenAI endpoint URL"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "deployment_name" {
  description = "Name of the deployed OpenAI model"
  value       = azurerm_cognitive_deployment.model.name
}

output "account_id" {
  description = "Azure OpenAI Cognitive Account resource ID"
  value       = azurerm_cognitive_account.openai.id
}
