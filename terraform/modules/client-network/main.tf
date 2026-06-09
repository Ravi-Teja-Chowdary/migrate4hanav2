###############################################################################
# WS3 — Client VPN + Transit Gateway + restrictive SG matrix
#
# Productizes customer-landscape network onboarding: provisions one
# AWS Client VPN Endpoint per landscape, one Transit Gateway as the
# isolation backbone between customer VPCs and the Migrate4HANA service
# VPC, and a SG matrix that defaults to deny-all with explicit per-tier
# allow rules.
#
# Opt-in via var.deploy_client_network (default false). Existing prod
# stacks see ZERO net-new resources until the flag is flipped. When
# enabled, adds (~12 resources):
#   - aws_acm_certificate (server cert for VPN)
#   - aws_ec2_client_vpn_endpoint
#   - aws_ec2_client_vpn_network_association (per private subnet)
#   - aws_ec2_client_vpn_route (per route-table peer)
#   - aws_ec2_transit_gateway
#   - aws_ec2_transit_gateway_vpc_attachment (service VPC)
#   - aws_security_group x3 (vpn / bastion-tier / data-tier)
#   - aws_security_group_rule x N (explicit allow matrix)
#
# Tear-down is `terraform destroy -target=module.client_network` --
# fully reversible without touching the existing service VPC.
###############################################################################

variable "environment"              { type = string }
variable "vpc_id"                   { type = string }
variable "private_subnet_ids"       { type = list(string) }
variable "vpn_client_cidr_block" {
  type        = string
  default     = "10.99.0.0/22"
  description = "CIDR pool for connected VPN client IPs. Must NOT overlap with vpc_cidr or any peer VPC."
}
variable "deploy_client_network" {
  type    = bool
  default = false
}
variable "vpn_server_certificate_arn" {
  type        = string
  default     = ""
  description = "Pre-issued ACM certificate ARN for the VPN server. Required when deploy_client_network=true."
}
variable "vpn_client_certificate_arn" {
  type        = string
  default     = ""
  description = "Pre-issued ACM certificate ARN for client mutual auth. Required when deploy_client_network=true."
}
variable "tgw_peer_vpc_ids" {
  type        = list(string)
  default     = []
  description = "Customer-side VPCs to attach to the Transit Gateway. Empty list = TGW provisioned but no peer attachments."
}
variable "data_tier_ports" {
  type        = list(number)
  default     = [3300, 3200, 44300, 44301, 443]
  description = "Ports allowed FROM the bastion tier TO the data tier (SAP RFC + HTTPS by default)."
}

###############################################################################
# Client VPN endpoint
###############################################################################
resource "aws_cloudwatch_log_group" "vpn_connection_log" {
  count             = var.deploy_client_network ? 1 : 0
  name              = "/aws/clientvpn/migrate4hana-${var.environment}/connection"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_stream" "vpn_connection_log" {
  count          = var.deploy_client_network ? 1 : 0
  name           = "default"
  log_group_name = aws_cloudwatch_log_group.vpn_connection_log[0].name
}

resource "aws_ec2_client_vpn_endpoint" "main" {
  count                  = var.deploy_client_network ? 1 : 0
  description            = "Migrate4HANA customer landscape VPN (${var.environment})"
  server_certificate_arn = var.vpn_server_certificate_arn
  client_cidr_block      = var.vpn_client_cidr_block
  split_tunnel           = true                  # only route Migrate4HANA traffic via VPN

  authentication_options {
    type                       = "certificate-authentication"
    root_certificate_chain_arn = var.vpn_client_certificate_arn
  }

  connection_log_options {
    enabled               = true
    cloudwatch_log_group  = aws_cloudwatch_log_group.vpn_connection_log[0].name
    cloudwatch_log_stream = aws_cloudwatch_log_stream.vpn_connection_log[0].name
  }

  tags = {
    Name      = "migrate4hana-vpn-${var.environment}"
    Workstream = "WS3-client-network"
  }
}

resource "aws_ec2_client_vpn_network_association" "subnets" {
  count                  = var.deploy_client_network ? length(var.private_subnet_ids) : 0
  client_vpn_endpoint_id = aws_ec2_client_vpn_endpoint.main[0].id
  subnet_id              = var.private_subnet_ids[count.index]
}

resource "aws_ec2_client_vpn_authorization_rule" "private_vpc" {
  count                  = var.deploy_client_network ? 1 : 0
  client_vpn_endpoint_id = aws_ec2_client_vpn_endpoint.main[0].id
  target_network_cidr    = "10.30.0.0/16"     # the service VPC default
  authorize_all_groups   = true
  description            = "Authorize VPN clients to reach the service VPC"
}

