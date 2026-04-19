# ──────────────────────────────────────────────────────────────
# VNet module — resources
# ──────────────────────────────────────────────────────────────

# ── Virtual Network ───────────────────────────────────────────

resource "azurerm_virtual_network" "main" {
  name                = "vnet-migrate4hana-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = var.vnet_address_space
  tags                = var.tags
}

# ── Subnets ───────────────────────────────────────────────────

resource "azurerm_subnet" "functions" {
  name                 = "snet-functions"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.functions]

  delegation {
    name = "functions-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "containers" {
  name                 = "snet-containers"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.containers]

  delegation {
    name = "containers-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "gpu" {
  name                 = "snet-gpu"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.gpu]
}

resource "azurerm_subnet" "sap" {
  name                 = "snet-sap"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.sap]
}

resource "azurerm_subnet" "endpoints" {
  name                 = "snet-endpoints"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.endpoints]
}

# ══════════════════════════════════════════════════════════════
# Network Security Groups
# ══════════════════════════════════════════════════════════════

# ── Functions NSG ─────────────────────────────────────────────

resource "azurerm_network_security_group" "functions" {
  name                = "nsg-functions-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Outbound — HTTPS to Internet
  security_rule {
    name                       = "Allow-Outbound-HTTPS"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Outbound — SAP RFC 3300-3399
  security_rule {
    name                       = "Allow-Outbound-SAP-RFC"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3300-3399"
    source_address_prefix      = "*"
    destination_address_prefix = var.sap_rfc_cidr
  }

  # Outbound — SAP GUI 3200
  security_rule {
    name                       = "Allow-Outbound-SAP-GUI"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3200"
    source_address_prefix      = "*"
    destination_address_prefix = var.sap_rfc_cidr
  }

  # Outbound — SAP HTTPS 44300
  security_rule {
    name                       = "Allow-Outbound-SAP-HTTPS"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "44300"
    source_address_prefix      = "*"
    destination_address_prefix = var.sap_rfc_cidr
  }

  # Outbound — deny remaining Internet
  security_rule {
    name                       = "Deny-Outbound-Internet"
    priority                   = 4000
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
}

resource "azurerm_subnet_network_security_group_association" "functions" {
  subnet_id                 = azurerm_subnet.functions.id
  network_security_group_id = azurerm_network_security_group.functions.id
}

# ── Containers NSG ────────────────────────────────────────────

resource "azurerm_network_security_group" "containers" {
  name                = "nsg-containers-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Outbound — HTTPS
  security_rule {
    name                       = "Allow-Outbound-HTTPS"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Outbound — SAP RFC 3300-3399
  security_rule {
    name                       = "Allow-Outbound-SAP-RFC"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3300-3399"
    source_address_prefix      = "*"
    destination_address_prefix = var.sap_rfc_cidr
  }

  # Inbound — from functions subnet
  security_rule {
    name                       = "Allow-Inbound-From-Functions"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = var.subnet_prefixes.functions
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "containers" {
  subnet_id                 = azurerm_subnet.containers.id
  network_security_group_id = azurerm_network_security_group.containers.id
}

# ── GPU NSG (air-gapped) ─────────────────────────────────────

resource "azurerm_network_security_group" "gpu" {
  name                = "nsg-gpu-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Inbound — port 8000 from functions subnet
  security_rule {
    name                       = "Allow-Inbound-8000-Functions"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8000"
    source_address_prefix      = var.subnet_prefixes.functions
    destination_address_prefix = "*"
  }

  # Inbound — port 8000 from containers subnet
  security_rule {
    name                       = "Allow-Inbound-8000-Containers"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8000"
    source_address_prefix      = var.subnet_prefixes.containers
    destination_address_prefix = "*"
  }

  # Outbound — allow VirtualNetwork only
  security_rule {
    name                       = "Allow-Outbound-VNet"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "VirtualNetwork"
  }

  # Outbound — DENY Internet (air-gap)
  security_rule {
    name                       = "Deny-Outbound-Internet"
    priority                   = 4000
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
}

resource "azurerm_subnet_network_security_group_association" "gpu" {
  subnet_id                 = azurerm_subnet.gpu.id
  network_security_group_id = azurerm_network_security_group.gpu.id
}

# ── SAP NSG ───────────────────────────────────────────────────

resource "azurerm_network_security_group" "sap" {
  name                = "nsg-sap-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Inbound — SAP RFC 3300 from functions + containers
  security_rule {
    name                         = "Allow-Inbound-RFC-Functions"
    priority                     = 100
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "3300"
    source_address_prefix        = var.subnet_prefixes.functions
    destination_address_prefix   = "*"
  }

  security_rule {
    name                         = "Allow-Inbound-RFC-Containers"
    priority                     = 110
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "3300"
    source_address_prefix        = var.subnet_prefixes.containers
    destination_address_prefix   = "*"
  }

  # Inbound — SAP GUI 3200 from functions + containers
  security_rule {
    name                         = "Allow-Inbound-GUI-Functions"
    priority                     = 120
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "3200"
    source_address_prefix        = var.subnet_prefixes.functions
    destination_address_prefix   = "*"
  }

  security_rule {
    name                         = "Allow-Inbound-GUI-Containers"
    priority                     = 130
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "3200"
    source_address_prefix        = var.subnet_prefixes.containers
    destination_address_prefix   = "*"
  }

  # Inbound — SAP HTTPS 44300 from functions + containers
  security_rule {
    name                         = "Allow-Inbound-HTTPS-Functions"
    priority                     = 140
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "44300"
    source_address_prefix        = var.subnet_prefixes.functions
    destination_address_prefix   = "*"
  }

  security_rule {
    name                         = "Allow-Inbound-HTTPS-Containers"
    priority                     = 150
    direction                    = "Inbound"
    access                       = "Allow"
    protocol                     = "Tcp"
    source_port_range            = "*"
    destination_port_range       = "44300"
    source_address_prefix        = var.subnet_prefixes.containers
    destination_address_prefix   = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "sap" {
  subnet_id                 = azurerm_subnet.sap.id
  network_security_group_id = azurerm_network_security_group.sap.id
}

# ── Endpoints NSG ─────────────────────────────────────────────

resource "azurerm_network_security_group" "endpoints" {
  name                = "nsg-endpoints-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Inbound — HTTPS from VirtualNetwork
  security_rule {
    name                       = "Allow-Inbound-HTTPS-VNet"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "endpoints" {
  subnet_id                 = azurerm_subnet.endpoints.id
  network_security_group_id = azurerm_network_security_group.endpoints.id
}

# ══════════════════════════════════════════════════════════════
# GPU subnet — route table (no default Internet route)
# ══════════════════════════════════════════════════════════════

resource "azurerm_route_table" "gpu" {
  name                          = "rt-gpu-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  disable_bgp_route_propagation = false
  tags                          = var.tags

  route {
    name                   = "force-vnet-only"
    address_prefix         = "0.0.0.0/0"
    next_hop_type          = "VnetLocal"
  }
}

resource "azurerm_subnet_route_table_association" "gpu" {
  subnet_id      = azurerm_subnet.gpu.id
  route_table_id = azurerm_route_table.gpu.id
}

# ══════════════════════════════════════════════════════════════
# Optional VNet peering to S/4HANA VNet
# ══════════════════════════════════════════════════════════════

resource "azurerm_virtual_network_peering" "to_s4hana" {
  count = var.s4hana_vnet_id != "" ? 1 : 0

  name                         = "peer-to-s4hana"
  resource_group_name          = var.resource_group_name
  virtual_network_name         = azurerm_virtual_network.main.name
  remote_virtual_network_id    = var.s4hana_vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = false
}
