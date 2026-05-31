#requires -Version 5.1
<#
.SYNOPSIS
    Build + push the Migrate4HANA Fargate worker image to ECR in one command.

.DESCRIPTION
    Wraps the manual runbook (steps 1-6) for getting the heavy-compute Docker
    image into the AWS account so Fargate stages can pull it. Re-run after
    every `terraform apply` (ECR repo is destroyed/recreated with the stack).

.PARAMETER Tag
    Image tag to publish. Default: latest.

.PARAMETER Region
    AWS region. Default: us-east-1.

.PARAMETER RepoName
    ECR repository name. Default: migrate4hana/worker (matches the Terraform
    ecs module).

.PARAMETER SkipBuild
    Skip the docker build step (re-push an already-built local image).

.EXAMPLE
    .\scripts\push-fargate-image.ps1
    # Build + push :latest to migrate4hana/worker in us-east-1.

.EXAMPLE
    .\scripts\push-fargate-image.ps1 -Tag v2026-05-31 -SkipBuild
    # Re-tag the existing local image and push under a versioned tag.
#>
[CmdletBinding()]
param(
    [string]$Tag      = "latest",
    [string]$Region   = "us-east-1",
    [string]$RepoName = "migrate4hana/worker",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$startedAt = Get-Date

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# Repo root = parent of the scripts/ directory this file lives in
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

# ── Pre-flight ────────────────────────────────────────────────────────────────
Write-Step "Pre-flight checks"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "docker CLI not found in PATH. Install Docker Desktop and try again."
}
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Fail "aws CLI not found in PATH. Install AWS CLI v2 and try again."
}

# Docker must be running AND in Linux container mode (AL2023 base won't run on Windows containers)
try {
    $dockerInfo = docker info --format '{{.OSType}}' 2>&1
} catch {
    Fail "Docker daemon not reachable. Start Docker Desktop and wait for the whale icon to go solid."
}
if ($LASTEXITCODE -ne 0) {
    Fail "Docker daemon not reachable. Start Docker Desktop and wait for the whale icon to go solid."
}
if ($dockerInfo.Trim() -ne "linux") {
    Fail "Docker is in '$dockerInfo' container mode. Right-click the Docker tray icon -> 'Switch to Linux containers' and re-run."
}
Write-Host "  docker: linux containers OK"

# AWS credentials
$callerIdentity = aws sts get-caller-identity --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE."
}
$identity = $callerIdentity | ConvertFrom-Json
$account  = $identity.Account
Write-Host "  AWS account: $account  (user: $($identity.Arn))"

# SAP NW RFC SDK must be present in ecs/ - Dockerfile copies it into the build
$sdkZip = Get-ChildItem -Path (Join-Path $repoRoot "ecs") -Filter "nwrfc750P_*.zip" -ErrorAction SilentlyContinue
if (-not $sdkZip) {
    Fail @"
SAP NW RFC SDK zip missing from ecs/.
Download nwrfc750P_*-linux64bit.zip from SAP Support Portal (Software Downloads ->
SAP NW RFC SDK 7.50) and place it in: $($repoRoot)\ecs\
"@
}
Write-Host "  SAP SDK: $($sdkZip.Name) ($([math]::Round($sdkZip.Length / 1MB, 1)) MB)"

$ecrHost = "$account.dkr.ecr.$Region.amazonaws.com"
$ecrUri  = "$ecrHost/$RepoName"
Write-Host "  Target:  $ecrUri`:$Tag"

# ── ECR repo must exist (Terraform creates it) ────────────────────────────────
Write-Step "Verifying ECR repository exists"
aws ecr describe-repositories --repository-names $RepoName --region $Region --output text *> $null
if ($LASTEXITCODE -ne 0) {
    Fail @"
ECR repository '$RepoName' not found in $Region.
Run 'terraform apply' first (the ecs module creates this repo) and confirm the
ECS task definition is in the state with: terraform state list | Select-String ecr
"@
}
Write-Host "  Repository OK"

