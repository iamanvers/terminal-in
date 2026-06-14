"""
TERMINAL//IN — packaged-app entry point (PyInstaller onedir, PRD 5b.1).

Frozen-mode contract (a SELF-SERVING desktop app — no browser, no visible URL):
  - All mutable state lives in %LOCALAPPDATA%\\TerminalIN (the process chdirs
    there, so every relative './data' path lands in the per-user data
    directory; the install dir stays read-only).
  - The Flask/SocketIO backend is the app's internal engine. It binds to
    127.0.0.1 on a FREE port (never the network, never a fixed port that could
    clash) — the web UI talks to it over that loopback socket. This is the
    standard pattern for a Python-backed desktop app; the port is an invisible
    implementation detail, not something the user opens in a browser.
  - The UI is hosted in a NATIVE OS window (pywebview → WebView2 on Windows),
    titled TERMINAL//IN, with the app icon. If the native runtime is missing we
    fall back to the default browser rather than failing.
  - Hardware maximization (terminal_in/hw.py) runs at boot inside the same
    process, so the shipped app engages all logical cores exactly like dev.
  - Configuration comes from the settings panel (DB) — no .env in a packaged
    install, though one in the data directory is honored if present.

Dev mode (python packaging/run_app.py) behaves exactly like
`python -m terminal_in.main` (browser + 0.0.0.0:5000).
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _appdata_dir() -> Path:
    appdata = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TerminalIN'
    for sub in ('data', 'data/logs', 'data/reports', 'data/artifacts'):
        (appdata / sub).mkdir(parents=True, exist_ok=True)
    return appdata


def _prepare_frozen_env() -> tuple[str, Path]:
    # PyInstaller onedir places bundled `datas` (the UI) under _internal/, which
    # is sys._MEIPASS — NOT next to the exe. Using the exe's own dir left
    # UI_OUT_DIR unset and the app served the API but 404'd the UI.
    bundle = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    appdata = _appdata_dir()
    os.chdir(appdata)                             # './data/...' → per-user dir

    ui = bundle / 'terminal_ui' / 'out'
    if ui.exists():
        os.environ.setdefault('UI_OUT_DIR', str(ui))
    os.environ.setdefault('HF_HOME', str(appdata / 'hf-cache'))

    # internal API: loopback only, on a free port
    host, port = '127.0.0.1', _free_port()
    os.environ['TIN_HOST'] = host
    os.environ['TIN_PORT'] = str(port)
    return f'http://{host}:{port}', appdata


def _maybe_onboard(appdata: Path) -> None:
    """First launch only: run the onboarding wizard in an ISOLATED subprocess
    (pywebview can start its loop once per process), so the collected capital /
    risk / keys are persisted to the settings DB before the backend boots."""
    try:
        import first_run
    except Exception:
        return
    if not first_run.needs_onboarding(appdata):
        return
    import subprocess
    env = {**os.environ, 'TIN_WIZARD': '1'}
    try:
        subprocess.run([sys.executable], env=env, check=False)
    except Exception:
        pass
    # If the wizard process didn't write the marker (crash / no webview), don't
    # block the app forever — mark done so we boot with defaults next time.
    if first_run.needs_onboarding(appdata):
        first_run.mark_done(appdata)


def _wait_until_up(url: str, timeout_s: float = 60.0) -> bool:
    host = url.split('//', 1)[1].split(':')[0]
    port = int(url.rsplit(':', 1)[1])
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def _icon_path() -> str | None:
    bundle = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    for cand in (bundle / 'terminalin.ico', bundle / 'terminal_ui' / 'out' / 'icon.svg'):
        if cand.exists():
            return str(cand)
    return None


def _run_wizard_only() -> None:
    """TIN_WIZARD subprocess: just show the onboarding window and exit."""
    appdata = _appdata_dir()
    os.chdir(appdata)
    try:
        import first_run
        first_run.run_wizard_window(appdata, icon=_icon_path())
    except Exception:
        pass


def _run_desktop() -> None:
    """Boot the backend in a thread, then host the UI in a native window."""
    url, appdata = _prepare_frozen_env()
    _maybe_onboard(appdata)               # first launch only, before the backend

    from terminal_in.main import main as app_main
    threading.Thread(target=app_main, daemon=True, name='backend').start()

    if not _wait_until_up(url):
        # backend didn't come up — surface it instead of a blank window
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, 'TERMINAL//IN backend failed to start. See '
               '%LOCALAPPDATA%\\TerminalIN\\data\\logs.', 'TERMINAL//IN', 0x10)
        os._exit(1)

    try:
        import webview
        webview.create_window('TERMINAL//IN', url, width=1440, height=900,
                              min_size=(1100, 700), background_color='#0A0B0D')
        webview.start(icon=_icon_path())          # blocks until the window closes
    except Exception:
        # No native webview runtime — degrade to the default browser, keep serving
        import webbrowser
        webbrowser.open(url)
        threading.Event().wait()                  # keep the process (and backend) alive
        return
    os._exit(0)                                   # window closed → stop the backend


def main() -> None:
    if os.environ.get('TIN_WIZARD') == '1':
        _run_wizard_only()
        return
    if FROZEN:
        _run_desktop()
    else:
        from terminal_in.main import main as app_main
        app_main()


if __name__ == '__main__':
    main()
