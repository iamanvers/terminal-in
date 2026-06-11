# TERMINAL//IN — Claude Code Instructions

Bloomberg-style **agentic** algorithmic trading terminal for Indian markets (NSE/BSE). Single-user, laptop-local, zero cloud cost except Kite Connect (₹2000/mo).

## Commands

```bash
# Run the app (paper mode)
.venv/Scripts/python.exe -m terminal_in.main

# Run via launcher (also creates venv + installs deps)
.\start.ps1

# Run tests (119 passing)
.venv/Scripts/pytest tests/ -v

# Train HMM regime classifier (after accumulating 500+ days of data)
.venv/Scripts/python.exe -m terminal_in.strategy_engine.regime.train --days 500

# LoRA fine-tune the financial SLM (smoke test: LORA_MAX_STEPS=200)
.venv/Scripts/python.exe -m terminal_in.agents.training.train_lora

# Ollama setup (installs Ollama, pulls qwen2.5:3b, creates financial-analyst)
.\setup_ollama.ps1

# Run UI dev server
cd terminal_ui && npm run dev   # http://localhost:3000

# Recursive training (also triggerable from /train UI)
#   smoke: POST /api/training/start {"max_steps": 200} — full: {"max_steps": -1}

# Low-latency mode (HIGH process priority + Python 3.14 experimental JIT)
.\start.ps1 -LowLatency
```

## Architecture

Single Python process, multi-threaded (real OS threads — **no eventlet**, see below). All threads communicate through the in-process `EventBus` singleton (`terminal_in/bus.py`). No Redis, no Docker.

**Agentic decision flow** (the core of Module 3):
```
orchestrator (6 deterministic lenses, 120s scan)
  → signal_filters (persistence debounce ≥2 scans, conf EMA, EV hysteresis, data-quality gate)
  → planner.candidates batch (top-5 eligible)
  → TradePlanner (1 Ollama LLM call/scan, JSON verdicts: approve/reject/size + reasoning)
  → strategy.signal → M2 risk gate (12 checks, unchanged) → broker
TradingSupervisor closes the loop: lens circuit breaker (3 losses → 2h suppression),
global throttle (5 losses → fewer candidates + higher EV bar), hard stop (8 → KillSwitch).
DecisionMemory persists every verdict; hindsight loop re-prices rejected candidates
after 4–72h (would_win/would_lose) and feeds the record back into the planner prompt.
```

