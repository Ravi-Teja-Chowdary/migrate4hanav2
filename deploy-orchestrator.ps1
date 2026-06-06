# Build orchestrator zip with utils modules bundled at root level
$build = "build-orch"
Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory $build | Out-Null

# Copy handler + the two utils it imports (logger, sap_host_runner)
Copy-Item lambda\migration-cockpit-orchestrator\handler.py $build\
Copy-Item lambda\utils\logger.py $build\
Copy-Item lambda\utils\sap_host_runner.py $build\

Compress-Archive -Path "$build\*" -DestinationPath orchestrator.zip -Force

Write-Host "==> Pushing to Lambda..." -ForegroundColor Cyan
aws lambda update-function-code `
    --region us-east-1 `
    --function-name migrate4hana-migration-cockpit-orchestrator-prod `
    --zip-file fileb://orchestrator.zip

Write-Host "==> Done. Now run: .\invoke-orchestrator.ps1" -ForegroundColor Green
