# TERMINAL//IN — Usage Guide

How to operate the terminal day-to-day. For *what* it is, see [../README.md](../README.md); for *where it's going*, see [PRD.md](PRD.md).

---

## 1. Starting and stopping

```powershell
# Interactive (console window, backend + UI dev server)
.\start.ps1                    # paper mode
.\start.ps1 -LowLatency        # + HIGH process priority + Python JIT
.\start.ps1 -Live              # live mode (needs fresh KITE_ACCESS_TOKEN)

# Background (no window — it trades, settles, and emails on its own)
.\background.ps1 -Start        # start hidden now
.\background.ps1 -Status       # check + health summary
.\background.ps1 -Stop         # stop
.\background.ps1 -Install      # auto-start at every logon (Scheduled Task)
.\background.ps1 -Uninstall    # remove auto-start

# UI (when backend started manually)
cd terminal_ui ; npm run dev   # http://localhost:3000
```

## 2. What runs autonomously (no clicks needed)

Once the backend is up, the full loop runs by itself:

| When (IST) | What happens |
|---|---|
| every 60s | 8 strategies evaluate the 72-symbol universe |
| every 120s | Orchestrator 6-lens scan → noise filters → LLM planner verdict → risk gate → **paper execution** |
| 08:50 | Fresh pre-open scan triggered |
| 08:55 | **Pre-open brief PDF** (trade suggestions + planner reasoning) generated → emailed |
| 09:15–15:30 | Live quotes, news every 15 min, supervisor control loop |
| 15:29 | EOD settlement — intraday positions closed at real prices |
| 15:45 | **EOD report PDF** (best/worst trades, longs/shorts, F&O, hindsight) → emailed |
| every 15 min | Hindsight loop re-prices past planner decisions |

The planner can *veto or shrink* trades but never bypass the risk gate. The kill switch (AGENTS page, or 8 consecutive losses) halts everything.

## 3. Email reports setup

Add to `.env` (Gmail: create an [App Password](https://myaccount.google.com/apppasswords), not your real password):

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=xxxx xxxx xxxx xxxx
REPORT_EMAIL_TO=you@example.com
```

Reports will not send until the SMTP sender credentials (`SMTP_USER`/`SMTP_PASS`)
and recipient are supplied in `.env` — PDFs still land in `data/reports/` regardless. On-demand:
`POST /api/training/report/run` with `{"kind": "pre_open" | "eod", "email": true}`.

## 4. The modules

- **MARKET** — watchlist, chart, news (filter chips: ALL/POS/NEG/HIGH IMPACT; headlines click through to the source), chat.
- **EQUITIES** — cash cockpit. Order ticket is open on the right by default: type a symbol (equities only), qty (or auto-size = 5% of equity), SL/target, confirm. BOOK/PERFORMANCE/SIGNALS tabs.
- **F&O** — *COCKPIT* (index complex + lot sizes, VIX context, index signals) and *OPTION CHAIN* (per-strike premiums + greeks by expiry; lot-based paper orders). Premiums are Black-Scholes theoretical from live spot + India VIX (labeled — not traded prices); OI/real-IV are live-only.
- **AGENTS** — *COMMAND* tab is the decision pipeline (scan table → planner verdicts with reasoning → supervisor breakers). *DECISION LOG* answers "why didn't you take X, and was that right?" (missed-winners filter). *AGENTS* tab has pause/resume/threshold controls per agent.
- **TRAIN** — smoke test (200 steps) or full LoRA run; run history with loss curves.
- **BACKTEST** — pick a horizon (1/2/5/10Y) → run; equity curve, per-lens/per-regime attribution, walk-forward-by-year, closed trades. No-lookahead replay over real OHLCV.
- **LEARN** — curated Varsity / Investopedia / quant tracks.

Toasts (bottom-right, 30s) announce trades, rejections, high-impact news, throttles, and planner approvals while you're on any page.

## 5. Routine operations

| Task | How |
|---|---|
| Pause all trading | AGENTS → kill switch GLOBAL PAUSE (or `POST /api/agents/risk/global-pause`) |
| Pause one strategy | AGENTS → AGENTS tab → card → PAUSE |
| Force a scan now | AGENTS → COMMAND → SCAN button |
| Check degraded state | amber badge on AGENTS page, or `GET /api/health` |
| Manual trade | EQUITIES → order ticket (goes through the same risk gate) |
| Retrain the model | TRAIN → SMOKE TEST first, FULL RUN overnight |
| Live mode | Fresh `KITE_ACCESS_TOKEN` in `.env` daily + `MODE=live` + restart |

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "BACKEND NOT RUNNING" in UI | `.\background.ps1 -Status`; check `data\logs\background.log.err`; port conflict is reported explicitly |
| Amber DEGRADED badge | `GET /api/health` lists the cause: `regime_heuristic` (normal until HMM trained), `ollama_offline` (start Ollama; planner runs stricter deterministic mode meanwhile), `sentiment_disabled`, `recent_errors` |
| Planner always rejects | Normal in sideways regimes — check DECISION LOG hindsight to see if it's right |
| No news | RSS refreshes every 15 min; check connectivity; NewsAPI key optional |
| Stale prices off-hours | Expected — last close shown when NSE is shut |
