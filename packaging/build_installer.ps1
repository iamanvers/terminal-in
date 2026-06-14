# TERMINAL//IN — one-command installer build (PRD 5b.1).
#
#   .\packaging\build_installer.ps1            # full: static UI -> exe -> setup
#   .\packaging\build_installer.ps1 -SkipUI    # reuse an existing terminal_ui\out
#   .\packaging\build_installer.ps1 -SkipExe   # only re-run Inno over dist\TerminalIN
#
# Stages
#   1. Next.js static export  -> terminal_ui\out   (BUILD_STATIC=1 next build)
#   2. PyInstaller onedir      -> dist\TerminalIN\TerminalIN.exe (+ _internal\)
#   3. Inno Setup              -> dist\TERMINAL-IN-Setup.exe
#
# Inno Setup (iscc) must be on PATH or at the default install location; if it's
# missing the script stops after stage 2 with the onedir app ready to zip/ship.

param([switch]$SkipUI, [switch]$SkipExe)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root '.venv\Scripts\python.exe'
Set-Location $root

if (-not $SkipExe) {
    if (-not $SkipUI) {
        Write-Host '[1/3] Building static UI (Next.js export)...' -ForegroundColor Cyan
        Push-Location (Join-Path $root 'terminal_ui')
        $env:BUILD_STATIC = '1'
        & npx next build
        Pop-Location
    } else { Write-Host '[1/3] Skipped UI build (-SkipUI)' -ForegroundColor DarkGray }

    Write-Host '[2/3] PyInstaller onedir build (this is slow — torch/transformers)...' -ForegroundColor Cyan
    & $py -m PyInstaller (Join-Path $PSScriptRoot 'terminal_in.spec') --noconfirm
    if (-not (Test-Path (Join-Path $root 'dist\TerminalIN\TerminalIN.exe'))) {
        throw 'PyInstaller did not produce dist\TerminalIN\TerminalIN.exe'
    }
} else { Write-Host '[1-2/3] Skipped exe build (-SkipExe)' -ForegroundColor DarkGray }

Write-Host '[3/3] Inno Setup packaging...' -ForegroundColor Cyan
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Warning 'Inno Setup (iscc) not found. The onedir app is ready at dist\TerminalIN.'
    Write-Warning 'Install Inno Setup 6 (https://jrsoftware.org/isdl.php), then: iscc packaging\installer.iss'
    exit 2
}
& $iscc (Join-Path $PSScriptRoot 'installer.iss')
Write-Host 'Done -> dist\TERMINAL-IN-Setup.exe' -ForegroundColor Green
