# TERMINAL//IN — Product Requirements Document

**Version:** 1.3 · **Date:** 2026-06-20 · **Status:** Living document

> **Positioning.** TERMINAL//IN is a research and execution terminal, not an alpha engine, and the distinction is grounded in its own evidence. A built-in falsification harness (`backtest/validation.py`) tests every claimed edge out-of-sample, net of real Indian transaction costs and walk-forward-fenced; the record stands at nine independent negatives, with no long-only configuration beating buy-and-hold NIFTY (see §6b). The delivered value lies in the cockpit, the agentic decision plumbing, the cost and data discipline, and a validation gate that declines to tune signals until they pass. The forward bet (§4, fundamentals plane) is one of data rather than model: orthogonal, point-in-time information that no free source currently provides for this universe.

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
| F&O (derivatives) | `/fno` | ✅ Shipped — chain + greeks + lot-based paper execution + SPAN-approx margin + portfolio greek caps + **per-strike vol-surface skew** + **multi-leg strategies** (spreads, iron condor, futures pair, covered call, straddle). Live-mode Kite chain ingestion shipped; live F&O *execution* is the only remaining stage. |
| Agent orchestration | `/agents` | ✅ Shipped incl. LLM planner |
| Backtest | `/backtest` | ✅ Shipped — walk-forward over 10y real OHLCV (v2 lens-mirror / v3 real planner-in-loop / real strategy_engine classes) + alpha-validation harness + **F&O iron-condor backtest** |
| Recursive training | `/train` | ✅ Shipped (deploy step manual) |
| Education | `/learn` | ✅ Shipped |
| Firm intelligence graph | `/firm` | ◯ Planned (P3) — per-stock business map: force-directed relational graph of news · suppliers · customers · peers · financials · live market value · corporate actions. See §4 P3 "Firm Intelligence Graph". |
| Market-hours + settlement realism | core | ✅ Shipped (MIS/CNC products, SL/target-driven exits, session-gated signals) |
| Packaging (single process) | — | ✅ Shipped (static UI served by Flask on :5000; headless via background.ps1) |
| Daily PDF reports + email | — | ✅ Shipped (pre-open 08:55 / EOD 15:45 IST, branded) |

### 3.2 The agentic decision pipeline (shipped)

```
6 rule lenses (120s, 72 symbols) → noise filters → LLM Trade Planner → M2 risk gate (17-check) → broker
   feedback: TradingSupervisor (fast) · StrategyLearner (medium) · recursive training (slow)
   audit: DecisionMemory + hindsight re-pricing of every verdict
```

The risk gate is **17 rejecting checks + 1 size-modifying (VIX reduce)** = 18 recorded conditions (`risk/gate.py`); `event_mask` is live-only, `correlation` only at ≥3 open positions, and the sector cap has a documented small-book floor (≤2/sector always allowed). Cash **shorts are intraday-only (MIS)** — NSE has no overnight CNC delivery short, so any SELL is squared off at EOD. The portfolio surfaces **all-time realized return tagged to initial capital** (not just open marks).

Key properties (acceptance criteria, all verified):
- A signal **cannot** fire on its first scan appearance (persistence ≥ 2), below EV 1.2 (with exit hysteresis at 1.0), on <30 daily bars, on stale data, or without a resolvable price at the margin check.
- The planner makes **exactly one** LLM call per scan (45–60s budget, latest-batch-wins) and can only veto or shrink — never bypass risk.
- Ollama offline ⇒ **stricter** deterministic bar, `planner_mode=degraded` flagged on every event, decision row, and UI badge.
- Every candidate's verdict is persisted; rejections are re-priced after 4–72h (`would_win`/`would_lose`/`flat`) and the aggregate record feeds the next planner prompt.
- 3 consecutive losses attributed to a lens ⇒ 2h suppression; 5 ⇒ global throttle; 8 ⇒ kill switch. Daily-loss proximity (60% of cap) also throttles.

### 3.3 Data

- **Live universe:** 72 NSE instruments (Nifty-100 large/mid caps + index complex), symbol-keyed sector map covering the full universe. **Research universe (backtest only):** +85 curated Nifty Midcap 150 names with **point-in-time membership** (`data_ingest/index_membership.py`, stable crc32 tokens, kept separate from the live scan), 84 backfilled to full 10y — survivorship-flagged until NSE dated reconstitution lands.
- Real OHLCV only: yfinance gap-aware backfill (10y daily back to 2016, 60d 5m) + live quotes; synthetic data is **banned** (GBM seeder deleted 2026-06-10).
- FinBERT news sentiment; `/api/health` reports degraded subsystems (regime heuristic, sentiment off, Ollama offline).
- **Point-in-time fundamentals store** (`data_ingest/fundamentals.py`): every datum carries a filing_date so a backtest at date D can never see a filing dated after D; as-reported, FAIL-CLOSED on undatable rows. The spine for the fundamentals plane (§4) — empty until dated ingest accumulates; yfinance restated `.info` is barred from it.

