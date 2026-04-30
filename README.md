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
- Last close prices served to UI even when market is closed — no blank tickers

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
- HMM-based 6-state regime classifier (strong_bull → strong_bear → high_vol) with size multipliers
- Dynamic Strategy Allocator (DSA): monthly rebalance using Bayesian win rate + Sharpe + regime fit
- M2 Risk Gate: 13 pre-trade checks (kill switch, tradeable instrument, VIX, drawdown, daily loss cap, signal dedup, duplicate position, margin, sector concentration, directional correlation, event mask)
- M3 Analyst: Bayesian scorecard per strategy with adaptive confidence thresholds (Half-Kelly sizing)

**3. Agentic Orchestrator**
- `TradeOrchestrator`: multi-lens EV-ranked scanner across all instruments (auto every 2 min)
- Scores setups by Expected Value: `EV = confidence × R:R × vol_factor × convergence_bonus`
- On-demand scan via AGENTS page button or `POST /api/strategies/orchestrator/scan`
- `StrategyLearner`: online Bayesian WR updates confidence thresholds after each trade closes
- Per-strategy adaptive parameters: min_confidence, kelly_fraction, sl_multiplier, target_multiplier

**4. Execution & Paper Trading**
- Paper broker: fill simulation with 0.03% slippage + ₹20/order commission
- Capital-constrained: orders rejected when notional exceeds available equity
- EOD settlement: auto-closes all intraday positions at 15:29 IST, snapshots equity, resets daily counters
- Live broker: Kite Connect REST integration (Zerodha) for live mode
- Per-trade journal: entry reasoning, exit analysis, lessons, rating, review status

---

## Architecture

```
Single Python process, multi-threaded. All components communicate via in-process EventBus.

terminal_in/                   ← Python backend
  main.py                      — entrypoint, wires all threads
  bus.py                       — EventBus singleton (pub/sub + hot-cache)
  db.py                        — SQLite WAL wrapper (thread-safe, 6 indexes)
  config.py                    — load_config() reads .env
  data_ingest/                 — tick feed, OHLCV backfill, paper seeder, instrument registry (18 symbols)
  news/                        — NewsAPI + FinBERT sentiment
  strategy_engine/             — 8 strategies, HMM classifier, DSA, engine loop, MarketContext
  risk/                        — M2 gate (13 checks), M3 analyst, event calendar
  execution/                   — PaperBroker, KiteBroker, SettlementService
  agents/                      — TradeOrchestrator (EV-ranked multi-lens scan), StrategyLearner
  api/                         — Flask + SocketIO, 6 route blueprints

terminal_ui/                   ← Next.js 14 frontend
  app/
    page.tsx                   — main dashboard: fixed viewport, 3-column layout
    agents/page.tsx            — agent monitoring + orchestrator + controls
    trade/page.tsx             — trade cockpit: positions + order ticket
  components/panels/           — MarketData, Chart, Strategy, Positions, Signals, Chat, RiskDashboard
```

**EventBus topics:** `ticks.{token}`, `regime.update`, `strategy.signal`, `order.approved`, `order.rejected`, `trade.opened`, `trade.closed`, `pnl.update`, `scorecard.update`, `news.signal`, `event.mask`, `orchestrator.scan_done`, `settlement.day_open`, `settlement.eod_close`, `settlement.eod_reset`

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
# Edit .env: set MODE=paper, INITIAL_CAPITAL=1000000

# Start backend
.venv/Scripts/python.exe -m terminal_in.main

# Start UI (separate terminal)
cd terminal_ui && npm install && npm run dev
# → http://localhost:3000
```

**Or use the PowerShell launcher (creates venv + installs deps + starts both):**
```powershell
.\start.ps1
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
| `NEWSAPI_KEY` | — | Optional news feed (~24 requests/day) |
| `JWT_SECRET` | `dev-secret` | API auth secret |

---

## Risk Gate (M2) — 13 Checks

