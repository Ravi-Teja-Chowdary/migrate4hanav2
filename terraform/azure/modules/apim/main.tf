###############################################################################
# APIM Module — Azure API Management for Migrate4HANA
#
# Replaces AWS API Gateway. Provides:
#   - HTTPS API surface for the migration pipeline
#   - JWT validation, rate limiting, CORS
#   - Key Vault–backed named values for secrets
###############################################################################

locals {
  default_tags = merge(var.tags, {
    Component   = "APIGateway"
    Environment = var.environment
  })

  api_operations = {
    # Pipeline endpoints
    "pipeline-assess" = {
      method       = "POST"
      url_template = "/pipeline/assess"
      display_name = "Run Assessment Pipeline"
    }
    "pipeline-convert" = {
      method       = "POST"
      url_template = "/pipeline/convert"
      display_name = "Run Conversion Pipeline"
    }
    "pipeline-complete" = {
      method       = "POST"
      url_template = "/pipeline/complete"
      display_name = "Run Post-Conversion Pipeline"
    }
    "pipeline-full" = {
      method       = "POST"
      url_template = "/pipeline/full"
      display_name = "Run Full Migration Pipeline"
    }
    "pipeline-ecc-full" = {
      method       = "POST"
      url_template = "/pipeline/ecc_full"
      display_name = "Run Full ECC Migration Pipeline"
    }

    # Connection testing
    "connections-ecc-test" = {
      method       = "POST"
      url_template = "/connections/ecc/test"
      display_name = "Test ECC Connection"
    }
    "connections-s4hana-test" = {
      method       = "POST"
      url_template = "/connections/s4hana/test"
      display_name = "Test S/4HANA Connection"
    }

    # Status / monitoring
    "status-get" = {
      method       = "GET"
      url_template = "/status"
      display_name = "Get Pipeline Status"
    }
    "progress-get" = {
      method       = "GET"
      url_template = "/progress"
      display_name = "Get Pipeline Progress"
    }
    "runs-pdf" = {
      method       = "GET"
      url_template = "/runs/{runId}/pdf"
      display_name = "Download Run PDF Report"
    }
  }
}

# ── API Management Instance ────────────────────────────────────────────────
resource "azurerm_api_management" "migrate4hana" {
  name                = "migrate4hana-apim-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  publisher_name      = var.publisher_name
  publisher_email     = var.publisher_email
  sku_name            = var.sku_name
  tags                = local.default_tags

  identity {
    type         = var.managed_identity_id != "" ? "UserAssigned" : "SystemAssigned"
    identity_ids = var.managed_identity_id != "" ? [var.managed_identity_id] : null
  }
}

# ── Named Value: Function App Host Key (Key Vault reference) ───────────────
resource "azurerm_api_management_named_value" "function_key" {
  count               = var.function_app_key_secret_uri != "" ? 1 : 0
  name                = "function-app-key"
  resource_group_name = var.resource_group_name
  api_management_name = azurerm_api_management.migrate4hana.name
  display_name        = "function-app-key"
  secret              = true

  value_from_key_vault {
    secret_id          = var.function_app_key_secret_uri
    identity_client_id = var.managed_identity_id != "" ? null : null
  }
}

# ── API Definition ─────────────────────────────────────────────────────────
resource "azurerm_api_management_api" "migrate4hana" {
  name                = "migrate4hana-api"
  resource_group_name = var.resource_group_name
  api_management_name = azurerm_api_management.migrate4hana.name
  revision            = "1"
  display_name        = "Migrate4HANA API"
  path                = "migrate4hana"
  protocols           = ["https"]
  service_url         = var.function_app_url
}

# ── API-Level Policy (JWT, rate-limit, CORS) ───────────────────────────────
resource "azurerm_api_management_api_policy" "migrate4hana" {
  api_name            = azurerm_api_management_api.migrate4hana.name
  api_management_name = azurerm_api_management.migrate4hana.name
  resource_group_name = var.resource_group_name

  xml_content = <<-XML
    <policies>
      <inbound>
        <base />
        <!-- CORS -->
        <cors allow-credentials="true">
          <allowed-origins>
            ${join("\n            ", [for o in var.allowed_origins : "<origin>${o}</origin>"])}
          </allowed-origins>
          <allowed-methods>
            <method>GET</method>
            <method>POST</method>
            <method>PUT</method>
            <method>DELETE</method>
            <method>OPTIONS</method>
          </allowed-methods>
          <allowed-headers>
            <header>*</header>
          </allowed-headers>
        </cors>
        <!-- Rate limiting -->
        <rate-limit calls="${var.rate_limit_calls}" renewal-period="${var.rate_limit_period}" />
        %{if var.jwt_openid_config_url != ""}
        <!-- JWT Validation -->
        <validate-jwt header-name="Authorization" require-scheme="Bearer"
                      failed-validation-httpcode="401"
                      failed-validation-error-message="Unauthorized">
          <openid-config url="${var.jwt_openid_config_url}" />
          %{if length(var.jwt_audiences) > 0}
          <audiences>
            ${join("\n            ", [for a in var.jwt_audiences : "<audience>${a}</audience>"])}
          </audiences>
          %{endif}
        </validate-jwt>
        %{endif}
      </inbound>
      <backend>
        <base />
      </backend>
      <outbound>
        <base />
      </outbound>
      <on-error>
        <base />
      </on-error>
    </policies>
  XML
}

# ── API Operations ─────────────────────────────────────────────────────────
resource "azurerm_api_management_api_operation" "ops" {
  for_each = local.api_operations

  operation_id        = each.key
  api_name            = azurerm_api_management_api.migrate4hana.name
  api_management_name = azurerm_api_management.migrate4hana.name
  resource_group_name = var.resource_group_name
  display_name        = each.value.display_name
  method              = each.value.method
  url_template        = each.value.url_template

  dynamic "template_parameter" {
    for_each = each.key == "runs-pdf" ? [1] : []
    content {
      name     = "runId"
      required = true
      type     = "string"
    }
  }

  response {
    status_code = 200
  }
}