```
terminal_in/                        ← Python backend
  main.py                           — entrypoint, wires all threads, port-conflict check
  config.py                         — load_config() reads .env (incl. PLANNER_ENABLED)
  bus.py                            — EventBus singleton (pub/sub + hot cache)
  db.py                             — thread-safe SQLite wrapper, auto-inits schema + migrations
  agents/
    orchestrator.py                 — TradeOrchestrator: 6-lens scan (S2/S4/S5/S8/MOM/NEWS),
                                      EV ranking, planner batch handoff
    trade_planner.py                — TradePlanner: LLM judge (Ollama qwen2.5:3b, format=json,
                                      45s timeout; degraded = stricter deterministic bar, flagged)
    decision_memory.py              — agent_decisions audit + hindsight loop + prompt context
    supervisor.py                   — TradingSupervisor: lens breakers, throttle, hard stop
    signal_filters.py               — CandidateTracker, RegimeHysteresis, data_quality (pure, tested)
    strategy_learner.py             — Bayesian WR tracking, adaptive params per 15 closed trades
    control.py                      — AgentRegistry + KillSwitch singletons
    financial_agent.py              — Ollama chat agent w/ yfinance tools (AI ANALYST tab)
    tools/yfinance_tools.py         — get_stock_data, scans, fundamentals
    training/
      prepare_dataset.py            — SFT dataset (sentiment + finance-alpaca + strategy_pairs
                                      + own trades + hindsight-judged agent decisions)
      strategy_pairs.py             — Claude-generated NSE strategy QA pairs
      train_lora.py                 — TinyLlama-1.1B LoRA (TRL 1.x API, UTF-8 re-exec,
                                      env: LORA_DATASET_DIR/LORA_OUTPUT_DIR/LORA_MAX_STEPS)
      recursive.py                  — TrainingOrchestrator: dataset→LoRA subprocess→metrics
                                      per run dir, training_runs table, 'training.status' topic
  data_ingest/
    instruments.py                  — InstrumentRegistry, 72 symbols, symbol-keyed SECTOR_MAP
                                      (single source of truth — gate resolves token→symbol→sector)
    streamer.py                     — KiteStreamer (live mode only)
    yf_fetcher.py                   — gap-aware yfinance backfill (730d daily + 60d 5m)
    yf_live.py                      — real-time price feed via yfinance (REAL prices, no noise)
    paper_tick_agg.py               — aggregates live ticks → 1m bars
  news/                             — NewsAPI fetcher, FinBERT sentiment, parser
  strategy_engine/                  — engine (8 strategies S1–S9 ex S7), DSA, regime/ (HMM)
  risk/                             — gate.py (M2 12-check), m3_analyst.py, event_calendar.py
  execution/                        — paper_broker, kite_broker, settlement (EOD close)
  api/
    app.py                          — Flask factory, SocketIO async_mode='threading',
                                      /api/health degraded-mode report
    websocket.py, event_buffer.py   — EventBus → SocketIO fan-out + ring buffer
    routes/                         — market, portfolio, strategies, trades, risk, chat,
                                      agents (planner/supervisor), agent_query, training

terminal_ui/                        ← Next.js 14 frontend (modules: MARKET·EQUITIES·F&O·AGENTS·TRAIN)
  app/page.tsx                      — MARKET: boot gate w/ retry+backoff, 3-col grid
  app/trade/page.tsx                — EQUITIES: cash cockpit (order ticket = EQ instruments only)
  app/fno/page.tsx                  — F&O: index complex + lot sizes, index signals, VIX context,
                                      Phase-2 derivatives scaffold (chain/lots/SPAN — see PRD)
  app/agents/page.tsx               — AGENTS: matrix, OrchestratorPanel, PlannerPanel,
                                      SupervisorPanel, DECISION LOG tab (hindsight), AI ANALYST
  app/train/page.tsx                — TRAIN: recursive training pipeline UI + run history
  components/panels/                — market data, chart, positions, signals, risk strip
  styles/globals.css                — design tokens (layered surfaces, type scale, chips, btns)
  lib/api.ts                        — typed API client (PlannerState, TrainingRun, …)

docs/PRD.md                         ← product requirements: F&O execution P2, multi-asset
                                      (CDS FX → MCX commodities → global) P3, low-latency roadmap
```

## Key Design Decisions

**REAL DATA ONLY (user mandate)** — No synthetic data anywhere. The GBM seeder (`paper_ohlcv.py`) was deleted and all synthetic bars purged from the DB (2026-06-10). Historical OHLCV comes exclusively from yfinance backfill (730d daily + 60d 5m, all 36 symbols); live ticks from `yf_live.py` (real quotes); intraday 1m from live tick aggregation. Never reintroduce synthetic/random market data.

**No eventlet** — eventlet monkey-patching turned every thread into a greenlet; one CPU-heavy task (FinBERT, yfinance parsing) stalled the whole process including Flask ("backend not loading"). Now `async_mode='threading'` + `simple-websocket` (real WS support) + `allow_unsafe_werkzeug=True`. Backend boots in ~3s.

**No silent fallbacks** — `/api/health` reports `degraded: [regime_heuristic | sentiment_disabled | ollama_offline]`; the agents page shows an amber DEGRADED badge. FinBERT fallback logs a rate-limited WARN per use. Planner degraded mode uses a *stricter* deterministic bar and is flagged on every event/decision/signal. The margin check **rejects** signals with no resolvable price (live tick → limit → SL) instead of bypassing.

