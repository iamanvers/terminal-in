# TERMINAL//IN — Product Requirements Document

**Version:** 1.0 · **Date:** 2026-06-10 · **Owner:** Anmol Verma · **Status:** Living document

---

## 1. Product vision

A single-user, laptop-local, **agentic trading terminal** for Indian markets that:

1. **Predicts and plans trades like a desk, not a scanner** — deterministic strategy lenses generate candidates; an LLM judge with persistent decision memory picks the ones worth making; closed-loop control systems suppress what stops working.
2. **Never acts on noise** — real market data only, multi-scan signal persistence, data-quality gates, and zero silent fallbacks anywhere in the signal path.
3. **Improves itself recursively** — every trade outcome and every hindsight-judged decision becomes training signal for the next model iteration.
4. Runs at **zero cloud cost** (local LLM, local DB, free data) with the only paid dependency being the broker API in live mode.

**Non-goals:** multi-user/SaaS, HFT/market-making, unattended live trading without daily human review, US equities.

---

## 2. Users & constraints

| Item | Value |
|---|---|
| User | Single operator (owner), trading own capital |
| Capital | ₹10,00,000 paper → live after 60 paper days |
| Risk profile | Tier-3 aggressive: ≤20% max drawdown, ≤4% daily loss |
| Platform | Windows 11 laptop, CPU-only (no GPU), 16 GB RAM |
| Broker | Zerodha Kite Connect (₹2,000/mo, live mode only) |
| Markets (current) | NSE cash equities + index complex |
| Market hours | 09:15–15:30 IST, T+1 settlement |

---

## 3. Current state (shipped)

### 3.1 Module map

| Module | Route | Status |
|---|---|---|
| Market intelligence | `/` | ✅ Shipped |
| Equities cockpit (cash) | `/trade` | ✅ Shipped |
| F&O (derivatives) | `/fno` | ◐ Phase 1 (view + signals); execution = P2 |
| Agent orchestration | `/agents` | ✅ Shipped incl. LLM planner |
| Recursive training | `/train` | ✅ Shipped (deploy step manual) |

### 3.2 The agentic decision pipeline (shipped)

```
6 rule lenses (120s, 72 symbols) → noise filters → LLM Trade Planner → M2 risk gate → broker
   feedback: TradingSupervisor (fast) · StrategyLearner (medium) · recursive training (slow)
   audit: DecisionMemory + hindsight re-pricing of every verdict
```

Key properties (acceptance criteria, all verified):
- A signal **cannot** fire on its first scan appearance (persistence ≥ 2), below EV 1.2 (with exit hysteresis at 1.0), on <30 daily bars, on stale data, or without a resolvable price at the margin check.
- The planner makes **exactly one** LLM call per scan (45–60s budget, latest-batch-wins) and can only veto or shrink — never bypass risk.
- Ollama offline ⇒ **stricter** deterministic bar, `planner_mode=degraded` flagged on every event, decision row, and UI badge.
- Every candidate's verdict is persisted; rejections are re-priced after 4–72h (`would_win`/`would_lose`/`flat`) and the aggregate record feeds the next planner prompt.
- 3 consecutive losses attributed to a lens ⇒ 2h suppression; 5 ⇒ global throttle; 8 ⇒ kill switch. Daily-loss proximity (60% of cap) also throttles.

### 3.3 Data

- 72 NSE instruments (Nifty-100 large/mid caps + index complex), symbol-keyed sector map covering the full universe.
- Real OHLCV only: yfinance gap-aware backfill (730d daily, 60d 5m) + live quotes; synthetic data is **banned** (GBM seeder deleted 2026-06-10).
- FinBERT news sentiment; `/api/health` reports degraded subsystems (regime heuristic, sentiment off, Ollama offline).

### 3.4 Recursive training (Module 4, shipped)

Pipeline per run: dataset rebuild (static corpora + own closed trades + hindsight-judged decisions) → LoRA fine-tune TinyLlama-1.1B in subprocess → real loss metrics from `trainer_state.json` → `training_runs` history. Smoke (200 steps) and full (3 epochs) modes from `/train`.
**Open:** deploy automation (merge → GGUF via llama.cpp → `ollama create`) and a held-out eval set (see P2).

---

## 4. Roadmap

### P2 — F&O execution (next major build)

