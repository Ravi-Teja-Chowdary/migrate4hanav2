#requires -Version 5.1
<#
.SYNOPSIS
    Sync the S/4HANA public IP and local ECC IP across the repo in one shot.

.DESCRIPTION
    Saves you from hunting for which file holds which IP every time CAL drifts
    or your laptop VMnet flips. Reads the current values, prompts for new ones
    (press Enter to keep the current value), and updates:

      * terraform/environments/prod/terraform.tfvars   (s4_public_ip)
      * scripts/launch-ecc-tunnel.ps1                  ($EccHost default)
      * scripts/update-ecc-secret.ps1                  (NEXT-STEPS example line)
      * scripts/update-s4-secret.ps1                   (.EXAMPLE comment)
      * scripts/update-cal-ecc-secret.ps1              (.EXAMPLE comments)

    Also handles the most-drift case: ngrok's random TCP port on every restart.
    The script auto-detects the running ngrok tunnel from its local API
    (http://127.0.0.1:4040) and chains into update-ngrok-ecc-secret.ps1 so the
    AWS sap-credentials secret stays in sync. You'll be prompted for the local
    ECC password once during that chained step.

    After running, the script prints the next commands you typically need
    (terraform apply, update-s4-secret, smoke test) with the new IPs inlined.

.PARAMETER S4PublicIp
    New S/4HANA CAL public IP. If omitted, the script prompts.

.PARAMETER EccLocalIp
    New local Windows ECC IP (the IP your laptop sees on the host-only VMnet,
    typically 192.168.100.x). If omitted, the script prompts.

.PARAMETER NgrokHost
    ngrok public hostname (e.g. 0.tcp.in.ngrok.io). If omitted, auto-detected
    from http://127.0.0.1:4040, or you'll be prompted.

.PARAMETER NgrokPort
    ngrok public TCP port (changes on every ngrok restart). If 0/omitted,
    auto-detected, or you'll be prompted.

.PARAMETER SkipNgrok
    Skip the ngrok secret update entirely (e.g. when you only want to refresh
    file-based defaults without touching AWS).

.PARAMETER NonInteractive
    Skip prompts even when a value is missing - use only when all needed
    parameters are explicitly passed.

.EXAMPLE
    .\scripts\sync-ips.ps1
    # Prompts for IPs (current values shown as defaults). Auto-detects running
    # ngrok and pushes the secret if a tunnel is up.

.EXAMPLE
    .\scripts\sync-ips.ps1 -S4PublicIp 18.234.1.50 -EccLocalIp 192.168.100.148 `
                           -NgrokHost 0.tcp.in.ngrok.io -NgrokPort 25192
    # Fully explicit; still prompts for the ECC password during the secret update.

.EXAMPLE
    .\scripts\sync-ips.ps1 -SkipNgrok
    # Update file defaults only, leave the AWS secret alone.
#>
[CmdletBinding()]
param(
    [string]$S4PublicIp = "",
    [string]$EccLocalIp = "",
    [string]$NgrokHost  = "",
    [int]   $NgrokPort  = 0,
    [switch]$SkipNgrok,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

function Write-Step  { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Skip  { param([string]$m) Write-Host "    $m" -ForegroundColor DarkGray }
function Write-Done  { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn  { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }

# ── Resolve repo + canonical file paths ──────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$tfvars    = Join-Path $repoRoot "terraform\environments\prod\terraform.tfvars"
$launchPs1 = Join-Path $scriptDir "launch-ecc-tunnel.ps1"
$updEcc    = Join-Path $scriptDir "update-ecc-secret.ps1"
$updS4     = Join-Path $scriptDir "update-s4-secret.ps1"
$updCal    = Join-Path $scriptDir "update-cal-ecc-secret.ps1"

# ── IPv4 validation ──────────────────────────────────────────────────────────
function Test-IPv4 {
    param([string]$ip)
    if (-not $ip) { return $false }
    return $ip -match '^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$'
}

# ── Read CURRENT values so we can show defaults ──────────────────────────────
Write-Step "Reading current values"

# Current S/4 IP - from tfvars
$currentS4 = $null
if (Test-Path $tfvars) {
    $m = (Get-Content $tfvars | Select-String -Pattern '^\s*s4_public_ip\s*=\s*"([^"]+)"').Matches
    if ($m.Count -gt 0) { $currentS4 = $m[0].Groups[1].Value }
}
$disp = if ($currentS4) { $currentS4 } else { '(not set)' }
Write-Host "    current S/4 public IP (tfvars):  $disp"

# Current ECC IP - from launch-ecc-tunnel.ps1 $EccHost default
$currentEcc = $null
if (Test-Path $launchPs1) {
    $m = (Get-Content $launchPs1 | Select-String -Pattern '\$EccHost\s*=\s*"([^"]+)"').Matches
    if ($m.Count -gt 0) { $currentEcc = $m[0].Groups[1].Value }
}
$disp = if ($currentEcc) { $currentEcc } else { '(not set)' }
Write-Host "    current local ECC IP (launch script default):  $disp"

# ── Prompt for new values (or use parameters) ────────────────────────────────
Write-Step "Collect new values"

function Read-IP {
    param([string]$label, [string]$current, [string]$preset, [switch]$Required)
    if ($preset) {
        if (-not (Test-IPv4 $preset)) {
            Write-Host "ERROR: '$preset' is not a valid IPv4 address" -ForegroundColor Red
            exit 1
        }
        Write-Host "    $label = $preset (from -parameter)"
        return $preset
    }
    if ($NonInteractive) {
        if ($Required -and -not $current) {
            Write-Host "ERROR: NonInteractive but no value for $label and no current value" -ForegroundColor Red
            exit 1
        }
        return $current
    }
    while ($true) {
        if ($current) { $prompt = "    $label [" + $current + "]" } else { $prompt = "    $label" }
        $val = Read-Host $prompt
        if (-not $val -and $current) { return $current }
        if (-not $val -and -not $current) { Write-Host "    (required)" -ForegroundColor Yellow; continue }
        if (Test-IPv4 $val) { return $val }
        Write-Host "    not a valid IPv4 address - try again" -ForegroundColor Yellow
    }
}

$newS4  = Read-IP -label "S/4HANA public IP"  -current $currentS4  -preset $S4PublicIp -Required
$newEcc = Read-IP -label "Local ECC IP"       -current $currentEcc -preset $EccLocalIp -Required

# ── Confirm before mutating files ────────────────────────────────────────────
Write-Step "Plan"
$dispS4  = if ($currentS4)  { $currentS4 }  else { '(none)' }
$dispEcc = if ($currentEcc) { $currentEcc } else { '(none)' }
Write-Host "    S/4 public IP:  $dispS4  ->  $newS4"
Write-Host "    Local ECC IP:   $dispEcc  ->  $newEcc"
$ipsUnchanged = ($currentS4 -eq $newS4 -and $currentEcc -eq $newEcc)
if ($ipsUnchanged) {
    Write-Host "`n    IPs already match - file edits will be skipped." -ForegroundColor DarkGray
    Write-Host "    (ngrok sync still runs below since the ngrok port drifts on every restart.)" -ForegroundColor DarkGray
} elseif (-not $NonInteractive) {
    $ok = Read-Host "`n    Apply these file updates? [Y/n]"
    if ($ok -and $ok.ToLower() -notin @("y", "yes")) {
        Write-Host "    File updates aborted (continuing to ngrok step)." -ForegroundColor Yellow
        $ipsUnchanged = $true   # skip file edits but stay in the script
    }
}

