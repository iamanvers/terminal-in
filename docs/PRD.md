# TERMINAL//IN — Product Requirements Document

**Version:** 1.1 · **Date:** 2026-06-11 · **Owner:** Anmol Verma · **Status:** Living document

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
| Education | `/learn` | ✅ Shipped |
| Market-hours + settlement realism | core | ✅ Shipped (MIS/CNC products, SL/target-driven exits, session-gated signals) |
| Packaging (single process) | — | ✅ Shipped (static UI served by Flask on :5000; headless via background.ps1) |
| Daily PDF reports + email | — | ✅ Shipped (pre-open 08:55 / EOD 15:45 IST, branded) |

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

### P2 — Portfolio holdings surface

A persistent ledger now exists (`data/portfolio.md`, regenerated on every fill/close/EOD; backed by the `trades` table). Next build: a **HOLDINGS panel** on the EQUITIES page (cash positions with live marks, unrealized P&L, product type, day change) and a positions section on the F&O page once derivative positions exist. API: extend `/api/portfolio/positions` with marks + product; reuse the ledger's assembly logic.

### P2 — Design maturation (packaged-product bar)

The packaged app (5b) raises the design bar from "internal terminal" to "product someone installs". Scope:
- **Fluidity pass**: route-level transitions, skeleton loaders on every panel (no layout jumps), 60fps hover/press interactions, reduced-motion compliance. Current liquid-tile foundation stays; evaluate spring-physics motion (CSS `linear()` easing) over the current cubic-bezier.
- **Design options review**: structured comparison before the P2 build — (a) keep hand-rolled CSS system, (b) adopt headless primitives (Radix) under our tokens for menus/dialogs/tooltips, (c) full component library (rejected by default: locks the visual identity). Decision recorded here before any code.
- **Palette consistency audit (PR-blocking)**: zero hex literals outside `lib/theme.ts` + `globals.css`; CI-style grep check added to the test suite; PDF/report colors derive from the same ramp constants.

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
| **Parallel strategy evaluation** — the 8 strategies evaluate concurrently in a thread pool (signals still published sequentially: the risk gate keeps stateful daily counters) | ✅ |
| **Batched OHLCV reads** — ONE window-function query for the whole 72-symbol universe instead of 144 per-cycle connections; raw-tuple → DataFrame fast path; orchestrator scan 732→374 ms measured | ✅ |
| **Parallel symbol analysis** — orchestrator scans all 72 symbols across an 8-worker pool (SQLite/numpy/pandas release the GIL) | ✅ |
| `LOW_LATENCY=1` → HIGH process priority (Windows `SetPriorityClass` / Unix nice) | ✅ |
| `PYTHON_JIT=1` opt-in — CPython 3.14 experimental copy-and-patch JIT (`.\start.ps1 -LowLatency`) | ✅ |
| In-process EventBus (function-call dispatch, no serialization on the hot path) | ✅ (by design) |
| No eventlet — real OS threads, CPU work cannot stall the API | ✅ |
| SQLite WAL + bus hot-cache (`get_cached`) so reads never block the tick path | ✅ |

**Parallelism audit (2026-06-10):** profiling showed the engine/orchestrator hot paths were **I/O-bound on SQLite round-trips, not compute-bound** — naive thread-pooling of per-symbol DB reads gained nothing (2156 ms parallel vs 1940 ms sequential) until reads were batched into single queries. Lesson encoded here: measure before parallelizing; batching beats threading for single-file SQLite.

**Async assessment:** a full asyncio rewrite is not worth it — the component threads + parallel pools already exploit the available concurrency, Flask/SocketIO threading mode works, and end-to-end latency is dominated by data-source polling and broker RTT. Targeted async (aiohttp for parallel yfinance/news fetches) is the only piece that would pay, tracked under Tier 2.

**C/C++ for "thinking" tasks:** the heavy computation already runs in native code — numpy/pandas (C), FinBERT inference (libtorch C++), and the LLM judge itself (Ollama **is** llama.cpp). The remaining pure-Python hot spots (lens scoring, filters) are now parallel and measure in single-digit ms. A Cython extension (`_fastind`) for indicators+filters is specced for Tier 3 **after** MSVC Build Tools are installed (same blocker as hmmlearn); numba is an alternative once it supports Python 3.14. Do this only if post-Tier-2 profiling shows these paths hot — currently they are not.

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

## 5b. Distribution: standalone, transferable Windows app (P2 — owner mandate 2026-06-11)

Supersedes the earlier single-machine packaging decision: the app must now be **installable on any Windows machine, run standalone, and receive remote updates**. Single-process serving (static UI via Flask, `background.ps1`) shipped earlier remains the runtime foundation the installer wraps.

