# ──────────────────────────────────────────────────────────────
# VNet module — outputs
# ──────────────────────────────────────────────────────────────

output "vnet_id" {
  description = "Resource ID of the VNet"
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "Name of the VNet"
  value       = azurerm_virtual_network.main.name
}

output "subnet_ids" {
  description = "Map of subnet name → resource ID"
  value = {
    functions  = azurerm_subnet.functions.id
    containers = azurerm_subnet.containers.id
    gpu        = azurerm_subnet.gpu.id
    sap        = azurerm_subnet.sap.id
    endpoints  = azurerm_subnet.endpoints.id
  }
}

output "functions_subnet_id" {
  description = "Resource ID of the functions subnet"
  value       = azurerm_subnet.functions.id
}

output "containers_subnet_id" {
  description = "Resource ID of the containers subnet"
  value       = azurerm_subnet.containers.id
}

output "gpu_subnet_id" {
  description = "Resource ID of the GPU subnet"
  value       = azurerm_subnet.gpu.id
}

output "sap_subnet_id" {
  description = "Resource ID of the SAP subnet"
  value       = azurerm_subnet.sap.id
}

output "endpoints_subnet_id" {
  description = "Resource ID of the endpoints subnet"
  value       = azurerm_subnet.endpoints.id
}
