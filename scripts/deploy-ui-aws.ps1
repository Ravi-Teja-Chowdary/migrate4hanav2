<#
.SYNOPSIS
    Deploy the Migrate4HANA UI + api-server to AWS.

.DESCRIPTION
    End-to-end deploy script for the customer-facing UI on AWS:

        1. terraform apply  (creates/updates ECR, ALB, Fargate, S3, CloudFront)
        2. docker build     (api_server image with bundled SAP NW RFC SDK)
        3. ECR login + push (image goes to migrate4hana-api-server-<env>)
        4. ECS force-new-deployment (rolls the Fargate service onto the new image)
        5. npm install + npm run build (React production bundle)
        6. aws s3 sync (uploads frontend/dist/ to the UI bucket)
        7. CloudFront invalidation (so users see new code immediately)
        8. Print the live URL.

    Idempotent. Re-run anytime you change UI or api_server code.

.PARAMETER Environment
    Terraform environment to target. Default 'prod'.

.PARAMETER SkipTerraform
    Skip steps 1 (terraform apply). Useful for UI-only or code-only redeploys
    when the infrastructure is already up.

.PARAMETER SkipUi
    Skip steps 5-7 (UI build/sync/invalidate). Useful for backend-only iteration.

.PARAMETER SkipApi
    Skip steps 2-4 (api-server build/push/redeploy). Useful for UI-only iteration.

.EXAMPLE
    pwsh scripts/deploy-ui-aws.ps1
    Full deploy from a clean checkout.

.EXAMPLE
    pwsh scripts/deploy-ui-aws.ps1 -SkipTerraform -SkipApi
    UI-only redeploy (fastest iteration loop after a React edit).

.EXAMPLE
    pwsh scripts/deploy-ui-aws.ps1 -SkipTerraform -SkipUi
    api-server-only redeploy (after a FastAPI edit).

.NOTES
    Prerequisites:
      - AWS CLI configured with credentials for the target account (905418407458)
      - Docker Desktop running
      - Terraform 1.5+
      - Node.js 18+ and npm
      - PowerShell 7 (pwsh)
#>

[CmdletBinding()]
param(
    [string]$Environment = 'prod',
    [switch]$SkipTerraform,
    [switch]$SkipUi,
    [switch]$SkipApi
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Note($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }
function Done($msg) { Write-Host "    $msg" -ForegroundColor Green }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TfDir = Join-Path $RepoRoot "terraform/environments/$Environment"
$FrontendDir = Join-Path $RepoRoot 'frontend'

if (-not (Test-Path $TfDir)) {
    throw "Terraform dir not found: $TfDir"
}

# ── 0. Sanity ──────────────────────────────────────────────────────────────
Step 0 "Sanity check"
$awsId = (aws sts get-caller-identity --query Account --output text 2>$null)
if (-not $awsId) { throw "AWS CLI not configured. Run 'aws configure' or set AWS_PROFILE." }
Note "AWS account: $awsId"
$region = (aws configure get region)
if (-not $region) { $region = 'us-east-1' }
Note "Region: $region"

# ── 1. Terraform ───────────────────────────────────────────────────────────
if (-not $SkipTerraform) {
    Step 1 "Terraform apply (ECR + Fargate + ALB + S3 + CloudFront)"
    Push-Location $TfDir
    try {
        Note "init..."
        terraform init -upgrade -input=false | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "terraform init failed (exit $LASTEXITCODE)" }
        Note "apply targeted to api_server + ui_hosting only..."
        # Use array splatting so PowerShell passes each arg as a single token —
        # backtick line continuation has been flaky with terraform's parser.
        $tfArgs = @(
            'apply', '-auto-approve',
            '-target=module.api_server',
            '-target=module.ui_hosting'
        )
        & terraform @tfArgs
        if ($LASTEXITCODE -ne 0) { throw "terraform apply failed (exit $LASTEXITCODE)" }
        Done "terraform apply complete"
    } finally {
        Pop-Location
    }
} else {
    Step 1 "Skipping terraform apply (-SkipTerraform)"
}

# Pull outputs once so we can reuse them
Step 'i' "Reading terraform outputs"
Push-Location $TfDir
$EcrUrl  = (terraform output -raw api_server_ecr_url).Trim()
$AlbDns  = (terraform output -raw api_server_alb_dns).Trim()
$EcsSvc  = (terraform output -raw api_server_ecs_service).Trim()
$Bucket  = (terraform output -raw ui_bucket_name).Trim()
$CfId    = (terraform output -raw ui_cloudfront_distribution_id).Trim()
$UiUrl   = (terraform output -raw ui_url).Trim()
Pop-Location
Note "ECR repo:          $EcrUrl"
Note "ALB DNS:           $AlbDns"
Note "ECS service:       $EcsSvc"
Note "UI S3 bucket:      $Bucket"
Note "CloudFront dist:   $CfId"
Note "UI URL:            $UiUrl"

$ImageTag = "ui-deploy-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$ImageRef = "${EcrUrl}:$ImageTag"
$EcrHost  = ($EcrUrl -split '/')[0]

