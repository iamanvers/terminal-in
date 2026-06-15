#!/usr/bin/env bash
# TERMINAL//IN — macOS / Linux launcher (mirror of start.ps1).
#
# Default (single-process, no Node at runtime): builds the static UI once and
# serves UI + API together on http://localhost:5000, then opens your browser.
# This is the cross-platform way to run the terminal on a Mac — the packaged
# Windows desktop app (pywebview/WebView2) is Windows-only; everything else is
# plain cross-platform Python + Flask.
#
# Usage:
#   ./start.sh                 paper mode, browser on :5000 (builds UI if needed)
#   ./start.sh --rebuild-ui    force a fresh static UI build
#   ./start.sh --dev           Next.js hot-reload on :3000 + API on :5000
#   ./start.sh --live          live mode (needs a valid KITE_ACCESS_TOKEN)
#   ./start.sh --low-latency   high priority + Python 3.14 experimental JIT
set -euo pipefail

LIVE=0; DEV=0; REBUILD=0; LOWLAT=0
for arg in "$@"; do
  case "$arg" in
    --live) LIVE=1 ;;
    --dev) DEV=1 ;;
    --rebuild-ui) REBUILD=1 ;;
    --low-latency) LOWLAT=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"
ROOT="$(pwd)"
echo "========================================"
echo "  TERMINAL//IN  |  Indian Markets QT"
echo "========================================"

# ── Python ────────────────────────────────────────────────────────────────────
PYBASE="$(command -v python3 || command -v python || true)"
[ -n "$PYBASE" ] || { echo "Python 3.11+ not found on PATH." >&2; exit 1; }
echo "Python: $("$PYBASE" --version)"

# ── venv (POSIX layout: .venv/bin) ─────────────────────────────────────────────
if [ ! -d .venv ]; then echo "Creating virtual environment…"; "$PYBASE" -m venv .venv; fi
PY=".venv/bin/python"

echo "Installing/updating dependencies…"
"$PY" -m pip install -q --upgrade pip
[ -f requirements.txt ] && "$PY" -m pip install -q -r requirements.txt || echo "requirements.txt missing — skipping"

# ── .env ────────────────────────────────────────────────────────────────────────
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo ".env created from .env.example — fill in your API keys."
fi

if [ "$LIVE" = 1 ]; then export MODE=live; echo "Mode: LIVE"; else export MODE="${MODE:-paper}"; echo "Mode: ${MODE}"; fi
if [ "$LOWLAT" = 1 ]; then export LOW_LATENCY=1; export PYTHON_JIT=1; echo "Low-latency: HIGH priority + PYTHON_JIT=1"; fi

mkdir -p data

# ── UI ──────────────────────────────────────────────────────────────────────────
if [ "$DEV" = 1 ]; then
  # hot-reload dev: Next on :3000 proxies /api -> :5000
  if [ -d terminal_ui ] && [ ! -d terminal_ui/node_modules ]; then
    echo "Installing UI dependencies (first run)…"; ( cd terminal_ui && npm install --silent )
  fi
  echo "Starting UI (dev) on http://localhost:3000 …"
  ( cd terminal_ui && npm run dev >/tmp/terminalin-ui.log 2>&1 & )
  URL="http://localhost:3000"
else
  # single-process: static export served by Flask on :5000
  if [ "$REBUILD" = 1 ] || [ ! -f terminal_ui/out/index.html ]; then
    if [ -d terminal_ui ]; then
      [ -d terminal_ui/node_modules ] || ( echo "Installing UI dependencies (first run)…"; cd terminal_ui && npm install --silent )
      echo "Building static UI (one-time; re-run with --rebuild-ui after UI changes)…"
      ( cd terminal_ui && BUILD_STATIC=1 npx next build )
    fi
  fi
  URL="http://localhost:5000"
fi

# ── open browser (mac: open, linux: xdg-open) — after a short boot delay ─────────
( sleep 4; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) &

echo ""
echo "Starting backend — UI + API on http://localhost:5000 …"
echo "Open ${URL}  ·  Ctrl+C to stop."
echo ""
exec "$PY" -m terminal_in.main
