# TERMINAL//IN

A Bloomberg-style algorithmic trading terminal for Indian equity markets (NSE/BSE), built to run entirely on a personal laptop. No cloud costs, no Docker, no external infrastructure — just Python, SQLite, and a Next.js UI.

---

## What It Does

TERMINAL//IN is a complete algorithmic trading system across four layers:

**1. Market Intelligence**
- Live price streaming for 18 NSE instruments (indices + large-cap equities)
- Real OHLCV data via yfinance (2-year history, backfilled on startup)
- Global market context: indices (DOW, S&P, NIKKEI, FTSE), FX rates, commodities, VIX
- News feed with FinBERT sentiment analysis (positive/negative/neutral)
- Economic calendar with event risk masking

**2. Autonomous Strategy Engine**
- 8 live strategies running every 60 seconds:
  - S1: Intraday Opening Range Breakout (NIFTY/BANKNIFTY)
  - S2: 52-Week High Breakout
  - S3: Midcap Momentum Breakout
  - S4: RSI Mean Reversion
  - S5: EMA Pullback (trend continuation)
  - S6: Pairs Cointegration (statistical arbitrage)
  - S8: VIX Spike Asymmetry (contrarian)
  - S9: Hawkes Process Momentum
- HMM-based 6-state regime classifier (strong_bull → strong_bear → high_vol)
- Dynamic Strategy Allocator (DSA): monthly rebalance using Bayesian win rate + Sharpe + regime fit
- M2 Risk Gate: 12-check pre-trade filter (VIX, drawdown, daily loss cap, signal dedup, correlation, event mask)
- M3 Analyst: Bayesian scorecard per strategy with adaptive confidence thresholds

**3. Agent Orchestrator**
- `TradeOrchestrator`: multi-lens analysis engine that scans all instruments every 2 minutes
- Scores setups by Expected Value (EV = confidence × R:R × vol_factor × convergence bonus)
- Fires top-K signals directly to execution; publishes ranked opportunity list to UI
- On-demand scan via UI button or API endpoint
- Learns from past trades via StrategyLearner (Bayesian WR feeds back into confidence weights)

**4. Execution & Paper Trading Cockpit**
- Paper broker: fill simulation with 0.03% slippage + ₹20/order commission
- Capital-constrained: orders rejected when notional exceeds available equity
- Short selling supported (SELL without an open position)
- Live broker: Kite Connect REST integration (Zerodha) for live mode
- Per-trade journal: entry reasoning, exit analysis, lessons, rating, review status
- Real-time WebSocket push to UI via SocketIO
- EOD settlement: auto-closes all positions at 15:30 IST, snapshots equity, resets daily counters

---

## Architecture

```
Single Python process, multi-threaded. All components communicate via in-process EventBus.

terminal_in/                   ← Python backend (48 files)
  main.py                      — entrypoint, wires all threads
  bus.py                       — EventBus singleton (pub/sub + hot-cache)
  db.py                        — SQLite WAL wrapper (thread-safe)
  config.py                    — load_config() reads .env
  data_ingest/                 — tick feed, OHLCV backfill, paper seeder, instrument registry
  news/                        — NewsAPI + FinBERT sentiment
  strategy_engine/             — 8 strategies, HMM classifier, DSA, engine loop, MarketContext
  risk/                        — M2 gate (12 checks), M3 analyst, event calendar
  execution/                   — PaperBroker, KiteBroker
  agents/                      — TradeOrchestrator (EV-ranked multi-lens scan)
  api/                         — Flask + SocketIO, 6 route blueprints

terminal_ui/                   ← Next.js 14 frontend (12 TSX files)
  app/
    page.tsx                   — main dashboard: fixed viewport, 3-column layout
    trade/page.tsx             — trade cockpit: agent panel + positions + order ticket
  components/panels/           — MarketData, Chart, Strategy, Positions, Signals, Chat
```

**EventBus topics:** `ticks.{token}`, `regime.update`, `strategy.signal`, `order.approved`, `order.rejected`, `trade.opened`, `trade.closed`, `pnl.update`, `scorecard.update`, `news.signal`, `event.mask`, `orchestrator.scan_done`

**Why local-only?** The original blueprint used Docker + TimescaleDB + Redis + MinIO. All replaced with SQLite (WAL mode) + Python EventBus + local folders. Total cost: ₹2000/month for Kite Connect in live mode. Zero otherwise.

---

## Setup

**Prerequisites:** Python 3.14, Node.js 18+, Windows 11

```bash
# Python backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

# Optional: FinBERT sentiment (~3GB, improves news signals)
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/pip install transformers

# Optional: HMM classifier (needs C++ Build Tools on Windows)
.venv/Scripts/pip install hmmlearn>=0.3.2

# Configure environment
copy .env.example .env
# Set: MODE=paper, INITIAL_CAPITAL=1000000

# Start backend
.venv/Scripts/python.exe -m terminal_in.main

# Start UI (separate terminal)
cd terminal_ui && npm install && npm run dev
# → http://localhost:3000  (main dashboard)
# → http://localhost:3000/trade  (trade cockpit)
```

