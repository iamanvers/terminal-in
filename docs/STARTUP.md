# TERMINAL//IN — Startup Guide (from scratch)

Get the terminal running on a clean Windows or macOS/Linux machine. The launcher
does the heavy lifting — it checks what you already have, only downloads what's
missing, shows numbered progress, and serves the app in your browser.

---

## TL;DR

```bash
# macOS / Linux
./start.sh            # first run: ~5–10 min (deps + UI build), then opens http://localhost:5000

# Windows (PowerShell)
.\start.ps1
```

```powershell
# Just verify your machine has the prerequisites, change nothing:
.\start.ps1 -Check     # Windows
./start.sh --check     # macOS/Linux
```

---

## Prerequisites

The launcher checks these and prints install commands if any are missing — you
don't have to guess. Install only what it flags.

| Tool | Version | Needed for | Install |
|------|---------|-----------|---------|
| **Python** | ≥ 3.11 (3.14 ideal) | the whole backend | macOS `brew install python@3.12` · Windows `winget install Python.Python.3.12` · Linux `apt install python3 python3-venv python3-pip` |
| **Node.js + npm** | ≥ 18 LTS | building the UI (first run only; a prebuilt UI can be served without it) | macOS `brew install node` · Windows `winget install OpenJS.NodeJS.LTS` · Linux `apt install nodejs npm` or nodejs.org |
| **Ollama** | any recent | the local LLM Trade Planner + AI analyst (**optional** — the app runs without it in a clearly-flagged *degraded* mode) | macOS `brew install ollama` · Windows `winget install Ollama.Ollama` · Linux `curl -fsSL https://ollama.com/install.sh \| sh`, then `ollama pull qwen2.5:3b` |

Nothing is sent to the cloud. The only paid/external dependency is **Zerodha Kite
Connect** (₹2000/mo) and only if you switch to *live* mode — paper mode needs no keys.

---

## What the launcher does (the 8 steps)

1. **Python** — finds it, checks ≥ 3.11.
2. **Node + npm** — checks ≥ 18 (skipped if a built UI already exists and you're not rebuilding).
3. **Ollama** — optional; warns + gives the install line if absent (planner/analyst degrade, never fail silently).
4. **Virtual environment** — creates `.venv` once, reuses it after.
5. **Python dependencies** — installs from `requirements.txt`; **skipped on later runs** unless `requirements.txt` changed (a hash stamp in `.venv/.req.hash`). First install pulls torch/transformers — a few minutes.
6. **Configuration** — seeds `.env` from `.env.example` if you don't have one (paper-mode defaults work out of the box).
7. **User interface** — builds the static UI once (reused after; `--rebuild-ui` / `-RebuildUI` to refresh). Or `--dev` / `-Dev` for the hot-reload dev server on `:3000`.
8. **Launch** — starts the backend, which serves the UI **and** API on `http://localhost:5000`, and opens your browser.

First boot also backfills ~10 years of real daily OHLCV from yfinance in the
background (you'll see log lines) and, once enough history exists, trains the HMM
regime model — both are automatic and one-time.

---

## Flags

| macOS/Linux | Windows | Effect |
|-------------|---------|--------|
| `--dev` | `-Dev` | Next.js hot-reload UI on `:3000` + API on `:5000` (for UI development) |
| `--rebuild-ui` | `-RebuildUI` | force a fresh static UI build (after UI edits) |
| `--live` | `-Live` | live trading via Kite (needs a valid `KITE_ACCESS_TOKEN`) |
| `--low-latency` | `-LowLatency` | HIGH process priority + Python 3.14 experimental JIT |
| `--check` | `-Check` | run the prerequisite checks only, then exit |

---

## Configuration (`.env`)

Paper mode needs nothing. To go further, edit `.env`:

- **Live trading:** `MODE=live`, `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN` (regenerated daily).
- **News sentiment (optional):** `NEWSAPI_KEY` — without it, the free RSS feeds still work.
- **Risk:** `INITIAL_CAPITAL`, `MAX_DD_PCT`, `DAILY_LOSS_CAP_PCT`.
- **LLM backend:** default talks to **Ollama** (`OLLAMA_HOST`, `OLLAMA_MODEL`). To use any
  OpenAI-compatible server instead (e.g. a local `llama-server`), set
  `LLM_BACKEND=openai`, `LLM_BASE_URL=http://localhost:8080`, `LLM_MODEL=<name>`.

---

## Troubleshooting

- **"Python is required" / too old** — install ≥ 3.11 (see table) and re-run.
- **"Node.js is required for the first UI build"** — install Node 18+, or copy in a prebuilt `terminal_ui/out`.
- **Port 5000 already in use** — stop the other process, or it's an old instance of this app still running.
- **AGENTS page shows a DEGRADED badge** — Ollama isn't running or has no model: `ollama pull qwen2.5:3b`. The system keeps working with a stricter deterministic planner bar.
- **UI changes not showing on `:5000`** — the static build is cached; re-run with `--rebuild-ui` / `-RebuildUI` (or use `--dev` for live reload).
- **Re-running is slow** — it shouldn't be: deps and the UI build are skipped when unchanged. Delete `.venv/.req.hash` to force a dependency reinstall.

---

## Tests

```bash
.venv/bin/python -m pytest tests/ -v        # macOS/Linux
.venv\Scripts\python.exe -m pytest tests\ -v   # Windows
```
