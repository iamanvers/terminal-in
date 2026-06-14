# PyInstaller spec — TERMINAL//IN onedir build (PRD 5b.1).
# Build:  .venv/Scripts/pyinstaller packaging/terminal_in.spec --noconfirm
# Output: dist/TerminalIN/TerminalIN.exe (+ support tree)
#
# v1 scope: trading terminal + reports + local LLM via Ollama/llama.cpp.
# The TRAIN module's fine-tuning needs the dev install (trl/peft excluded —
# they pull GBs and spawn `sys.executable -m ...` subprocesses that cannot
# work from a frozen exe). The UI hides nothing: training start returns a
# clear "requires dev install" error in packaged mode.

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Anchor everything on the repo root regardless of invocation cwd
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
sys.path.insert(0, ROOT)

block_cipher = None

hiddenimports = [
    'first_run',                          # onboarding wizard (sibling of run_app)
    'engineio.async_drivers.threading',   # flask-socketio threading mode
    'simple_websocket',
    'dotenv',
    # native desktop window (pywebview → WebView2 via pythonnet/winforms)
    'webview', 'clr', 'clr_loader',
    *collect_submodules('webview'),
    *collect_submodules('clr_loader'),
    *collect_submodules('terminal_in'),
]

datas = [
    (os.path.join(ROOT, 'terminal_ui', 'out'), 'terminal_ui/out'),
    (os.path.join(ROOT, 'Modelfile'), '.'),
    (os.path.join(ROOT, 'docs', 'LEGAL.md'), 'docs'),
    (os.path.join(ROOT, 'docs', 'USAGE.md'), 'docs'),
    (os.path.join(SPECPATH, 'terminalin.ico'), '.'),     # window/app icon
    *collect_data_files('transformers', include_py_files=False),
    *collect_data_files('webview'),                       # bridge JS + assets
    *collect_data_files('clr_loader'),                    # native ffi
]

a = Analysis(
    ['run_app.py'],
    pathex=[ROOT, SPECPATH],          # SPECPATH = packaging/, so `import first_run` resolves
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # training stack — dev-install only (see header)
        'trl', 'peft', 'datasets', 'accelerate',
        # never ship the dev/test toolchain
        'pytest', 'pyinstaller', 'IPython', 'jupyter',
        # GUI toolkits some deps probe for
        'tkinter', 'PyQt5', 'PySide6', 'matplotlib',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TerminalIN',
    icon=os.path.join(SPECPATH, 'terminalin.ico'),
    version=os.path.join(SPECPATH, 'version_info.txt'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # self-serving desktop app — no console window
                              # (logs go to %LOCALAPPDATA%/TerminalIN/data/logs)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='TerminalIN',
)
