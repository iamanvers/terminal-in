#!/usr/bin/env bash
# TERMINAL//IN — macOS / Linux launcher (bootstraps from nothing).
#
# Brings the terminal up on a fresh machine: checks prerequisites (with install
# guidance, never a cryptic failure), reuses anything already present (no
# needless re-downloads), shows numbered progress, then serves UI + API on
# http://localhost:5000 in your browser.
#
# Usage:
#   ./start.sh                 paper mode, browser on :5000 (builds UI once)
#   ./start.sh --dev           Next.js hot-reload on :3000 + API on :5000
#   ./start.sh --rebuild-ui    force a fresh static UI build
#   ./start.sh --live          live mode (needs a valid KITE_ACCESS_TOKEN)
#   ./start.sh --low-latency   high priority + Python 3.14 experimental JIT
#   ./start.sh --check         run the prerequisite checks only, then exit
set -euo pipefail

LIVE=0; DEV=0; REBUILD=0; LOWLAT=0; CHECK=0
for arg in "$@"; do case "$arg" in
  --live) LIVE=1 ;; --dev) DEV=1 ;; --rebuild-ui) REBUILD=1 ;;
  --low-latency) LOWLAT=1 ;; --check) CHECK=1 ;;
  *) echo "unknown flag: $arg" >&2; exit 2 ;;
esac; done

cd "$(dirname "$0")"
B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; X=$'\033[0m'
STEP=0; TOTAL=8
step(){ STEP=$((STEP+1)); printf "${C}[%d/%d]${X} ${B}%s${X}\n" "$STEP" "$TOTAL" "$1"; }
ok(){   printf "      ${G}✓${X} %s\n" "$1"; }
warn(){ printf "      ${Y}!${X} %s\n" "$1"; }
die(){  printf "      ${R}✗ %s${X}\n" "$1"; exit 1; }
ver_ge(){ [ "$(printf '%s\n%s' "$1" "$2" | sort -V | head -1)" = "$2" ]; }  # $1 >= $2 ?

printf "${B}========================================${X}\n"
printf "${B}  TERMINAL//IN  |  Indian Markets QT${X}\n"
printf "${B}========================================${X}\n"

OS="$(uname -s)"; IS_MAC=0; [ "$OS" = "Darwin" ] && IS_MAC=1

# ── [1] Python ≥ 3.11 ───────────────────────────────────────────────────────────
step "Checking Python (need ≥ 3.11)…"
PYBASE="$(command -v python3 || command -v python || true)"
if [ -z "$PYBASE" ]; then
  warn "Python not found."
  [ "$IS_MAC" = 1 ] && echo "        Install: brew install python@3.12   (or https://python.org/downloads)" \
                     || echo "        Install: sudo apt install python3 python3-venv python3-pip   (or your distro's package)"
  die "Python is required."
fi
PYV="$("$PYBASE" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
ver_ge "$PYV" "3.11" && ok "Python $PYV ($PYBASE)" || die "Python $PYV is too old — need ≥ 3.11."

# ── [2] Node.js + npm (only needed to BUILD the UI) ──────────────────────────────
step "Checking Node.js + npm (to build the UI)…"
UI_PREBUILT=0; [ -f terminal_ui/out/index.html ] && UI_PREBUILT=1
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODEV="$(node -v | sed 's/^v//')"
  ver_ge "$NODEV" "18.0.0" && ok "Node $NODEV, npm $(npm -v)" || warn "Node $NODEV is old — 18+ recommended."
else
  if [ "$UI_PREBUILT" = 1 ] && [ "$REBUILD" = 0 ] && [ "$DEV" = 0 ]; then
    warn "Node not found, but a built UI exists — will serve that (skip if you don't need a rebuild)."
  else
    warn "Node.js 18+ not found — needed to build the UI."
    [ "$IS_MAC" = 1 ] && echo "        Install: brew install node   (or https://nodejs.org)" \
                       || echo "        Install: https://nodejs.org  (or: sudo apt install nodejs npm)"
    die "Node.js is required for the first UI build."
  fi
