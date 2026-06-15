# TERMINAL//IN — Windows launcher (bootstraps from nothing).
#
# Brings the terminal up on a fresh machine: checks prerequisites (with install
# guidance, never a cryptic failure), reuses anything already present (no
# needless re-downloads), shows numbered progress, then serves UI + API on
# http://localhost:5000 in your browser.
#
# Usage:
#   .\start.ps1                paper mode, browser on :5000 (builds UI once)
#   .\start.ps1 -Dev           Next.js hot-reload on :3000 + API on :5000
#   .\start.ps1 -RebuildUI     force a fresh static UI build
#   .\start.ps1 -Live          live mode (needs a valid KITE_ACCESS_TOKEN)
#   .\start.ps1 -LowLatency    HIGH process priority + Python 3.14 experimental JIT
#   .\start.ps1 -Check         run the prerequisite checks only, then exit
param(
    [switch]$Live, [switch]$Dev, [switch]$RebuildUI, [switch]$LowLatency, [switch]$Check
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$script:Step = 0; $Total = 8
function Step($m){ $script:Step++; Write-Host ("[{0}/{1}] " -f $script:Step,$Total) -ForegroundColor Cyan -NoNewline; Write-Host $m }
function Ok($m){   Write-Host "      v $m" -ForegroundColor Green }
function Warn($m){ Write-Host "      ! $m" -ForegroundColor Yellow }
function Die($m){  Write-Host "      x $m" -ForegroundColor Red; exit 1 }

Write-Host "========================================" -ForegroundColor White
Write-Host "  TERMINAL//IN  |  Indian Markets QT"     -ForegroundColor White
Write-Host "========================================" -ForegroundColor White

# ── [1] Python >= 3.11 ──────────────────────────────────────────────────────────
Step "Checking Python (need >= 3.11)..."
$PyCmd = $null
foreach ($c in @("python","python3","py")) { if (Get-Command $c -ErrorAction SilentlyContinue) { $PyCmd = $c; break } }
if (-not $PyCmd) {
    Warn "Python not found."
    Write-Host "        Install: winget install Python.Python.3.12   (or https://python.org/downloads)" -ForegroundColor Gray
    Die "Python is required."
}
$PyV = & $PyCmd -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'
if ([version]$PyV -lt [version]"3.11") { Die "Python $PyV is too old - need >= 3.11." }
Ok "Python $PyV ($PyCmd)"

# ── [2] Node.js + npm (only needed to BUILD the UI) ─────────────────────────────
Step "Checking Node.js + npm (to build the UI)..."
$UiPrebuilt = Test-Path "terminal_ui\out\index.html"
if ((Get-Command node -ErrorAction SilentlyContinue) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    $NodeV = (node -v).TrimStart("v")
    if ([version]$NodeV -lt [version]"18.0.0") { Warn "Node $NodeV is old - 18+ recommended." } else { Ok "Node $NodeV, npm $(npm -v)" }
} else {
    if ($UiPrebuilt -and -not $RebuildUI -and -not $Dev) {
        Warn "Node not found, but a built UI exists - will serve that."
    } else {
        Warn "Node.js 18+ not found - needed to build the UI."
        Write-Host "        Install: winget install OpenJS.NodeJS.LTS   (or https://nodejs.org)" -ForegroundColor Gray
        Die "Node.js is required for the first UI build."
    }
}

# ── [3] Ollama (optional) ────────────────────────────────────────────────────────
Step "Checking Ollama (local LLM - optional)..."
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Ok "Ollama present"
    if ((ollama list 2>$null | Measure-Object -Line).Lines -gt 1) { Ok "models installed" } else { Warn "no models yet - run: ollama pull qwen2.5:3b" }
} else {
    Warn "Ollama not found - the Trade Planner + AI analyst will run DEGRADED (flagged, not silent)."
    Write-Host "        Install: winget install Ollama.Ollama; ollama pull qwen2.5:3b   (or https://ollama.com)" -ForegroundColor Gray
}

if ($Check) { Write-Host "`nPrerequisite check complete." -ForegroundColor Green; exit 0 }

# ── [4] Virtual environment (reuse if present) ──────────────────────────────────
Step "Python virtual environment..."
if (Test-Path ".venv") { Ok "reusing .venv" } else { Write-Host "      creating .venv..."; & $PyCmd -m venv .venv; Ok "created" }
$VenvPy = ".venv\Scripts\python.exe"

# ── [5] Dependencies (skip when requirements.txt is unchanged) ──────────────────
Step "Python dependencies..."
$ReqHash = (Get-FileHash requirements.txt -Algorithm MD5).Hash
$Stamp = ".venv\.req.hash"
if ((Test-Path $Stamp) -and ((Get-Content $Stamp -ErrorAction SilentlyContinue) -eq $ReqHash)) {
    Ok "already up to date (requirements.txt unchanged)"
} else {
    Write-Host "      installing... (first run pulls torch/transformers - a few minutes)"
    & $VenvPy -m pip install -q --upgrade pip
    & $VenvPy -m pip install -q -r requirements.txt
    Set-Content $Stamp $ReqHash; Ok "installed"
}

# ── [6] Configuration ────────────────────────────────────────────────────────────
Step "Configuration (.env)..."
if (Test-Path ".env") { Ok ".env present" }
elseif (Test-Path ".env.example") { Copy-Item ".env.example" ".env"; Ok ".env created from .env.example - add your API keys" }
else { Warn "no .env / .env.example - running on defaults (paper mode)" }
if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" | Out-Null }
if ($Live) { $env:MODE = "live"; Warn "MODE=LIVE" } else { if (-not $env:MODE) { $env:MODE = "paper" }; Ok "MODE=$($env:MODE)" }
if ($LowLatency) { $env:LOW_LATENCY = "1"; $env:PYTHON_JIT = "1"; Ok "low-latency: HIGH priority + JIT" }

# ── [7] User interface ───────────────────────────────────────────────────────────
Step "User interface..."
if ($Dev) {
    if (-not (Test-Path "terminal_ui\node_modules")) { Write-Host "      npm install (first run)..."; Push-Location terminal_ui; npm install --silent; Pop-Location }
    Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory "terminal_ui" -WindowStyle Minimized
    Ok "dev server on http://localhost:3000 (hot reload)"; $Url = "http://localhost:3000"
} else {
    if ($RebuildUI -or -not $UiPrebuilt) {
        if (-not (Test-Path "terminal_ui\node_modules")) { Write-Host "      npm install (first run)..."; Push-Location terminal_ui; npm install --silent; Pop-Location }
        Write-Host "      building static UI (one-time; re-run with -RebuildUI after UI edits)..."
        Push-Location terminal_ui; $env:BUILD_STATIC = "1"; npx next build | Out-Null; Remove-Item Env:\BUILD_STATIC; Pop-Location
        Ok "UI built"
    } else { Ok "reusing built UI (-RebuildUI to refresh)" }
    $Url = "http://localhost:5000"
}

# ── [8] Launch ────────────────────────────────────────────────────────────────────
Step "Launching backend - UI + API on http://localhost:5000..."
Start-Job -ScriptBlock { Start-Sleep 4; Start-Process $using:Url } | Out-Null
Write-Host "`nOpen $Url  -  Ctrl+C to stop.`n" -ForegroundColor Green
& $VenvPy -m terminal_in.main
