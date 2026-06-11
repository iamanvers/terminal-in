# TERMINAL//IN — background service control
#
# The trading loop is fully autonomous (scan → LLM planner → risk gate →
# paper execution → settlement). This script runs the backend headless so it
# trades, settles, and emails reports without a console window open.
#
# Usage:
#   .\background.ps1 -Start      # start backend hidden, right now
#   .\background.ps1 -Stop       # stop the background backend
#   .\background.ps1 -Status     # is it running?
#   .\background.ps1 -Install    # auto-start at logon (Windows Scheduled Task)
#   .\background.ps1 -Uninstall  # remove the scheduled task

param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Install,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"   # pythonw = no console
$TaskName    = "TERMINAL-IN Backend"
$LogFile     = Join-Path $ProjectRoot "data\logs\background.log"

function Get-BackendPid {
    $conn = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return $conn.OwningProcess }
    return $null
}

if ($Status) {
    $bpid = Get-BackendPid
    if ($bpid) {
        Write-Host "RUNNING (pid $bpid) — API http://localhost:5000" -ForegroundColor Green
        try {
            $h = Invoke-RestMethod "http://localhost:5000/api/health" -TimeoutSec 3
            Write-Host "health: $($h.status)  degraded: $($h.degraded -join ', ')" -ForegroundColor Gray
        } catch {}
    } else {
        Write-Host "NOT RUNNING" -ForegroundColor Red
    }
    exit 0
}

if ($Stop) {
    $bpid = Get-BackendPid
    if ($bpid) { Stop-Process -Id $bpid -Force; Write-Host "Stopped (pid $bpid)." -ForegroundColor Yellow }
    else { Write-Host "Not running." -ForegroundColor Gray }
    exit 0
}

if ($Start) {
    if (Get-BackendPid) { Write-Host "Already running." -ForegroundColor Yellow; exit 0 }
    New-Item -ItemType Directory -Force (Split-Path $LogFile) | Out-Null
    # pythonw.exe detaches from the console entirely; logs go to file
    Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "terminal_in.main" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError  "$LogFile.err"
    Start-Sleep -Seconds 4
    if (Get-BackendPid) { Write-Host "Started in background — API on :5000, log: $LogFile" -ForegroundColor Green }
    else { Write-Host "Failed to start — check $LogFile.err" -ForegroundColor Red }
    exit 0
}

if ($Install) {
    $action  = New-ScheduledTaskAction -Execute $VenvPython `
        -Argument "-m terminal_in.main" -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "TERMINAL//IN autonomous trading backend" -Force | Out-Null
    Write-Host "Installed: backend auto-starts at logon (task '$TaskName')." -ForegroundColor Green
    Write-Host "Start now with: .\background.ps1 -Start" -ForegroundColor Gray
    exit 0
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task removed." -ForegroundColor Yellow
    exit 0
}

Write-Host "Usage: .\background.ps1 -Start | -Stop | -Status | -Install | -Uninstall"
