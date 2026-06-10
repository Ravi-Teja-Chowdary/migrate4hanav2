#requires -Version 5.1
<#
.SYNOPSIS
  Re-package every migrate4hana Lambda whose handler imports lambda/utils/*
  symbols so the utils sit alongside the handler in the zip.

.DESCRIPTION
  The terraform lambda module zips each `source_dir` in isolation with
  `data.archive_file`, but most handlers do `from logger import ...` and
  similar — those modules live in `lambda/utils/`. Without this script
  every freshly-applied Lambda lands as ~6 KB and crashes at cold start
  with `Runtime.ImportModuleError: No module named 'logger'`.

  Run this AFTER `terraform apply` and AFTER any manual handler edit
  that needs to be re-shipped. Idempotent.

.PARAMETER Env
  Deploy environment suffix (default: prod). Function names become
  migrate4hana-<key>-<env>.

.PARAMETER OnlyMissing
  Only re-deploy Lambdas whose current CodeSize is < 50 KB (a stale-
  zip heuristic). Default: false (rebuild everything).

.EXAMPLE
  ./scripts/package-lambdas-with-utils.ps1 -Env prod
  ./scripts/package-lambdas-with-utils.ps1 -Env prod -OnlyMissing
#>
param(
  [string]$Env = "prod",
  [switch]$OnlyMissing
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..").Path
$utilsDir = Join-Path $repo "lambda\utils"
$buildRoot = Join-Path $repo ".deploy-tmp\rebuild"

if (-not (Test-Path $utilsDir)) { throw "utils dir not found: $utilsDir" }
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

# Discover which Lambdas import a bare utils module name.
$utilModules = @("logger","validation","rfc_pool","sap_fields","reconciler",
                 "persistent_key_map","telemetry","data_scrubber")
$pattern = "^from (" + ($utilModules -join "|") + ")\b"
$lambdas = @()
foreach ($d in (Get-ChildItem (Join-Path $repo "lambda") -Directory)) {
  $h = Join-Path $d.FullName "handler.py"
  if (-not (Test-Path $h)) { continue }
  $hit = Select-String -Path $h -Pattern $pattern -Quiet
  if ($hit) { $lambdas += $d.Name }
}
Write-Host "[$($lambdas.Count)] handlers need utils bundled."

foreach ($name in $lambdas) {
  $fn = "migrate4hana-$name-$Env"
  if ($OnlyMissing) {
    $size = (aws lambda get-function-configuration --function-name $fn --region us-east-1 --query "CodeSize" --output text 2>$null)
    if ($size -and [int]$size -ge 50000) { Write-Host "  $fn ($size B) - already bundled, skip"; continue }
  }
  $stage = Join-Path $buildRoot $name
  Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $stage | Out-Null
  Copy-Item (Join-Path $repo "lambda\$name\*") -Destination $stage -Recurse -Force -Exclude "__pycache__"
  Copy-Item (Join-Path $utilsDir "*.py") -Destination $stage -Force
  Remove-Item -Recurse -Force (Join-Path $stage "__pycache__") -ErrorAction SilentlyContinue
  $zip = Join-Path $buildRoot "$name.zip"
  if (Test-Path $zip) { Remove-Item $zip -Force }
  Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
  $out = aws lambda update-function-code --function-name $fn --zip-file "fileb://$zip" --region us-east-1 --query "[FunctionName,CodeSize]" --output text 2>&1
  Write-Host "  $out"
}
Write-Host "done."
