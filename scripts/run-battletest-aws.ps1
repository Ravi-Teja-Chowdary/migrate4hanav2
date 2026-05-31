#requires -Version 5.1
<#
.SYNOPSIS
    Run the comprehensive battletest on your deployed AWS Migrate4HANA stack.

.DESCRIPTION
    One-command launcher. Generates synthetic SAP-shaped fixtures locally,
    uploads them to the S3 staging bucket, triggers a Fargate task on the
    deployed cluster, polls for completion, downloads the results JSON, and
    regenerates BATTLETEST_RESULTS.md.

    Prerequisites:
      1. terraform apply on terraform/environments/prod  (200 AWS resources)
      2. .\scripts\push-fargate-image.ps1                 (image to ECR)

    What runs WHERE:
      - Generation             : local (fast, no AWS cost)
      - Fixtures upload        : local -> S3 staging bucket
      - Orchestrator execution : FARGATE TASK on the deployed cluster
      - Trust spine modules    : execute INSIDE the Fargate container
      - Mock SAP target        : in-process inside the Fargate container
      - Results                : Fargate -> S3 -> local
      - Report                 : local from downloaded results

.PARAMETER Scale
    tiny | small | medium | large | xlarge   (default: small)
    See tests/battletest/generator.py for record counts per scale.

.PARAMETER Threads
    Concurrency inside the Fargate orchestrator (default: 16).

.PARAMETER IncludeCodeRemediation
    Run 100 synthetic ABAP programs through the remediator. Adds ~30 sec.

.PARAMETER Region
    AWS region. Default us-east-1.

.PARAMETER Environment
    Terraform environment. Default 'prod'.

.PARAMETER PollIntervalSeconds
    How often to check Fargate task status. Default 30.

.PARAMETER TimeoutMinutes
    Max wait for the Fargate task. Default 90.

.EXAMPLE
    .\scripts\run-battletest-aws.ps1 -Scale large -IncludeCodeRemediation
    # Full real-environment-scale proof run

.EXAMPLE
    .\scripts\run-battletest-aws.ps1 -Scale small
    # Quick AWS smoke test (~5 min)
#>
[CmdletBinding()]
param(
    [ValidateSet("tiny", "small", "medium", "large", "xlarge")]
    [string]$Scale = "small",
    [int]$Threads = 0,           # 0 = auto-pick per scale
    [switch]$IncludeCodeRemediation,
    [string]$Region = "us-east-1",
    [string]$Environment = "prod",
    [string]$Bucket = "",        # override if auto-discovery doesn't find the right bucket
    [int]$PollIntervalSeconds = 30,
    [int]$TimeoutMinutes = 0     # 0 = auto-pick per scale
)

# Scale-aware defaults so 'large' has enough threads + timeout headroom
$ScaleDefaults = @{
    tiny    = @{ Threads =  8;  TimeoutMinutes =  10 }
    small   = @{ Threads = 16;  TimeoutMinutes =  20 }
    medium  = @{ Threads = 32;  TimeoutMinutes =  60 }
    large   = @{ Threads = 64;  TimeoutMinutes = 180 }   # 5.5M records, ~2-3h
    xlarge  = @{ Threads = 64;  TimeoutMinutes = 720 }   # overnight
}
if ($Threads -eq 0)        { $Threads        = $ScaleDefaults[$Scale].Threads }
if ($TimeoutMinutes -eq 0) { $TimeoutMinutes = $ScaleDefaults[$Scale].TimeoutMinutes }

$ErrorActionPreference = "Stop"
$startedAt = Get-Date

