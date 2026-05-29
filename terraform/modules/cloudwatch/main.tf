###############################################################################
# CloudWatch Module — Migration monitoring & alerting
###############################################################################

variable "environment" { type = string }
variable "lambda_arns" { type = map(string) }
variable "state_machine_arn" { type = string }
variable "alert_email" { type = string }

# ── SNS Topic for alerts ─────────────────────
resource "aws_sns_topic" "alerts" {
  name = "migrate4hana-alerts-${var.environment}"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Dashboard ────────────────────────────────
resource "aws_cloudwatch_dashboard" "migration" {
  dashboard_name = "Migrate4HANA-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Invocations by Stage"
          metrics = [for k, v in var.lambda_arns : [
            "AWS/Lambda", "Invocations",
            "FunctionName", "migrate4hana-${k}-${var.environment}"
          ]]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Errors by Stage"
          metrics = [for k, v in var.lambda_arns : [
            "AWS/Lambda", "Errors",
            "FunctionName", "migrate4hana-${k}-${var.environment}"
          ]]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Duration by Stage"
          metrics = [for k, v in var.lambda_arns : [
            "AWS/Lambda", "Duration",
            "FunctionName", "migrate4hana-${k}-${var.environment}"
          ]]
          period = 300
          stat   = "Average"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title = "Step Functions Executions"
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", var.state_machine_arn]
          ]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      }
    ]
  })
}

# ── Alarms ───────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "pipeline_failed" {
  alarm_name          = "migrate4hana-pipeline-failed-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Migration pipeline execution failed"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    StateMachineArn = var.state_machine_arn
  }
}
