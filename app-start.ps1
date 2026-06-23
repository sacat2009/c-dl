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
Write-Host "Checking yt-dlp dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade -r requirements.txt

if (-not (Test-Path "node_modules\electron")) {
    Write-Host "Installing Electron desktop runtime..." -ForegroundColor Cyan
    npm.cmd install
}

$Electron = Join-Path $Root "node_modules\.bin\electron.cmd"
if (-not (Test-Path $Electron)) {
    throw "Electron launcher was not found. Please run npm.cmd install again."
}

Write-Host "Starting C DL desktop app..." -ForegroundColor Green
Start-Process -FilePath $Electron -ArgumentList "." -WorkingDirectory $Root -WindowStyle Hidden