function Write-Step { param([string]$Msg) Write-Host "`n==> $Msg" -ForegroundColor Cyan }
function Fail { param([string]$Msg) Write-Host "`nERROR: $Msg" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

# ── Pre-flight ────────────────────────────────────────────────────────────────
Write-Step "Pre-flight checks"

if (-not (Get-Command aws    -ErrorAction SilentlyContinue)) { Fail "aws CLI not in PATH"     }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python not in PATH"     }

$identity = aws sts get-caller-identity --output json | ConvertFrom-Json
$account  = $identity.Account
Write-Host "  AWS account: $account (user: $($identity.Arn))"

$cluster = "migrate4hana-$Environment"
$taskDefFamily = "migrate4hana-heavy-$Environment"
$containerName = "migration-worker"
$ecrUri = "$account.dkr.ecr.$Region.amazonaws.com/migrate4hana/worker:latest"

# Resolve the staging bucket name. Order:
#   0. -Bucket param (manual override)
#   1. `terraform output s3_staging_bucket` from the env directory (authoritative)
#   2. Fallback: discover from S3 by name pattern
$bucket = if ($Bucket) { $Bucket } else { $null }
$tfEnvDir = Join-Path $repoRoot "terraform\environments\$Environment"
if (-not $bucket -and (Test-Path $tfEnvDir)) {
    Push-Location $tfEnvDir
    try {
        $tfOut = terraform output -raw s3_staging_bucket 2>$null
        if ($LASTEXITCODE -eq 0 -and $tfOut -and $tfOut -notmatch "No outputs found") {
            $bucket = $tfOut.Trim()
        }
    } catch {}
    Pop-Location
}
if (-not $bucket) {
    # Discover by name pattern (handles both naming conventions: with + without account suffix)
    $candidates = aws s3api list-buckets --query "Buckets[?starts_with(Name, 'migrate4hana-staging-$Environment')].Name" --output text 2>$null
    if ($candidates) {
        $bucket = ($candidates -split "\s+" | Where-Object { $_ })[0]
    }
}
if (-not $bucket) {
    Fail "Could not resolve staging bucket. Tried -Bucket override, terraform output, and s3api list-buckets. Pass -Bucket manually."
}
Write-Host "  Cluster:        $cluster"
Write-Host "  Task def family:$taskDefFamily"
Write-Host "  Container name: $containerName"
Write-Host "  ECR image:      $ecrUri"
Write-Host "  Staging bucket: s3://$bucket"
Write-Host "  Scale:          $Scale (threads=$Threads, timeout=${TimeoutMinutes}min)"

# Verify the cluster exists
$clusterStatus = aws ecs describe-clusters --clusters $cluster --region $Region `
    --query "clusters[0].status" --output text 2>$null
if ($clusterStatus -ne "ACTIVE") {
    Fail "ECS cluster '$cluster' is not ACTIVE (status=$clusterStatus). Did you run terraform apply?"
}
Write-Host "  Cluster status: $clusterStatus"

# Verify the staging bucket is reachable
aws s3api head-bucket --bucket $bucket 2>$null
if ($LASTEXITCODE -ne 0) { Fail "S3 bucket s3://$bucket not reachable. Did terraform apply complete?" }

# Verify the base task definition exists (terraform creates a stub pointing at
# alpine:latest as a placeholder; we register a new revision below with the
# real ECR image).
$baseTaskDef = aws ecs describe-task-definition --task-definition $taskDefFamily `
    --region $Region --output json 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "Task definition family '$taskDefFamily' not registered. Did terraform apply complete?"
}
$baseTaskDefObj = $baseTaskDef | ConvertFrom-Json
Write-Host "  Base task def:  $($baseTaskDefObj.taskDefinition.taskDefinitionArn)"

