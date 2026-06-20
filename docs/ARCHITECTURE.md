# TERMINAL//IN — Architecture

A concise map of how the system is put together. For exhaustive, file-level detail see
[`CLAUDE.md`](../CLAUDE.md); for the rationale and roadmap see [`PRD.md`](PRD.md).

## Process model

A **single multi-threaded Python process** — real OS threads, no eventlet, no Redis, no
Docker, no message broker. Components communicate through an in-process **`EventBus`**
singleton (`terminal_in/bus.py`): publish/subscribe plus a hot cache for last-known
values. Flask + SocketIO run in `threading` mode and fan the bus out to the UI over
WebSockets. One process keeps the whole system inspectable and laptop-local; the packaged
Windows build hosts the same backend on a private loopback port inside a native window.

The high-level trade loop and feedback paths are drawn in [`architecture.svg`](architecture.svg).

## Threads

Wired in `main.py`, each a daemon thread over the shared bus and SQLite DB:

- **data ingest** — yfinance backfill (24h refresh) + live quote feed + tick→1m aggregation
- **strategy engine** — 8 rule strategies, 60s cadence
- **orchestrator** — 6-lens scan, 120s, hands candidates to the planner
- **planner** — LLM judge between orchestrator and risk gate
- **supervisor** — per-trade circuit breakers, throttle, kill switch
- **hindsight** — re-prices rejected/closed decisions, feeds the planner prompt
- **settlement** — EOD square-off + daily P&L reset (market-hours aware)
- **news fetcher** — RSS + NewsAPI → FinBERT + India-macro sentiment
- **reports** — pre-open brief + EOD PDF
- **knowledge ingest** — firm-document RAG ingest + rolling-horizon compaction
- **F&O strategy manager** — multi-leg structures (paper)

## Data planes

Every plane is **real-data-only** and **fail-closed**: undatable or unverifiable data is
dropped, never guessed, and any degradation is surfaced on `/api/health` (no silent
fallbacks).

| Plane | Module | What it holds |
|-------|--------|---------------|
| **Market data** | `data_ingest/` | Real NSE OHLCV (yfinance, ~10y daily + 60d 5m, gap-aware) + live quotes + 1m tick aggregation. Never synthetic. |
| **Regime** | `strategy_engine/regime/` | 6-state HMM (pure-NumPy backend on 3.14); heuristic fallback until trained, flagged. |
| **News + sentiment** | `news/` | RSS/NewsAPI → FinBERT, corrected by an **India-macro layer** so broad-market direction (rupee, crude, rates, FII flows) carries the right sign. |
| **Events** | `data_ingest/events.py` | Point-in-time NSE corporate-announcement archive (filing timestamps; figures null, never faked). |
| **Fundamentals** | `data_ingest/fundamentals.py` | Point-in-time financials store: `get_pit(symbol, metric, as_of)` can never see a filing dated after `as_of`. As-reported only. |
| **Index membership** | `data_ingest/index_membership.py` | Research universe + dated membership (`members_as_of`) — the survivorship-correct universe query; loader for delisted names. |
| **Firm knowledge** | `knowledge/` | Vector-less point-in-time RAG over real firm documents (below). |

### Firm-knowledge RAG

`knowledge/firm_store.py` is a single **SQLite-FTS5** table — BM25 lexical retrieval, **no
embeddings or vector index**. Each row is a firm document (filing / announcement / news /
report) with a `filing_date` anchor. Properties:

