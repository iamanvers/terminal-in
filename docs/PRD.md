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
| F&O (derivatives) | `/fno` | ◑ Phase 1 (view + signals) + chain + lot-based paper execution; SPAN gate + strategy migration remain |
| Agent orchestration | `/agents` | ✅ Shipped incl. LLM planner |
| Recursive training | `/train` | ✅ Shipped (deploy step manual) |
| Education | `/learn` | ✅ Shipped |
| Firm intelligence graph | `/firm` | ◯ Planned (P3) — per-stock business map: force-directed relational graph of news · suppliers · customers · peers · financials · live market value · corporate actions. See §4 P3 "Firm Intelligence Graph". |
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

### P2 — F&O execution (Stages 1–5 shipped; portfolio greek + event-day risk caps shipped 2026-06-14)

**Why separate from equities:** derivatives differ in every dimension that matters — lot-based sizing, expiry lifecycle, SPAN margining, non-linear payoff, and the underlyings (indices) are not cash-tradeable at all. Bolting options onto the cash pipeline would corrupt risk checks; F&O gets its own instrument model, broker path, and gate checks.

| Feature | Status |
|---|---|
| Contract model | ✅ `data_ingest/fno_instruments.py`: synthetic deterministic tokens, expiry calendar (weekly NIFTY / monthly per index), strike chain. Live Kite-dump ingestion deferred to live mode. |
| Chain UI | ✅ OPTION CHAIN view on `/fno`: CE/PE premiums + greeks per strike, ATM highlight, expiry chips. **OI/real-IV are live-only (null in paper, never fabricated)** — premiums are Black-Scholes theoretical from real spot + India VIX (labeled). |
| Paper execution | ✅ `execution/fno_paper_broker.py`: lot-based orders, premium P&L, theoretical mark-to-market on underlying ticks, expiry square-off at intrinsic; shares the cash account. UI order ticket + positions panel on `/fno`. |
| Margin | ✅ `risk/span_margin.py`: scenario-based **SPAN approximation** — worst-case loss over a price (±3.5σ/2-day, VIX-implied) × vol grid + exposure add-on. ATM short > OTM short; futures ~7% notional. Long option = premium. Labeled approx. |
| Strategies | ✅ `execution/fno_signal_router.py`: S1 ORB + S8 VIX index signals express as ATM options (BUY→CALL, SELL→PUT) on the F&O broker, with market-hours + kill-switch checks. |
| Risk additions | ✅ `fno_paper_broker._risk_check`: per-expiry concentration + max short-option legs (shipped earlier) PLUS equity-normalized **portfolio greek caps** (net delta notional ≤ 400%, net short-gamma loss on a 2% gap ≤ 5%, net vega ≤ 2% of equity) and **event-day limits** (full blackout on a 0-mask event; near expiry/RBI/FOMC refuse new short-gamma legs). |
| Greeks (P3 bridge) | ✅ Black-Scholes delta/theta/vega/gamma per contract (`execution/options_pricing.py`); **portfolio greek caps live** + `portfolio_greeks()` served on `/api/fno/positions` and shown on the F&O BOOK (net delta / θ / vega / Γ@2%, labeled theoretical). |

### P2 — Portfolio holdings surface

A persistent ledger now exists (`data/portfolio.md`, regenerated on every fill/close/EOD; backed by the `trades` table). Next build: a **HOLDINGS panel** on the EQUITIES page (cash positions with live marks, unrealized P&L, product type, day change) and a positions section on the F&O page once derivative positions exist. API: extend `/api/portfolio/positions` with marks + product; reuse the ledger's assembly logic.

### P2 — Design maturation (packaged-product bar)