fi

# ── [3] Ollama (optional — the local LLM judge/analyst) ──────────────────────────
step "Checking Ollama (local LLM — optional)…"
if command -v ollama >/dev/null 2>&1; then
  ok "Ollama present ($(ollama --version 2>/dev/null | head -1))"
  ollama list 2>/dev/null | grep -q . && ok "models installed" || warn "no models yet — run: ollama pull qwen2.5:3b"
else
  warn "Ollama not found — the Trade Planner + AI analyst will run DEGRADED (flagged, not silent)."
  [ "$IS_MAC" = 1 ] && echo "        Install: brew install ollama && ollama pull qwen2.5:3b   (or https://ollama.com)" \
                     || echo "        Install: curl -fsSL https://ollama.com/install.sh | sh && ollama pull qwen2.5:3b"
fi

[ "$CHECK" = 1 ] && { printf "\n${G}Prerequisite check complete.${X}\n"; exit 0; }

# ── [4] Virtual environment (reuse if present) ───────────────────────────────────
step "Python virtual environment…"
if [ -d .venv ]; then ok "reusing .venv"; else echo "      creating .venv…"; "$PYBASE" -m venv .venv; ok "created"; fi
PY=".venv/bin/python"

# ── [5] Dependencies (skip when requirements.txt is unchanged) ───────────────────
step "Python dependencies…"
REQ_HASH="$( ( command -v shasum >/dev/null && shasum requirements.txt || md5 -q requirements.txt ) 2>/dev/null | awk '{print $1}')"
STAMP=".venv/.req.hash"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$REQ_HASH" ]; then
  ok "already up to date (requirements.txt unchanged)"
else
  echo "      installing… (first run pulls torch/transformers — a few minutes)"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt
  echo "$REQ_HASH" > "$STAMP"; ok "installed"
fi

# ── [6] Configuration ────────────────────────────────────────────────────────────
step "Configuration (.env)…"
if [ -f .env ]; then ok ".env present"
elif [ -f .env.example ]; then cp .env.example .env; ok ".env created from .env.example — add your API keys"
else warn "no .env / .env.example — running on defaults (paper mode)"; fi
mkdir -p data
if [ "$LIVE" = 1 ]; then export MODE=live; warn "MODE=LIVE"; else export MODE="${MODE:-paper}"; ok "MODE=${MODE}"; fi
if [ "$LOWLAT" = 1 ]; then export LOW_LATENCY=1; export PYTHON_JIT=1; ok "low-latency: HIGH priority + JIT"; fi

# ── [7] User interface ───────────────────────────────────────────────────────────
step "User interface…"
if [ "$DEV" = 1 ]; then
  [ -d terminal_ui/node_modules ] || { echo "      npm install (first run)…"; ( cd terminal_ui && npm install --silent ); }
  ( cd terminal_ui && npm run dev >/tmp/terminalin-ui.log 2>&1 & )
  ok "dev server on http://localhost:3000 (hot reload)"; URL="http://localhost:3000"
else
  if [ "$REBUILD" = 1 ] || [ "$UI_PREBUILT" = 0 ]; then
    [ -d terminal_ui/node_modules ] || { echo "      npm install (first run)…"; ( cd terminal_ui && npm install --silent ); }
    echo "      building static UI (one-time; re-run with --rebuild-ui after UI edits)…"
    ( cd terminal_ui && BUILD_STATIC=1 npx next build >/dev/null )
    ok "UI built"
  else
    ok "reusing built UI (--rebuild-ui to refresh)"
  fi
  URL="http://localhost:5000"
fi

# ── [8] Launch ────────────────────────────────────────────────────────────────────
step "Launching backend — UI + API on http://localhost:5000…"
( sleep 4; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) &
printf "\n${G}Open ${URL}${X}  ·  Ctrl+C to stop.\n\n"
exec "$PY" -m terminal_in.main
