resource "azurerm_cdn_frontdoor_profile" "this" {
  count               = var.enable_waf ? 1 : 0
  name                = "migrate4hana-fd-${var.environment}"
  resource_group_name = var.resource_group_name
  sku_name            = "Premium_AzureFrontDoor"

  tags = var.tags
}

resource "azurerm_cdn_frontdoor_firewall_policy" "this" {
  count                             = var.enable_waf ? 1 : 0
  name                              = "migrate4hanawaf${var.environment}"
  resource_group_name               = var.resource_group_name
  sku_name                          = azurerm_cdn_frontdoor_profile.this[0].sku_name
  enabled                           = true
  mode                              = "Prevention"

  managed_rule {
    type    = "Microsoft_DefaultRuleSet"
    version = "2.1"
    action  = "Block"
  }

  managed_rule {
    type    = "Microsoft_BotManagerRuleSet"
    version = "1.0"
    action  = "Block"
  }

  custom_rule {
    name     = "RateLimit"
    enabled  = true
    type     = "RateLimitRule"
    action   = "Block"
    priority = 100

    rate_limit_threshold          = 1000
    rate_limit_duration_in_minutes = 5

    match_condition {
      match_variable = "RemoteAddr"
      operator       = "IPMatch"
      negation_condition = true
      match_values   = ["0.0.0.0/0"]
    }
  }

  custom_rule {
    name     = "BlockSQLi"
    enabled  = true
    type     = "MatchRule"
    action   = "Block"
    priority = 200

    match_condition {
      match_variable = "QueryString"
      operator       = "Contains"
      transforms     = ["UrlDecode"]
      match_values   = ["SELECT", "UNION", "DROP", "INSERT", "--", "1=1"]
    }
  }

  tags = var.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  count                    = var.enable_waf ? 1 : 0
  name                     = "migrate4hana-ep-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this[0].id

  tags = var.tags
}

resource "azurerm_cdn_frontdoor_origin_group" "this" {
  count                    = var.enable_waf ? 1 : 0
  name                     = "migrate4hana-origin-group-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this[0].id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    path                = "/health"
    protocol            = "Https"
    interval_in_seconds = 30
    request_type        = "HEAD"
  }
}

resource "azurerm_cdn_frontdoor_origin" "this" {
  count                          = var.enable_waf ? 1 : 0
  name                           = "migrate4hana-origin-${var.environment}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.this[0].id
  enabled                        = true

  host_name          = var.backend_host
  origin_host_header = var.backend_host
  http_port          = 80
  https_port         = 443
  priority           = 1
  weight             = 1000

  certificate_name_check_enabled = true
}

resource "azurerm_cdn_frontdoor_route" "this" {
  count                         = var.enable_waf ? 1 : 0
  name                          = "migrate4hana-route-${var.environment}"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.this[0].id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.this[0].id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.this[0].id]

  supported_protocols    = ["Http", "Https"]
  patterns_to_match      = ["/*"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = true
  link_to_default_domain = true
}

resource "azurerm_cdn_frontdoor_security_policy" "this" {
  count                    = var.enable_waf ? 1 : 0
  name                     = "migrate4hana-secpol-${var.environment}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this[0].id

  security_policies {
    firewall {
      cdn_frontdoor_firewall_policy_id = azurerm_cdn_frontdoor_firewall_policy.this[0].id

      association {
        domain {
          cdn_frontdoor_domain_id = azurerm_cdn_frontdoor_endpoint.this[0].id
        }

        patterns_to_match = ["/*"]
      }
    }
  }
}
