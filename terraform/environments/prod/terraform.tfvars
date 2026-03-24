###############################################################################
# Migrate4HANA — Production Environment Configuration
###############################################################################

aws_region  = "us-east-1"
environment = "prod"
alert_email = "sap-migration-oncall@company.com"

# VPC (3 AZs for high availability, different CIDR from dev/staging)
vpc_cidr             = "10.30.0.0/16"
availability_zones   = ["us-east-1a", "us-east-1b", "us-east-1c"]
private_subnet_cidrs = ["10.30.1.0/24", "10.30.2.0/24", "10.30.3.0/24"]
public_subnet_cidrs  = ["10.30.101.0/24", "10.30.102.0/24", "10.30.103.0/24"]

# VPN mandatory for production
enable_vpn_gateway = true
on_prem_cidr       = "172.16.0.0/12"

# S3
s3_staging_bucket = "migrate4hana-staging-prod"

# Lambda Layer (same layer ARN across environments)
pyrfc_layer_arn = ""

# WAF rate limiting (stricter for production)
waf_rate_limit = 1000
