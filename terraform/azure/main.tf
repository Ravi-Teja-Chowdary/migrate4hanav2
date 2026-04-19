# ──────────────────────────────────────────────────────────────
# Migrate4HANA — Azure root module
# ──────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# ── Shared locals ─────────────────────────────────────────────

locals {
  tags = {
    project     = "migrate4hana"
    environment = var.environment
    managed_by  = "terraform"
  }
}

data "azurerm_client_config" "current" {}

# ── Resource group ────────────────────────────────────────────

resource "azurerm_resource_group" "main" {
  name     = "rg-migrate4hana-${var.environment}"
  location = var.location
  tags     = local.tags
}

# ── Modules ───────────────────────────────────────────────────

module "vnet" {
  source = "./modules/vnet"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  vnet_address_space  = var.vnet_address_space
  subnet_prefixes     = var.subnet_prefixes
  sap_rfc_cidr        = var.sap_rfc_cidr
  tags                = local.tags
}

module "keyvault" {
  source = "./modules/keyvault"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  tenant_id           = data.azurerm_client_config.current.tenant_id
  tags                = local.tags
}

# ── Audit & Monitoring (needed early — provides Log Analytics workspace) ──

module "audit" {
  source = "./modules/audit"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  alert_email         = var.alert_email
}

# ── Storage ────────────────────────────────────────────────────

module "storage" {
  source = "./modules/storage"

  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  environment          = var.environment
  storage_account_name = "stmigrate4hana${var.environment}"
  allowed_subnet_ids = [
    module.vnet.functions_subnet_id,
    module.vnet.containers_subnet_id,
  ]
  endpoints_subnet_id = module.vnet.endpoints_subnet_id
}

# ── Cosmos DB ──────────────────────────────────────────────────

module "cosmosdb" {
  source = "./modules/cosmosdb"

  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  environment              = var.environment
  cosmosdb_account_name    = "cosmos-migrate4hana-${var.environment}"
  endpoints_subnet_id      = module.vnet.endpoints_subnet_id
  log_analytics_workspace_id = module.audit.log_analytics_workspace_id
}

# ── Azure OpenAI ───────────────────────────────────────────────

module "openai" {
  source = "./modules/openai"

  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  environment                  = var.environment
  subnet_id                    = module.vnet.endpoints_subnet_id
  managed_identity_principal_id = module.keyvault.managed_identity_principal_id
  log_analytics_workspace_id   = module.audit.log_analytics_workspace_id
}

# ── GPU VM (air-gapped LLM) ───────────────────────────────────

module "gpu_vm" {
  source = "./modules/gpu-vm"
  count  = var.enable_gpu_vm ? 1 : 0

  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  environment              = var.environment
  gpu_subnet_id            = module.vnet.gpu_subnet_id
  functions_subnet_prefix  = var.subnet_prefixes.functions
  containers_subnet_prefix = var.subnet_prefixes.containers
  storage_account_name     = module.storage.storage_account_name
  managed_identity_id      = module.keyvault.managed_identity_id
  ssh_public_key           = var.ssh_public_key
}

# ── Web PubSub (telemetry — created before functions to break cycle) ──

module "web_pubsub" {
  source = "./modules/web-pubsub"

  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  environment                   = var.environment
  function_app_url              = "" # set post-deploy; hub event handler updated after functions exist
  managed_identity_principal_id = module.keyvault.managed_identity_principal_id
}

# ── Azure Functions (18 stage handlers) ───────────────────────

module "functions" {
  source = "./modules/functions"

  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  environment                  = var.environment
  functions_subnet_id          = module.vnet.functions_subnet_id
  managed_identity_id          = module.keyvault.managed_identity_id
  managed_identity_client_id   = module.keyvault.managed_identity_client_id
  storage_account_name         = module.storage.storage_account_name
  storage_account_key          = module.storage.primary_access_key
  cosmosdb_endpoint            = module.cosmosdb.cosmosdb_endpoint
  cosmosdb_key                 = module.cosmosdb.cosmosdb_primary_key
  keyvault_uri                 = module.keyvault.vault_uri
  web_pubsub_connection_string = module.web_pubsub.connection_string
  openai_endpoint              = module.openai.endpoint
  openai_api_key_secret_uri    = "${module.keyvault.vault_uri}secrets/openai-api-key"
}

# ── Container Apps (4 heavy compute) ──────────────────────────

module "container_apps" {
  source = "./modules/container-apps"

  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  environment                  = var.environment
  containers_subnet_id         = module.vnet.containers_subnet_id
  managed_identity_id          = module.keyvault.managed_identity_id
  managed_identity_client_id   = module.keyvault.managed_identity_client_id
  keyvault_uri                 = module.keyvault.vault_uri
  storage_account_name         = module.storage.storage_account_name
  cosmosdb_endpoint            = module.cosmosdb.cosmosdb_endpoint
  web_pubsub_connection_string = module.web_pubsub.connection_string
}

# ── Durable Functions (orchestrator) ──────────────────────────

module "durable_functions" {
  source = "./modules/durable-functions"

  resource_group_name                = azurerm_resource_group.main.name
  location                           = azurerm_resource_group.main.location
  environment                        = var.environment
  functions_subnet_id                = module.vnet.functions_subnet_id
  managed_identity_id                = module.keyvault.managed_identity_id
  managed_identity_client_id         = module.keyvault.managed_identity_client_id
  function_app_url                   = module.functions.function_app_url
  container_app_urls                 = module.container_apps.container_app_urls
  storage_connection_string          = module.storage.primary_connection_string
  keyvault_uri                       = module.keyvault.vault_uri
  application_insights_connection_string = module.functions.application_insights_connection_string
}

# ── API Management ────────────────────────────────────────────

module "apim" {
  source = "./modules/apim"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  publisher_email     = var.alert_email
  function_app_url    = module.functions.function_app_url
}

# ── WAF (Front Door) ──────────────────────────────────────────

module "waf" {
  source = "./modules/waf"
  count  = var.enable_waf ? 1 : 0

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  backend_host        = module.apim.gateway_url
  enable_waf          = var.enable_waf
}

# ── Data Migration (Data Factory) ─────────────────────────────

module "data_migration" {
  source = "./modules/data-migration"

  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  environment         = var.environment
  data_factory_name   = "adf-migrate4hana-${var.environment}"
  ecc_db_host         = var.ecc_db_host
  ecc_db_name         = var.ecc_db_name
  s4_db_host          = var.s4_db_host
  s4_db_name          = var.s4_db_name
  keyvault_id         = module.keyvault.vault_id
  keyvault_uri        = module.keyvault.vault_uri
}