# ── 2-4. api-server image build + push + redeploy ─────────────────────────
if (-not $SkipApi) {
    Step 2 "Docker build api-server image"
    Push-Location $RepoRoot
    try {
        $dockerArgs = @(
            'build',
            '-f', 'Dockerfile.api-server',
            '-t', "migrate4hana-api-server:$ImageTag",
            '-t', "${EcrUrl}:$ImageTag",
            '-t', "${EcrUrl}:latest",
            '.'
        )
        & docker @dockerArgs
        if ($LASTEXITCODE -ne 0) { throw "docker build failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Done "image built"

    Step 3 "ECR login + push"
    $loginPwd = (aws ecr get-login-password --region $region)
    if ($LASTEXITCODE -ne 0) { throw "aws ecr get-login-password failed" }
    $loginPwd | docker login --username AWS --password-stdin $EcrHost
    if ($LASTEXITCODE -ne 0) { throw "docker login failed (exit $LASTEXITCODE)" }
    docker push "${EcrUrl}:$ImageTag"
    if ($LASTEXITCODE -ne 0) { throw "docker push (tag) failed (exit $LASTEXITCODE)" }
    docker push "${EcrUrl}:latest"
    if ($LASTEXITCODE -ne 0) { throw "docker push (latest) failed (exit $LASTEXITCODE)" }
    Done "image pushed to $ImageRef"

    Step 4 "Force ECS Fargate redeploy"
    # Match the migrate4hana-<env> cluster created by module.ecs. We tried
    # 'migration' first; doesn't substring-match 'migrate4hana'.
    $clusterArn = (aws ecs list-clusters --query "clusterArns[?contains(@, 'migrate4hana')] | [0]" --output text).Trim()
    if (-not $clusterArn -or $clusterArn -eq 'None') {
        throw "Could not find an ECS cluster containing 'migrate4hana' in its ARN."
    }
    Note "cluster: $clusterArn"
    $ecsArgs = @(
        'ecs', 'update-service',
        '--cluster', $clusterArn,
        '--service', $EcsSvc,
        '--force-new-deployment',
        '--output', 'text'
    )
    & aws @ecsArgs > $null
    if ($LASTEXITCODE -ne 0) { throw "aws ecs update-service failed (exit $LASTEXITCODE)" }
    Done "ECS service $EcsSvc rolled (Fargate will pull new image)"
    Note "Watch rollout: aws ecs describe-services --cluster $clusterArn --services $EcsSvc --query 'services[0].deployments'"
} else {
    Step 2 "Skipping docker build / push / ECS redeploy (-SkipApi)"
}

# ── 5-7. React UI build + sync + invalidate ───────────────────────────────
if (-not $SkipUi) {
    Step 5 "Build React UI (npm install + npm run build)"
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path 'node_modules')) {
            Note "node_modules missing — running npm install…"
            npm install --no-audit --no-fund
        }
        npm run build
        if (-not (Test-Path 'dist')) {
            throw "npm run build produced no dist/ directory"
        }
    } finally {
        Pop-Location
    }
    Done "React build complete (frontend/dist/)"

    Step 6 "Sync frontend/dist/ to s3://$Bucket"
    $distPath = (Join-Path $FrontendDir 'dist')
    $syncArgs1 = @(
        's3', 'sync', $distPath, "s3://$Bucket",
        '--delete',
        '--cache-control', 'public,max-age=31536000,immutable',
        '--exclude', 'index.html',
        '--exclude', '*.html'
    )
    & aws @syncArgs1
    if ($LASTEXITCODE -ne 0) { throw "aws s3 sync (assets) failed (exit $LASTEXITCODE)" }
    # index.html stays no-cache so new deploys are visible immediately.
    $syncArgs2 = @(
        's3', 'sync', $distPath, "s3://$Bucket",
        '--exclude', '*',
        '--include', '*.html',
        '--cache-control', 'no-cache, no-store, must-revalidate'
    )
    & aws @syncArgs2
    if ($LASTEXITCODE -ne 0) { throw "aws s3 sync (html) failed (exit $LASTEXITCODE)" }
    Done "S3 sync complete"

    Step 7 "CloudFront invalidation"
    $invArgs = @(
        'cloudfront', 'create-invalidation',
        '--distribution-id', $CfId,
        '--paths', '/*',
        '--query', 'Invalidation.Id',
        '--output', 'text'
    )
    $invId = (& aws @invArgs).Trim()
    if ($LASTEXITCODE -ne 0) { throw "cloudfront invalidation failed (exit $LASTEXITCODE)" }
    Done "invalidation id: $invId (completes in ~1-2 min)"
} else {
    Step 5 "Skipping UI build / sync / invalidate (-SkipUi)"
}

# ── Done ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Migrate4HANA UI deployed" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Open this URL:" -ForegroundColor White
Write-Host "    $UiUrl" -ForegroundColor Yellow
Write-Host ""
Write-Host "  ALB origin (for debug):  http://$AlbDns/api/health" -ForegroundColor DarkGray
Write-Host "  ECS service:             $EcsSvc" -ForegroundColor DarkGray
Write-Host "  S3 bucket:               $Bucket" -ForegroundColor DarkGray
Write-Host "  CloudFront distribution: $CfId" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  CloudFront caches for ~1-2 min. If you don't see the new" -ForegroundColor DarkGray
Write-Host "  version, force-refresh the browser (Ctrl+F5)." -ForegroundColor DarkGray
Write-Host ""
