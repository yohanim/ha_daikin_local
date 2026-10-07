<#
.SYNOPSIS
    Run the CI validations locally in throwaway Linux containers (WSL Containers / wslc).

.DESCRIPTION
    - hassfest: same image as the GitHub Action (ghcr.io/home-assistant/hassfest).
    - tests:    full pytest suite (Home Assistant harness) in a python:3.14 container,
                avoiding native-wheel builds on Windows.
    Containers are removed after each run (--rm). The repository is mounted read-write
    but bytecode/pytest caches are disabled so nothing Linux-specific is left behind.

.EXAMPLE
    ./scripts/validate-local.ps1              # hassfest + tests
    ./scripts/validate-local.ps1 -Only hassfest
#>
param(
    [ValidateSet("all", "hassfest", "tests")]
    [string]$Only = "all"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot/..").Path

if (-not (Get-Command wslc -ErrorAction SilentlyContinue)) {
    throw "wslc not found: install/update WSL (wsl --install, then wsl --update)."
}

$failed = @()

if ($Only -in "all", "hassfest") {
    Write-Host "==> hassfest" -ForegroundColor Cyan
    wslc run --rm --pull always -v "${repo}:/github/workspace" ghcr.io/home-assistant/hassfest
    if ($LASTEXITCODE -ne 0) { $failed += "hassfest" }
}

if ($Only -in "all", "tests") {
    Write-Host "==> pytest (full, Home Assistant harness)" -ForegroundColor Cyan
    wslc run --rm --pull missing -v "${repo}:/src" -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.14 `
        sh -c "pip install -q --root-user-action=ignore -r requirements_test.txt && python -m pytest -q -p no:cacheprovider"
    if ($LASTEXITCODE -ne 0) { $failed += "tests" }
}

if ($failed) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All local validations passed." -ForegroundColor Green