### 5b.1 Windows installer (.exe)
- **PyInstaller `--onedir`** build of the backend (never `--onefile` — torch/transformers make a 3–5 GB payload; onedir avoids per-launch temp unpacking), bundling Python 3.14 runtime + `terminal_in/` + static `terminal_ui/out`.
- **Inno Setup** wraps the onedir tree + bundled LLM (5b.3) into `TERMINAL-IN-Setup.exe`: Start-menu entry, desktop shortcut, optional logon auto-start (replaces `background.ps1 -Install`).
- **Data separation for transferability**: all mutable state (SQLite DB, reports, models, logs, settings) moves to `%LOCALAPPDATA%\TerminalIN\`; the install dir stays read-only. Backup/transfer = copy one folder.
- First-run wizard: capital, risk tier, optional Kite/SMTP keys — replaces hand-editing `.env`.

### 5b.2 Settings panel (top-right frame)
- Gear icon in the TopBar (top-right) → slide-over **SETTINGS** panel; groups: Trading (mode, capital, risk caps), Planner (enabled, model, timeout), Data (symbols refresh, news sources), Reports (SMTP, recipient, schedule), System (low-latency, JIT, log level).
- Backend: `settings` table overriding `.env` defaults; `GET/POST /api/settings` with type/range validation. Hot-applicable settings take effect immediately (planner toggle, thresholds, SMTP); restart-required ones are flagged in the UI.
- `.env` remains the bootstrap layer; the settings table wins where both define a value.

### 5b.3 Bundled base LLM (general-finance weights, no personal data)
- Ship a **finance-tuned base model fine-tuned ONLY on public corpora** (sentiment, finance-alpaca, NSE strategy QA) — explicitly excluding the owner's trades and decisions, so the installable artifact carries no personal trading data.
- Runtime: **bundled `llama-server.exe` (llama.cpp) + GGUF** — removes the Ollama install dependency entirely; the planner/analyst speak the same OpenAI-compatible API.
- The personal layer (own trades + hindsight decisions) remains a **local TRAIN-module LoRA** applied on top, per machine, never distributed.

### 5b.4 Hardware maximization (CPU + GPU as available)
- `torch.set_num_threads(physical_cores)` + `OMP_NUM_THREADS` at boot; HIGH process priority default in packaged mode.
- Device autodetect at startup: CUDA → DirectML (any Windows GPU) → CPU; applies to FinBERT inference and LoRA training (`use_cpu` only when nothing better exists); llama.cpp `--n-gpu-layers auto`.
- `/api/health` reports the active device per subsystem (no silent CPU fallback when a GPU exists).

### 5b.5 Remote updates
- Update channel: **GitHub Releases** — the app checks the latest-release tag at boot (and daily), downloads the new package in the background, applies on next restart, keeps the previous version for rollback. Signed checksums.
- Mechanism final call deferred (full installer re-run vs delta patching); the version-check endpoint + UI "update available" toast land first.

## 5c. Model deploy + Claude-augmented training (P2, partially blocked)

- **Weight adjustment after training** = the LoRA deploy pipeline: merge adapter → `convert_hf_to_gguf.py` (llama.cpp, not yet vendored) → `ollama create financial-analyst-vN` → planner hot-switch with rollback. Blocked on: a completed training run (smoke test in progress) + llama.cpp clone.
- **Claude-as-teacher dataset expansion**: grow `strategy_pairs.py` with Claude-generated QA on documented winning strategies (momentum/quality factor literature, Varsity strategy modules, public quant write-ups) and periodic web-sourced market-structure updates. Quality bar: every generated pair must cite the mechanism (why the edge exists), not just the rule. Target +500 pairs per quarter, versioned in git.

### P4 / Release 2 — Next-generation base models

The current stack (qwen2.5:3b judge, TinyLlama-1.1B trainee) was chosen for CPU-era constraints. Once the packaged app ships and hardware detection (5b.4) is live, re-evaluate against the then-best small open-source models — candidates as of writing: **Qwen3 4B/8B**, **Llama 4 small variants**, **Phi-4-mini**, **Gemma 3 4B**, **DeepSeek-R1 distills (7B/8B)** — all GGUF-served via the bundled llama.cpp, so a model swap is a file replacement + Modelfile bump, no code change.

Gate for adoption (per model, on the eval set from §P2 training): ≥10% better planner-verdict accuracy at ≤1.5× latency on reference hardware, and a clean license for redistribution inside the installer. Not before P4 — the backtest engine and F&O execution outrank model churn.

## 6. Quality & operations

- **Tests:** 119 passing (gate, broker, persistence, filters, planner, supervisor); every new module ships with unit tests; planner/LLM tests run fully mocked.
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
