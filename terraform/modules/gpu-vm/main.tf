resource "azurerm_network_interface" "gpu" {
  count               = var.enable ? 1 : 0
  name                = "migrate4hana-llm-nic-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = var.gpu_subnet_id
    private_ip_address_allocation = "Dynamic"
  }

  tags = var.tags
}

resource "azurerm_network_security_group" "gpu_nsg" {
  count               = var.enable ? 1 : 0
  name                = "migrate4hana-gpu-nsg-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  # Allow inbound Ollama API calls from functions subnet
  security_rule {
    name                       = "AllowFunctionsOllamaAPI"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["11434"]
    source_address_prefix      = var.functions_subnet_prefix
    destination_address_prefix = "*"
  }

  # Allow inbound Ollama API calls from containers subnet
  security_rule {
    name                       = "AllowContainersOllamaAPI"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["11434"]
    source_address_prefix      = var.containers_subnet_prefix
    destination_address_prefix = "*"
  }

  # Allow SSH from management IP
  security_rule {
    name                       = "AllowSSHManagement"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["22"]
    source_address_prefix      = var.management_ip
    destination_address_prefix = "*"
  }

  # Allow outbound to VirtualNetwork (internal communication)
  security_rule {
    name                       = "AllowVNetOutbound"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "VirtualNetwork"
  }

  # Allow outbound HTTPS for initial Ollama install and model download
  # NOTE: After provisioning, manually tighten this rule or revoke it
  # to achieve full air-gap. The DenyInternetOutbound rule (pri 4096)
  # blocks all other outbound traffic.
  security_rule {
    name                       = "AllowInitialSetupHTTPS"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }

  # CRITICAL: Deny all outbound Internet traffic for air-gap
  security_rule {
    name                       = "DenyInternetOutbound"
    priority                   = 4096
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }

  tags = var.tags
}

resource "azurerm_network_interface_security_group_association" "gpu" {
  count                     = var.enable ? 1 : 0
  network_interface_id      = azurerm_network_interface.gpu[0].id
  network_security_group_id = azurerm_network_security_group.gpu_nsg[0].id
}

resource "azurerm_route_table" "gpu" {
  count               = var.enable ? 1 : 0
  name                = "migrate4hana-gpu-rt-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name

  route {
    name           = "drop-internet"
    address_prefix = "0.0.0.0/0"
    next_hop_type  = "None"
  }

  tags = var.tags
}

resource "azurerm_subnet_route_table_association" "gpu" {
  count          = var.enable ? 1 : 0
  subnet_id      = var.gpu_subnet_id
  route_table_id = azurerm_route_table.gpu[0].id
}

resource "azurerm_linux_virtual_machine" "gpu" {
  count               = var.enable ? 1 : 0
  name                = "migrate4hana-llm-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  size                = var.vm_size
  admin_username      = "azureuser"

  network_interface_ids = [
    azurerm_network_interface.gpu[0].id,
  ]

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.ssh_public_key
  }

  source_image_reference {
    publisher = "microsoft-dsvm"
    offer     = "ubuntu-hpc"
    sku       = "2204"
    version   = "latest"
  }

  os_disk {
    name                 = "migrate4hana-llm-osdisk-${var.environment}"
    disk_size_gb         = 512
    storage_account_type = "Premium_LRS"
    caching              = "ReadWrite"
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [var.managed_identity_id]
  }

  custom_data = base64encode(file("${path.module}/cloud-init.yaml"))

  tags = var.tags
}