The packaged app (5b) raises the design bar from "internal terminal" to "product someone installs". Scope:
- **Fluidity pass**: route-level transitions, skeleton loaders on every panel (no layout jumps), 60fps hover/press interactions, reduced-motion compliance. Current liquid-tile foundation stays; evaluate spring-physics motion (CSS `linear()` easing) over the current cubic-bezier.
- **Design options review**: structured comparison before the P2 build — (a) keep hand-rolled CSS system, (b) adopt headless primitives (Radix) under our tokens for menus/dialogs/tooltips, (c) full component library (rejected by default: locks the visual identity). Decision recorded here before any code.
- **Palette consistency audit (PR-blocking)** — ◐ SHIPPED as a ratchet (2026-06-14): `tests/test_palette.py` scans `app/` + `components/` for hex literals against the design-system palette (`theme.ts` + `globals.css`) and fails the build if the total count rises above the recorded baseline (833) or a new off-palette colour appears (distinct baseline 37). Full tokenisation of 800+ existing literals is a large, visually-risky migration done by ratcheting the baselines DOWN over time, not a big-bang; new code must use THEME tokens. Three stray-but-real colours (deepest surface `#080808`, regime extremes `#3FD487`/`#A13238`) were promoted to named tokens. NEXT: drive the baselines toward zero; derive PDF/report colours from the same ramp.

### P2 — Backtest engine — ◐ v1 SHIPPED (2026-06-12)

`terminal_in/backtest/engine.py`: replays real daily OHLCV (DB, ≥250 bars enforced, no lookahead — bar-t signals fill at t+1 open) through lens signals → persistence ≥2 → deterministic planner bar → gate-lite (max positions, sector floor+cap) → SL/target fills (stop-before-target, slippage+costs). Per-strategy + walk-forward-by-year stats → data/backtests/.
First run (500d, 67 symbols): 10 trades, all S4; +0.14%, Sharpe 0.11, max DD −0.61%. **Known v1 gaps:** fixed 1.625 R:R makes the EV bar admit only deep-oversold S4 (S2/S5 confidences can never clear 1.2 — use the live orchestrator EV formula next); engine-strategy replay and the LLM-planner replay (sampled) pending; surface on /train.

(original spec follows)

Replay 2y of real OHLCV through the **full agentic stack** (lenses → filters → deterministic-planner mode → gate) with walk-forward splits; Sharpe/Calmar/max-DD per strategy per regime; results feed DSA priors and the strategy gene pool. Lives in `terminal_in/backtest/`, surfaced on `/train`.

### P2 — Training eval + deploy automation — ✅ SHIPPED (2026-06-12)

Eval set live (`agents/training/evalset.py`, 42 graded items / 4 categories; results in `data/training/eval/`). **First verdict: qwen2.5:3b 83.3% vs financial-analyst-v2 9.5% — v2 NOT promoted.** The recursive pipeline (train→deploy→eval) is fully proven; the 1.1B base model was the bottleneck (cannot follow instructions). **Fix shipped 2026-06-14:** the local LoRA base is now **Qwen/Qwen2.5-1.5B-Instruct** (`LORA_BASE_MODEL` default; 1.5B fp32 fits the 16 GB laptop with gradient checkpointing; the Alpaca-text dataset and q/k/v/o_proj targets need no change). 3B+ stays a cloud-GPU run (colab/). Deploy reads the base from the adapter config, so any base merges→GGUF unchanged. Deploy automation shipped earlier (5c).

**Dual-control execution (owner mandate 2026-06-12):** every trade now requires BOTH a deterministic strategy signal AND LLM-judge concurrence — engine signals route through the planner (`PLANNER_GATES_ENGINE`, settings toggle, default on; degraded mode = stricter deterministic bar, never silent). Planner batches merge rather than drop. Sector gate: small-book floor + cap are hot settings (`SECTOR_SMALL_BOOK_FLOOR`, `SECTOR_CAP_PCT`) after the 2026-06-12 deadlock fix.

### P2 — (superseded) original eval/deploy notes

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

### P3 — Firm Intelligence Graph (per-stock business map)

**Owner idea 2026-06-14.** A new module (`/firm`) that renders **one company at a
time as a force-directed relational graph** — the same node/edge visual language as
the codebase-memory graph index (see CLAUDE.md "Codebase Memory MCP"), repurposed
from "how this code ties together" to "how this *business* ties together". Pick a
symbol; the firm sits at the centre and its world fans out around it.

