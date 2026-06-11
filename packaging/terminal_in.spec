# PyInstaller spec — TERMINAL//IN onedir build (PRD 5b.1).
# Build:  .venv/Scripts/pyinstaller packaging/terminal_in.spec --noconfirm
# Output: dist/TerminalIN/TerminalIN.exe (+ support tree)
#
# v1 scope: trading terminal + reports + local LLM via Ollama/llama.cpp.
# The TRAIN module's fine-tuning needs the dev install (trl/peft excluded —
# they pull GBs and spawn `sys.executable -m ...` subprocesses that cannot
# work from a frozen exe). The UI hides nothing: training start returns a
# clear "requires dev install" error in packaged mode.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = [
    'engineio.async_drivers.threading',   # flask-socketio threading mode
    'simple_websocket',
    'dotenv',
    *collect_submodules('terminal_in'),
]

datas = [
    ('../terminal_ui/out', 'terminal_ui/out'),    # static UI export
    ('../Modelfile', '.'),                         # analyst system prompt
    ('../docs/LEGAL.md', 'docs'),
    ('../docs/USAGE.md', 'docs'),
    *collect_data_files('transformers', include_py_files=False),
]

a = Analysis(
    ['run_app.py'],
    pathex=['..'],
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
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,             # console build: logs visible; -w later via Inno
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
