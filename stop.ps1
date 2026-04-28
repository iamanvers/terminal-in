# TERMINAL//IN — graceful stop
# Sends SIGINT to any python process running terminal_in.main

$procs = Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match "terminal" -or $true }

if (-not $procs) {
    Write-Host "No Python processes found." -ForegroundColor Yellow
    exit 0
}

foreach ($p in $procs) {
    Write-Host "Stopping PID $($p.Id)..." -ForegroundColor Yellow
    $p.CloseMainWindow() | Out-Null
    Start-Sleep -Milliseconds 500
    if (-not $p.HasExited) {
        Stop-Process -Id $p.Id -Force
    }
}

Write-Host "TERMINAL//IN stopped." -ForegroundColor Green