**Planes (graph + side panels):**
- **Relational graph (centre)** — nodes: the firm, its **suppliers**, **customers**,
  **competitors/peers**, subsidiaries/parent, key people, and the sector/index it
  belongs to. Edges: `supplies → · buys-from · competes-with · owns · part-of`. Node
  colour = FinBERT news sentiment; node size = relevance/market cap. Click a node to
  recentre on that firm (graph traversal, same UX as the code graph's `trace_path`).
- **Financials panel** — P&L / balance-sheet / cash-flow ratios and trends from
  yfinance fundamentals (the existing `tools/yfinance_tools.py` fundamentals path).
- **Live market value** — market cap = live price (`yf_live.py`) × shares
  outstanding, with the day's move and 52-wk context.
- **News & sentiment feed** — the existing news module (NewsAPI + FinBERT) filtered
  to this firm and its graph neighbours, so a supplier's bad print is visible on the
  customer's page.
- **Corporate actions / firm decisions** — dividends, splits, buybacks, board
  outcomes, earnings dates (yfinance + `risk/event_calendar.py`).

**DATA HONESTY (hard requirement, same mandate as the rest of the app):** yfinance
does **not** ship a supplier/customer graph. Relationship edges come from (a) a small
**curated seed** for the 72-symbol universe and (b) **news/filing-extracted** edges
produced by the local SLM, every derived edge **labelled with a confidence and a
source**, shown dimmer, and **never presented as authoritative fact**. Financials,
price, and corporate actions are real (yfinance/live); nothing is fabricated and
nothing is written to `ohlcv_*`. Missing data shows as "—", never invented.

**Synergy with M6:** this graph *is* the **relational plane ("how it ties back")** of
the Module 6 multimodal fusion (see below and `docs/WORLD_MODEL.md`). Building the
curated firm graph + news-extracted edges here delivers M6's Stage-1 relational/
textual grounding as a usable product feature first, then feeds the same edges into
the world-model latent later. Build order: curated seed + financials/news/actions
panels (no new ML) → force-directed graph UI → SLM edge-extraction (confidence-
flagged) → wire into M6 fusion. Reuses a force-directed graph renderer; page root
stays `background: transparent` so the mesh shows through (design-system invariant).

### P3/P4 — Module 6: World-Model Decisioning Core (forward-looking judge)

**Full design: [docs/WORLD_MODEL.md](WORLD_MODEL.md).** Owner mandate 2026-06-13.

The current decisioning core is **backward-looking**: lenses compute indicators on
past bars, the EV formula is a static heuristic, and the LLM judge recalls a
hindsight record and *guesses* — it never simulates the future. M6 replaces the
heart of the pipeline with a forward model, synthesising three ideas:

- **JEPA** (Joint-Embedding Predictive Architecture) — learn a market-state
  **latent** and predict in *representation* space, not price space. Markets are
  near-efficient: predicting tomorrow's close fits noise (both reference papers
  cap at ~54% direction accuracy and one *underperforms* buy-and-hold). Predicting
  the *latent* (regime drift, factor/vol structure, lead-lag) is tractable and
  actionable. The HMM regime becomes an interpretable projection of this latent.
- **World models** (Dreamer-lineage) — a latent **transition model** rolls `z_t`
  forward into a *distribution* of futures (imagination), read out as model-based
  EV: `E[return]`, CVaR downside, `P(target before stop)`, horizon — replacing the
  static `conf·RR·vol·convergence`.
- **Directional competence** (Zhu et al. 2026, LSTM-RF) — track trailing HR+/HR−
  per lens×direction×regime and weight/abstain accordingly. Cheapest, highest
  effort/reward; buildable now with the existing hindsight loop and no new ML.

**Honest framing:** "99th percentile" = breadth + forward simulation +
calibration/abstention + risk discipline, **not** predictive-accuracy magic (which
the literature shows is unreachable). Success is measured in Sharpe / max-DD /
hit-rate-when-not-abstaining.

**Slots in** between the lenses and the LLM judge; the judge becomes a reasoning
layer over a quantified forward distribution. **Hard fences:** imagination/latent
rollouts are NEVER persisted as market data (REAL-DATA-ONLY preserved); the risk
gate stays final; degraded mode falls back to the current judge and is flagged;
**promotion is gated on beating the current judge in walk-forward backtest** (10y
data + engine v2). Staged A→E (encoder · competence · world model · model-based EV
judge · optional latent policy), each shippable and eval-gated; the 10y backfill
(Change_46) is the training substrate. CPU-feasible at small latent dims for A–D;
E (RL-in-imagination) is the expensive, optional, last phase.

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