# ── ECR login ─────────────────────────────────────────────────────────────────
Write-Step "Logging in to ECR (token valid ~12h)"
$pw = aws ecr get-login-password --region $Region
if ($LASTEXITCODE -ne 0) { Fail "Failed to fetch ECR login password." }
$pw | docker login --username AWS --password-stdin $ecrHost
if ($LASTEXITCODE -ne 0) { Fail "docker login to $ecrHost failed." }

# ── Build ─────────────────────────────────────────────────────────────────────
if (-not $SkipBuild) {
    Write-Step "Building image (this takes 5-8 min the first time)"
    Write-Host "  Build context: $repoRoot"
    docker build -f ecs/Dockerfile -t "migrate4hana-worker:$Tag" .
    if ($LASTEXITCODE -ne 0) { Fail "docker build failed." }
} else {
    Write-Step "Skipping build (-SkipBuild). Verifying local image exists."
    $imgs = docker images --format '{{.Repository}}:{{.Tag}}' migrate4hana-worker
    if (-not ($imgs -split "`n" | Where-Object { $_ -eq "migrate4hana-worker:$Tag" })) {
        Fail "Local image migrate4hana-worker:$Tag not found. Drop -SkipBuild or build manually first."
    }
    Write-Host "  Found: migrate4hana-worker:$Tag"
}

# ── Tag + push ────────────────────────────────────────────────────────────────
Write-Step "Tagging + pushing to $ecrUri`:$Tag"
docker tag "migrate4hana-worker:$Tag" "${ecrUri}:$Tag"
if ($LASTEXITCODE -ne 0) { Fail "docker tag failed." }
docker push "${ecrUri}:$Tag"
if ($LASTEXITCODE -ne 0) { Fail "docker push failed." }

# ── Verify ────────────────────────────────────────────────────────────────────
Write-Step "Verifying push landed in ECR"
$pushedJson = aws ecr describe-images `
    --repository-name $RepoName `
    --image-ids "imageTag=$Tag" `
    --region $Region `
    --output json
if ($LASTEXITCODE -ne 0) { Fail "Could not describe pushed image." }
$pushed = ($pushedJson | ConvertFrom-Json).imageDetails[0]
$sizeMb = [math]::Round($pushed.imageSizeInBytes / 1MB, 1)
Write-Host "  Pushed:  tag=$($pushed.imageTags[0])  size=${sizeMb}MB  digest=$($pushed.imageDigest.Substring(0,19))..."
Write-Host "  PushedAt: $($pushed.imagePushedAt)"

# ── Warn about running tasks (won't auto-pull new image) ──────────────────────
Write-Step "Checking for running Fargate tasks (they will not auto-pull the new image)"
$cluster = "migrate4hana-prod"
$taskArnsRaw = aws ecs list-tasks --cluster $cluster --region $Region --query "taskArns" --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $taskArnsRaw -and $taskArnsRaw.Trim() -ne "None") {
    $taskArns = $taskArnsRaw -split "\s+"
    Write-Host "  WARNING: $($taskArns.Count) task(s) currently running in cluster '$cluster'." -ForegroundColor Yellow
    Write-Host "  Stop them so the next start uses the new image:" -ForegroundColor Yellow
    foreach ($arn in $taskArns) {
        Write-Host "    aws ecs stop-task --cluster $cluster --task $arn --region $Region" -ForegroundColor Yellow
    }
} else {
    Write-Host "  No running tasks in cluster '$cluster' (or cluster not deployed yet) - new starts will pull the new image."
}

$elapsed = (Get-Date) - $startedAt
Write-Host ""
Write-Host "Done in $([math]::Round($elapsed.TotalSeconds, 1))s.  Fargate stages (1, 5, 12, 12A) will now pull ${ecrUri}:$Tag on next launch." -ForegroundColor Green
