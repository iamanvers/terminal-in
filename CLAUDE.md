# TERMINAL//IN — Claude Code Instructions

Bloomberg-style algorithmic trading terminal for Indian markets (NSE/BSE). Single-user, laptop-local, zero cloud cost except Kite Connect (₹2000/mo).

## Commands

```bash
# Run the app (paper mode)
.venv/Scripts/python.exe -m terminal_in.main

# Run via launcher (also creates venv + installs deps)
.\start.ps1

# Run tests
.venv/Scripts/pytest tests/ -v

# Train HMM regime classifier (after accumulating 500+ days of data)
.venv/Scripts/python.exe -m terminal_in.strategy_engine.regime.train --days 500

# Run UI dev server
cd terminal_ui && npm run dev   # http://localhost:3000
```

## Architecture

Single Python process, multi-threaded. All threads communicate through the in-process `EventBus` singleton (`terminal_in/bus.py`). No Redis, no Docker, no external services except the Kite WebSocket.

```
terminal_in/                        ← Python backend (48 files, all import clean)
  main.py                           — entrypoint, wires all threads
  config.py                         — load_config() reads .env
  bus.py                            — EventBus singleton (pub/sub + hot cache)
  db.py                             — thread-safe SQLite wrapper, auto-inits schema
  data_ingest/
    instruments.py                  — InstrumentRegistry, 18 symbols, stub tokens
    streamer.py                     — KiteStreamer (live WebSocket, paper mode skips)
    bhavcopy.py                     — legacy NSE bhavcopy (superseded by yf_fetcher)
    yf_fetcher.py                   — yfinance OHLCV backfill (confirmed working)
    paper_ohlcv.py                  — synthetic OHLCV seeder for paper mode (GBM)
  news/
    fetcher.py                      — NewsAPI polling, 15-min interval
    sentiment.py                    — FinBERT sentiment (ProsusAI/finbert, confirmed)
    parser.py                       — headline → NewsItem, instrument extraction
  strategy_engine/
    context.py                      — MarketContext: OHLCV + tick + regime wrapper
    engine.py                       — StrategyEngine: runs all strategies every 60s
    dsa.py                          — Dynamic Strategy Allocator (monthly rebalance)
    strategies/
      base.py                       — BaseStrategy ABC
      s1_intra_orb.py               — Opening Range Breakout (index-only)
      s2_nifty_52w.py               — 52-week high/low breakout (NIFTY/BANKNIFTY)
      s3_midcap_breakout.py         — Breakout scan (dynamic: ctx.instruments)
      s4_rsi_reversion.py           — RSI mean-reversion
      s5_mid_pullback.py            — Pullback-to-EMA (dynamic: ctx.instruments)
      s6_pairs_cointegration.py     — Pairs cointegration (dynamic combinations)
      s8_vix_asymmetry.py           — VIX spike fade
      s9_hawkes_cont.py             — Hawkes process momentum continuation
    regime/
      classifier.py                 — HMM 6-state (heuristic fallback if no .pkl)
      train.py                      — HMM training CLI (needs 500+ days data)
  risk/
    gate.py                         — RiskSupervisor: M2 12-check gate
    m3_analyst.py                   — TradeAnalyst: Bayesian scorecard
    event_calendar.py               — Economic calendar event mask
  execution/
    paper_broker.py                 — PaperBroker: fill simulation (0.03% slip + ₹20)
    kite_broker.py                  — KiteBroker: real Kite Connect REST orders
  api/
    app.py                          — Flask app factory + SocketIO init
    websocket.py                    — SocketIO WebSocket fan-out from EventBus
    routes/
      market.py                     — /api/ohlcv, /api/ticks, /api/news, /api/instruments
      portfolio.py                  — /api/portfolio
      strategies.py                 — /api/strategies (DSA scorecard)
      trades.py                     — /api/trades
      risk.py                       — /api/regime, /api/events

terminal_ui/                        ← Next.js 14 frontend (11 TSX files, all panels live)
  app/
    page.tsx                        — main layout: fixed viewport, 3-col grid
    layout.tsx                      — root layout, JetBrains Mono, globals.css
  components/
    panels/
      RiskDashboardPanel.tsx        — single-row strip: regime + equity/PnL/DD/VIX/size
      MarketDataPanel.tsx           — 18-token price table, live change%, color coded
      ChartPanel.tsx                — lightweight-charts candlestick, 6 symbols, 3 TFs
      StrategyBookPanel.tsx         — DSA scorecard + allocation bars
      PositionsPanel.tsx            — open positions table, live P&L
      SignalFeedPanel.tsx           — signals/news/events tabs
    primitives/
      Badge.tsx                     — variant badges: side, sentiment, impact, regime
      StatusDot.tsx                 — WS connection indicator
      PriceTag.tsx                  — color-coded price with change%
```

## Key Design Decisions

**Local-only stack** — Original blueprint used Docker + TimescaleDB + Redis + MinIO. Replaced with SQLite (WAL mode) + Python EventBus + local folders. Docker doesn't run on this machine.

**EventBus topics** — `ticks.{token}`, `regime.update`, `strategy.signal`, `order.approved`, `order.rejected`, `trade.opened`, `trade.closed`, `pnl.update`, `scorecard.update`, `news.signal`, `event.mask`. Glob matching: `ticks.*` catches all tokens.

**Paper vs live** — Controlled by `MODE=paper|live` in `.env`. PaperBroker simulates fills with 0.03% slippage + ₹20/order commission. KiteBroker uses real Kite Connect REST. `use_kite_live` is only true when `MODE=live` AND `KITE_ACCESS_TOKEN` is set.

