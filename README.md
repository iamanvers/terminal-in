# TERMINAL//IN

A Bloomberg-style algorithmic trading terminal for Indian equity markets (NSE/BSE), built to run entirely on a personal laptop. No cloud costs, no Docker, no external infrastructure — just Python, SQLite, and a Next.js UI.

---

## What It Does

TERMINAL//IN is a complete algorithmic trading system with three layers:

**1. Market Intelligence**
- Live price streaming for 36 NSE instruments (Nifty 50 constituents + indices)
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
- M2 Risk Gate: 12-check pre-trade filter (VIX, drawdown, daily loss cap, correlation, event mask)
- M3 Analyst: Bayesian scorecard per strategy

**3. Execution & Monitoring**
- Paper broker: full fill simulation with 0.03% slippage + ₹20/order commission
- Live broker: Kite Connect REST integration (Zerodha)
- Per-symbol agentic analysis: RSI-14, EMA-20/50, ATR-14, 52W H/L, strategy lens verdicts
- Real-time WebSocket push to UI via SocketIO

---

## Architecture

```
Single Python process, multi-threaded. All components communicate via in-process EventBus.

terminal_in/                   ← Python backend
  main.py                      — entrypoint, wires all threads
  bus.py                       — EventBus singleton (pub/sub + hot-cache)
  db.py                        — SQLite WAL wrapper (thread-safe)
  data_ingest/                 — tick feed, OHLCV backfill, paper seeder
  news/                        — NewsAPI + FinBERT sentiment
  strategy_engine/             — 8 strategies, HMM classifier, DSA, engine loop
  risk/                        — M2 gate, M3 analyst, event calendar
  execution/                   — PaperBroker, KiteBroker
  api/                         — Flask + SocketIO, 6 route blueprints

terminal_ui/                   ← Next.js 14 frontend
  app/page.tsx                 — fixed viewport, 3-column Bloomberg-style layout
  components/panels/           — MarketData, Chart, Strategy, Positions, Signals, Chat
```

**Why local-only?** The original blueprint used Docker + TimescaleDB + Redis + MinIO. All replaced with SQLite (WAL mode) + Python EventBus + local folders. Total cost: ₹2000/month for Kite Connect in live mode. Zero otherwise.

**EventBus topics:** `ticks.{token}`, `regime.update`, `strategy.signal`, `order.approved`, `order.rejected`, `trade.opened`, `trade.closed`, `pnl.update`, `scorecard.update`, `news.signal`, `event.mask`

---

## Setup

**Prerequisites:** Python 3.14, Node.js 18+, Windows 11 (or adapt paths)

```bash
# Clone and set up Python venv
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

# Optional: FinBERT sentiment (3GB, worth it)
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/pip install transformers

# Optional: HMM classifier (needs C++ Build Tools on Windows)
.venv/Scripts/pip install hmmlearn>=0.3.2

# Configure .env (copy from .env.example)
cp .env.example .env
# Edit: MODE=paper, INITIAL_CAPITAL=1000000, optionally NEWSAPI_KEY

# Start backend
.venv/Scripts/python.exe -m terminal_in.main

# Start UI (in another terminal)
cd terminal_ui && npm install && npm run dev
# → http://localhost:3000
```

**Or use the launcher:**
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

## Tracked Instruments (36 total)

**Indices:** NIFTY 50, BANKNIFTY, FINNIFTY, INDIA VIX, NIFTYBEES
**Large-cap equities (Nifty 50 + SENSEX 30 core):**
RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, BAJFINANCE, HINDUNILVR, WIPRO, LT, MARUTI, ASIANPAINT, TATAMOTORS, SUNPHARMA, TATASTEEL, POWERGRID, NTPC, ONGC, TITAN, HCLTECH, TECHM, ADANIPORTS, ULTRACEMCO, NESTLEIND, JSWSTEEL, DRREDDY, BAJAJFINSV, DIVISLAB, HINDALCO

---

## UI Layout

```
┌─────────────────────────────────────────────────────┐
│  TERMINAL//IN          [ticker marquee]     ● LIVE  │
├─────────────────────────────────────────────────────┤
│  REGIME · EQUITY · P&L · DRAWDOWN · VIX · SIZE     │
├──────────────┬──────────────────────┬───────────────┤
│              │                      │               │
│  MARKET DATA │    CANDLESTICK       │     CHAT      │
│  NSE / BSE   │    CHART             │     AI        │
│  GLOBAL / FX │    EMA 9/21          │               │
│  COMMOD/RISK │    Volume            │               │
├──────────────┼──────────────────────┼───────────────┤
│  STRATEGY    │    OPEN POSITIONS    │  TOP SIGNALS  │
│  BOOK + DSA  │    Live P&L          │  (deduplicated│
├──────────────┴──────────────────────┴───────────────┤
│  SIGNAL FEED  [SIGNALS | NEWS | EVENTS]             │
└─────────────────────────────────────────────────────┘
```

Click any ticker → instrument modal (price, RSI/EMA/ATR indicators, strategy lens analysis, sparkline, news)
Click any global/FX/commod quote → price modal with 90-day sparkline

---

## Roadmap

### Module 2 — Trade Execution & Settlement (Paper Trading Cockpit)
Full paper trading simulation with realistic market mechanics:
- Manual trade entry alongside automated strategy signals
- Intraday settlement simulation against real OHLCV prices
- P&L attribution: strategy vs manual, sector, regime
- Trade journal with entry/exit reasoning
- Drawdown analytics and position sizing feedback
- Feeds performance data back into DSA rebalance cycle

### Module 3 — Agent Orchestrator Dashboard
Real-time monitoring of all autonomous strategy agents:
- Per-agent state: running/paused/error, last signal, last evaluation
- Live strategy evaluation logs with market context
- Agent controls: pause, resume, force-evaluate, adjust confidence threshold
- Signal lineage: see which regime + indicators triggered a specific trade
- EventBus message inspector (live pub/sub stream)

### Module 4 — Strategy Training & Backtesting
Build more dynamic strategies using ML instead of pure math:
- Historical backtest runner: replay OHLCV through strategy engine
- Walk-forward validation to prevent overfitting
- HMM classifier training UI (accumulate 500+ trading days first)
- Feature importance analysis: which indicators matter per regime
- Agent-generated strategies: LLM proposes new strategy rules → backtest → promote
- Strategy gene pool: combine elements of high-performing strategies

---

## Development Notes

- **Paper mode**: All 36 instruments stream synthetic ticks every second from real historical closing prices. Strategies evaluate every 60s. Paper fills execute immediately with slippage simulation.
- **Live mode**: Set `MODE=live` + valid `KITE_ACCESS_TOKEN`. KiteStreamer opens WebSocket, KiteBroker places real orders.
- **HMM classifier**: Runs in heuristic mode until 500+ trading days accumulate. Train with: `.venv/Scripts/python -m terminal_in.strategy_engine.regime.train --days 500`
- **FinBERT**: Optional but recommended. Degrades gracefully to neutral sentiment if not installed.
- **Port 5000**: Flask API. Port 3000: Next.js UI. No proxy needed; Next.js rewrites `/api/*` → `localhost:5000`.
