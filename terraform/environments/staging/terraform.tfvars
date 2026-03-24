###############################################################################
# Migrate4HANA — Staging Environment Configuration
###############################################################################

aws_region  = "us-east-1"
environment = "staging"
alert_email = "sap-migration-team@company.com"

# VPC (different CIDR from dev to allow VPC peering)
vpc_cidr             = "10.20.0.0/16"
availability_zones   = ["us-east-1a", "us-east-1b"]
private_subnet_cidrs = ["10.20.1.0/24", "10.20.2.0/24"]
public_subnet_cidrs  = ["10.20.101.0/24", "10.20.102.0/24"]

# VPN required for staging
enable_vpn_gateway = true
on_prem_cidr       = "172.16.0.0/12"

# S3
s3_staging_bucket = "migrate4hana-staging-staging"

# Lambda Layer (same layer ARN across environments)
pyrfc_layer_arn = ""

# WAF rate limiting (requests per 5 min per IP)
waf_rate_limit = 2000