**Noise reduction** — a setup must appear in ≥2 consecutive scans (debounce), its EMA-smoothed confidence must clear 0.45, and EV must enter above 1.2 (hysteresis exit at 1.0) before it is fireable. Regime multiplier changes only after the regime holds 2 consecutive scans. `data_quality()` blocks signals on <30 daily bars, bars older than 7 days, or stale/no live price (`LOW DQ` rows in the scan table).

**EventBus topics** — `ticks.{token}`, `regime.update`, `strategy.signal`, `order.approved/rejected`, `trade.opened/closed`, `pnl.update`, `scorecard.update`, `news.signal`, `orchestrator.scan_done`, `planner.candidates`, `planner.verdict`, `supervisor.state`, `supervisor.throttle`, `kill_switch.global_pause`, `settlement.*`. Glob: `ticks.*`.

**Paper vs live** — `MODE=paper|live` in `.env`. PaperBroker: 0.03% slip + ₹20/order. `use_kite_live` only when `MODE=live` AND `KITE_ACCESS_TOKEN` set.

**Market-hours discipline** — `terminal_in/market_hours.py` is the single source of truth (Mon–Fri 09:15–15:30 IST + holiday calendar). Gate check 0d rejects `market_closed` (paper AND live); engine suppresses signals off-hours; orchestrator scans are display-only off-hours. Never reintroduce simulated clocks.

**Settlement mechanics** — product-aware like a real broker: MIS (S1, time_exit, explicit) squares off at EOD (`mis_square_off`); CNC (default) carries overnight and exits ONLY when ticks cross stop-loss/target (`paper_broker._check_exit`). EOD snapshot marks carried positions to market. Signals: S2–S9 once per (strategy, token) per session; S1 30-min cooldown.

**Packaging** — `cd terminal_ui && BUILD_STATIC=1 npx next build` → Flask serves `terminal_ui/out` (SPA fallback; `/api`+`/socket.io` guarded). Whole app = one process on :5000. `background.ps1 -Start|-Install` for headless/auto-start. Dev hot-reload on :3000 unchanged.

