<#
.SYNOPSIS
  Build the pyrfc Lambda layer in Docker (Amazon Linux 2023) so the wheel + .so
  match the Lambda runtime exactly. PowerShell equivalent of the bash script in
  PREREQUISITES §4.

.DESCRIPTION
  Production-grade path: bring your own SAP NW RFC SDK 7.50 (Linux x86_64) as a
  `nwrfc750P_*.zip` placed in this directory. The script runs Amazon Linux 2023
  in Docker, installs python3.11 + build tooling, compiles/installs pyrfc
  against the SDK, copies the SDK .so files into the layer's lib/, and zips
  the layer as `pyrfc-layer.zip` in this directory.

.PREREQUISITES
  - Docker Desktop installed and running on Windows.
  - A nwrfc750P_*.zip in the current (layer-build/) directory.
  - Internet access for `dnf install` + `pip install pyrfc`.

.USAGE
  cd layer-build
  .\build_pyrfc_layer.ps1
  # If execution policy blocks the script:
  #   powershell -ExecutionPolicy Bypass -File .\build_pyrfc_layer.ps1
#>

$ErrorActionPreference = "Stop"

# ── 1. locate the SAP SDK zip in the current directory ────────────────────
$sdkZip = Get-ChildItem -Filter "nwrfc750P_*.zip" | Select-Object -First 1
if (-not $sdkZip) {
    Write-Error @"
No nwrfc750P_*.zip found in $((Get-Location).Path).
Download the SAP NW RFC SDK 7.50 (Linux on x86_64 64bit) from
https://support.sap.com/swdc -> 'SAP NW RFC SDK 7.50' (needs an S-User)
and drop the zip into this directory, then re-run.
"@
    exit 1
}
Write-Host "Using SDK: $($sdkZip.Name)" -ForegroundColor Cyan

# ── 2. verify Docker is available ────────────────────────────────────────
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "docker info failed" }
}
catch {
    Write-Error "Docker is not running or not installed. Start Docker Desktop and try again."
    exit 1
}

# ── 3. the bash payload that runs inside the container ───────────────────
# Single-quoted here-string so PowerShell doesn't expand $vars; the bash side
# reads $SDK_ZIP from the environment we pass via `docker run -e`.
$bashPayload = @'
set -e
echo "[layer-build] installing build tooling..."
dnf -y -q install python3.11 python3.11-pip python3.11-devel gcc gcc-c++ make unzip zip

rm -rf build && mkdir -p build/python build/lib

echo "[layer-build] extracting SAP NW RFC SDK..."
unzip -q -o "$SDK_ZIP" -d /opt/sap
if [ -d /opt/sap/nwrfcsdk ]; then cp -r /opt/sap/nwrfcsdk/* /opt/sap/; fi

echo "[layer-build] installing pyrfc against the SDK..."
export SAPNWRFC_HOME=/opt/sap
export LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH
python3.11 -m pip install --quiet --target build/python pyrfc

echo "[layer-build] copying SDK .so files into layer's lib/..."
cp -r /opt/sap/lib/* build/lib/

echo "[layer-build] zipping layer..."
cd build && zip -qr ../pyrfc-layer.zip python lib
echo "[layer-build] done."
'@

# ── 4. run the container; mount cwd as /work, pass SDK filename via env ──
docker run --rm `
    -v "${PWD}:/work" `
    -w /work `
    -e "SDK_ZIP=$($sdkZip.Name)" `
    public.ecr.aws/amazonlinux/amazonlinux:2023 `
    bash -c $bashPayload

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed (exit code $LASTEXITCODE)."
    exit $LASTEXITCODE
}

# ── 5. report success ────────────────────────────────────────────────────
if (Test-Path "pyrfc-layer.zip") {
    $sizeMB = [math]::Round((Get-Item pyrfc-layer.zip).Length / 1MB, 1)
    Write-Host ""
    Write-Host "built: $((Get-Location).Path)\pyrfc-layer.zip ($sizeMB MB)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next step:" -ForegroundColor Yellow
    Write-Host "  cd ..\terraform\environments\prod"
    Write-Host "  terraform apply    # Terraform auto-detects the zip and publishes the layer"
} else {
    Write-Error "Build appears to have failed -- pyrfc-layer.zip was not created."
    exit 1
}