### 5b.1 Windows installer (.exe) — IN PROGRESS (2026-06-14)
**Status:** spec + frozen-mode entry shipped (`packaging/run_app.py`, `packaging/terminal_in.spec`); data-dir contract implemented (exe chdirs to `%LOCALAPPDATA%\TerminalIN`, bundled UI via `UI_OUT_DIR`). **Boot-tested (2026-06-14):** the onedir exe launches, binds the API, and creates the per-user data dir — caught + fixed a bug where the UI 404'd (bundled datas live in `_internal/` = `sys._MEIPASS`, not next to the exe).

**Self-serving desktop app (owner mandate 2026-06-14):** the shipped exe must NOT be "open your browser to localhost." It is now a native app:
- The Flask/SocketIO backend is the app's internal engine, bound to **127.0.0.1 on a free port** (`TIN_HOST`/`TIN_PORT`; dev stays `0.0.0.0:5000`). The local server is the standard IPC layer for a Python-backed desktop app — keeping the polished web UI without an HTTP rewrite — but the port is an invisible loopback detail, never a visible URL.
- The UI is hosted in a **native OS window via pywebview** (WebView2 on Windows), titled `TERMINAL//IN`, with the brand icon (`terminalin.ico`). Browser fallback only if the native runtime is absent (flagged).
- **Hardware maximization runs in-process** (`hw.apply()` at boot) — the shipped app engages all logical cores exactly like dev.
- Build flags: `console=False` (no console window; logs → `%LOCALAPPDATA%\TerminalIN\data\logs`), `icon` + `version_info.txt` (file properties read `TERMINAL//IN`), pywebview/pythonnet bundled.

**Update 2026-06-14 — installer pieces shipped (pending a full build run):**
- **First-run wizard** (`packaging/first_run.py`): a native pywebview window on the very first launch collects capital, risk tier, mode, and optional Kite/SMTP keys, and persists them through the validated settings path BEFORE the backend builds Config (so they take effect on the first boot). Runs in an isolated subprocess (`TIN_WIZARD=1`) because pywebview's loop starts once per process. Pure mapping unit-tested.
- **Inno Setup wrapper** (`packaging/installer.iss`): bundles the onedir tree into `TERMINAL-IN-Setup.exe` — Start-menu + desktop shortcuts (icon), optional logon auto-start, license page (`docs/LEGAL.md`), uninstaller that preserves user data in `%LOCALAPPDATA%\TerminalIN`.
- **One-command pipeline** (`packaging/build_installer.ps1`): static UI export → PyInstaller onedir → `iscc`; degrades to the onedir app if Inno Setup isn't installed.

**Next:** run the full build on the target machine (`.\packaging\build_installer.ps1`) and smoke-test the wizard + shortcuts; then 5b.3 (bundle `llama-server.exe` + GGUF to drop the Ollama dependency) and 5b.5 remote updates.

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

**Measured on the reference machine (Ryzen 7 7730U, 8C/16T, Radeon iGPU, 2026-06-12), qwen2.5:3b Q4:**

| Path | Prompt eval | Generation |
|---|---|---|
| Ollama CPU, 8 threads (default) | ~2,200 tok/s (prefix-cached) | **10.7 tok/s** |
| Ollama CPU, 16 threads | — | 8.9 tok/s (SMT hurts — bandwidth-bound) |
| llama.cpp **Vulkan iGPU** (full offload) | 25 tok/s | 9.5 tok/s |
| financial-analyst-v1 (TinyLlama 1.1B Q4) | — | **~28 tok/s** |