**Or use the launcher (Windows):**
```powershell
.\start.ps1   # creates venv, installs deps, starts both processes
```

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `MODE` | `paper` | `paper` or `live` |
| `INITIAL_CAPITAL` | `1000000` | Starting capital in ₹ |
| `MAX_DD_PCT` | `0.20` | Max drawdown before circuit breaker |
| `DAILY_LOSS_CAP_PCT` | `0.04` | Max daily loss as % of capital |
| `KITE_API_KEY` | — | Required for live mode |
| `KITE_API_SECRET` | — | Required for live mode |
| `KITE_ACCESS_TOKEN` | — | Daily token from Kite login |
| `NEWSAPI_KEY` | — | Optional, ~24 requests/day at 2-hour intervals |
| `JWT_SECRET` | `dev-secret` | API auth secret |

---

## Instruments (18)

**Indices:** NIFTY 50, BANKNIFTY, FINNIFTY, INDIA VIX, NIFTYBEES

**Large-cap equities:** RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, BAJFINANCE, HINDUNILVR, WIPRO, ADANIPORTS (+ more via instrument registry)

---

## UI Layout

### Main Dashboard (`/`)
```
┌─────────────────────────────────────────────────────┐
│  TERMINAL//IN          [ticker marquee]     ● LIVE  │
├─────────────────────────────────────────────────────┤
│  REGIME · EQUITY · P&L · DRAWDOWN · VIX · SIZE     │
├──────────────┬──────────────────────┬───────────────┤
│  MARKET DATA │    CANDLESTICK       │     CHAT      │
│  NSE / Global│    EMA 9/21, Volume  │     AI        │
│  FX / Commod │    1m / 5m / 1d     │               │
├──────────────┼──────────────────────┼───────────────┤
│  STRATEGY    │  OPEN POSITIONS      │  SIGNAL FEED  │
│  BOOK + DSA  │  Live P&L            │  Signals/News │
└──────────────┴──────────────────────┴───────────────┘
```

### Trade Cockpit (`/trade`)
```
┌──────────────────┬───────────────────┬──────────────┐
│  AGENT COCKPIT   │  OPEN POSITIONS   │ ORDER TICKET │
│  OPPORTUNITIES   │  Live P&L/SL/Tgt  │ BUY / SELL   │
│  SIGNAL LOG      │                   │ auto SL/size │
│  JOURNAL         ├───────────────────┼──────────────┤
│                  │  CLOSED TRADES    │  LEARNING    │
│  [SCAN NOW] btn  │  filter + history │  attribution │
└──────────────────┴───────────────────┴──────────────┘
Stats strip: EQUITY · DAY P&L · DRAWDOWN · WIN RATE · TOTAL P&L · POSITIONS
```

---

## Tests

```bash
.venv/Scripts/pytest tests/ -v
# 57 tests covering: DB persistence, risk gate (12 checks + signal dedup),
# paper broker (capital tracking, PnL, SL/target, multi-position)
```

---

## Roadmap

### ✅ Module 1 — Market Intelligence
Live data, news sentiment, regime classifier, strategy engine, risk gate, execution. **Complete.**

### ✅ Module 2 — Trade Execution & Settlement
Paper trading cockpit, capital constraints, signal dedup, agent orchestrator, trade journal, EOD settlement, learner feedback loop, 57 tests. **Complete.**

### Module 3 — Agent Dashboard & Controls
Per-agent state monitoring, live strategy evaluation logs, agent pause/resume/force-eval, signal lineage inspector, EventBus message inspector.

### Module 4 — Strategy Training & Backtesting
Historical backtest runner (walk-forward validation), HMM training UI (500+ day threshold), feature importance by regime, LLM-proposed strategy rules via Ollama + phi3:mini, strategy gene pool.

---

## Development Notes

- **Paper mode ticks**: Synthetic ticks fire every second from historical close prices (Gaussian micro-vol). Chart tick updates are gated to market hours (09:15–15:30 IST Mon–Fri) to avoid post-close bar pollution.
- **Signal dedup**: Same instrument is blocked for 5 minutes after approval to prevent strategy flood. Paper mode allows 200 trades/day vs 20 in live.
- **Capital tracking**: PaperBroker tracks `capital_in_use` (sum of open position notionals). Orders exceeding available equity are hard-rejected.
- **Live mode**: Set `MODE=live` + valid `KITE_ACCESS_TOKEN`. KiteStreamer opens WebSocket, KiteBroker places real orders via Kite Connect REST.
- **HMM classifier**: Heuristic mode until 500+ trading days accumulate. Train: `.venv/Scripts/python -m terminal_in.strategy_engine.regime.train --days 500`
- **FinBERT**: Optional. Degrades gracefully to neutral/0.0 if not installed.
- **Ports**: Flask API on 5000, Next.js on 3000. Next.js rewrites `/api/*` → `localhost:5000`.
