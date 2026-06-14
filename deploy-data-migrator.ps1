# Bundle the data-migrator handler + all utils modules it actually imports,
# then push to Lambda. Without utils bundled, the handler's try/except wrappers
# silently degrade (logger -> no-op, KeyMap -> None, etc.), so things "work"
# but never actually use PersistentKeyMap, transformation_engine, bapi_loader
# and friends. With this deploy, the real code paths activate.
$build = "build-dm"
Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory $build | Out-Null

# Handler at the root of the zip
Copy-Item lambda\data-migrator\handler.py $build\

# All utils flat-copied alongside (lambda runtime root is on sys.path)
# Skip __pycache__ and any test-only files
Get-ChildItem lambda\utils\*.py -File |
    Where-Object { $_.Name -notmatch '^(test_|conftest)' } |
    Copy-Item -Destination $build\

# (Optional) include the local_aws_shim for any code that probes it
if (Test-Path lambda\utils\local_aws_shim.py) {
    Copy-Item lambda\utils\local_aws_shim.py $build\ -Force
}

# Scaffolder runtime: dq_rules/ package. The generated spines import from
# `dq_rules.<rule>` so this subpackage MUST ship with the zip. Without it
# the spine's "from dq_rules.X import X" line raises ModuleNotFoundError
# at cold start and the spine fails to register.
if (Test-Path lambda\utils\dq_rules) {
    Copy-Item -Recurse -Force lambda\utils\dq_rules $build\
    Write-Host "==> dq_rules/ subpackage included" -ForegroundColor DarkCyan
} else {
    Write-Host "==> WARNING: lambda\utils\dq_rules not found. Generated spines that reference DQ rules will fail at import. Run: python -m scaffolder.build --sync-rules" -ForegroundColor Yellow
}

Write-Host "==> Files staged for zip:" -ForegroundColor Cyan
Get-ChildItem $build | Select-Object Name | Format-Table | Out-String | Write-Host

Compress-Archive -Path "$build\*" -DestinationPath data-migrator.zip -Force

Write-Host "==> Pushing to Lambda..." -ForegroundColor Cyan
aws lambda update-function-code `
    --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --zip-file fileb://data-migrator.zip

Write-Host ""
Write-Host "==> Done. Next: re-run the smoke test, then verify DynamoDB:" -ForegroundColor Green
Write-Host "  aws lambda invoke --region us-east-1 ``"
Write-Host "      --function-name migrate4hana-data-migrator-prod ``"
Write-Host "      --cli-binary-format raw-in-base64-out ``"
Write-Host "      --payload file://payload.json ngrok-smoke.json"
Write-Host "  Get-Content ngrok-smoke.json | ConvertFrom-Json | ConvertTo-Json -Depth 6"
Write-Host ""
Write-Host "  # After the smoke returns row_count > 0, check DDB for key-map items:"
Write-Host "  aws dynamodb scan --region us-east-1 ``"
Write-Host "      --table-name migrate4hana-key-map-prod ``"
Write-Host "      --max-items 5 --output table"
