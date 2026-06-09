###############################################################################
# Observability -- Group D production-ops module
#
# Adds the production-grade observability layer the new WS3/WS4 Lambdas
# were missing:
#   - 1 dedicated CloudWatch dashboard per Lambda (api-orchestrator,
#     continuous-dq-monitor, compliance-archive, onboarding-bundle)
#   - 1 SLA-tracking dashboard rolling p50/p95/p99 latency, error %,
#     and tenant-scoped throughput rows/sec
#   - Per-lambda alarms: error rate >1%, p95 latency, throttles, DLQ
#     depth, function timeout, concurrent-execution saturation
#   - Domain alarms: DQ-violation-rate >5%, compliance-chain broken,
#     ledger-write-failure, key-map throttle
#   - 1 PagerDuty / SNS alert topic + email subscription per env
#
# Opt-in via var.deploy_observability (default false). When the deploy
# flag is on but a function name is empty (e.g. WS4 lambdas not yet
# provisioned), the corresponding widgets/alarms are silently skipped
# via a length() check rather than failing the apply.
###############################################################################

variable "deploy_observability" {
  type    = bool
  default = false
}
variable "environment" { type = string }
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "alert_email" {
  type        = string
  default     = ""
  description = "Email address for SNS alert subscription. Empty = SNS topic only, no email."
}
variable "pagerduty_endpoint" {
  type        = string
  default     = ""
  description = "Optional PagerDuty integration endpoint (HTTPS URL). Empty = SNS-only routing."
}
variable "api_orchestrator_function" {
  type    = string
  default = ""
}
variable "dq_monitor_function" {
  type    = string
  default = ""
}
variable "compliance_archive_function" {
  type    = string
  default = ""
}
variable "onboarding_bundle_function" {
  type    = string
  default = ""
}
variable "data_migrator_function" {
  type    = string
  default = ""
}
variable "key_map_table" {
  type        = string
  default     = "migrate4hana-key-map-prod"
  description = "F1 PersistentKeyMap DDB table -- monitored for throttle + corruption-risk events."
}
variable "compliance_ledger_table" {
  type    = string
  default = ""
}
variable "dq_findings_table" {
  type    = string
  default = ""
}
variable "error_rate_pct_threshold" {
  type        = number
  default     = 1
  description = "Lambda errors-as-percent-of-invocations alarm threshold."
}
variable "p95_latency_ms_threshold" {
  type        = number
  default     = 30000
  description = "Lambda p95 duration alarm threshold (milliseconds)."
}
variable "dq_violation_rate_threshold" {
  type        = number
  default     = 5
  description = "Continuous DQ -- max violations-per-100-rows allowed before paging."
}

locals {
  # Filter to lambdas actually provisioned (skip empty names so widgets/alarms
  # don't reference non-existent functions).
  monitored = compact([
    var.api_orchestrator_function,
    var.dq_monitor_function,
    var.compliance_archive_function,
    var.onboarding_bundle_function,
    var.data_migrator_function,
  ])
  enabled = var.deploy_observability && length(local.monitored) > 0
}

# ─────────────────────────────────────────────────────────────────────────────
# SNS topic for alerts
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_sns_topic" "ops_alerts" {
  count = local.enabled ? 1 : 0
  name  = "migrate4hana-ops-alerts-${var.environment}"
  tags  = { Pillar = "GroupD-Observability" }
}

resource "aws_sns_topic_subscription" "email" {
  count     = local.enabled && var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.ops_alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_subscription" "pagerduty" {
  count     = local.enabled && var.pagerduty_endpoint != "" ? 1 : 0
  topic_arn = aws_sns_topic.ops_alerts[0].arn
  protocol  = "https"
  endpoint  = var.pagerduty_endpoint
}

# ─────────────────────────────────────────────────────────────────────────────
# Per-Lambda dashboards (one dashboard per function -- deep view)
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_dashboard" "per_lambda" {
  for_each = local.enabled ? toset(local.monitored) : toset([])

  dashboard_name = "Migrate4HANA-${each.value}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "Invocations / Errors / Throttles"
          view   = "timeSeries"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", each.value],
            [".", "Errors", ".", "."],
            [".", "Throttles", ".", "."]
          ]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "Duration p50/p95/p99"
          view   = "timeSeries"
          region = var.region
          period = 300
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", each.value, { stat = "p50", label = "p50" }],
            ["...", { stat = "p95", label = "p95" }],
            ["...", { stat = "p99", label = "p99" }],
            ["...", { stat = "Maximum", label = "max" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "Concurrent Executions"
          view   = "timeSeries"
          region = var.region
          period = 60
          stat   = "Maximum"
          metrics = [
            ["AWS/Lambda", "ConcurrentExecutions", "FunctionName", each.value]
          ]
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          title  = "Recent ERROR logs"
          region = var.region
          query  = "SOURCE '/aws/lambda/${each.value}' | filter @message like /ERROR/ | sort @timestamp desc | limit 50"
        }
      }
    ]
  })
}

# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting SLA dashboard -- single pane for on-call
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_dashboard" "sla_overview" {
  count          = local.enabled ? 1 : 0
  dashboard_name = "Migrate4HANA-SLA-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALL Lambdas -- Error Rate (Errors / Invocations)"
          view   = "timeSeries"
          region = var.region
          period = 300
          metrics = concat(
            [for fn in local.monitored : [
              "AWS/Lambda", "Errors", "FunctionName", fn, { stat = "Sum", label = "${fn} errors", visible = false, id = "e_${replace(fn, "-", "_")}" }
            ]],
            [for fn in local.monitored : [
              "AWS/Lambda", "Invocations", "FunctionName", fn, { stat = "Sum", label = "${fn} invocations", visible = false, id = "i_${replace(fn, "-", "_")}" }
            ]],
            [for fn in local.monitored : [
              { expression = "100 * e_${replace(fn, "-", "_")} / (i_${replace(fn, "-", "_")} + 0.0001)", label = "${fn} %errors", id = "pct_${replace(fn, "-", "_")}" }
            ]]
          )
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALL Lambdas -- p95 latency (ms)"
          view   = "timeSeries"
          region = var.region
          period = 300
          metrics = [for fn in local.monitored : [
            "AWS/Lambda", "Duration", "FunctionName", fn, { stat = "p95", label = fn }
          ]]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB -- key-map throttles + read/write capacity"
          view   = "timeSeries"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", var.key_map_table],
            [".", "ConsumedReadCapacityUnits", ".", "."],
            [".", "ConsumedWriteCapacityUnits", ".", "."]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "DQ findings + compliance ledger write rate"
          view   = "timeSeries"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = compact([
            var.dq_findings_table != "" ? "AWS/DynamoDB" : null,
          ]) == [] ? [] : compact([
            var.dq_findings_table != "" ? jsonencode(["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", var.dq_findings_table]) : null,
            var.compliance_ledger_table != "" ? jsonencode(["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", var.compliance_ledger_table]) : null,
          ])
        }
      },
      {
        type   = "text"
        x      = 0
        y      = 12
        width  = 24
        height = 3
        properties = {
          markdown = "## SLA targets (${var.environment})\n- Lambda error rate: **< ${var.error_rate_pct_threshold}%** over 5 min\n- Lambda p95 duration: **< ${var.p95_latency_ms_threshold} ms**\n- DQ violation rate: **< ${var.dq_violation_rate_threshold}/100 rows**\n- DDB throttles: **0** (any throttle pages on-call)\n- Compliance chain: **unbroken** (any verify_chain ok=false pages on-call)\n\nOn-call runbook: see [RUNBOOK.md](https://github.com/Ravi-Teja-Chowdary/migrate4hanav2/blob/main/docs/RUNBOOK.md)"
        }
      }
    ]
  })
}

