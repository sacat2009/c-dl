$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = "python"
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Please install Python 3.10 or newer."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating local virtual environment..." -ForegroundColor Cyan
    & $Python -m venv .venv
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
Write-Host "Installing/updating yt-dlp..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --upgrade -r requirements.txt

Write-Host ""
Write-Host "Starting yt-dlp Chinese UI: http://127.0.0.1:8765" -ForegroundColor Green
Write-Host "Downloads folder: $Root\downloads" -ForegroundColor Green
Write-Host ""
& $VenvPython app.py