### 3.4 Recursive training (Module 4, shipped)

Pipeline per run: dataset rebuild (static corpora + own closed trades + hindsight-judged decisions + Claude reasoning-traces) → LoRA fine-tune **Qwen2.5-1.5B-Instruct** in subprocess (TinyLlama-1.1B retired — failed the eval gate) → real loss metrics from `trainer_state.json` → `training_runs` history. Smoke (200 steps) and full modes from `/train`; deploy = merge → GGUF → `ollama create` (shipped).
**Open:** deploy automation (merge → GGUF via llama.cpp → `ollama create`) and a held-out eval set (see P2).

---

## 4. Roadmap

### P2 — F&O execution (Stages 1–6 shipped; only live-mode Kite F&O *execution* remains)

**Why separate from equities:** derivatives differ in every dimension that matters — lot-based sizing, expiry lifecycle, SPAN margining, non-linear payoff, and the underlyings (indices) are not cash-tradeable at all. Bolting options onto the cash pipeline would corrupt risk checks; F&O gets its own instrument model, broker path, and gate checks.

| Feature | Status |
|---|---|
| Contract model | ✅ `data_ingest/fno_instruments.py`: synthetic deterministic tokens, expiry calendar (weekly NIFTY / monthly per index), strike chain. Live Kite-dump ingestion deferred to live mode. |
| Chain UI | ✅ OPTION CHAIN view on `/fno`: CE/PE premiums + greeks per strike, ATM highlight, expiry chips. **OI/real-IV are live-only (null in paper, never fabricated)** — premiums are Black-Scholes theoretical from real spot + India VIX (labeled). |
| Paper execution | ✅ `execution/fno_paper_broker.py`: lot-based orders, premium P&L, theoretical mark-to-market on underlying ticks, expiry square-off at intrinsic; shares the cash account. UI order ticket + positions panel on `/fno`. |
| Margin | ✅ `risk/span_margin.py`: scenario-based **SPAN approximation** — worst-case loss over a price (±3.5σ/2-day, VIX-implied) × vol grid + exposure add-on. ATM short > OTM short; futures ~7% notional. Long option = premium. Labeled approx. |
| Signal routing | ✅ `execution/fno_signal_router.py`: S1 ORB + S8 VIX index signals express as **risk-defined debit spreads** by default (bull-call / bear-put; `FNO_DIRECTIONAL_STRUCTURE=spread\|option`, `FNO_SPREAD_WIDTH`), market-hours + kill-switch checked. |
| Vol surface | ✅ `execution/vol_surface.py`: per-strike **skew/smile** (equity-index negative skew, mild wing smile, short-tenor steepening, clamped) replaces flat-VIX as the per-strike IV; ATM preserved bit-for-bit; `VOL_SURFACE=false` reverts; live Kite per-strike IV overrides. Feeds chain greeks + SPAN consistently via `_iv_at`. |
| Multi-leg strategies | ✅ `place_combo` (atomic multi-leg, **combo-level** greek/margin/event risk — never leg-by-leg) + `execution/fno_strategies.py` leg-builders + `fno_strategy_manager.py` (periodic scan, book-reconciled dedupe): **variance harvest** (range+VIX→NIFTY iron condor), **futures pair** (cointegration→long cheap/short rich FUT — the fundable market-neutral form), **covered call**, **event straddle**. Per-kind env toggles. All eval-gated capabilities, not tuned alpha. |
| F&O backtest | ✅ `backtest/fno_engine.py` + `/api/backtest/fno`: monthly NIFTY iron condor over 10y real NIFTY+VIX, shorts at the VIX-implied ~1-SD move, realistic NSE-options costs, no lookahead. **Verdict (negative #8): theoretical CAGR +0.74% / Sharpe 0.13 / −25% DD — not a deployable edge** (theoretical BS premiums flatter short-premium; real is worse). |
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

### P2/P3 — Fundamentals plane (ACTIVE — the one untested alpha lever)

Owner direction 2026-06-18: ground the (technical-only) strategies in **firm
fundamentals** and **expand the universe to mid-caps**, then backtest. This is exactly
what §6b concluded was the only untested edge — orthogonal **point-in-time** data, a
data-acquisition problem, not a model change. Decided: data source = **hybrid (BSE
XBRL for breadth + firm-IR-site PDFs for depth)**; universe = **large-cap 72 + Nifty
Midcap 150**.

**Two make-or-break traps (violating either makes the backtest a lie):** (1)
**point-in-time integrity** — today's restated numbers vs past prices = lookahead;
use each datum only after its filing date, as-reported; (2) **survivorship** — today's
mid/small list is survivor-skewed; need point-in-time index membership incl. delisted
names. The store + membership model enforce these by construction.

| Stage | Status |
|---|---|
| 1 — PIT fundamentals store | ✅ `data_ingest/fundamentals.py` — filing_date vs period_end, `get_pit(as_of)` no-lookahead, as-reported, FAIL-CLOSED. Empty until ingest. |
| 2 — Universe expansion | ✅ `data_ingest/index_membership.py` — 85 curated Nifty Midcap 150 (research-only, separate from live 72), point-in-time `members_as_of`, stable tokens; 84/85 backfilled to 10y. Survivorship-flagged (current snapshot; load NSE dated reconstitution to fix). |
| 3 — Ingest adapters | ◯ BSE-XBRL (breadth) + firm-IR-PDF (depth) writing dated rows; forward-accumulate (exchange access is bot-hostile → a trustworthy 10y historical PIT backtest needs accumulation or a licensed dataset). |
| 4 — Factors + backtest | ◯ value/quality/growth cross-sectional factors computed point-in-time → backtest via `validation.py`. Interim (runnable now on prices): cross-sectional reversal/momentum on the wider midcap universe via `members_as_of`. |

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

The current stack (qwen2.5:3b judge, Qwen2.5-1.5B-Instruct trainee) was chosen for CPU-era constraints. Once the packaged app ships and hardware detection (5b.4) is live, re-evaluate against the then-best small open-source models — candidates as of writing: **Qwen3 4B/8B**, **Llama 4 small variants**, **Phi-4-mini**, **Gemma 3 4B**, **DeepSeek-R1 distills (7B/8B)** — all GGUF-served via the bundled llama.cpp, so a model swap is a file replacement + Modelfile bump, no code change.

Gate for adoption (per model, on the eval set from §P2 training): ≥10% better planner-verdict accuracy at ≤1.5× latency on reference hardware, and a clean license for redistribution inside the installer. Not before P4 — the backtest engine and F&O execution outrank model churn.

## 6. Quality & operations

- **Tests:** 276 passing (gate, broker, persistence, filters, planner, supervisor, backtest, validation, m6, events, costs, vol surface, F&O pricing/broker/strategies/manager/backtest, fundamentals, index membership, palette, onboarding); every new module ships with unit tests; planner/LLM tests run fully mocked.
- **License & positioning:** personal / source-available (see `LICENSE`); `CONTRIBUTING.md` records the hard invariants; README carries badges + a Positioning section. The "validation negatives are results, don't tune to pass" discipline is itself an invariant.
- **No-silent-degradation invariant:** any subsystem fallback must (a) log at WARN with rate limiting, (b) appear in `/api/health`, (c) badge in the UI. PR-blocking rule.
- **Real-data invariant:** no synthetic/random market data may enter `ohlcv_*` tables or the tick path. PR-blocking rule.
- **Commit convention:** `Change_N: summary` on `main`.
- **Docs:** README (operator-facing), CLAUDE.md (agent/dev-facing), this PRD (product). Update all three at every phase boundary; session context persists to Claude memory.

## 6b. Alpha Validation — Results to Date (2026-06-20)

A falsification-first harness (`terminal_in/backtest/validation.py`) serves as the promotion
gate for any edge claim: benchmarks (buy-hold NIFTY, equal-weight, a 1,000× random-symbol
null), Deflated Sharpe and White Reality Check, per-strategy significance, planner isolation,
±20% robustness, regime and time concentration, and survivorship — all net of the shared cost
model (`execution/costs.py`) and walk-forward-fenced. Full detail: **[ALPHA_FINDINGS.md](ALPHA_FINDINGS.md)**.

**Verdict: no long-only configuration tested beats buy-and-hold NIFTY net of costs** —
**nine independent fenced negatives**: (1) price-only technicals; (2) LLM/planner marginal
value; (3) the Module-6 D₀ forward-EV head; (4) directional-competence weighting; (5) the
event/PEAD and VIX-reaction planes; (6) cross-sectional 1-month reversal (an apparent pulse
that dies on hardening — Deflated Sharpe 0.72 < 0.95 — and decomposes to beta, not alpha);
(7) directional long/short across the system's own signals (the lens score carries a negative
cross-sectional IC of −1.35, i.e. lens-favoured names underperform equal-weight, which is why
long-only trails passive); (8) the F&O variance-risk-premium harvester (monthly NIFTY iron
condor, theoretical Sharpe 0.13 / CAGR +0.74%, where theoretical pricing flatters short
premium); and (9) hardened cross-sectional reversal and momentum books (best Deflated Sharpe
0.867 < 0.95). Net return is ~3% CAGR versus ~11.6% for the index and ~21% for equal-weighting
the same names. The bottleneck is signal and data, not model capacity — a larger LLM does not
help (the planner adds approximately zero; the literature direction-accuracy ceiling is ~54%).

