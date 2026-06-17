# Contributing to TERMINAL//IN

This is a single-developer, personal project (see [LICENSE](LICENSE) — personal/
source-available). Contributions are not solicited, but if you're working in a
fork, these are the rules the codebase holds itself to.

## Environment

- **Python 3.14** on Windows 11 (also runs on macOS/Linux via `start.sh`).
- Create the venv and install deps:
  ```bash
  python -m venv .venv
  .venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
  ```
- Run the app (paper mode): `.venv/Scripts/python.exe -m terminal_in.main`
- Run the UI dev server: `cd terminal_ui && npm run dev`

## Tests

The suite must stay green. Run it before every commit:

```bash
.venv/Scripts/pytest tests/ -v
```

New behavior needs a test. Pure logic (gate checks, cost math, statistics,
pricing) is tested without a DB or network — follow the existing patterns in
`tests/`.

## Hard invariants (PR-blocking)

These are not style preferences — violating any of them is a defect:

1. **No synthetic or random market data** in `ohlcv_*` tables or the tick path,
   ever. Historical data comes only from yfinance backfill; live ticks from real
   quotes. World-model imagination / latent rollouts are never persisted as market
   data, never fed to lenses/strategies as bars, never shown as quotes.
2. **No silent degradation.** Any fallback must log a WARN, appear in
   `/api/health`, and surface as a badge in the UI. If a subsystem degrades
   quietly, that's a bug.
3. **The planner/judge can veto or shrink a signal, never bypass the risk gate.**
   The 17-check M2 gate is final.
4. **Validation negatives are results — do not tune signals until they pass.**
   `backtest/validation.py` is a falsification harness, not a number to optimize.
   See [`docs/ALPHA_FINDINGS.md`](docs/ALPHA_FINDINGS.md).
5. **Data honesty.** Theoretical/estimated values (Black-Scholes premiums, SPAN
   margin, margin bands) are labeled as such; values that are only available live
   (OI, real IV, volume) are null in paper, never fabricated.

## Style

Match the surrounding code: its naming, comment density, and idioms. The
transaction-cost model (`execution/costs.py`) and the risk gate (`risk/gate.py`)
are good reference points for the expected level of inline documentation.
