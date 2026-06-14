# TERMINAL//IN — Claude Code Instructions

Bloomberg-style **agentic** algorithmic trading terminal for Indian markets (NSE/BSE). Single-user, laptop-local, zero cloud cost except Kite Connect (₹2000/mo).

## Commands

```bash
# Run the app (paper mode)
.venv/Scripts/python.exe -m terminal_in.main

# Run via launcher (also creates venv + installs deps)
.\start.ps1

# Run tests (160 passing)
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
#   LOCAL ceiling: max ~1.5B fp32 (Qwen2.5-1.5B fits 16GB); 3B+ NOT viable
#   (bf16 emulated on Zen3 → ~90-day ETA; fp32 12.4GB → swaps). iGPU shares RAM.
#   3B+ trains on a cloud GPU (kept in the LOCAL-only colab/ dir, gitignored).

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

terminal_ui/                        ← Next.js 14 frontend (modules: MARKET·EQUITIES·F&O·AGENTS·TRAIN·BACKTEST)
  app/page.tsx                      — MARKET: boot gate w/ retry+backoff, 3-col grid
  app/trade/page.tsx                — EQUITIES: cash cockpit (order ticket = EQ instruments only)
  app/fno/page.tsx                  — F&O: COCKPIT (index complex + lot sizes, index signals,
                                      VIX context) | OPTION CHAIN (theoretical premiums + greeks,
                                      expiry/strike, lot-based paper order). SPAN gate = Stage 4
  app/agents/page.tsx               — AGENTS: matrix, OrchestratorPanel, PlannerPanel,
                                      SupervisorPanel, DECISION LOG tab (hindsight), AI ANALYST
  app/train/page.tsx                — TRAIN: recursive training pipeline UI + run history
  app/backtest/page.tsx             — BACKTEST: horizon picker, equity curve, per-lens/regime
                                      attribution, walk-forward-by-year, closed trades (P2)
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

**Packaging** — `cd terminal_ui && BUILD_STATIC=1 npx next build` → Flask serves `terminal_ui/out` (SPA fallback; `/api`+`/socket.io` guarded). DEV = one process on :5000 (browser). `background.ps1 -Start|-Install` for headless/auto-start. Dev hot-reload on :3000 unchanged.

**Shipped exe = self-serving desktop app** (NOT browser+localhost — owner mandate 2026-06-14). `packaging/run_app.py` frozen path: binds the Flask/SocketIO backend to **127.0.0.1 on a FREE port** (`TIN_HOST`/`TIN_PORT`, read by `main.py`; dev default `0.0.0.0:5000` unchanged), then hosts the UI in a **native OS window via pywebview** (WebView2 on Windows) titled `TERMINAL//IN` with `terminalin.ico`. The port is an invisible loopback detail, never a URL the user opens. Browser fallback if no native runtime. `hw.apply()` runs at boot in the SAME process, so the packaged app engages all logical cores like dev. Build: `.venv/Scripts/pyinstaller packaging/terminal_in.spec --noconfirm` (onedir; `console=False`; `icon`+`version_info.txt` → file props read `TERMINAL//IN`; pywebview/pythonnet bundled; datas live in `_internal/` = `sys._MEIPASS`, NOT next to the exe). Icon regen: `python packaging/make_icon.py` (Pillow → multi-size .ico from `app/icon.svg`).