**One genuine open lead.** On the wider large-plus-mid-cap universe, a fundable long-only
12-1 momentum tilt beats an equal-weight benchmark by ~0.63 risk-adjusted Sharpe at the same
beta — unlike reversal, whose excess is pure beta. It is survivorship-suspect (the wider
universe is a current snapshot) and not yet multiple-testing-deflated, so it remains a lead
pending point-in-time index membership including delisted names, not an established edge.

**Implications for this roadmap:**
- Module 6 Phases C + D₀ are BUILT and FAILED their gate (not promoted; `terminal_in/m6/`).
  The research arc (A/B/D/E — JEPA + world model) should be pursued ONLY against genuinely
  orthogonal **point-in-time data**, not more price-derived features.
- The honest levers are **data, not model**: real point-in-time fundamentals, analyst-estimate
  revisions (SUE/consensus — 0% free PIT coverage for this universe today), relational/
  supply-chain signal, alternative data. Each is a data-acquisition project.
- Two architectural reframes worth a fenced test before more modelling (see literature scan,
  §7b): (a) **cross-sectional market-neutral long/short** evaluation — measure the signal's
  cross-sectional IC and the dollar-neutral top-minus-bottom spread Sharpe (costs + borrow
  modelled), since long-only selection structurally cannot out-return a bull index; (b)
  forward-accumulated firm-news sentiment evaluated on a true forward holdout.

