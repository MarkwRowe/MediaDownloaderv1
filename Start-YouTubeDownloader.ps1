param(
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$appFile = Join-Path $projectDir 'app.py'
$url = "http://127.0.0.1:$Port"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Virtual environment Python not found: $pythonExe" -ForegroundColor Red
    Write-Host "Run: python -m venv .venv and install requirements first." -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}

if (-not (Test-Path $appFile)) {
    Write-Host "Could not find app.py at: $appFile" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Start-Process $url
    Write-Host "Server already running on port $Port. Opened browser." -ForegroundColor Green
    exit 0
}

Start-Process $url
Set-Location $projectDir
& $pythonExe $appFile