**Paper tick feed** — `main._start_paper_tick_feed()` tracks session-open price per token. Change% is calculated as `(current - session_open) / session_open * 100` — not random noise. Ticks at 1-second intervals with Gaussian(0, 0.02%) micro-volatility.

**OHLCV data** — `yf_fetcher.backfill()` downloads real NSE data via yfinance (confirmed: NIFTY 50 at 24,092 on 2026-04-27). Symbols mapped via `YF_MAP`: NIFTY 50→^NSEI, BANKNIFTY→^NSEBANK, VIX→^INDIAVIX, equities→SYMBOL.NS. `paper_ohlcv.seed()` seeds synthetic bars on first startup if DB is empty.

**DB API conventions** — `get_ohlcv_1d(token, limit=300)` and `get_ohlcv_1m(token, limit=500)` return pandas DataFrames with DatetimeIndex. `insert_trade(dict)` accepts both `instrument_id` (new code) and `instrument_token` (Kite format). `close_trade(trade_id, data_dict)` accepts a dict with `pnl`, `exit_reason`, `closed_at`.

**pandas 2.x timestamp serialization** — `datetime64[ms, UTC].astype('int64')` returns milliseconds (not nanoseconds) in pandas 2.x. Always convert via `(series - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1ms')` in API routes.

**HMM classifier** — 6 states: strong_bull, bull, sideways, bear, strong_bear, high_vol. Falls back to heuristic mode if `hmm_model.pkl` not present (expected at start before 500 days of data exist). 3-day hysteresis prevents thrashing.

**DSA scoring** — `0.40 × regime_fit + 0.30 × Bayesian_WR + 0.30 × rolling_Sharpe`. Monthly rebalance, ±15% gradient cap per cycle, 5% floor per strategy.

**M2 gate order** — event_mask → VIX hard stop → drawdown → daily loss cap → daily trade count → confidence threshold → max open positions → no duplicate instrument → margin → sector (stub) → correlation → VIX reduce (non-blocking).

**Strategy instrument scanning** — S3/S5/S6 scan `ctx.instruments` dynamically, no hardcoded symbol lists. S3 = all non-index equities; S5 = same; S6 = combinations of first 10 equities, max 15 pairs.

**ChartPanel race condition** — `chartReady` state flag ensures OHLCV data load only fires after lightweight-charts is initialized (both useEffects fire simultaneously on mount without this).

**Instrument registry** — 18 symbols with stable paper-mode tokens: NIFTY 50 (256265), BANKNIFTY (260105), FINNIFTY (257801), INDIA VIX (264969), NIFTYBEES (2800641), RELIANCE (738561), HDFCBANK (341249), TCS (2953217), INFY (408065), ICICIBANK (1270529), SBIN (779521), AXISBANK (1510401), KOTAKBANK (492033), BAJFINANCE (4267265), HINDUNILVR (356865), WIPRO (969473).

## Dependencies

Install: `pip install -r requirements.txt` (inside `.venv`).

**hmmlearn** — needs Microsoft C++ Build Tools to compile on Windows. Regime classifier works in heuristic mode without it. Install Build Tools from https://visualstudio.microsoft.com/visual-cpp-build-tools/ then `pip install hmmlearn>=0.3.2`.

**FinBERT (torch + transformers)** — ~3 GB, optional. Installed and confirmed working: `ProsusAI/finbert` via torch 2.11.0+cpu + transformers 5.6.2. Install separately: `pip install torch --index-url https://download.pytorch.org/whl/cpu` then `pip install transformers`. News sentiment degrades gracefully to neutral/0.0 if not installed.

**yfinance** — `yfinance>=0.2.38` in requirements.txt. Confirmed working for NSE data. Used for OHLCV backfill only (not real-time ticks).

## Environment

Python 3.14 on Windows 11. Interpreter: `.venv/Scripts/python.exe`. VS Code interpreter set via `.vscode/settings.json`.

`.env` variables: `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN` (daily), `NEWSAPI_KEY`, `JWT_SECRET`, `MODE` (paper/live), `INITIAL_CAPITAL=1000000`, `MAX_DD_PCT=0.20`, `DAILY_LOSS_CAP_PCT=0.04`.

## What's Built / What's Next

**Complete (Python backend — 48 files, all import clean):**
- Foundation: config, bus, db, schema
- Data ingest: KiteStreamer, yfinance backfill, synthetic paper OHLCV, instrument registry (18 symbols)
- News: NewsAPI fetcher, FinBERT sentiment (confirmed), parser
- Strategy engine: MarketContext, 8 strategies (S1–S9 except S7), HMM classifier, DSA, engine loop
- Risk: M2 gate (12 checks), M3 analyst (Bayesian scorecard), event calendar
- Execution: PaperBroker, KiteBroker
- API: Flask app factory, 6 route blueprints, SocketIO WebSocket fan-out

**Complete (Terminal UI — 11 TSX files, all panels functional):**
- Layout: fixed viewport, 3-column responsive grid, risk strip above grid
- RiskDashboardPanel: regime, equity, day P&L, drawdown, VIX, size multiplier, positions, trades, circuit breaker warning
- MarketDataPanel: 18-token live price table, real session change%, color-coded
- ChartPanel: lightweight-charts candlestick, 6 symbols, 1m/5m/1d, live tick updates
- StrategyBookPanel: DSA scorecard + allocation bars
- PositionsPanel: open positions, live P&L
- SignalFeedPanel: signals tab (with symbol names, live prices, targets, SL), news tab, events tab

**Remaining:**
- Tests — unit + integration (no test coverage yet)
- Backtest module — historical strategy simulation, performance metrics
- ws-bridge — optional Node.js WebSocket bridge (not needed, SocketIO handles it)
