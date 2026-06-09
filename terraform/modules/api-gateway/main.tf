###############################################################################
# WS1 — Visual Business Authoring API Gateway
#
# Front door for the api-orchestrator lambda (lambda/api-orchestrator/handler.py).
# HTTP API (v2) with IAM authorization, single $default stage, Lambda proxy
# integration so the lambda owns its route table. Independent + opt-in via
# var.deploy_api_gateway (default false) -- deploying this module change to
# existing prod stacks adds ZERO resources until the flag is flipped.
#
# When enabled, exposes the same operations as the deprecated
# scripts/manage-value-maps.ps1 plus telemetry queries against the F1
# PersistentKeyMap DDB table. The future React console (WS1.2, separate
# delivery) will consume these endpoints.
###############################################################################

variable "environment"       { type = string }
variable "api_lambda_arn"    { type = string }
variable "api_lambda_name"   { type = string }
variable "deploy_api_gateway" {
  type    = bool
  default = false
}
variable "allowed_iam_principals" {
  type        = list(string)
  default     = []
  description = "List of IAM principal ARNs allowed to invoke the API. Empty list = no caller restriction beyond AWS_IAM auth."
}

resource "aws_apigatewayv2_api" "api_orchestrator" {
  count         = var.deploy_api_gateway ? 1 : 0
  name          = "migrate4hana-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "Migrate4HANA visual business authoring + telemetry API (WS1)"

  cors_configuration {
    allow_origins = ["*"]                # Production deploy will tighten via UI origin list
    allow_methods = ["GET", "PUT", "POST", "DELETE", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization", "X-Tenant-Id"]
    max_age       = 300
  }

  tags = {
    Name      = "migrate4hana-api-${var.environment}"
    Workstream = "WS1-visual-business-authoring"
  }
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  count                  = var.deploy_api_gateway ? 1 : 0
  api_id                 = aws_apigatewayv2_api.api_orchestrator[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.api_lambda_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# Route catalog -- one route per (METHOD, path). Lambda's handler routes
# internally so all routes target the same integration.
locals {
  api_routes = var.deploy_api_gateway ? {
    health                     = "GET /health"
    list_value_maps            = "GET /value-maps"
    get_value_map              = "GET /value-maps/{name}"
    put_value_map              = "PUT /value-maps/{name}"
    delete_value_map           = "DELETE /value-maps/{name}"
    list_rulesets              = "GET /rulesets"
    get_ruleset                = "GET /rulesets/{object}"
    put_ruleset                = "PUT /rulesets/{object}"
    list_telemetry_runs        = "GET /telemetry/runs"
    get_telemetry_run_detail   = "GET /telemetry/runs/{run_id}"
    resolve_key                = "GET /telemetry/key-map/{object}/{source_key}"
  } : {}
}

resource "aws_apigatewayv2_route" "routes" {
  for_each           = local.api_routes
  api_id             = aws_apigatewayv2_api.api_orchestrator[0].id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda[0].id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_stage" "default" {
  count       = var.deploy_api_gateway ? 1 : 0
  api_id      = aws_apigatewayv2_api.api_orchestrator[0].id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access[0].arn
    format          = jsonencode({
      requestId   = "$context.requestId"
      ip          = "$context.identity.sourceIp"
      route       = "$context.routeKey"
      status      = "$context.status"
      latency_ms  = "$context.responseLatency"
      integration = "$context.integrationStatus"
      userAgent   = "$context.identity.userAgent"
    })
  }

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }

  tags = { Name = "migrate4hana-api-stage-${var.environment}" }
}

resource "aws_cloudwatch_log_group" "api_access" {
  count             = var.deploy_api_gateway ? 1 : 0
  name              = "/aws/apigateway/migrate4hana-api-${var.environment}"
  retention_in_days = 30
}

# Lambda permission so API Gateway can invoke the api-orchestrator lambda.
resource "aws_lambda_permission" "api_gateway" {
  count         = var.deploy_api_gateway ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.api_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api_orchestrator[0].execution_arn}/*/*"
}

output "api_endpoint" {
  value       = var.deploy_api_gateway ? aws_apigatewayv2_api.api_orchestrator[0].api_endpoint : ""
  description = "HTTPS base URL of the WS1 API (empty if not deployed)"
}

output "api_id" {
  value       = var.deploy_api_gateway ? aws_apigatewayv2_api.api_orchestrator[0].id : ""
  description = "API Gateway v2 ID for IAM policy attachment"
}