**Why separate from equities:** derivatives differ in every dimension that matters — lot-based sizing, expiry lifecycle, SPAN margining, non-linear payoff, and the underlyings (indices) are not cash-tradeable at all. Bolting options onto the cash pipeline would corrupt risk checks; F&O gets its own instrument model, broker path, and gate checks.

| Feature | Requirement |
|---|---|
| Contract model | `fno_instruments` table: underlying, expiry, strike, opt_type, lot_size, from Kite instruments dump (live) / NSE bhavcopy (paper) |
| Chain UI | NIFTY/BANKNIFTY weekly + monthly chains with OI, IV, volume per strike on `/fno` |
| Paper execution | Lot-based orders; expiry-aware positions; auto square-off at expiry; option premium P&L |
| Margin | SPAN-approximation for short options/futures replacing the 30% notional rule (per-segment margin model in the gate) |
| Strategies | S1 ORB and S8 VIX migrate to actual derivative expressions (buy ATM option / futures) instead of NIFTYBEES proxy |
| Risk additions | Per-expiry concentration, max short-gamma exposure, event-day (expiry/budget/RBI) position limits |
| Greeks (P3 bridge) | Black-Scholes delta/theta/vega per position, portfolio-level greek caps |

### P2 — Backtest engine

Replay 2y of real OHLCV through the **full agentic stack** (lenses → filters → deterministic-planner mode → gate) with walk-forward splits; Sharpe/Calmar/max-DD per strategy per regime; results feed DSA priors and the strategy gene pool. Lives in `terminal_in/backtest/`, surfaced on `/train`.

### P2 — Training eval + deploy automation

- Held-out eval set (~200 prompts: sentiment, NSE strategy QA, planner-verdict format checks); score each adapter before/after; promote only on improvement.
- One-click deploy: merge adapter → GGUF (vendored llama.cpp) → `ollama create financial-analyst-vN` → planner hot-switches model → previous model kept for rollback.
- Scheduled cadence: weekly auto-run once ≥100 new judged decisions accumulate.

### P3 — Multi-asset expansion (FX + commodities)

Phased by data availability and broker support; each asset class is a **segment plugin** following the F&O pattern (own instrument model, margin rules, market hours, gate checks):

| Phase | Segment | Venue | Instruments | Data | Broker | Notes |
|---|---|---|---|---|---|---|
| P3.1 | Currency derivatives | NSE CDS | USDINR, EURINR futures/options | yfinance (USDINR=X) + Kite | Kite (same account) | Market hours 09:00–17:00; tiny lot margin; hedges the equity book |
| P3.2 | Commodities | MCX | Gold, silver, crude oil, natural gas futures | yfinance proxies (GC=F, CL=F) + MCX bhavcopy | Kite Commodity (separate enablement) | Evening session 17:00–23:30 extends the trading day; needs session-aware settlement |
| P3.3 | Global (read-only first) | CME/COMEX/FX | ES, NQ, 6E, GC | yfinance | none (analysis only) | Drives the GLOBAL tab from display-only to signal inputs (overnight gap prediction for NSE open) |
| P3.4 | Global execution | IBKR | US ETFs/futures | IBKR API | Interactive Brokers | Only if LRS/ODI compliance is resolved; out of scope until then |

Cross-cutting requirements for multi-asset: per-segment market calendars and settlement clocks; multi-currency P&L (INR base); per-segment capital allocation envelope on top of DSA; regime classifier per asset class (equity HMM does not transfer to commodities).

### P3 — Options strategy engine

Multi-leg positions (spreads, straddles, iron condors) as first-class objects: combined margin, net greeks, payoff curves in UI, leg-level fills, early-exit rules.

---

## 5. Low-latency roadmap

**Reality check (design position):** TERMINAL//IN is a positional/swing system on a 60–120s decision cadence, executing through a broker REST API. The latency budget is dominated by: data-source polling (1–5 s, yfinance), broker round-trip (~100–300 ms, Kite REST), and exchange-side matching. Sub-microsecond techniques (kernel bypass, FPGA) require colocation and direct market access that retail Kite accounts cannot reach — implementing them on a laptop would be cargo-culting. The plan below orders work by actual end-to-end impact.

### Tier 1 — shipped (this build)

