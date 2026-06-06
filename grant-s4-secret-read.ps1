# Add inline IAM policy to the Lambda role so it can read the s4hana-credentials secret.
# This role is shared by all migrate4hana Lambdas in prod, so granting it once
# benefits the orchestrator + any future Lambda that needs s4 creds.

$Region   = "us-east-1"
$RoleName = "migrate4hana-lambda-prod"
$Secret   = "migrate4hana/prod/s4hana-credentials"

Write-Host "==> Resolving secret ARN for $Secret"
$arn = (aws secretsmanager describe-secret --region $Region `
        --secret-id $Secret --query ARN --output text).Trim()
if (-not $arn -or $arn -eq "None") {
    Write-Host "ERROR: secret '$Secret' not found. Run .\scripts\update-s4-secret.ps1 first." -ForegroundColor Red
    exit 1
}
Write-Host "    ARN: $arn"

# Inline policy granting GetSecretValue on the exact secret ARN.
# Use a wildcard suffix because AWS Secrets Manager appends a random 6-char hash.
$policy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],"Resource":"' + $arn + '"}]}'

Write-Host "==> Attaching inline policy 's4hana-credentials-read' to role $RoleName"
aws iam put-role-policy `
    --role-name $RoleName `
    --policy-name s4hana-credentials-read `
    --policy-document $policy

if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Done. IAM propagation can take 5-10 seconds." -ForegroundColor Green
    Write-Host "    Now re-run: .\invoke-orchestrator.ps1"
} else {
    Write-Host "ERROR: put-role-policy failed" -ForegroundColor Red
    exit 1
}
