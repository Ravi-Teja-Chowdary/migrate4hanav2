output "private_ip_address" {
  description = "Private IP address of the GPU VM (LOCAL_LLM_ENDPOINT for genai_router)"
  value       = var.enable ? azurerm_network_interface.gpu[0].private_ip_address : ""
}
