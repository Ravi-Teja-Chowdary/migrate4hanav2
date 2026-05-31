###############################################################################
# Migrate4HANA — WAF Module
# AWS WAFv2 Web ACL with rate limiting, managed rule groups, and DDoS protection
###############################################################################

variable "environment" {
  type = string
}

variable "rate_limit" {
  type        = number
  description = "Max requests per 5-minute window per IP"
  default     = 1000
}

# ─────────────────────────────────────────────
# WAFv2 Web ACL
# ─────────────────────────────────────────────
resource "aws_wafv2_web_acl" "main" {
  name        = "migrate4hana-waf-${var.environment}"
  description = "Migrate4HANA API protection - rate limiting, common exploits, SQLi, XSS"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Rule 1: Rate limiting per IP
  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "migrate4hana-rate-limit-${var.environment}"
    }
  }

  # Rule 2: AWS Managed Rules — Common Rule Set (OWASP Top 10)
  rule {
    name     = "aws-common-rules"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "migrate4hana-common-rules-${var.environment}"
    }
  }

  # Rule 3: SQL Injection protection
  rule {
    name     = "sql-injection"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "migrate4hana-sqli-${var.environment}"
    }
  }

  # Rule 4: Known bad inputs
  rule {
    name     = "known-bad-inputs"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "migrate4hana-bad-inputs-${var.environment}"
    }
  }

  # Rule 5: IP reputation list (blocks known malicious IPs)
  rule {
    name     = "ip-reputation"
    priority = 5

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "migrate4hana-ip-reputation-${var.environment}"
    }
  }

  visibility_config {
    sampled_requests_enabled   = true
    cloudwatch_metrics_enabled = true
    metric_name                = "migrate4hana-waf-${var.environment}"
  }

  tags = {
    Name        = "migrate4hana-waf-${var.environment}"
    Component   = "Security"
    Environment = var.environment
  }
}

# ─────────────────────────────────────────────
# WAF Logging to CloudWatch
# ─────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-migrate4hana-${var.environment}"
  retention_in_days = 90

  tags = {
    Component   = "Security"
    Environment = var.environment
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.main.arn

  logging_filter {
    default_behavior = "KEEP"

    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ANY"

      condition {
        action_condition {
          action = "BLOCK"
        }
      }

      condition {
        action_condition {
          action = "COUNT"
        }
      }
    }
  }
}

# ─────────────────────────────────────────────
# CloudWatch Alarm — WAF blocked requests spike
# ─────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "waf_blocked_requests" {
  alarm_name          = "migrate4hana-waf-blocked-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "BlockedRequests"
  namespace           = "AWS/WAFV2"
  period              = 300
  statistic           = "Sum"
  threshold           = 100
  alarm_description   = "WAF blocked > 100 requests in 5 min - possible attack"

  dimensions = {
    WebACL = aws_wafv2_web_acl.main.name
    Rule   = "ALL"
    Region = "us-east-1"
  }

  tags = {
    Component   = "Security"
    Environment = var.environment
  }
}

# ─────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────
output "web_acl_arn" {
  value       = aws_wafv2_web_acl.main.arn
  description = "WAF Web ACL ARN — attach to ALB or API Gateway"
}

output "web_acl_id" {
  value       = aws_wafv2_web_acl.main.id
  description = "WAF Web ACL ID"
}
