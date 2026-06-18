"""
Point-in-time fundamentals store (Stage 1 of the fundamentals plane).

The spine for grounding strategies in firm fundamentals WITHOUT lying to the
backtest. The cardinal sin of a fundamental backtest is using TODAY's restated
numbers against a PAST price — the strategy then "knows" earnings that weren't
public yet. This store makes that impossible by construction:

  - Every datum carries a FILING_DATE (when it became public) separate from the
    PERIOD_END (the fiscal period it describes). A figure for FY2018 filed in
    May-2018 must not be visible to a decision dated April-2018.
  - `get_pit(symbol, metric, as_of)` returns the latest value whose filing_date
    <= as_of — never a figure that hadn't been filed yet.
  - As-reported only: figures are stored as filed; restatements are NOT folded
    back over history (each filing keeps its own date+value).
  - FAIL CLOSED: a row whose filing_date can't be parsed is DROPPED, never guessed
    — exactly like the event archive (`events.py`). No date ⇒ not point-in-time ⇒
    it does not exist for us.

This module only DEFINES + STORES + QUERIES point-in-time fundamentals. The ingest
adapters (BSE XBRL for breadth, firm-IR PDFs for depth) write dated rows here in a
later stage; until real dated data is accumulated the store is simply empty, and any
factor/backtest that reads it gets nothing rather than a biased guess. yfinance
`.info` fundamentals are RESTATED + undated → they are NOT point-in-time and must
never be written here (only used live, clearly labeled).

Cache: data/fundamentals/pit_fundamentals.parquet (gitignored, per-deployment).
"""

import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CACHE_DIR = Path('./data/fundamentals')
STORE = CACHE_DIR / 'pit_fundamentals.parquet'

# Canonical as-reported metrics (₹ crore unless noted). Factors are derived from
# these + price downstream — we store raw filings, not ratios.
PIT_METRICS = frozenset({
    'revenue',           # net sales / total income for the period
    'net_income',        # PAT (profit after tax)
    'operating_profit',  # EBITDA / operating profit
    'eps',               # reported EPS (₹/share) for the period
    'equity',            # shareholders' equity / net worth
    'total_debt',        # borrowings
    'shares_out',        # shares outstanding (crore)
})

COLUMNS = ['symbol', 'metric', 'period_end', 'filing_date', 'value', 'source', 'as_reported']


def _parse_date(v) -> date | None:
    """Parse a filing/period date FAIL-CLOSED — None on anything unparseable."""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d-%b-%Y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, errors='raise').date()
    except Exception:
        return None


def record_fundamentals(rows: list[dict]) -> dict:
    """Append dated fundamental rows. Each row needs symbol, metric, period_end,
    filing_date, value (+ optional source). FAIL CLOSED: rows without a parseable
    filing_date OR an unknown metric are DROPPED. Returns ingest honesty counts."""
    kept, dropped = [], 0
    for r in rows:
        fd = _parse_date(r.get('filing_date'))
        pe = _parse_date(r.get('period_end'))
        metric = str(r.get('metric', '')).lower()
        val = r.get('value')
        if fd is None or pe is None or metric not in PIT_METRICS or val is None:
            dropped += 1                              # no date / bad metric ⇒ never guess
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            dropped += 1
            continue
        kept.append({
            'symbol': str(r.get('symbol', '')).upper(), 'metric': metric,
            'period_end': pe.isoformat(), 'filing_date': fd.isoformat(),
            'value': val, 'source': str(r.get('source', 'unknown')),
            'as_reported': bool(r.get('as_reported', True)),
        })
    if kept:
        df_new = pd.DataFrame(kept, columns=COLUMNS)
        existing = load_fundamentals()
        out = pd.concat([existing, df_new], ignore_index=True) if len(existing) else df_new
        # dedupe on the natural key (a re-ingest of the same filing is idempotent)
        out = out.drop_duplicates(subset=['symbol', 'metric', 'period_end', 'filing_date'],
                                  keep='last')
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(STORE, index=False)
    summary = {'ingested': len(kept), 'dropped_unverifiable': dropped,
               'total_rows': len(load_fundamentals())}
    log.info('fundamentals: ingested %d, dropped %d (no/bad date), total %d',
             summary['ingested'], summary['dropped_unverifiable'], summary['total_rows'])
    return summary


def load_fundamentals() -> pd.DataFrame:
    if STORE.exists():
        try:
            return pd.read_parquet(STORE)
        except Exception:
            log.exception('fundamentals: failed to read store')
    return pd.DataFrame(columns=COLUMNS)


def get_pit(symbol: str, metric: str, as_of) -> float | None:
    """Point-in-time value: the latest `metric` for `symbol` whose filing_date is
    ON OR BEFORE `as_of`. Returns None if nothing was public by then. This is the
    no-lookahead guarantee — a backtest at date D can only ever see filings <= D."""
    as_of = _parse_date(as_of)
    if as_of is None:
        return None
    df = load_fundamentals()
    if not len(df):
        return None
    m = df[(df['symbol'] == str(symbol).upper()) & (df['metric'] == str(metric).lower())]
    m = m[pd.to_datetime(m['filing_date']).dt.date <= as_of]
    if not len(m):
        return None
    # latest by filing_date, tie-break by period_end (newest fiscal period)
    m = m.sort_values(['filing_date', 'period_end'])
    return float(m['value'].iloc[-1])


def as_of_snapshot(symbols: list[str], metric: str, as_of) -> dict:
    """Cross-sectional point-in-time snapshot: {symbol: value} for every symbol that
    had `metric` public by `as_of`. The honest input for a cross-sectional rank."""
    return {s: v for s in symbols if (v := get_pit(s, metric, as_of)) is not None}


def freshness() -> dict:
    """Coverage report for /api/health-style honesty (how much PIT data exists)."""
    df = load_fundamentals()
    if not len(df):
        return {'rows': 0, 'symbols': 0, 'metrics': 0, 'latest_filing': None,
                'note': 'empty — no point-in-time fundamentals ingested yet'}
    return {
        'rows': int(len(df)), 'symbols': int(df['symbol'].nunique()),
        'metrics': int(df['metric'].nunique()),
        'latest_filing': str(df['filing_date'].max()),
        'as_reported_pct': round(float(df['as_reported'].mean()) * 100, 1),
    }