- **Point-in-time** — `retrieve(symbol, query, as_of)` filters `filing_date ≤ as_of`.
- **Chunked** — long heterogeneous documents are split into overlapping FTS rows, so
  retrieval is at chunk granularity (the RAG pattern; firm docs don't fit a key/value shape).
- **Rolling 5-year horizon** — full text is kept recent, the 13mo–5y band is compressed to
  searchable summaries, beyond 5y is purged.

It is filled by ingest adapters (`knowledge/ingest.py`): the NSE event archive, persisted
news, BSE filings, IR PDFs, and the **firm-research collector** (`data_ingest/firm_research.py`)
— an autonomous gatherer that reads a firm's robots.txt + sitemap, ranks every URL against
an exhaustive collection spec (16 categories, each with a cadence), fetches reports/results/
disclosures (clearing WAFs via a browser TLS profile), dates them point-in-time, and stores
them chunked. It runs in two phases: **profile** (periodic full crawl → per-ticker map) and
**refresh** (each session, deltas on the volatile links only). The RAG grounds the AI
analyst and is the substrate for future fundamentals-driven, cross-sectional signals.

## Decision flow

```
orchestrator (6 lenses, 120s, 72 symbols)
  → signal_filters (data-quality · persistence ≥2 · confidence EMA · EV/regime hysteresis)
  → TradePlanner (one LLM call/scan: approve / reject / size + decision-memory context)
  → M2 risk gate (17 deterministic checks)
  → broker (paper sim / Kite REST) → settlement → P&L
```

The planner can **veto or shrink** a signal but can **never bypass** the risk gate. When
the LLM is unavailable it degrades to a stricter deterministic bar, flagged on every
decision — never silent.

### Risk gate

`risk/gate.py` runs 17 rejecting checks plus one size-reducing check, in order: kill-switch,
auto-trade, symbol block, tradeable instrument, market-open, event mask (live-only), VIX
hard-stop, drawdown, daily-loss cap, daily trade count, confidence, max positions,
duplicate, signal dedup, margin (rejects unpriceable orders), sector (with a small-book
floor), correlation (only at ≥3 open), and a VIX size-reduce. A concurrency lock guards the
counter checks.

### Feedback loops (three speeds)

- **Supervisor** (per trade) — lens circuit breakers, global throttle, hard stop → kill switch.
- **Learner** (per ~15 closed trades) — Bayesian win-rate, adaptive thresholds.
- **DecisionMemory + TRAIN** (hindsight → retraining) — every verdict is persisted; the
  hindsight loop re-prices outcomes; the recursive trainer fine-tunes the SLM on the record.

## Execution

`execution/`: a **PaperBroker** (0.03% slip + ₹20/order, product-aware MIS/CNC settlement)
and a **KiteBroker** (live REST). Derivatives have their own path — `fno_paper_broker.py`
(lot-based, Black-Scholes theoretical premiums, SPAN-approx margin, portfolio greek caps).
Transaction costs are a single shared model (`execution/costs.py`) used by the paper broker
and the backtest so they cannot diverge.

## Backtest + validation

`backtest/engine.py` replays real daily OHLCV through a deterministic mirror of the live
pipeline (no lookahead, fills at t+1 open, full Indian cost stack). `backtest/validation.py`
is the **falsification harness** and promotion gate: benchmarks (buy-hold / equal-weight /
random-symbol null), Deflated Sharpe + White Reality Check, walk-forward fences,
robustness, concentration, and survivorship checks. Nothing is promoted to the live judge
without earning it out-of-sample (see [`ALPHA_FINDINGS.md`](ALPHA_FINDINGS.md)).

## API + UI + persistence

- **API** — Flask blueprints under `terminal_in/api/routes/` (market, portfolio, trades,
  risk, agents, training, backtest, fno, knowledge, settings); SocketIO for live events.
- **UI** — Next.js 14 (`terminal_ui/`), six modules; served statically by Flask in
  production (one process) or hot-reloaded in dev.
- **Persistence** — thread-safe SQLite (WAL) for trades/news/decisions; parquet caches for
  derived archives (events, fundamentals); a separate SQLite-FTS5 file for firm knowledge.
  Per-deployment artifacts (DB, HMM model, knowledge store) are gitignored.

## Hard invariants (PR-blocking)

- No synthetic/random market data in `ohlcv_*` or the tick path — ever.
- World-model imagination is never persisted as market data or shown as quotes.
- Any fallback logs a WARN, appears in `/api/health`, and is badged in the UI.
- The planner/judge can veto or shrink signals but can never bypass the risk gate.
