###############################################################################
# API Gateway WebSocket — Real-Time Telemetry Streaming
# Streams structured log events from Lambda stages to the React frontend.
#
# Architecture:
#   Lambda handlers → log_stage_event() → boto3 post_to_connection()
#   → API Gateway WebSocket → Connected React LogViewer
###############################################################################

# -----------------------------------------------------------------------------
# WebSocket API
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "telemetry_ws" {
  name                       = "migrate4hana-telemetry-${var.environment}"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = {
    Component = "Telemetry"
  }
}

# -----------------------------------------------------------------------------
# DynamoDB table to track connected WebSocket clients
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "ws_connections" {
  name         = "migrate4hana-ws-connections-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Component = "Telemetry"
  }
}

# -----------------------------------------------------------------------------
# Lambda function for WebSocket connection management
# -----------------------------------------------------------------------------
data "archive_file" "ws_handler" {
  type        = "zip"
  output_path = "${path.module}/ws_handler.zip"

  source {
    content = <<-PYTHON
import json
import os
import boto3
import time
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("CONNECTIONS_TABLE", "migrate4hana-ws-connections-dev")

def lambda_handler(event, context):
    route = event.get("requestContext", {}).get("routeKey", "")
    connection_id = event.get("requestContext", {}).get("connectionId", "")

    table = dynamodb.Table(TABLE_NAME)

    if route == "$connect":
        # Store new connection with 24h TTL
        table.put_item(Item={
            "connectionId": connection_id,
            "connectedAt": int(time.time()),
            "ttl": int(time.time()) + 86400,
        })
        logger.info(f"WebSocket connected: {connection_id}")
        return {"statusCode": 200}

    elif route == "$disconnect":
        table.delete_item(Key={"connectionId": connection_id})
        logger.info(f"WebSocket disconnected: {connection_id}")
        return {"statusCode": 200}

    elif route == "$default":
        # Echo or handle incoming messages from the frontend
        return {"statusCode": 200, "body": "OK"}

    return {"statusCode": 200}
PYTHON
    filename = "handler.py"
  }
}

resource "aws_iam_role" "ws_lambda" {
  name = "migrate4hana-ws-lambda-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ws_lambda" {
  name = "ws-lambda-policy"
  role = aws_iam_role.ws_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:Scan",
          "dynamodb:GetItem"
        ]
        Resource = aws_dynamodb_table.ws_connections.arn
      },
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = "${aws_apigatewayv2_api.telemetry_ws.execution_arn}/*"
      }
    ]
  })
}

resource "aws_lambda_function" "ws_handler" {
  function_name = "migrate4hana-ws-handler-${var.environment}"
  role          = aws_iam_role.ws_lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 128

  filename         = data.archive_file.ws_handler.output_path
  source_code_hash = data.archive_file.ws_handler.output_base64sha256

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }
}

resource "aws_lambda_permission" "ws_apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.telemetry_ws.execution_arn}/*"
}

# -----------------------------------------------------------------------------
# WebSocket Routes & Integrations
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "ws_connect" {
  api_id             = aws_apigatewayv2_api.telemetry_ws.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.ws_handler.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "ws_connect" {
  api_id    = aws_apigatewayv2_api.telemetry_ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_connect.id}"
}

resource "aws_apigatewayv2_integration" "ws_disconnect" {
  api_id             = aws_apigatewayv2_api.telemetry_ws.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.ws_handler.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "ws_disconnect" {
  api_id    = aws_apigatewayv2_api.telemetry_ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_disconnect.id}"
}

resource "aws_apigatewayv2_integration" "ws_default" {
  api_id             = aws_apigatewayv2_api.telemetry_ws.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.ws_handler.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "ws_default" {
  api_id    = aws_apigatewayv2_api.telemetry_ws.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.ws_default.id}"
}

# -----------------------------------------------------------------------------
# Stage & Deployment
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_stage" "ws_stage" {
  api_id      = aws_apigatewayv2_api.telemetry_ws.id
  name        = var.environment
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  tags = {
    Component = "Telemetry"
  }
}

# -----------------------------------------------------------------------------
# IAM policy for Lambda stages to post to WebSocket connections
# (Attach this to the main Lambda execution role)
# -----------------------------------------------------------------------------
resource "aws_iam_policy" "telemetry_broadcast" {
  name        = "migrate4hana-telemetry-broadcast-${var.environment}"
  description = "Allows Lambda migration stages to push logs to WebSocket clients"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["execute-api:ManageConnections"]
        Resource = "${aws_apigatewayv2_api.telemetry_ws.execution_arn}/${var.environment}/POST/@connections/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Scan",
          "dynamodb:GetItem"
        ]
        Resource = aws_dynamodb_table.ws_connections.arn
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "websocket_url" {
  value       = "${aws_apigatewayv2_api.telemetry_ws.api_endpoint}/${var.environment}"
  description = "WebSocket URL for frontend telemetry streaming"
}

output "websocket_api_id" {
  value       = aws_apigatewayv2_api.telemetry_ws.id
  description = "API Gateway WebSocket API ID"
}

output "connections_table_name" {
  value       = aws_dynamodb_table.ws_connections.name
  description = "DynamoDB table tracking active WebSocket connections"
}

output "telemetry_broadcast_policy_arn" {
  value       = aws_iam_policy.telemetry_broadcast.arn
  description = "IAM policy ARN to attach to Lambda roles for WebSocket broadcasting"
}

output "management_endpoint" {
  value       = "https://${aws_apigatewayv2_api.telemetry_ws.id}.execute-api.${var.region}.amazonaws.com/${var.environment}"
  description = "API Gateway Management API endpoint for post_to_connection calls"
}