| Item | Status |
|---|---|
| Vectorized indicator math (numpy/pandas-C EMA/RSI/ATR replacing Python loops; 72-symbol pass ≈ 67 ms) | ✅ |
| `LOW_LATENCY=1` → HIGH process priority (Windows `SetPriorityClass` / Unix nice) | ✅ |
| `PYTHON_JIT=1` opt-in — CPython 3.14 experimental copy-and-patch JIT (`.\start.ps1 -LowLatency`) | ✅ |
| In-process EventBus (function-call dispatch, no serialization on the hot path) | ✅ (by design) |
| No eventlet — real OS threads, CPU work cannot stall the API | ✅ |
| SQLite WAL + bus hot-cache (`get_cached`) so reads never block the tick path | ✅ |

### Tier 2 — biggest real-latency wins (live-mode path, P2)

1. **Kite WebSocket ticks** (`KiteStreamer` exists, unused in paper mode): replaces yfinance polling — seconds → **sub-100 ms** market data. The single largest improvement available.
2. **Event-driven scan triggers**: let large tick moves (>0.5% in 60s) trigger an immediate orchestrator scan instead of waiting for the 120s timer.
3. **Order path**: pre-validated order templates per candidate (gate pre-checks at signal time), so approval → Kite POST has no recomputation; persistent HTTP session with connection pooling to Kite.
4. **Planner off the critical path**: approved-signal fast lane — gate executes immediately; LLM verdict arrives asynchronously and can only *cancel within a grace window*, never delay entry (config flag; keeps the judge without paying its 10–20s on entry timing).

### Tier 3 — engineering hardening (P3, measure first)

1. **Numba `@njit`** on the lens-scoring loop and signal filters if profiling shows them hot after Tier 2 (current scan cost is I/O-bound on SQLite reads, not compute).
2. **Shared-memory ring buffer** for ticks (multiprocessing.shared_memory) if the UI fan-out ever needs to move out-of-process; msgpack instead of JSON on the SocketIO wire.
3. **DB read elimination**: per-symbol OHLCV LRU cache invalidated by backfill events — removes ~72 SQLite reads per scan.
4. **VPS near exchange** (AWS Mumbai, ~1–5 ms to NSE endpoints vs ~30–60 ms residential): run the backend headless there in live mode, UI connects remotely. This — not kernel bypass — is the realistic "get closer to the exchange" move for a Kite-based system.

### Explicitly rejected (with reasons, revisit only if DMA access changes)

- **Kernel bypass (DPDK/OpenOnload), userspace TCP** — requires specialized NICs + colocation + direct exchange connectivity; Kite REST/WS terminates at Zerodha's servers regardless.
- **FPGA/ASIC feed handlers** — no raw multicast feed access at retail.
- **CPU isolation/realtime kernels** — Windows laptop; marginal next to a 100 ms broker RTT.

---

## 6. Quality & operations

- **Tests:** 113 passing (gate, broker, persistence, filters, planner, supervisor); every new module ships with unit tests; planner/LLM tests run fully mocked.
- **No-silent-degradation invariant:** any subsystem fallback must (a) log at WARN with rate limiting, (b) appear in `/api/health`, (c) badge in the UI. PR-blocking rule.
- **Real-data invariant:** no synthetic/random market data may enter `ohlcv_*` tables or the tick path. PR-blocking rule.
- **Commit convention:** `Change_N: summary` on `main`.
- **Docs:** README (operator-facing), CLAUDE.md (agent/dev-facing), this PRD (product). Update all three at every phase boundary; session context persists to Claude memory.

## 7. Success metrics

| Metric | Target | Where measured |
|---|---|---|
| Paper-trading profitability | Positive expectancy over 60 paper days; Sharpe > 1.0 | `/trade` performance tab |
| Planner value-add | Approved-trade win rate > deterministic-only baseline; missed-winner rate < 30% of rejections | DECISION LOG hindsight |
| Control-loop efficacy | Max consecutive-loss streak ≤ 8 (hard stop ceiling); no >4% daily loss breaches | supervisor state + settlement history |
| Model improvement | Eval-set score improves run-over-run; final loss decreasing at constant data scale | `/train` run history |
| System reliability | Backend boot < 5 s; zero silent degraded states; UI never false-reports backend down | /api/health + boot logs |