**Design system** — `terminal_ui/lib/theme.ts` + `styles/globals.css` are the single palette source (cool dark surfaces, electric-blue accent ramp #0094FB/#00B9FC/#006FF9/#004AF8/#0025F6; gold #FFB02E = warn ONLY — never tabs/buttons/affordances; active states + primary actions = accent blue). Fonts: Geist Mono (data) / Geist (UI) / Georgia (display). Logo: `terminal_ui/app/icon.svg` (favicon + TopBar + PDF reports). Never add per-page palette constants. Background: `MeshBackground.tsx` = embossed dot-matrix on a fixed z-0 canvas — dots NEVER move, the cursor is a soft lamp; resting field pre-rendered once and blitted. Page roots must stay `background: transparent` (an opaque page root hides the mesh — the original "mesh not working" bug); chrome strips (TopBar/ticker/risk strip/module headers) are translucent rgba + backdrop blur; panels stay solid for legibility.

**Settings** — `terminal_in/app_settings.py` SCHEMA + `app_settings` table override `.env` (settings > env > default); gear icon (TopBar) opens the panel; hot vs RESTART flagged; secrets masked. Boot: `apply_overrides(db)` before Config rebuild.

**Portfolio statement** — `portfolio_ledger.build_statement(db, broker)` is the single assembly → data/portfolio.md + `/api/portfolio/holdings` + HoldingsPanel (EQUITIES/F&O, composition bar + product chips). Never duplicate this math.

**Analyst (AI ANALYST tab)** — app-aware system prompt + LIVE CONTEXT injection (bus caches); NDJSON streaming via `/api/agents/query/stream`; keep_alive 30m + boot warmup. Generation is DDR-bandwidth-bound (~10.7 tok/s for 3B Q4; 16 threads or Vulkan iGPU do NOT help — measured, see PRD 5b.4); levers = model size, prefix cache, streaming.

**Model deploy** — `agents/training/deploy.py`: adapter → merge → GGUF → Q4_K_M → `ollama create financial-analyst-vN`; `POST /api/training/deploy`. llama.cpp vendored under `vendor/` (gitignored). Adapter dirs nest: `runs/<id>/adapter/adapter/`.

**Contract specs** — `data_ingest/contract_specs.py` = sourced NSE lot sizes/expiries + margin BAND (estimate, labeled); served at `/api/market/contract-specs`. Never hardcode lots/margins in the UI.

**Daily reports** — `terminal_in/reporting/daily_report.py`: pre-open brief 08:55 IST (fresh scan at 08:50) + EOD 15:45 → branded PDF (reportlab; Rs not ₹ — Helvetica glyph) → SMTP email (`SMTP_*`, `REPORT_EMAIL_TO` in .env). On-demand: `POST /api/training/report/run`.

**OHLCV data** — `yf_fetcher.backfill()` is gap-aware FORWARD (checks `db.get_ohlcv_last_dates()`, fetches only missing recent days); `backfill_history()` is gap-aware BACKWARD (checks `db.get_ohlcv_first_dates()`, fetches the missing [target_start, earliest) window — default 10y, idempotent once at depth). Both run in the 24h refresh thread; deep history feeds HMM training + walk-forward backtests. All 72 symbols reach back to 2016 (~2,470 daily bars). `YF_MAP`: NIFTY 50→^NSEI, BANKNIFTY→^NSEBANK, VIX→^INDIAVIX, **TATAMOTORS→TMPV.NS** (2025 demerger delisted TATAMOTORS.NS on Yahoo), equities→SYMBOL.NS.

**Backtest (P2)** — `terminal_in/backtest/engine.py` `run_backtest(db, days, symbols)` is v2: replays real `ohlcv_1d` through a deterministic MIRROR of the live pipeline (regime heuristic-parity → lenses S2/S4/S5/MOM with live confidences+regime mult → `EV = avg_conf×R:R×vol×convergence` → persistence ≥2 → planner degraded bar EV≥1.2/conf≥0.45 → gate-lite max-pos/sector → fill at **t+1 open**, SL/target ±1.5/2.5 ATR, stop checked before target). **No lookahead, no synthetic data** (refuses <250 bars/symbol). Long-only cash segment; NEWS lens excluded (no historical headlines). Output includes `equity_curve` (≤300 pts) + `recent_trades` (≤60) + per-lens/per-regime/walk-forward-by-year. Served `/api/backtest/run` (POST, background; GET=status) + `/api/backtest/latest`; BACKTEST UI module. The lens/EV math is hand-kept in formula-parity with the live orchestrator — if you change orchestrator scoring, mirror it here. Keystone eval gate for future strategy/edge-model/M6 changes. Tests: `tests/test_backtest.py`.

**F&O execution (P2, Stages 1–5)** — derivatives get their OWN path (the cash path would corrupt risk checks). `data_ingest/fno_instruments.py` = contract model (synthetic deterministic tokens ≥9e11, expiry calendar, chain builder); `execution/options_pricing.py` = pure-stdlib Black-Scholes (price + greeks). **DATA HONESTY:** option premiums/greeks are Black-Scholes **theoretical** from REAL spot + India VIX (the NIFTY 30d IV) as the IV proxy, labeled `theoretical=True`; **OI/real-IV/volume are live-only and null in paper — never fabricated**, nothing written to `ohlcv_*`. `execution/fno_paper_broker.py` = lot-based paper execution (qty=lots×lot_size, entry_price=premium → (exit−entry)×qty IS premium P&L), marks positions by re-pricing on underlying ticks, expiry square-off at intrinsic, **shares the cash account** via `PaperBroker.reserve_capital/release_capital/apply_external_pnl`. `risk/span_margin.py` = scenario-based SPAN approximation (worst loss over price ±3.5σ/2-day VIX-implied × vol grid + 2% exposure; long option = premium paid). `execution/fno_signal_router.py` = S1/S8 index signals → ATM CE (BUY) / PE (SELL) on the F&O broker (market-hours + kill-switch checked). API `/api/fno/{underlyings,expiries,chain,order,positions,close}`. Only paper mode; live Kite F&O is a later stage. Tests: `tests/test_fno*.py`.

**DB API conventions** — `get_ohlcv_1d/1m` return pandas DataFrames with DatetimeIndex. `insert_trade(dict)` accepts `instrument_id` or `instrument_token`. `agent_decisions` table stores planner verdicts + hindsight (see decision_memory.py).

**pandas 2.x timestamps** — convert via `(series - pd.Timestamp('1970-01-01', tz='UTC')) // pd.Timedelta('1ms')`, never `.astype('int64')`.

**HMM classifier** — 6 states; heuristic fallback until `hmm_model.pkl` exists (degraded mode, reported in /api/health). 3-day hysteresis. `classifier.mode` → 'hmm'|'heuristic'. Trainer (`regime/train.py`) uses **hmmlearn when importable, else `regime/nphmm.py`** — a pure-NumPy Gaussian HMM (log-space Baum-Welch + Viterbi, full covars, k-means init, sticky-transition prior) written because hmmlearn ships no Python 3.14 wheel. Same interface (fit/predict/predict_proba/score/means_), picklable, so the classifier loads either backend unchanged. **Self-bootstrapping**: `main._maybe_train_hmm()` trains in the backfill thread on boot when ≥500 NIFTY bars exist and no model is on disk, then hot-swaps into the live `classifier` singleton (no restart needed). `hmm_model.pkl` is gitignored (per-deployment artifact, like the DB). Trained model: learned transmat diagonal ~0.93–0.98 (correctly sticky regimes).

**DSA scoring** — `0.40 × regime_fit + 0.30 × Bayesian_WR + 0.30 × rolling_Sharpe`; monthly rebalance, ±15% gradient cap, 5% floor; WARNs when scoring on uninformed priors.

**M2 gate order** — kill_switch → symbol block → event_mask → VIX hard stop → drawdown → daily loss cap → daily trade count → confidence (learner-adaptive) → max positions → duplicate → signal dedup → margin (live-tick priced, rejects unpriceable) → sector → correlation → VIX reduce.

**TRL 1.x / transformers 5.x gotchas** — `SFTTrainer(processing_class=tokenizer)` (not `tokenizer=`); SFTConfig holds `dataset_text_field`/`max_length`/`packing`; `dtype=` not `torch_dtype=`; TRL import crashes on Windows cp1252 — train_lora.py re-execs with `-X utf8`.

**Ollama** — `OLLAMA_HOST` (default localhost:11434), `OLLAMA_MODEL` (default qwen2.5:3b; `financial-analyst` = qwen + system prompt from `Modelfile`). Used by TradePlanner (trade loop) and financial_agent (chat). Planner: `PLANNER_ENABLED=true|false`.

## Dependencies

Install: `pip install -r requirements.txt` (inside `.venv`).

**hmmlearn** — no Python 3.14 wheel; build fails without MSVC. `regime/nphmm.py` (pure NumPy + scikit-learn k-means init) is the in-tree replacement and the active backend on 3.14 — no MSVC needed.
**FinBERT (torch + transformers)** — torch 2.11.0+cpu + transformers 5.6.2, confirmed working.
**Training stack** — trl 1.3.0, peft 0.19.1, datasets 4.8.5, accelerate 1.13.0 (see TRL gotchas above).
**yfinance 1.3.0** — backfill + live quotes, confirmed working.
**flask-socketio + simple-websocket** — threading mode WebSockets. Do NOT reinstall eventlet.

## Environment

Python 3.14 on Windows 11. Interpreter: `.venv/Scripts/python.exe`.

`.env`: `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN` (daily), `NEWSAPI_KEY`, `JWT_SECRET`, `MODE` (paper/live), `INITIAL_CAPITAL=1000000`, `MAX_DD_PCT=0.20`, `DAILY_LOSS_CAP_PCT=0.04`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `PLANNER_ENABLED`.

## What's Built / What's Next

**Complete:**
- Modules: MARKET, EQUITIES (cash cockpit), F&O (view+signals + chain + lot-based paper execution), AGENTS (full agentic layer: planner/supervisor/memory/filters), TRAIN (recursive training pipeline), BACKTEST (walk-forward eval over 10y real OHLCV)
- F&O execution Stages 1–5 shipped: contract model + Black-Scholes theoretical chain (`data_ingest/fno_instruments.py`, `execution/options_pricing.py`, `/api/fno/*`), OPTION CHAIN UI + order ticket + positions, lot-based paper execution (`execution/fno_paper_broker.py` — premium P&L, expiry square-off, shared account), scenario-based **SPAN-approx margin** (`risk/span_margin.py`), and S1/S8 index→ATM-option routing (`execution/fno_signal_router.py`). Remaining: per-expiry/short-gamma risk caps, live-mode Kite chain ingestion.
- 72-symbol universe with full sector coverage; real-data-only ingest; degraded-mode surfacing; 160 tests passing
- Low-latency Tier 1: vectorized indicators (72-symbol pass ≈ 67 ms), LOW_LATENCY priority flag, PYTHON_JIT opt-in (see PRD §5)

**Remaining (see docs/PRD.md for full detail):**
- P2: F&O execution (contract chain, lot-based fills, SPAN margin) — separate pipeline, NOT a bolt-on to the equities path
- P2: Backtest engine — DONE (v2): `terminal_in/backtest/engine.py` replays real daily OHLCV through the deterministic core (regime→lenses→EV→persistence→planner degraded bar→gate-lite→next-open fills), no lookahead, long-only cash segment, walk-forward by year + per-lens/per-regime attribution. Served at `/api/backtest/run|latest` (background run) + BACKTEST module (`app/backtest/page.tsx`: horizon picker, equity curve, attribution tables, closed trades). NEXT: full agentic-stack replay (live planner LLM in the loop), parameter walk-forward for the LightGBM edge model
- P2: Training eval set + deploy automation (merge → GGUF via llama.cpp → ollama create)
- P2 latency: Kite WebSocket ticks in live mode, event-driven scans, async planner fast-lane
- P3: Multi-asset (NSE CDS FX → MCX commodities → global read-only → IBKR), options strategy engine
- P3/P4: **Module 6 — World-Model Decisioning Core** (forward-looking judge). Design: `docs/WORLD_MODEL.md`. Replaces the backward-looking core (lenses recall + LLM guesses from hindsight) with a **dual-process** judge: System 1 = JEPA market-state latent + world-model imagination (model-based EV); System 2 = our own pre-trained-then-locally-fine-tuned reasoning SLM. **Multimodal fusion** over five data planes — technical · relational graph ("how it ties back") · fundamentals · news/sentiment · macro — into one latent. Reasoning is **trained by us only**: teacher-distilled traces (Claude) + outcome grounding (hindsight P&L) + world-model consistency verifier. Directional competence (trailing HR+/HR− per lens×dir×regime) from the hindsight loop. The 10y backfill is the training substrate. Staged A→E + a parallel multimodal/reasoning track (Stage-1 textual grounding ships cheap, Stage-2 latent→SLM coupling is research-grade/last); each eval-gated on beating the current judge in walk-forward backtest. "99th percentile" = breadth + forward simulation + coherence + abstention + risk discipline, NOT predictive-accuracy magic (literature caps ~54% direction). Phase C (competence) + Stage-1 fundamentals/macro/news context are buildable now with no new ML — do first.

**Hard invariants (PR-blocking):**
- No synthetic/random market data in ohlcv_* tables or the tick path — ever
- **World-model imagination / latent rollouts are NEVER persisted as market data, never fed to lenses/strategies as bars, never shown as quotes** — imagination is a fenced planning tool inside the judge (M6); the REAL-DATA-ONLY mandate covers it
- Any fallback must log WARN + appear in /api/health + badge in UI (no silent degradation)
- The planner/judge can veto/shrink signals but can never bypass the risk gate
