# Build payload.json programmatically — no manual paste = no embedded newlines
$p = @{}
$p.run_id           = "ngrok-smoke-001"
$p.object           = "Customer"
$bkt                = "migrate4hana-staging-prod"
$key                = "runs/ngrok-smoke-001/data-migrator/mc/Customer.csv"
$p.template_s3_uri  = "s3://$bkt/$key"
$p.target_creds_arn = "migrate4hana/prod/s4hana-credentials"
$p.mc_project       = "M4H_LIFT_AND_SHIFT"
$p.mc_mode          = "simulate"
$p.runbook_only     = $false

# ConvertTo-Json -Compress = single line, well-formed JSON
($p | ConvertTo-Json -Compress) | Out-File -Encoding ASCII payload.json

Write-Host "==> payload.json contents:" -ForegroundColor Cyan
Get-Content payload.json
Write-Host ""

# Invoke the orchestrator Lambda
Write-Host "==> Invoking orchestrator..." -ForegroundColor Cyan
aws lambda invoke `
    --region us-east-1 `
    --function-name migrate4hana-migration-cockpit-orchestrator-prod `
    --cli-binary-format raw-in-base64-out `
    --payload file://payload.json `
    mc-runbook.json

Write-Host ""
Write-Host "==> Lambda response:" -ForegroundColor Cyan
Get-Content mc-runbook.json | ConvertFrom-Json | ConvertTo-Json -Depth 6