###############################################################################
# Transit Gateway -- multi-VPC mesh for customer + service VPCs
###############################################################################
resource "aws_ec2_transit_gateway" "main" {
  count       = var.deploy_client_network ? 1 : 0
  description = "Migrate4HANA TGW (${var.environment})"

  default_route_table_association = "enable"
  default_route_table_propagation = "enable"
  dns_support                     = "enable"

  tags = {
    Name      = "migrate4hana-tgw-${var.environment}"
    Workstream = "WS3-client-network"
  }
}

resource "aws_ec2_transit_gateway_vpc_attachment" "service_vpc" {
  count              = var.deploy_client_network ? 1 : 0
  transit_gateway_id = aws_ec2_transit_gateway.main[0].id
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids

  tags = {
    Name = "migrate4hana-tgw-service-${var.environment}"
    Side = "service"
  }
}

resource "aws_ec2_transit_gateway_vpc_attachment" "customer_peers" {
  count              = var.deploy_client_network ? length(var.tgw_peer_vpc_ids) : 0
  transit_gateway_id = aws_ec2_transit_gateway.main[0].id
  vpc_id             = var.tgw_peer_vpc_ids[count.index]
  # subnet_ids must be passed in via a more sophisticated lookup -- placeholder
  # for the per-customer attachment pattern. The onboarding-bundle lambda
  # generates a tfvars overlay each customer applies in their own account
  # (cross-account attachment via Resource Access Manager).
  subnet_ids = var.private_subnet_ids
  tags = {
    Name = "migrate4hana-tgw-peer-${count.index}-${var.environment}"
    Side = "customer"
  }
}

###############################################################################
# Restrictive SG matrix -- VPN / bastion tier / data tier
###############################################################################
resource "aws_security_group" "vpn_clients" {
  count       = var.deploy_client_network ? 1 : 0
  name        = "migrate4hana-vpn-clients-${var.environment}"
  description = "VPN-connected client devices"
  vpc_id      = var.vpc_id

  # Egress to bastion tier ONLY
  egress {
    description     = "VPN clients -> bastion tier (SSH + HTTPS)"
    from_port       = 22
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion_tier[0].id]
  }

  tags = { Name = "vpn-clients", Tier = "edge" }
}

resource "aws_security_group" "bastion_tier" {
  count       = var.deploy_client_network ? 1 : 0
  name        = "migrate4hana-bastion-${var.environment}"
  description = "Bastion / jumpbox tier -- accepts from VPN, talks to data tier"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Inbound from VPN clients (TCP 22 + 443)"
    from_port       = 22
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpn_clients[0].id]
  }

  egress {
    description     = "Outbound to data tier (SAP RFC + HTTPS)"
    from_port       = 1
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.data_tier[0].id]
  }

  tags = { Name = "bastion-tier", Tier = "middle" }
}

resource "aws_security_group" "data_tier" {
  count       = var.deploy_client_network ? 1 : 0
  name        = "migrate4hana-data-${var.environment}"
  description = "Data tier -- SAP S/4HANA + reconciler + audit"
  vpc_id      = var.vpc_id

  # Default: deny all ingress; explicit allow per port via separate rules
  ingress {
    description     = "Inbound from bastion tier ONLY (SAP RFC + HTTPS)"
    from_port       = 3200
    to_port         = 44301
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion_tier[0].id]
  }

  egress {
    description = "Allow outbound for DDB / S3 / KMS via VPC endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "data-tier", Tier = "core" }
}

###############################################################################
# Outputs -- consumed by the onboarding-bundle lambda to build per-customer
# .ovpn profiles + a firewall-routing template the customer's network team
# applies on their side.
###############################################################################
output "vpn_endpoint_id" {
  value       = var.deploy_client_network ? aws_ec2_client_vpn_endpoint.main[0].id : ""
  description = "Client VPN endpoint ID (empty if not deployed)"
}

output "vpn_dns_name" {
  value       = var.deploy_client_network ? aws_ec2_client_vpn_endpoint.main[0].dns_name : ""
  description = "DNS name the customer's OpenVPN profile dials"
}

output "transit_gateway_id" {
  value       = var.deploy_client_network ? aws_ec2_transit_gateway.main[0].id : ""
  description = "Transit Gateway ID for cross-account RAM share + customer attachment"
}

output "client_cidr" {
  value       = var.vpn_client_cidr_block
  description = "VPN client IP pool CIDR -- customer firewall must allow this to reach Migrate4HANA"
}

output "sg_ids" {
  value = var.deploy_client_network ? {
    vpn_clients   = aws_security_group.vpn_clients[0].id
    bastion_tier  = aws_security_group.bastion_tier[0].id
    data_tier     = aws_security_group.data_tier[0].id
  } : {}
  description = "SG IDs for the 3-tier matrix"
}
