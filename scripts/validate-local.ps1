<#
.SYNOPSIS
    Run the CI validations locally in throwaway Linux containers (WSL Containers / wslc).

.DESCRIPTION
    - hassfest: same image as the GitHub Action (ghcr.io/home-assistant/hassfest).
    - tests:    full pytest suite (Home Assistant harness) in a python:3.14 container,
                inside a virtualenv, avoiding native-wheel builds on Windows. Like CI it
                runs twice: "pinned" (requirements_test.txt, Core at the hacs.json floor)
                and "latest" (requirements_test_latest.txt, newest harness and Core).
    Containers are removed after each run (--rm). The repository is mounted read-write
    but bytecode/pytest caches are disabled so nothing Linux-specific is left behind.

.EXAMPLE
    ./scripts/validate-local.ps1                      # hassfest + tests (pinned and latest)
    ./scripts/validate-local.ps1 -Only hassfest
    ./scripts/validate-local.ps1 -Only tests -Harness latest
#>
param(
    [ValidateSet("all", "hassfest", "tests")]
    [string]$Only = "all",
    [ValidateSet("both", "pinned", "latest")]
    [string]$Harness = "both"
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
    $runs = [ordered]@{
        pinned = "requirements_test.txt"
        latest = "requirements_test_latest.txt"
    }
    foreach ($name in $runs.Keys) {
        if ($Harness -ne "both" -and $Harness -ne $name) { continue }
        $req = $runs[$name]
        Write-Host "==> pytest ($name harness, $req)" -ForegroundColor Cyan
        $script = "python -m venv /tmp/venv" +
            " && /tmp/venv/bin/python -m pip install -q --root-user-action=ignore --disable-pip-version-check -U -r $req" +
            " && /tmp/venv/bin/python -m pip show homeassistant 2>/dev/null | head -2" +
            " && /tmp/venv/bin/python -m pytest -q -p no:cacheprovider"
        wslc run --rm --pull missing -v "${repo}:/src" -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.14 `
            sh -c $script
        if ($LASTEXITCODE -ne 0) { $failed += "tests ($name)" }
    }
}

if ($failed) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All local validations passed." -ForegroundColor Green