# Verify the ECR image exists (you ran push-fargate-image.ps1 first, right?)
aws ecr describe-images --repository-name migrate4hana/worker `
    --image-ids "imageTag=latest" --region $Region --output text *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "ECR image $ecrUri not found. Run .\scripts\push-fargate-image.ps1 first."
}
Write-Host "  ECR image OK"

# ── Step 1: Generate fixtures locally ────────────────────────────────────────
Write-Step "Step 1/5 — Generate synthetic SAP-shaped fixtures (scale=$Scale) locally"
python tests/battletest/generator.py --scale $Scale
if ($LASTEXITCODE -ne 0) { Fail "generator.py failed" }

if ($IncludeCodeRemediation) {
    python tests/battletest/abap_generator.py --count 100
    if ($LASTEXITCODE -ne 0) { Fail "abap_generator.py failed" }
}

# ── Step 2: Upload fixtures to S3 ────────────────────────────────────────────
Write-Step "Step 2/5 — Upload fixtures to S3"
$s3FixPrefix = "battletest/scale-$Scale/"
$localFixDir = "tests/battletest/fixtures/scale-$Scale"

aws s3 sync $localFixDir "s3://$bucket/$s3FixPrefix" --region $Region --no-progress
if ($LASTEXITCODE -ne 0) { Fail "S3 fixtures upload failed" }
Write-Host "  Uploaded to s3://$bucket/$s3FixPrefix"

if ($IncludeCodeRemediation) {
    $s3AbapPrefix = "battletest/abap-suite/"
    aws s3 sync "tests/battletest/abap-suite" "s3://$bucket/$s3AbapPrefix" --region $Region --no-progress
    if ($LASTEXITCODE -ne 0) { Fail "S3 ABAP suite upload failed" }
    Write-Host "  Uploaded ABAP suite to s3://$bucket/$s3AbapPrefix"
}

# ── Step 3: Get networking config from the existing prod stack ───────────────
Write-Step "Step 3/5 — Resolve VPC networking for Fargate"

# First find the VPC by Name tag so we can filter subnets + SGs by vpc_id
# (much more reliable than guessing tag patterns)
$vpcId = aws ec2 describe-vpcs --region $Region `
    --filters "Name=tag:Name,Values=migrate4hana-$Environment" `
    --query "Vpcs[0].VpcId" --output text 2>$null
if (-not $vpcId -or $vpcId -eq "None") {
    Fail "Could not find VPC tagged Name=migrate4hana-$Environment. Did terraform apply complete?"
}
Write-Host "  VPC: $vpcId"

# Private subnets - terraform names them migrate4hana-private-<index>-<env>
$subnets = aws ec2 describe-subnets --region $Region `
    --filters "Name=vpc-id,Values=$vpcId" `
              "Name=tag:Name,Values=migrate4hana-private-*-$Environment" `
    --query "Subnets[].SubnetId" --output text
if (-not $subnets) {
    Fail "Could not find private subnets in $vpcId tagged migrate4hana-private-*-$Environment"
}
$subnetList = $subnets -split "\s+" | Where-Object { $_ }
Write-Host "  Subnets: $($subnetList -join ', ')"

# ECS security group - terraform creates with name_prefix migrate4hana-ecs-
$sg = aws ec2 describe-security-groups --region $Region `
    --filters "Name=vpc-id,Values=$vpcId" `
              "Name=group-name,Values=migrate4hana-ecs-*" `
    --query "SecurityGroups[0].GroupId" --output text
if (-not $sg -or $sg -eq "None") { Fail "ECS security group not found in $vpcId" }
Write-Host "  Security group: $sg"

# ── Step 4a: Register a new task definition revision pointing at the real ECR image
Write-Step "Step 4a/6 — Register a fresh task definition revision pointing at the ECR image"

# Pull the existing task def (terraform stub or previous revision), swap the
# image field to the real ECR URI, register as a new revision.
$baseDef = $baseTaskDefObj.taskDefinition
$container = $baseDef.containerDefinitions[0]
$container.image = $ecrUri

# Build the register-task-definition payload (only the writable fields)
$registerPayload = @{
    family                  = $baseDef.family
    networkMode             = $baseDef.networkMode
    cpu                     = $baseDef.cpu
    memory                  = $baseDef.memory
    requiresCompatibilities = @($baseDef.requiresCompatibilities)
    executionRoleArn        = $baseDef.executionRoleArn
    taskRoleArn             = $baseDef.taskRoleArn
    containerDefinitions    = $baseDef.containerDefinitions
}

$registerJsonPath = Join-Path $env:TEMP "battletest-taskdef-$([guid]::NewGuid()).json"
$registerPayload | ConvertTo-Json -Depth 20 | Set-Content -Path $registerJsonPath -Encoding utf8

$registered = aws ecs register-task-definition --region $Region `
    --cli-input-json "file://$registerJsonPath" --output json | ConvertFrom-Json
Remove-Item -Path $registerJsonPath -Force -ErrorAction SilentlyContinue

if (-not $registered.taskDefinition.taskDefinitionArn) {
    Fail "register-task-definition failed - see error above"
}
$activeTaskDefArn = $registered.taskDefinition.taskDefinitionArn
Write-Host "  Registered: $activeTaskDefArn"

# ── Step 4b: Trigger Fargate task ────────────────────────────────────────────
Write-Step "Step 4b/6 — Launch Fargate battletest task"