# ── Apply edits ──────────────────────────────────────────────────────────────
if (-not $ipsUnchanged) {
    Write-Step "Updating files"
}

function Update-FileContent {
    param([string]$path, [string]$pattern, [string]$replacement, [string]$label)
    if (-not (Test-Path $path)) {
        Write-Skip "${label}: file not found - skipped"
        return $false
    }
    $orig = Get-Content $path -Raw
    $new  = [regex]::Replace($orig, $pattern, $replacement)
    if ($new -eq $orig) {
        Write-Skip "${label}: nothing matched the pattern - skipped"
        return $false
    }
    Set-Content -Path $path -Value $new -NoNewline
    Write-Done "${label}: updated"
    return $true
}

# 1. tfvars - s4_public_ip
if ($currentS4 -ne $newS4) {
    [void](Update-FileContent `
        -path $tfvars `
        -pattern '(?m)^(\s*s4_public_ip\s*=\s*")[^"]+(")' `
        -replacement "`${1}$newS4`${2}" `
        -label "terraform.tfvars (s4_public_ip)")
}

# 2. launch-ecc-tunnel.ps1 - $EccHost default
if ($currentEcc -ne $newEcc) {
    [void](Update-FileContent `
        -path $launchPs1 `
        -pattern '(\$EccHost\s*=\s*")[^"]+(")' `
        -replacement "`${1}$newEcc`${2}" `
        -label "launch-ecc-tunnel.ps1 (`$EccHost default)")
    # Also update the docstring mentions of the old IP, since they'd now be misleading
    if ($currentEcc) {
        [void](Update-FileContent `
            -path $launchPs1 `
            -pattern [regex]::Escape($currentEcc) `
            -replacement $newEcc `
            -label "launch-ecc-tunnel.ps1 (docstring references)")
    }
}

