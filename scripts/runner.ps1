<#
.SYNOPSIS
    Shortify developer automation script for Windows PowerShell.
.DESCRIPTION
    Provides unified commands matching the Makefile targets for native Windows environments.
.EXAMPLE
    .\scripts\runner.ps1 test
    .\scripts\runner.ps1 lint
    .\scripts\runner.ps1 typecheck
    .\scripts\runner.ps1 run
#>

param (
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet("install", "run", "test", "lint", "format", "typecheck", "security", "load-test", "benchmark", "up", "down", "clean")]
    [string]$Command
)

$ErrorActionPreference = "Stop"

# Auto-detect local virtualenv if present
$VenvBin = ""
if (Test-Path ".\.venv\Scripts\python.exe") {
    $VenvBin = ".\.venv\Scripts\"
}

function Invoke-VenvCmd([string]$Exe, [string[]]$CmdArgs) {
    $Target = if ($VenvBin -and (Test-Path "$VenvBin$Exe.exe")) { "$VenvBin$Exe.exe" } else { $Exe }
    & $Target $CmdArgs
}

switch ($Command) {
    "install" {
        Write-Host "Installing dependencies..." -ForegroundColor Cyan
        Invoke-VenvCmd "python" @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-VenvCmd "pip" @("install", "-e", ".[dev]")
    }
    "run" {
        Write-Host "Starting FastAPI development server on http://localhost:8000..." -ForegroundColor Cyan
        Invoke-VenvCmd "uvicorn" @("app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload")
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        Invoke-VenvCmd "pytest" @("tests/", "-v")
    }
    "lint" {
        Write-Host "Running Ruff lint..." -ForegroundColor Cyan
        Invoke-VenvCmd "ruff" @("check", "app", "tests", "load_tests", "scripts")
    }
    "format" {
        Write-Host "Running Ruff format verification..." -ForegroundColor Cyan
        Invoke-VenvCmd "ruff" @("format", "--check", "app", "tests", "load_tests", "scripts")
    }
    "typecheck" {
        Write-Host "Running mypy strict type checks..." -ForegroundColor Cyan
        Invoke-VenvCmd "mypy" @("app", "tests")
    }
    "security" {
        Write-Host "Running Bandit & pip-audit security scans..." -ForegroundColor Cyan
        Invoke-VenvCmd "bandit" @("-r", "app")
        Invoke-VenvCmd "pip-audit" @()
    }
    "load-test" {
        Write-Host "Running Locust load test..." -ForegroundColor Cyan
        Invoke-VenvCmd "locust" @("-f", "load_tests/locustfile.py", "--headless", "-u", "100", "-r", "10", "--run-time", "1m", "--host", "http://localhost:8000")
    }
    "benchmark" {
        Write-Host "Running benchmark suite..." -ForegroundColor Cyan
        Invoke-VenvCmd "python" @("scripts/run_benchmarks.py")
    }
    "up" {
        Write-Host "Starting Docker Compose services..." -ForegroundColor Cyan
        docker compose up -d
    }
    "down" {
        Write-Host "Stopping Docker Compose services..." -ForegroundColor Cyan
        docker compose down
    }
    "clean" {
        Write-Host "Cleaning cache directories..." -ForegroundColor Cyan
        Get-ChildItem -Path . -Include __pycache__, .pytest_cache, .ruff_cache, .mypy_cache -Recurse -Force | Remove-Item -Recurse -Force
        Write-Host "Clean completed." -ForegroundColor Green
    }
}