**Conclusion:** generation on this class of machine is **DDR-bandwidth-bound** — the iGPU shares the same memory bus, so neither more threads nor GPU offload helps. The levers that actually work: (1) **model size/quantization** (1.1B ≈ 3× faster than 3B), (2) prompt-prefix caching (keep_alive + stable system prompts — shipped), (3) streaming so perceived latency = first token (shipped: 6s first token). A discrete-GPU or higher-bandwidth machine changes this calculus; re-measure before re-architecting.
- `torch.set_num_threads(physical_cores)` + `OMP_NUM_THREADS` at boot; HIGH process priority default in packaged mode.
- Device autodetect at startup: CUDA → DirectML (any Windows GPU) → CPU; applies to FinBERT inference and LoRA training (`use_cpu` only when nothing better exists); llama.cpp `--n-gpu-layers auto`.
- `/api/health` reports the active device per subsystem (no silent CPU fallback when a GPU exists).

### 5b.5 Remote updates
- Update channel: **GitHub Releases** — the app checks the latest-release tag at boot (and daily), downloads the new package in the background, applies on next restart, keeps the previous version for rollback. Signed checksums.
- Mechanism final call deferred (full installer re-run vs delta patching); the version-check endpoint + UI "update available" toast land first.

## 5c. Model deploy + Claude-augmented training (P2, partially blocked)

- **Weight adjustment after training** — ✅ SHIPPED (2026-06-12): `terminal_in/agents/training/deploy.py` runs merge → GGUF f16 → Q4_K_M quantize → `ollama create financial-analyst-vN`; llama.cpp vendored (`vendor/llamacpp` Vulkan binaries + converter source). `POST /api/training/deploy {run_id}`. First deploy: financial-analyst-v1 (637 MB, ~28 tok/s CPU) from the smoke-test adapter. Model switch stays manual via the OLLAMA_MODEL setting (dropdown lists installed models) — promotion requires the eval set (still open below).
- **Claude-as-teacher dataset expansion**: grow `strategy_pairs.py` with Claude-generated QA on documented winning strategies (momentum/quality factor literature, Varsity strategy modules, public quant write-ups) and periodic web-sourced market-structure updates. Quality bar: every generated pair must cite the mechanism (why the edge exists), not just the rule. Target +500 pairs per quarter, versioned in git.

### Base-model selection for training (decided 2026-06-12)

| Use | Model | License | Why |
|---|---|---|---|
| **LoRA training base (now)** | Qwen2.5-3B-Instruct, bf16 on CPU | Qwen research (personal use OK; NOT for installer) | Best-in-class instruction following at a size that fits 16 GB RAM in bf16 (~6 GB); same family as the planner runtime |
| Inference upgrades (Release 2) | Qwen3-4B (Apache-2.0), Phi-4-mini (MIT) | Redistributable | Drop-in via Ollama/GGUF, no training required; eval-gated |
| Retired | TinyLlama-1.1B | Apache-2.0 | Proved the pipeline; failed the eval gate (9.5%) — cannot follow instructions |

Training-fit knobs added to `train_lora.py`: `LORA_DTYPE=bf16`, `LORA_BATCH_SIZE=1`, `LORA_GRAD_ACCUM=16`, `LORA_MAX_SEQ_LEN=384` is the expected 3B CPU recipe (~19–29 h/350 steps; weekend job, not overnight).

### P4 / Release 2 — Next-generation base models

The current stack (qwen2.5:3b judge, TinyLlama-1.1B trainee) was chosen for CPU-era constraints. Once the packaged app ships and hardware detection (5b.4) is live, re-evaluate against the then-best small open-source models — candidates as of writing: **Qwen3 4B/8B**, **Llama 4 small variants**, **Phi-4-mini**, **Gemma 3 4B**, **DeepSeek-R1 distills (7B/8B)** — all GGUF-served via the bundled llama.cpp, so a model swap is a file replacement + Modelfile bump, no code change.

Gate for adoption (per model, on the eval set from §P2 training): ≥10% better planner-verdict accuracy at ≤1.5× latency on reference hardware, and a clean license for redistribution inside the installer. Not before P4 — the backtest engine and F&O execution outrank model churn.

## 6. Quality & operations

- **Tests:** 160 passing (gate, broker, persistence, filters, planner, supervisor, backtest, F&O pricing + broker); every new module ships with unit tests; planner/LLM tests run fully mocked.
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