# 3. update-ecc-secret.ps1 - NEXT-STEPS example line if it references the old IP
if ($currentEcc -ne $newEcc -and $currentEcc) {
    [void](Update-FileContent `
        -path $updEcc `
        -pattern [regex]::Escape($currentEcc) `
        -replacement $newEcc `
        -label "update-ecc-secret.ps1 (example references)")
}

# 4. update-s4-secret.ps1 - .EXAMPLE comment if it references the old IP
if ($currentS4 -ne $newS4 -and $currentS4) {
    [void](Update-FileContent `
        -path $updS4 `
        -pattern [regex]::Escape($currentS4) `
        -replacement $newS4 `
        -label "update-s4-secret.ps1 (example references)")
}

# 5. update-cal-ecc-secret.ps1 - comments often hold a sample CAL ECC IP
# (this script is for CAL, not local ECC, so don't touch it from -EccLocalIp;
# update it only if its examples reference the S/4 IP we just changed)
if ($currentS4 -ne $newS4 -and $currentS4) {
    [void](Update-FileContent `
        -path $updCal `
        -pattern [regex]::Escape($currentS4) `
        -replacement $newS4 `
        -label "update-cal-ecc-secret.ps1 (example references)")
}

# ── ngrok secret update (the most-drift one) ─────────────────────────────────
# ngrok TCP gives a random external port on every restart, so the AWS
# sap-credentials secret needs the new port pushed every session. We try to
# auto-detect from ngrok's local API (always at http://127.0.0.1:4040), and
# fall back to prompts if it's not running locally.
if (-not $SkipNgrok) {
    Write-Step "ngrok tunnel sync"

    $detectedHost = ""
    $detectedPort = 0
    try {
        $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2 -ErrorAction Stop
        foreach ($t in $tunnels.tunnels) {
            if ($t.proto -eq "tcp" -and $t.public_url) {
                # public_url is "tcp://0.tcp.in.ngrok.io:25192"
                if ($t.public_url -match '^tcp://([^:]+):(\d+)$') {
                    $detectedHost = $matches[1]
                    $detectedPort = [int]$matches[2]
                    Write-Host "    Detected running ngrok tunnel: ${detectedHost}:${detectedPort}" -ForegroundColor Green
                    Write-Host "      forwards to: $($t.config.addr)" -ForegroundColor DarkGray
                    break
                }
            }
        }
    } catch {
        Write-Host "    ngrok local API at 127.0.0.1:4040 not reachable (ngrok agent not running?)" -ForegroundColor DarkGray
    }

    # Choose final values: parameter > detected > prompt
    $finalNgrokHost = $NgrokHost
    $finalNgrokPort = $NgrokPort
    if (-not $finalNgrokHost) { $finalNgrokHost = $detectedHost }
    if ($finalNgrokPort -le 0) { $finalNgrokPort = $detectedPort }

    if (-not $finalNgrokHost -or $finalNgrokPort -le 0) {
        if (-not $NonInteractive) {
            $ans = Read-Host "    Push ngrok secret update now? [y/N]"
            if ($ans -and $ans.ToLower() -in @("y","yes")) {
                if (-not $finalNgrokHost) {
                    $finalNgrokHost = Read-Host "    ngrok host (e.g. 0.tcp.in.ngrok.io)"
                }
                if ($finalNgrokPort -le 0) {
                    while ($true) {
                        $p = Read-Host "    ngrok port (e.g. 25192)"
                        if ($p -match '^\d+$' -and [int]$p -gt 0 -and [int]$p -le 65535) {
                            $finalNgrokPort = [int]$p; break
                        }
                        Write-Host "    not a valid port - try again" -ForegroundColor Yellow
                    }
                }
            }
        }
    }

    if ($finalNgrokHost -and $finalNgrokPort -gt 0) {
        Write-Host "    Invoking update-ngrok-ecc-secret.ps1 with ${finalNgrokHost}:${finalNgrokPort}" -ForegroundColor Cyan
        Write-Host "    (you will be prompted for the local ECC password)" -ForegroundColor DarkGray
        $updScript = Join-Path $scriptDir "update-ngrok-ecc-secret.ps1"
        if (Test-Path $updScript) {
            & $updScript -NgrokHost $finalNgrokHost -NgrokPort $finalNgrokPort
        } else {
            Write-Host "    update-ngrok-ecc-secret.ps1 not found - skipped" -ForegroundColor Yellow
        }
    } else {
        Write-Host "    ngrok update skipped (no host/port available)" -ForegroundColor DarkGray
    }
}

