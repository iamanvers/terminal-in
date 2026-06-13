"""
TERMINAL//IN — packaged-app entry point (PyInstaller onedir, PRD 5b.1).

Frozen-mode contract:
  - All mutable state lives in %LOCALAPPDATA%\\TerminalIN (the process
    chdirs there, so every relative './data' path in the codebase lands in
    the per-user data directory; the install dir stays read-only).
  - The static UI ships inside the bundle; UI_OUT_DIR points Flask at it.
  - Configuration comes from the settings panel (DB) — there is no .env in
    a packaged install, though one is honored if the operator creates it
    in the data directory.

Dev mode (python packaging/run_app.py) behaves exactly like
`python -m terminal_in.main`.
"""

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)


def _prepare_frozen_env() -> None:
    # PyInstaller onedir places bundled `datas` (the UI) under _internal/, which
    # is sys._MEIPASS — NOT next to the exe. Using the exe's own dir left
    # UI_OUT_DIR unset and the app served the API but 404'd the UI.
    bundle = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    appdata = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TerminalIN'
    for sub in ('data', 'data/logs', 'data/reports', 'data/artifacts'):
        (appdata / sub).mkdir(parents=True, exist_ok=True)
    os.chdir(appdata)                             # './data/...' → per-user dir

    ui = bundle / 'terminal_ui' / 'out'
    if ui.exists():
        os.environ.setdefault('UI_OUT_DIR', str(ui))

    # HF models (FinBERT) cache beside the data, not in the install dir
    os.environ.setdefault('HF_HOME', str(appdata / 'hf-cache'))


def main() -> None:
    if FROZEN:
        _prepare_frozen_env()
    from terminal_in.main import main as app_main
    app_main()


if __name__ == '__main__':
    main()