## 6c. Cross-sectional reframe + forward plan (2026-06-17)

The literature scan (§7b) said the durable edge is **cross-sectional + market-neutral**,
not directional. So we built and ran that test (`validation.py --longshort`):

- **A1 — cross-sectional IC**, **A2 — dollar-neutral long/short book**, rebalanced every
  20d. **Indian context (hard constraint):** the cash segment cannot hold overnight
  shorts, so the short leg is a **single-stock future** (F&O-eligible names only; ~6 bps
  round-trip estimate, flagged), long leg is cash CNC, benchmark is **cash/0** (a neutral
  book's bar — not NIFTY).
- **Result:** 12-1 momentum is null (IC-IR 0.88). 1-month reversal *looked* like a pulse
  (IC-IR +1.96) — so it was **hardened before any engine work** (`--longshort --hard`:
  realistic futures+borrow cost, sqrt market-impact + capacity curve, deflated Sharpe over
  the 5-horizon search). **It does not survive: Deflated Sharpe 0.72 < 0.95** (undeflated
  per-period Sharpe ~0.12), and the fenced **dynamic** variants are *worse* than the
  in-sample static pick (walk-forward horizon 0.24, regime-conditioned 0.28, vs 0.44).
  Capacity is fine at retail scale (Sharpe ~0.44 to ₹10cr; 0.23 at ₹100cr). **Verdict: not
  a deployable edge — no engine sleeve.** Hardening-before-engine did its job.

**Forward plan (sequenced, each behind the same walk-forward gate):**
1. **A1/A2 + hardening — DONE** (this build). Reversal failed the hardened gate; the
   "harden before you build the engine" discipline saved the futures-execution work. No
   engine sleeve until something clears the hardened gate (DSR > 0.95 net of impact).
2. **Firm Intelligence Graph (`/firm`, see §4 P3)** — the relational data plane: clean
   edges first (sector map + rolling price co-movement/correlation + factor exposure),
   force-directed UI (codebase-memory MCP graph is the visual seed), then **relational
   FEATURES** (peer-relative return, sector-relative momentum, lead-lag) fed into the
   cross-sectional frame above. Relational structure is the orthogonal lever both papers
   exploit and the one input with a non-trivial prior we haven't tried.
3. **Self-improving infra:** news time-bounding (12-month rolling summaries, purge >5yr);
   forward-accumulate timestamped firm-news sentiment (no honest 10y archive exists —
   evaluate on a forward holdout); honest "model-on-start" (boot/nightly rebuild the
   candidate dataset + **re-run the validation gate**, auto-promote ONLY on a pass).

**Universe capacity — mid/small caps:** more breadth strengthens cross-sectional dispersion
(reversal is documented stronger in less-covered names), but frictions bite hardest on a
turnover-heavy neutral book: liquidity/impact (flat slippage understates it), **shortability**
(most mid/small are not F&O-eligible → can't short → breaks the neutral book), and
**survivorship** (today's mid/small list is heavily survivor-skewed). **Status (2026-06-18):**
the **Nifty Midcap 150 research universe is now ADDED** (§4 fundamentals plane Stage 2) — 85
curated names, 10y price backfill, with a **point-in-time membership model** so the survivorship
fix is structural (the seed is a current snapshot, flagged, pending NSE dated reconstitution
incl. delisted names). Still required before trusting a mid/small neutral result: dated
reconstitution + a liquidity-aware impact model; **small-caps stay out of the neutral book**.

## 7. Success metrics

> Reality check (2026-06-17): the profitability/planner-value targets below are **currently
> unmet** — see §6b. They remain the bar; nothing ships as "alpha" until it clears the
> validation gate net of costs, OOS.

| Metric | Target | Where measured |
|---|---|---|
| Beats passive, net | Net Sharpe AND CAGR > buy-hold NIFTY over walk-forward, survives Deflated Sharpe | `validation.py` (the gate) |
| Paper-trading profitability | Positive expectancy over 60 paper days; Sharpe > 1.0 | `/trade` performance tab |
| Planner value-add | Approved-trade win rate > deterministic-only baseline; missed-winner rate < 30% of rejections | DECISION LOG hindsight |
| Control-loop efficacy | Max consecutive-loss streak ≤ 8 (hard stop ceiling); no >4% daily loss breaches | supervisor state + settlement history |
| Model improvement | Eval-set score improves run-over-run; final loss decreasing at constant data scale | `/train` run history |
| System reliability | Backend boot < 5 s; zero silent degraded states; UI never false-reports backend down | /api/health + boot logs |

## 7b. Literature scan — "what are we missing?" (2026-06-17)

Reviewed four sources the owner flagged. Honest read on each and what it implies:

- **Mercanti, *Using AI to Enhance Alpha Generation* (Medium)** — conceptual; yfinance-only,
  no OOS results, no costs, no leakage discussion. This is precisely the naive approach our
  harness already falsified. No new lever.
- **algoadvantage, *The Right Way to Use AI in Trading* (Substack)** — thesis: AI's value is
  **process + validation, not strategy authorship**; enforce "separation of powers" (the AI
  author cannot be the backtester judge); "the alpha is in the process, not the prompt." This
  **endorses our architecture** (deterministic validation gate, walk-forward fencing, AI as
  assistant). Confirms method; reveals no missing signal.
- **Wang et al., *Alpha-GPT* (arXiv 2308.00016)** — LLM mediates human alpha-MINING over
  WorldQuant's **~5,000-field multi-modal universe (price-volume + fundamentals + derivatives
  + news sentiment)**; alpha comes from **data breadth + cross-sectional symbolic search**,
  not the LLM predicting price. Admits in-sample ≫ OOS (overfitting); competition-scored, no
  net-of-cost detail. Lesson: **data breadth + cross-sectional construction is the lever** —
  consistent with our conclusion.
- **Ghatak et al., *Increase Alpha* (arXiv 2509.16707)** — the headline case ("Sharpe 2.54 vs
  S&P 1.19, OOS walk-forward, 814 US equities"). Read critically, the number rests on three
  things our gate is built to strip out: **(1) transaction costs explicitly NOT included**
  (non-compounded gross returns, no slippage/borrow); **(2) heavy data-snooping** (2,280
  scenarios/stock, per-stock "best signal period," 11 ranking rules, no multiple-testing
  correction); **(3) black-box proprietary features** (non-reproducible, can't audit for
  look-ahead). It is also a **market-NEUTRAL long/short** book (≈−5% S&P correlation) using
  **fundamentals + news/social sentiment** — so "beats the S&P" is the wrong frame: the edge
  is *cross-sectional spread + uncorrelatedness*, not directional out-return, and it leans on
  **data we don't have** (fundamentals, sentiment). It is reported, not independently verified
  net of costs.

**Net takeaway:** nothing here is a technique we "missed" so much as confirmation that (i) the
edge in published work lives in **orthogonal point-in-time data** (fundamentals, sentiment,
cross-asset) and **market-neutral cross-sectional construction**, and (ii) the impressive
numbers are typically **gross of costs and/or data-snooped** — exactly what our validation
harness exists to expose. The two concretely actionable reframes are folded into §6b.
