# TERMINAL//IN — Ollama setup script
# Run this once to install Ollama and create the financial analyst model
# Usage: .\setup_ollama.ps1

$ErrorActionPreference = 'Stop'

Write-Host "`nTERMINAL//IN — Ollama Financial Analyst Setup" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# ── Check if Ollama is installed ─────────────────────────────────────────────
$ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaExe) {
    Write-Host "`nOllama not found. Downloading installer..." -ForegroundColor Yellow
    $installer = "$env:TEMP\OllamaSetup.exe"
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $installer
    Write-Host "Installing Ollama..." -ForegroundColor Yellow
    Start-Process -FilePath $installer -ArgumentList "/S" -Wait
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    Write-Host "Ollama installed." -ForegroundColor Green
} else {
    Write-Host "Ollama already installed at: $($ollamaExe.Source)" -ForegroundColor Green
}

# ── Start Ollama service ──────────────────────────────────────────────────────
Write-Host "`nStarting Ollama service..." -ForegroundColor Yellow
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3

# ── Pull base model ───────────────────────────────────────────────────────────
$model = "qwen2.5:3b"
Write-Host "`nPulling base model: $model (~2GB, may take a few minutes)..." -ForegroundColor Yellow
ollama pull $model
Write-Host "Base model ready." -ForegroundColor Green

# ── Create custom financial analyst model ────────────────────────────────────
Write-Host "`nCreating financial-analyst model from Modelfile..." -ForegroundColor Yellow
Set-Location "c:\Users\anmol\claude_apps\terminal-in"
ollama create financial-analyst -f Modelfile
Write-Host "financial-analyst model created." -ForegroundColor Green

# ── Update .env ───────────────────────────────────────────────────────────────
$envPath = ".env"
if (Test-Path $envPath) {
    $content = Get-Content $envPath -Raw
    if ($content -notmatch "OLLAMA_MODEL") {
        Add-Content $envPath "`nOLLAMA_HOST=http://localhost:11434`nOLLAMA_MODEL=financial-analyst"
        Write-Host "Updated .env with OLLAMA_MODEL=financial-analyst" -ForegroundColor Green
    } else {
        # Update existing OLLAMA_MODEL line
        $content = $content -replace "OLLAMA_MODEL=.*", "OLLAMA_MODEL=financial-analyst"
        Set-Content $envPath $content
        Write-Host "Updated .env: OLLAMA_MODEL=financial-analyst" -ForegroundColor Green
    }
}

# ── Verify ────────────────────────────────────────────────────────────────────
Write-Host "`nVerifying setup..." -ForegroundColor Yellow
$response = ollama run financial-analyst "What is the RSI overbought level and what does it mean?"
Write-Host "`nModel response:" -ForegroundColor Cyan
Write-Host $response -ForegroundColor White

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "The financial-analyst model is now active for TERMINAL//IN AI ANALYST tab." -ForegroundColor Green
Write-Host "Restart the backend to pick up the new OLLAMA_MODEL setting." -ForegroundColor Yellow