$envOverrides = @(
    @{ name = "M4H_MODE";                            value = "battletest" }
    @{ name = "M4H_BATTLETEST_SCALE";                value = $Scale }
    @{ name = "M4H_BATTLETEST_S3_BUCKET";            value = $bucket }
    @{ name = "M4H_BATTLETEST_S3_FIXTURES_PREFIX";   value = $s3FixPrefix }
    @{ name = "M4H_BATTLETEST_S3_ABAP_PREFIX";       value = "battletest/abap-suite/" }
    @{ name = "M4H_BATTLETEST_S3_RESULTS_PREFIX";    value = "battletest/results/" }
    @{ name = "M4H_BATTLETEST_THREADS";              value = "$Threads" }
    @{ name = "M4H_BATTLETEST_CODE_REM";             value = $(if ($IncludeCodeRemediation) {"1"} else {"0"}) }
)

$overridesJson = @{
    containerOverrides = @(
        @{
            name        = $containerName
            environment = $envOverrides
        }
    )
} | ConvertTo-Json -Depth 5 -Compress

$networkJson = @{
    awsvpcConfiguration = @{
        subnets          = $subnetList
        securityGroups   = @($sg)
        assignPublicIp   = "DISABLED"
    }
} | ConvertTo-Json -Depth 5 -Compress

$runResp = aws ecs run-task --cluster $cluster --task-definition $activeTaskDefArn `
    --launch-type FARGATE --count 1 `
    --region $Region `
    --network-configuration $networkJson `
    --overrides $overridesJson `
    --output json | ConvertFrom-Json

if (-not $runResp.tasks) {
    Write-Host "Failures: $($runResp.failures | ConvertTo-Json -Depth 3)"
    Fail "Fargate run-task returned no task"
}
$taskArn = $runResp.tasks[0].taskArn
Write-Host "  Task launched: $taskArn"

# ── Step 5: Poll for completion ──────────────────────────────────────────────
Write-Step "Step 5/5 — Poll Fargate task (every ${PollIntervalSeconds}s, timeout ${TimeoutMinutes}min)"
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$lastStatus = ""
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollIntervalSeconds
    $task = aws ecs describe-tasks --cluster $cluster --tasks $taskArn `
        --region $Region --output json | ConvertFrom-Json
    $status = $task.tasks[0].lastStatus
    $elapsed = [int]((Get-Date) - $startedAt).TotalSeconds
    if ($status -ne $lastStatus) {
        Write-Host "  [${elapsed}s] status=$status"
        $lastStatus = $status
    }
    if ($status -eq "STOPPED") {
        $exitCode = $task.tasks[0].containers[0].exitCode
        $reason   = $task.tasks[0].stoppedReason
        Write-Host "  Stopped: exitCode=$exitCode reason=$reason"
        if ($exitCode -ne 0) {
            Write-Host "  Last 50 lines of CloudWatch log:"
            $logGroup = "/ecs/migrate4hana-$Environment"
            $taskId = $taskArn.Split("/")[-1]
            $logStream = "migration/$containerName/$taskId"
            aws logs get-log-events --log-group-name $logGroup --log-stream-name $logStream `
                --region $Region --limit 50 --output text --query "events[].message" 2>$null
            Fail "Fargate task exited with code $exitCode"
        }
        break
    }
}
if ($lastStatus -ne "STOPPED") { Fail "Fargate task did not complete within $TimeoutMinutes min" }

# ── Step 6: Download results + generate report ───────────────────────────────
Write-Step "Step 6/6 — Download results from S3 + regenerate BATTLETEST_RESULTS.md"

$localResultsDir = "tests/battletest/results"
New-Item -ItemType Directory -Force -Path $localResultsDir | Out-Null
aws s3 sync "s3://$bucket/battletest/results/" $localResultsDir --region $Region --exclude "*" --include "*aws*.json" --no-progress

python tests/battletest/generate_report.py --results $localResultsDir --out BATTLETEST_RESULTS.md
if ($LASTEXITCODE -ne 0) { Fail "generate_report.py failed" }

$elapsed = (Get-Date) - $startedAt
Write-Host "`n$('='*78)" -ForegroundColor Green
Write-Host "BATTLETEST COMPLETE - took $([math]::Round($elapsed.TotalMinutes,1)) min total" -ForegroundColor Green
Write-Host "$('='*78)" -ForegroundColor Green
Write-Host "Report: BATTLETEST_RESULTS.md"
Write-Host "Raw results in S3: s3://$bucket/battletest/results/"
Write-Host "`nNext: open BATTLETEST_RESULTS.md and cite the headline numbers in your PITCH_DECK.md slide 8.5"
