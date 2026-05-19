<#
.SYNOPSIS
Run all three e2e scenario suites.
Results are written to test-execution/ during the run, then conftest.py
moves each file to test-results/e2e/<suite>/<timestamp>-<suite>.xml on completion.
Must be run from riia-jun-release/ with the API server running on port 8000.
Each suite runs independently — a failure in one does NOT stop the others.
#>

if (-not (Test-Path -Path "test-execution")) {
    New-Item -ItemType Directory -Force -Path "test-execution" | Out-Null
}

$GlobalExitCode = 0

Write-Host "=== RITA scenarios ===" -ForegroundColor Cyan
pytest tests/e2e/test_rita_scenarios.py --junitxml=test-execution/e2e-rita.xml -v
if ($LASTEXITCODE -ne 0) { $GlobalExitCode = 1 }

Write-Host "=== FnO scenarios ===" -ForegroundColor Cyan
pytest tests/e2e/test_fno_scenarios.py --junitxml=test-execution/e2e-fno.xml -v
if ($LASTEXITCODE -ne 0) { $GlobalExitCode = 1 }

Write-Host "=== Ops scenarios ===" -ForegroundColor Cyan
pytest tests/e2e/test_ops_scenarios.py --junitxml=test-execution/e2e-ops.xml -v
if ($LASTEXITCODE -ne 0) { $GlobalExitCode = 1 }

Write-Host "=== Done. Results archived to test-results/e2e/ ===" -ForegroundColor Green
exit $GlobalExitCode
