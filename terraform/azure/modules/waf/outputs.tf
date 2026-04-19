output "frontend_endpoint" {
  description = "Azure Front Door endpoint hostname"
  value       = var.enable_waf ? azurerm_cdn_frontdoor_endpoint.this[0].host_name : ""
}

output "waf_policy_id" {
  description = "WAF policy resource ID"
  value       = var.enable_waf ? azurerm_cdn_frontdoor_firewall_policy.this[0].id : ""
}
