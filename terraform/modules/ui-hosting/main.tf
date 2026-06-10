# ──────────────────────────────────────────────────────────────────────────
# ui-hosting module — S3 + CloudFront for the React UI
# ──────────────────────────────────────────────────────────────────────────
# Hosts the React build (frontend/dist/) on S3 behind CloudFront. Customers
# get a single HTTPS URL; CloudFront routes /api/* to the api-server ALB and
# the rest to S3.
#
# Uses the CloudFront default *.cloudfront.net domain (built-in HTTPS via
# the AWS-managed cert). A real custom domain can be wired in by passing
# `custom_domain` + an existing ACM cert ARN in us-east-1; left empty by
# default so this deploys without any DNS prerequisites.
#
# Inputs:
#   environment, alb_dns_name (origin), custom_domain (optional),
#   acm_cert_arn_us_east_1 (required only when custom_domain set)
#
# Outputs:
#   bucket_name, cloudfront_distribution_id, cloudfront_domain_name, ui_url
# ──────────────────────────────────────────────────────────────────────────

variable "environment"  { type = string }
variable "alb_dns_name" { type = string }

variable "custom_domain" {
  type    = string
  default = ""
}

variable "acm_cert_arn_us_east_1" {
  type    = string
  default = ""
}

# ── S3 bucket for React build artefacts ────────────────────────────────────
resource "aws_s3_bucket" "ui" {
  bucket        = "migrate4hana-ui-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true   # so destroy/replace stays cheap; dist/ is regenerable

  tags = {
    Name        = "migrate4hana-ui-${var.environment}"
    Component   = "UiHosting"
    Environment = var.environment
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket = aws_s3_bucket.ui.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ui" {
  bucket = aws_s3_bucket.ui.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Origin Access Control — only CloudFront can read from S3.
resource "aws_cloudfront_origin_access_control" "ui" {
  name                              = "migrate4hana-ui-oac-${var.environment}"
  description                       = "OAC for CloudFront → S3 UI bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── CloudFront distribution ────────────────────────────────────────────────
locals {
  use_custom_domain = var.custom_domain != "" && var.acm_cert_arn_us_east_1 != ""
}

resource "aws_cloudfront_distribution" "ui" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  http_version        = "http2and3"
  price_class         = "PriceClass_100"     # US + EU edges; cheapest tier
  comment             = "Migrate4HANA UI · ${var.environment}"

  aliases = local.use_custom_domain ? [var.custom_domain] : []

  # ── Origins ──
  # 1. S3 — static React bundle (HTML/JS/CSS)
  origin {
    domain_name              = aws_s3_bucket.ui.bucket_regional_domain_name
    origin_id                = "s3-ui"
    origin_access_control_id = aws_cloudfront_origin_access_control.ui.id
  }

  # 2. ALB — api_server.py backend
  origin {
    domain_name = var.alb_dns_name
    origin_id   = "alb-api"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"     # ALB has HTTP listener; CF→ALB stays inside AWS
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # ── Default behavior: S3 (React app) ──
  default_cache_behavior {
    target_origin_id       = "s3-ui"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # CachingOptimized managed policy (long TTL for static assets)
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # ── /api/* behavior: ALB (no cache, all methods, forward auth) ──
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "alb-api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # CachingDisabled — every API call hits the origin
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    # AllViewerExceptHostHeader — forwards auth header, query strings, cookies
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # SPA routing: 403/404 (S3 returns these for client-side routes like /runs)
  # are rewritten to /index.html so React Router can handle them.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
    error_caching_min_ttl = 0
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.use_custom_domain
    acm_certificate_arn            = local.use_custom_domain ? var.acm_cert_arn_us_east_1 : null
    ssl_support_method             = local.use_custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_custom_domain ? "TLSv1.2_2021" : "TLSv1"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  tags = {
    Name        = "migrate4hana-ui-${var.environment}"
    Component   = "UiHosting"
    Environment = var.environment
  }
}

# ── S3 bucket policy: grant CloudFront OAC read ─────────────────────────────
data "aws_iam_policy_document" "ui_bucket_policy" {
  statement {
    sid     = "AllowCloudFrontOAC"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.ui.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = data.aws_iam_policy_document.ui_bucket_policy.json
}

# ── Outputs ────────────────────────────────────────────────────────────────
output "bucket_name" {
  description = "S3 bucket the deploy script syncs frontend/dist/ to."
  value       = aws_s3_bucket.ui.id
}

output "cloudfront_distribution_id" {
  description = "Distribution ID (for `cloudfront create-invalidation`)."
  value       = aws_cloudfront_distribution.ui.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.ui.domain_name
}

output "ui_url" {
  description = "Customer-facing URL."
  value       = local.use_custom_domain ? "https://${var.custom_domain}" : "https://${aws_cloudfront_distribution.ui.domain_name}"
}
