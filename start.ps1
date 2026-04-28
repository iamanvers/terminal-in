# TERMINAL//IN — Windows launcher
# Usage: .\start.ps1          (paper mode, uses .env)
#        .\start.ps1 -Live    (live mode — requires valid KITE_ACCESS_TOKEN)

param(
    [switch]$Live
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TERMINAL//IN  |  Indian Markets QT   " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── Resolve project root (directory containing this script) ──────────────────
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# ── Check Python ─────────────────────────────────────────────────────────────
$PythonCmd = "python"
try {
    $PythonVersion = & $PythonCmd --version 2>&1
    Write-Host "Python: $PythonVersion" -ForegroundColor Green
} catch {
    Write-Error "Python not found. Install Python 3.11+ and ensure it is on PATH."
}

# ── Virtual environment ───────────────────────────────────────────────────────
$VenvDir = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    & $PythonCmd -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

# ── Install dependencies ──────────────────────────────────────────────────────
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $ReqFile) {
    Write-Host "Installing/updating dependencies..." -ForegroundColor Yellow
    & $VenvPip install -q -r $ReqFile
} else {
    Write-Warning "requirements.txt not found — skipping dependency install."
}

# ── .env ──────────────────────────────────────────────────────────────────────
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvFile)) {
    $EnvExample = Join-Path $ProjectRoot ".env.example"
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Host ".env created from .env.example — fill in your API keys." -ForegroundColor Yellow
    } else {
        Write-Warning "No .env or .env.example found."
    }
}

# ── Override MODE if -Live ────────────────────────────────────────────────────
if ($Live) {
    $env:MODE = "live"
    Write-Host "Mode: LIVE" -ForegroundColor Red
} else {
    if (-not $env:MODE) { $env:MODE = "paper" }
    Write-Host "Mode: $($env:MODE.ToUpper())" -ForegroundColor Green
}

# ── SQLite DB init ────────────────────────────────────────────────────────────
$SchemaFile = Join-Path $ProjectRoot "db\init\schema.sql"
$DbFile     = Join-Path $ProjectRoot "data\terminal_in.db"
$DataDir    = Join-Path $ProjectRoot "data"

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

if (-not (Test-Path $DbFile)) {
    Write-Host "Initialising SQLite database..." -ForegroundColor Yellow
    if (Test-Path $SchemaFile) {
        # DB will be auto-initialised by DB() on first use — schema embedded in db.py
        Write-Host "DB will be initialised on first start." -ForegroundColor Gray
    }
}

# ── Terminal UI (Next.js) ─────────────────────────────────────────────────────
$UIDir = Join-Path $ProjectRoot "terminal_ui"
if (Test-Path (Join-Path $UIDir "package.json")) {
    $NodeModules = Join-Path $UIDir "node_modules"
    if (-not (Test-Path $NodeModules)) {
        Write-Host "Installing UI dependencies (first run)..." -ForegroundColor Yellow
        Push-Location $UIDir
        npm install --silent
        Pop-Location
    }
    Write-Host "Starting UI on http://localhost:3000 ..." -ForegroundColor Cyan
    Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory $UIDir -WindowStyle Minimized
}

# ── Launch Python backend ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "Starting backend on http://localhost:5000 ..." -ForegroundColor Cyan
Write-Host "UI on http://localhost:3000 | Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

& $VenvPython -m terminal_in.main