**Design system** — `terminal_ui/lib/theme.ts` + `styles/globals.css` are the single palette source (cool dark surfaces, electric-blue accent ramp #0094FB/#00B9FC/#006FF9/#004AF8/#0025F6; gold #FFB02E = warn ONLY). Fonts: Geist Mono (data) / Geist (UI) / Georgia (display). Logo: `terminal_ui/app/icon.svg` (favicon + TopBar + PDF reports). Never add per-page palette constants.

**Daily reports** — `terminal_in/reporting/daily_report.py`: pre-open brief 08:55 IST (fresh scan at 08:50) + EOD 15:45 → branded PDF (reportlab; Rs not ₹ — Helvetica glyph) → SMTP email (`SMTP_*`, `REPORT_EMAIL_TO` in .env). On-demand: `POST /api/training/report/run`.

**OHLCV data** — `yf_fetcher.backfill()` is gap-aware: checks `db.get_ohlcv_last_dates()` and fetches only missing days; 24h refresh thread. `YF_MAP`: NIFTY 50→^NSEI, BANKNIFTY→^NSEBANK, VIX→^INDIAVIX, **TATAMOTORS→TMPV.NS** (2025 demerger delisted TATAMOTORS.NS on Yahoo), equities→SYMBOL.NS.

**DB API conventions** — `get_ohlcv_1d/1m` return pandas DataFrames with DatetimeIndex. `insert_trade(dict)` accepts `instrument_id` or `instrument_token`. `agent_decisions` table stores planner verdicts + hindsight (see decision_memory.py).

**pandas 2.x timestamps** — convert via `(series - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1ms')`, never `.astype('int64')`.

**HMM classifier** — 6 states; heuristic fallback until `hmm_model.pkl` exists (degraded mode, reported in /api/health). 3-day hysteresis. `classifier.mode` → 'hmm'|'heuristic'.

**DSA scoring** — `0.40 × regime_fit + 0.30 × Bayesian_WR + 0.30 × rolling_Sharpe`; monthly rebalance, ±15% gradient cap, 5% floor; WARNs when scoring on uninformed priors.

**M2 gate order** — kill_switch → symbol block → event_mask → VIX hard stop → drawdown → daily loss cap → daily trade count → confidence (learner-adaptive) → max positions → duplicate → signal dedup → margin (live-tick priced, rejects unpriceable) → sector → correlation → VIX reduce.

**TRL 1.x / transformers 5.x gotchas** — `SFTTrainer(processing_class=tokenizer)` (not `tokenizer=`); SFTConfig holds `dataset_text_field`/`max_length`/`packing`; `dtype=` not `torch_dtype=`; TRL import crashes on Windows cp1252 — train_lora.py re-execs with `-X utf8`.

**Ollama** — `OLLAMA_HOST` (default localhost:11434), `OLLAMA_MODEL` (default qwen2.5:3b; `financial-analyst` = qwen + system prompt from `Modelfile`). Used by TradePlanner (trade loop) and financial_agent (chat). Planner: `PLANNER_ENABLED=true|false`.

## Dependencies

Install: `pip install -r requirements.txt` (inside `.venv`).

**hmmlearn** — needs MS C++ Build Tools on Windows; heuristic mode works without it.
**FinBERT (torch + transformers)** — torch 2.11.0+cpu + transformers 5.6.2, confirmed working.
**Training stack** — trl 1.3.0, peft 0.19.1, datasets 4.8.5, accelerate 1.13.0 (see TRL gotchas above).
**yfinance 1.3.0** — backfill + live quotes, confirmed working.
**flask-socketio + simple-websocket** — threading mode WebSockets. Do NOT reinstall eventlet.

## Environment

Python 3.14 on Windows 11. Interpreter: `.venv/Scripts/python.exe`.

`.env`: `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN` (daily), `NEWSAPI_KEY`, `JWT_SECRET`, `MODE` (paper/live), `INITIAL_CAPITAL=1000000`, `MAX_DD_PCT=0.20`, `DAILY_LOSS_CAP_PCT=0.04`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `PLANNER_ENABLED`.

## What's Built / What's Next

**Complete:**
- Modules: MARKET, EQUITIES (cash cockpit), F&O Phase 1 (view+signals), AGENTS (full agentic layer: planner/supervisor/memory/filters), TRAIN (recursive training pipeline)
- 72-symbol universe with full sector coverage; real-data-only ingest; degraded-mode surfacing; 113 tests passing
- Low-latency Tier 1: vectorized indicators (72-symbol pass ≈ 67 ms), LOW_LATENCY priority flag, PYTHON_JIT opt-in (see PRD §5)

**Remaining (see docs/PRD.md for full detail):**
- P2: F&O execution (contract chain, lot-based fills, SPAN margin) — separate pipeline, NOT a bolt-on to the equities path
- P2: Backtest engine (`terminal_in/backtest/` empty) — replay through the full agentic stack, walk-forward
- P2: Training eval set + deploy automation (merge → GGUF via llama.cpp → ollama create)
- P2 latency: Kite WebSocket ticks in live mode, event-driven scans, async planner fast-lane
- P3: Multi-asset (NSE CDS FX → MCX commodities → global read-only → IBKR), options strategy engine
- HMM training once 500+ days of real data accumulate

**Hard invariants (PR-blocking):**
- No synthetic/random market data in ohlcv_* tables or the tick path — ever
- Any fallback must log WARN + appear in /api/health + badge in UI (no silent degradation)
- The planner can veto/shrink signals but can never bypass the risk gate