| # | Check | Blocks if |
|---|---|---|
| 0a | Kill switch | Global pause engaged |
| 0b | Symbol block | Instrument manually blocked |
| 0c | Tradeable instrument | VIX / raw NIFTY / BANKNIFTY / FINNIFTY (F&O-only, not cash tradeable) |
| 1 | Event mask | Within economic event blackout window (live only) |
| 2 | VIX hard stop | India VIX > 35 |
| 3 | Drawdown circuit | Portfolio drawdown > MAX_DD_PCT |
| 4 | Daily loss cap | Day P&L loss > DAILY_LOSS_CAP_PCT |
| 5 | Trade count | Daily trades ≥ 20 (live) / 200 (paper) |
| 6 | Confidence | Signal confidence < adaptive min (per StrategyLearner) |
| 7 | Position limit | ≥ 10 open positions |
| 8 | Duplicate | Same instrument already open |
| 8b | Signal dedup | Same instrument approved < 5 minutes ago |
| 9 | Margin | Trade notional > 30% of equity |
| 10 | Sector concentration | Adding position would put > 40% of book in one sector |
| 11 | Directional crowding | ≥ 3 open positions in same sector + same direction |
| 12 | VIX reduce *(non-blocking)* | VIX > 25 → halves quantity |

---

## Instruments (18)

**Non-tradeable (indices only — excluded from order flow):**
NIFTY 50, BANKNIFTY, FINNIFTY, INDIA VIX

**Tradeable:**
NIFTYBEES (ETF), RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, BAJFINANCE, HINDUNILVR, WIPRO, LT, MARUTI, ADANIPORTS

---

## UI Layout

### Main Dashboard (`/`)
```
┌──────────────────────────────────────────────────────────────────────┐
│  TERMINAL//IN  [live ticker tape — always scrolling]    ● LIVE/DISC  │
├──────────────────────────────────────────────────────────────────────┤
│  REGIME STRIP: current regime + size multiplier + full 6-state legend│
├──────────────┬──────────────────────┬────────────────────────────────┤
│  MARKET DATA │    CANDLESTICK       │     CHAT (AI assistant)        │
│  NSE / BSE   │    EMA 9/21, Volume  │                                │
│  GLOBAL / FX │    1m / 5m / 1d     │                                │
├──────────────┼──────────────────────┼────────────────────────────────┤
│  STRATEGY    │  OPEN POSITIONS      │  SIGNAL FEED                   │
│  BOOK + DSA  │  Live P&L/SL/Target  │  Signals / News / Events       │
└──────────────┴──────────────────────┴────────────────────────────────┘
```

### Agent Dashboard (`/agents`)
```
┌─────────────────────────────────────────────────────────────────────┐
│  COMMAND STRIP: system health · regime · equity · decision funnel   │
├─────────────┬───────────────────────────────┬───────────────────────┤
│  AGENT      │  MATRIX / PIPELINE /          │  INSPECTOR            │
│  GROUPS     │  SCOREBOARD / BROADCAST       │  (selected agent or   │
│             │                               │   signal lineage)     │
│  TRIGGER    │  [Orchestrator scan results]  │                       │
│  AGENTS     │  [Strategy agent cards]       │                       │
│             │  [System agent cards]         │                       │
│  RISK       │                               │                       │
│  COMMAND    │                               │                       │
└─────────────┴───────────────────────────────┴───────────────────────┘
```

---

## Tests

```bash
.venv/Scripts/pytest tests/ -v
# 77 tests covering:
#   DB persistence (signal lineage, risk decisions, portfolio snapshots)
#   Risk gate — all 13 checks including sector/correlation/non-tradeable
#   Paper broker — capital tracking, PnL, SL/target auto-close, multi-position
```

---

## Regime States

| State | Color | Size × | Description |
|---|---|---|---|
| strong_bull | green | 1.2 | Trending hard up — full size |
| bull | green | 1.0 | Uptrend — normal size |
| sideways | amber | 0.7 | Range-bound — reduced size |
| bear | red | 0.5 | Downtrend — defensive |
| strong_bear | dark red | 0.3 | Hard down — minimal exposure |
| high_vol | purple | 0.2 | VIX elevated — halved size |

The regime strip at the top of every page shows the current state and all 6 states as a legend.

---

## Roadmap

### ✅ Module 1 — Market Intelligence
Live data, news sentiment, regime classifier, strategy engine, risk gate, execution. **Complete.**

### ✅ Module 2 — Trade Execution & Settlement
Paper cockpit, capital constraints, EOD settlement, learner feedback loop, 77 tests. **Complete.**

### ✅ Module 3 — Agent Dashboard & Controls
Per-agent state monitoring, strategy evaluation logs, pause/resume/force-eval, signal lineage inspector, EventBus broadcast inspector, orchestrator scan results, on-demand agent execution. **Complete.**

### Module 4 — Strategy Training & Backtesting
Historical backtest runner (walk-forward validation), HMM training UI (500+ day threshold), feature importance by regime, LLM-proposed strategy rules, strategy gene pool.