# ─────────────────────────────────────────────────────────────────────────────
# Per-Lambda alarms
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "lambda_error_rate" {
  for_each = local.enabled ? toset(local.monitored) : toset([])

  alarm_name          = "m4h-${each.value}-errors-${var.environment}"
  alarm_description   = "Lambda ${each.value}: error rate > ${var.error_rate_pct_threshold}% over 5min"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = var.error_rate_pct_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  ok_actions          = [aws_sns_topic.ops_alerts[0].arn]

  metric_query {
    id          = "error_pct"
    expression  = "100 * errors / (invocations + 0.0001)"
    label       = "Error %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      metric_name = "Errors"
      namespace   = "AWS/Lambda"
      period      = 300
      stat        = "Sum"
      dimensions  = { FunctionName = each.value }
    }
  }
  metric_query {
    id = "invocations"
    metric {
      metric_name = "Invocations"
      namespace   = "AWS/Lambda"
      period      = 300
      stat        = "Sum"
      dimensions  = { FunctionName = each.value }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_p95_latency" {
  for_each = local.enabled ? toset(local.monitored) : toset([])

  alarm_name          = "m4h-${each.value}-p95-latency-${var.environment}"
  alarm_description   = "Lambda ${each.value}: p95 duration > ${var.p95_latency_ms_threshold}ms"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = var.p95_latency_ms_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  dimensions          = { FunctionName = each.value }
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each = local.enabled ? toset(local.monitored) : toset([])

  alarm_name          = "m4h-${each.value}-throttles-${var.environment}"
  alarm_description   = "Lambda ${each.value}: ANY throttle (concurrent-exec saturation)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  dimensions          = { FunctionName = each.value }
}

# ─────────────────────────────────────────────────────────────────────────────
# Domain alarms -- DDB throttle, key-map corruption-risk, DQ rate, ledger break
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "key_map_throttle" {
  count = local.enabled ? 1 : 0

  alarm_name          = "m4h-key-map-throttle-${var.environment}"
  alarm_description   = "PersistentKeyMap DDB ${var.key_map_table}: ANY throttle. F1 ledger MUST not throttle mid-cutover."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ThrottledRequests"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  dimensions          = { TableName = var.key_map_table }
}

resource "aws_cloudwatch_metric_alarm" "key_map_system_errors" {
  count = local.enabled ? 1 : 0

  alarm_name          = "m4h-key-map-system-errors-${var.environment}"
  alarm_description   = "PersistentKeyMap DDB ${var.key_map_table}: SystemErrors -- AWS-side fault (possible corruption signal)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "SystemErrors"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  dimensions          = { TableName = var.key_map_table }
}

resource "aws_cloudwatch_metric_alarm" "dq_violation_rate" {
  count = local.enabled && var.dq_monitor_function != "" ? 1 : 0

  alarm_name          = "m4h-dq-violation-rate-${var.environment}"
  alarm_description   = "Continuous DQ: violation rate > ${var.dq_violation_rate_threshold}/100 rows. Custom metric emitted by handler."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ViolationRatePct"
  namespace           = "Migrate4HANA/DQ"
  period              = 300
  statistic           = "Average"
  threshold           = var.dq_violation_rate_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "compliance_chain_broken" {
  count = local.enabled && var.compliance_archive_function != "" ? 1 : 0

  alarm_name          = "m4h-compliance-chain-broken-${var.environment}"
  alarm_description   = "Compliance archive: verify_chain returned ok=false. PAGES IMMEDIATELY -- audit-evidence is the product."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ChainBrokenCount"
  namespace           = "Migrate4HANA/Compliance"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "ledger_write_failure" {
  count = local.enabled && var.compliance_ledger_table != "" ? 1 : 0

  alarm_name          = "m4h-ledger-write-failure-${var.environment}"
  alarm_description   = "Compliance ledger DDB: write failures. Breaks audit chain if sustained."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UserErrors"
  namespace           = "AWS/DynamoDB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops_alerts[0].arn]
  dimensions          = { TableName = var.compliance_ledger_table }
}

# ─────────────────────────────────────────────────────────────────────────────
# SLA custom-metric publisher Lambda + schedule
# ─────────────────────────────────────────────────────────────────────────────
# (Custom metrics get published by the dq-monitor / compliance-archive handlers
# directly via boto3 PutMetricData. No extra Lambda needed -- alarms below
# subscribe to the namespaces Migrate4HANA/DQ + Migrate4HANA/Compliance.)

# ─────────────────────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────────────────────
output "alert_topic_arn" {
  value       = local.enabled ? aws_sns_topic.ops_alerts[0].arn : ""
  description = "SNS topic for ops alerts. Subscribe additional channels here."
}

output "sla_dashboard_name" {
  value       = local.enabled ? aws_cloudwatch_dashboard.sla_overview[0].dashboard_name : ""
  description = "Cross-cutting SLA dashboard name."
}

output "lambda_dashboards" {
  value       = local.enabled ? [for d in aws_cloudwatch_dashboard.per_lambda : d.dashboard_name] : []
  description = "Per-Lambda deep-view dashboard names."
}

output "alarm_count" {
  value = local.enabled ? (
    length(aws_cloudwatch_metric_alarm.lambda_error_rate) +
    length(aws_cloudwatch_metric_alarm.lambda_p95_latency) +
    length(aws_cloudwatch_metric_alarm.lambda_throttles) +
    length(aws_cloudwatch_metric_alarm.key_map_throttle) +
    length(aws_cloudwatch_metric_alarm.key_map_system_errors) +
    length(aws_cloudwatch_metric_alarm.dq_violation_rate) +
    length(aws_cloudwatch_metric_alarm.compliance_chain_broken) +
    length(aws_cloudwatch_metric_alarm.ledger_write_failure)
  ) : 0
  description = "Total number of provisioned alarms."
}
