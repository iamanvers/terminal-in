<div align="center">

<img src="docs/banner.svg" alt="TERMINAL//IN" width="440" />

### Agentic algorithmic trading terminal for Indian markets

![tests](https://img.shields.io/badge/tests-324_passing-brightgreen)
![python](https://img.shields.io/badge/python-3.14-blue)
![frontend](https://img.shields.io/badge/frontend-Next.js_14-black)
![mode](https://img.shields.io/badge/mode-paper_%7C_live-0094FB)
![data](https://img.shields.io/badge/data-real--only-0094FB)
![license](https://img.shields.io/badge/license-personal_use-lightgrey)

A single-machine stack (Python · SQLite · static Next.js) with a local language model in
the trade-decision loop and a falsification-first backtest harness. No cloud dependencies.

</div>

> Paper-first; live execution via Zerodha Kite Connect when enabled. Operates exclusively on real market data and observes real NSE market hours, products (MIS/CNC), and settlement — including in simulation.

---

## Positioning

A **research and execution terminal, not an alpha engine** — and it proves the distinction
with its own evidence. The harness (`backtest/validation.py`) tests every claimed edge
out-of-sample, net of real Indian costs, walk-forward-fenced. The verdict: **no long-only
configuration beats buy-and-hold NIFTY** — nine independent negatives; the full stack
returns ~3% CAGR vs ~11.6% (index) and ~21% (equal-weight). One open lead remains — a
fundable long-only momentum tilt on the mid-cap universe — pending a survivorship
correction. Full record: **[docs/ALPHA_FINDINGS.md](docs/ALPHA_FINDINGS.md)**.

The delivered value is **trustworthy engineering**: a single-process local stack (no cloud,
Redis, or Docker), real-data-only ingestion with degraded-mode surfacing, a 17-check
pre-trade risk gate, product-aware paper settlement, an audited Indian transaction-cost
model, and an agentic loop whose LLM judge can veto or shrink — never bypass — the gate.
The forward bet is **data, not models**: orthogonal point-in-time information (fundamentals,
firm filings, relational structure) the roadmap aims to acquire.

---

## Modules

| Module | Route | Purpose |
|--------|-------|---------|
| **MARKET** | `/` | Watchlist (72 NSE instruments + indices/FX/commodities), charts, news + sentiment, regime strip, signal feed |
| **EQUITIES** | `/trade` | Cash cockpit: portfolio statement (holdings, MIS/CNC), positions, order ticket, P&L attribution, trade history |
| **F&O** | `/fno` | Derivatives: index cockpit (greeks, lots, India VIX, signals) + option chain (Black-Scholes premiums/greeks, lot-based paper fills, SPAN-approx margin) |
| **AGENTS** | `/agents` | Scan matrix, LLM Trade Planner verdicts, supervisor loop, decision log with hindsight, streaming AI analyst |
| **TRAIN** | `/train` | Recursive LoRA fine-tune on the system's own trades + judged decisions; live loss curve + run history |
| **BACKTEST** | `/backtest` | Walk-forward over 10y real OHLCV (no lookahead); real planner in the loop; per-lens/regime/year attribution |

**Maturity:** the six modules, the risk gate, paper + Kite-live execution, F&O paper execution, training, and the backtest/validation harness are **shipped**. Module 6's forward judge (competence, LightGBM EV head), the event/PEAD plane, and a VIX-reaction matrix are **built, eval-gated, and not promoted** (they failed walk-forward — see ALPHA_FINDINGS). Multi-asset, multi-leg options, and the Firm Intelligence Graph are **roadmap** (`docs/PRD.md`).

## Screens

> Bloomberg-style dense terminal — layered dark surfaces over an embossed dot-matrix mesh, frosted-glass chrome, electric-blue accent. Captures are paper mode, market closed.

| MARKET | EQUITIES | F&O | AGENTS |
|:-:|:-:|:-:|:-:|
| ![](docs/screenshots/market.png) | ![](docs/screenshots/equities.png) | ![](docs/screenshots/fno.png) | ![](docs/screenshots/agents.png) |

## Architecture

A single multi-threaded Python process. Components communicate through an in-process
`EventBus` — no Redis, no broker. Real market data flows in; trade outcomes flow back as
three feedback loops at three speeds (supervisor → learner → recursive training). Full
detail and the data planes: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

![TERMINAL//IN system architecture](docs/architecture.svg)

The agentic decision flow:

```
6 lenses (52w · RSI · EMA · VIX · MOM · NEWS), every 120s × 72 symbols
        ▼  noise reduction: data-quality · persistence ≥2 · conf EMA · EV/regime hysteresis
top-5 candidates ▼  TRADE PLANNER — local LLM judge (approve/reject/size + decision memory)
        │            Ollama down → stricter deterministic bar (flagged, never silent)
approved ▼  M2 RISK GATE — 17 deterministic checks (planner can veto, never bypass)
        ▼  broker (paper sim / Kite REST) → settlement → P&L
        └─▶ feedback: Supervisor (per-trade breakers) · Learner (params/15 trades) · DecisionMemory (hindsight) → TRAIN
```

## What's under the hood

- **Strategy engine** — 8 rule strategies (ORB, 52w breakout, RSI reversion, EMA pullback, pairs RV, VIX fade, Hawkes momentum), 60s cadence. Cash shorts are intraday-only (MIS), per NSE.
- **Regime** — 6-state HMM (heuristic fallback until trained; degraded mode reported).
- **Risk** — 17-check pre-trade gate (+ VIX size-reduce), sector caps, drawdown/daily-loss limits, kill switch, margin check that rejects unpriceable orders.
- **Data** — real NSE OHLCV via yfinance (~10y daily + 60d 5m, gap-aware), live quotes, and FinBERT news sentiment corrected by an **India-macro layer** (a weaker rupee / fuel-price drop carry the correct broad-market sign).
- **Firm knowledge** — vector-less point-in-time RAG (SQLite FTS5/BM25, no embeddings) over real filings, announcements, and news, chunked on a rolling 5-year horizon; fed by an autonomous **firm-research collector** that maps each firm's sitemap and ingests reports/results/disclosures. Grounds the AI analyst and is the substrate for fundamentals-driven signals.
- **Health** — `/api/health` reports every degraded subsystem; no silent fallbacks in the signal path.

## Quick start

```bash
# macOS / Linux — browser-served on localhost:5000, no Node at runtime
./start.sh                 # venv + deps + static UI build, serves UI+API on :5000
./start.sh --dev           # Next.js hot-reload :3000 + API :5000
#   --live (needs KITE_ACCESS_TOKEN) · --low-latency · --check (verify prerequisites)
```

```powershell
# Windows
.\start.ps1                # venv + deps + start
.\setup_ollama.ps1         # local LLM for the Trade Planner (~2 GB, one-time)
.\packaging\build_installer.ps1   # → dist\TERMINAL-IN-Setup.exe (self-serving desktop app)
.venv\Scripts\pytest tests\ -v    # 324 tests
```

The packaged Windows `.exe` is a **self-serving desktop app** — backend on a private loopback port, UI in a native WebView2 window, no browser. First launch runs an onboarding wizard. Setup walkthrough: **[docs/STARTUP.md](docs/STARTUP.md)**.

**`.env`:** `MODE=paper|live`, `KITE_API_KEY/SECRET/ACCESS_TOKEN`, `NEWSAPI_KEY`, `INITIAL_CAPITAL`, `MAX_DD_PCT`, `DAILY_LOSS_CAP_PCT`, `PLANNER_ENABLED`. **LLM backend:** `OLLAMA_HOST`/`OLLAMA_MODEL`, or `LLM_BACKEND=openai` + `LLM_BASE_URL`/`LLM_MODEL` for any OpenAI-compatible server (e.g. a local `llama-server`).

Operator guide: [docs/USAGE.md](docs/USAGE.md) · Product spec: [docs/PRD.md](docs/PRD.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Legal: [docs/LEGAL.md](docs/LEGAL.md)

## Notes

- **Latency** — a 120s-cadence positional system on a broker REST API, not HFT. In-process EventBus, vectorized indicators, optional Python 3.14 JIT (`PYTHON_JIT=1`) and high priority (`LOW_LATENCY=1`). Upgrade path (Kite WebSocket, VPS, C hot loops) in the PRD.
- **Training** — each run rebuilds the SFT dataset (financial corpora + the system's own closed trades + hindsight-judged decisions), LoRA fine-tunes Qwen2.5-1.5B locally, and eval-gates (must beat the incumbent) before deploy.
- **Legal** — a personal analysis/automation tool, **not investment advice**. Local-first: no telemetry, no cloud, no account system. See [docs/LEGAL.md](docs/LEGAL.md).

## Roadmap (detail in [docs/PRD.md](docs/PRD.md))

- **P2** — full `strategy_engine` replay in the backtest; bundle `llama-server`+GGUF to drop the Ollama dependency; GitHub-Releases auto-update.
- **P3** — multi-asset (NSE CDS USDINR → MCX commodities → global); multi-leg options as first-class positions; the Firm Intelligence Graph (relational plane for cross-sectional signals).

## Project layout

```
terminal_in/            Python backend (threads + EventBus)
  agents/               orchestrator, trade_planner (LLM judge), supervisor, memory,
                        filters, learner, financial_agent, training/ (LoRA, deploy)
  strategy_engine/      8 strategies, regime HMM (+ pure-NumPy backend), DSA
  risk/                 M2 gate, M3 analyst, event calendar, SPAN-approx margin
  execution/            paper + F&O brokers, options pricing, Kite, settlement, cost model
  backtest/             walk-forward engine + validation.py (DSR / White RC / IC harness)
  m6/                   forward-judge experiments — built, eval-gated, NOT live
  knowledge/            firm-document RAG (FTS5 store, ingest adapters, pdf extract, rag)
  data_ingest/          yfinance, instruments, F&O contracts, events, fundamentals,
                        index membership, firm_research (sitemap collector), bse_filings
  news/                 NewsAPI + FinBERT + India-macro sentiment layer
  reporting/  persistence/  api/   (+ main, config, market_hours, hw, bus, db)
terminal_ui/            Next.js 14 — MARKET / EQUITIES / F&O / AGENTS / TRAIN / BACKTEST
tests/                  324 tests
```

---

*Single-machine, local-first, real-data-only. NSE market hours. Built with Claude Code.*