# ── Print next-steps with IPs inlined ────────────────────────────────────────
Write-Step "NEXT STEPS - copy-paste in order"
Write-Host ""
Write-Host "  # 1. Apply terraform - refreshes Route 53 + NAT EIP outputs" -ForegroundColor DarkGray
Write-Host "  cd terraform\environments\prod"
Write-Host "  terraform apply -auto-approve"
Write-Host "  cd ..\..\..`n"

Write-Host "  # 2. Re-point S/4 secret + open S/4 SG to Lambda NAT EIP" -ForegroundColor DarkGray
Write-Host "  .\scripts\update-s4-secret.ps1 -S4PublicIp $newS4`n"

Write-Host "  # 3. Sanity-check Lambda can reach S/4 + local ECC paths" -ForegroundColor DarkGray
Write-Host "  Test-NetConnection $newS4 -Port 3300 -InformationLevel Quiet"
Write-Host "  Test-NetConnection $newEcc -Port 3341 -InformationLevel Quiet`n"

Write-Host "  # 4. Smoke-test the data-migrator end-to-end" -ForegroundColor DarkGray
Write-Host "  aws lambda invoke --region us-east-1 ``"
Write-Host "      --function-name migrate4hana-data-migrator-prod ``"
Write-Host "      --cli-binary-format raw-in-base64-out ``"
Write-Host "      --payload file://payload.json ngrok-smoke.json"
Write-Host "  Get-Content ngrok-smoke.json | ConvertFrom-Json | ConvertTo-Json -Depth 6`n"

Write-Host "==> Sync complete." -ForegroundColor Green
