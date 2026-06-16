"""
Phase 1 — point-in-time firm-event archive (Module 6 event plane).

Builds a table of corporate announcements with PRECISE filing timestamps, sourced
from the NSE corporate-announcements archive (the only programmatically reachable
exchange feed in this environment — BSE's API returns the empty sentinel to
non-browser requests; yfinance carries only ~2y of RESTATED dates and is barred by
the invariant below).

*** INVARIANT #1 — POINT-IN-TIME OR IT DOESN'T SHIP (PR-blocking) ***
  (a) ANNOUNCEMENT-DATE: we store NSE's `an_dt` (filing timestamp, to the second),
      never a period/quarter date.
  (b) AS-REPORTED: the structured numbers are NOT in the feed (they live in the
      attached PDF). We do NOT pull restated figures from yfinance/screener — so
      `as_reported` is null. Honest: we have the event + its date, not the figures.
  (c) CONSENSUS: no free point-in-time estimate exists for Indian names → `consensus`
      is null for the entire universe. `earnings_surprise` therefore cannot be
      computed and is emitted as null+flag downstream — never backfilled.

FAIL CLOSED: any announcement whose `an_dt` cannot be parsed to the second is
DROPPED and counted, never guessed. A dropped event is fine; a wrongly-dated one
would be fatal (it would leak the future into a past feature).

The archive is cached to data/events/nse_announcements.parquet (a derived cache —
NOT market data; nothing here is ever written to ohlcv_*).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CACHE = Path('./data/events/nse_announcements.parquet')
_NSE = 'https://www.nseindia.com'
_API = _NSE + '/api/corporate-announcements'
_REFERER = _NSE + '/companies-listing/corporate-filings-announcements'

# event_type ∈ {results, guidance, rating_change, board_meeting, regulatory, corp_action, other}
# classified from NSE's `desc` / subject by keyword — order matters (first match wins).
_RULES = [
    ('results',       ('financial result', 'outcome of board meeting', 'integrated filing- financ',
                       'unaudited financ', 'audited financ', 'quarterly result')),
    ('corp_action',   ('dividend', 'bonus', 'stock split', 'sub-division', 'buyback', 'buy back',
                       'rights issue', 'record date')),
    ('rating_change', ('credit rating', 'rating',)),
    ('guidance',      ('press release', 'analyst', 'institutional investor', 'concall', 'con. call',
                       'earnings call', 'investor presentation', 'investor meet')),
    ('regulatory',    ('sebi', 'regulation 30', 'takeover', 'insider trading', 'litigation',
                       'penalt', 'show cause')),
    ('board_meeting', ('board meeting', 'intimation of board')),
]


def classify(desc: str, subject: str = '') -> str:
    # Match on NSE's official `desc` category (clean); the freeform attachment
    # subject bleeds 'financial result' into unrelated filings, so it's a
    # fallback only when desc is empty.
    t = (desc or '').lower() or (subject or '').lower()
    for etype, keys in _RULES:
        if any(k in t for k in keys):
            return etype
    return 'other'


def _parse_ts(an_dt: str):
    """NSE 'DD-Mon-YYYY HH:MM:SS' → datetime, or None (→ row dropped, fail-closed)."""
    if not an_dt:
        return None
    for fmt in ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y'):
        try:
            return datetime.strptime(an_dt.strip(), fmt)
        except ValueError:
            continue
    return None


def _session():
    import requests
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json,text/plain,*/*', 'Referer': _REFERER,
    })
    s.get(_NSE, timeout=10)
    s.get(_REFERER, timeout=10)
    return s


def _fetch_symbol(s, symbol: str, frm: str, to: str) -> list[dict]:
    from urllib.parse import quote
    # URL-encode the symbol so names with '&' (e.g. M&M) aren't truncated.
    u = f'{_API}?index=equities&symbol={quote(symbol)}&from_date={frm}&to_date={to}'
    r = s.get(u, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f'NSE {r.status_code} for {symbol}')
    j = r.json()
    return j if isinstance(j, list) else j.get('data', [])


def build_event_archive(symbols: list[str], start: str = '01-01-2016',
                        end: str | None = None, delay: float = 1.2,
                        progress_cb=None) -> dict:
    """Fetch + cache the NSE announcement archive for `symbols`. Returns a summary
    dict with point-in-time honesty counts. start/end are 'DD-MM-YYYY'."""
    end = end or datetime.now().strftime('%d-%m-%Y')
    s = _session()
    rows, ingested, dropped = [], 0, 0
    for i, sym in enumerate(symbols):
        if progress_cb:
            progress_cb(i / max(len(symbols), 1), sym)
        try:
            raw = _fetch_symbol(s, sym, start, end)
        except Exception as e:
            log.warning('events: fetch failed for %s: %r — skipped', sym, e)
            continue
        for x in raw:
            ts = _parse_ts(x.get('an_dt') or x.get('sort_date') or '')
            if ts is None:                       # FAIL CLOSED — never guess a date
                dropped += 1
                continue
            desc = (x.get('desc') or '').strip()
            subj = (x.get('attchmntText') or x.get('sm_name') or '').strip()
            rows.append({
                'symbol': sym, 'announce_ts': ts.isoformat(timespec='seconds'),
                'announce_date': ts.strftime('%Y-%m-%d'),
                'event_type': classify(desc, subj), 'subject': desc[:120],
                'as_reported': None,             # invariant (b): not in feed, not faked
                'consensus': None,               # invariant (c): no PIT consensus exists
            })
            ingested += 1
        time.sleep(delay)                        # be polite to NSE
    df = pd.DataFrame(rows).drop_duplicates(['symbol', 'announce_ts', 'subject'])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)
    summary = {
        'events_ingested': int(len(df)),
        'events_dropped_unverifiable_date': int(dropped),
        'pit_consensus_pct': 0.0,                # honest: none available
        'symbols_with_events': int(df['symbol'].nunique()) if len(df) else 0,
        'symbols_requested': len(symbols),
        'by_type': df['event_type'].value_counts().to_dict() if len(df) else {},
        'span': [df['announce_date'].min(), df['announce_date'].max()] if len(df) else [None, None],
        'cache': str(CACHE),
    }
    log.info('events: ingested %d, dropped %d (unverifiable date), consensus %.0f%%',
             summary['events_ingested'], summary['events_dropped_unverifiable_date'],
             summary['pit_consensus_pct'])
    return summary


def load_events() -> pd.DataFrame:
    """Load the cached archive (empty DataFrame if not built yet)."""
    if not CACHE.exists():
        return pd.DataFrame(columns=['symbol', 'announce_ts', 'announce_date',
                                     'event_type', 'subject', 'as_reported', 'consensus'])
    return pd.read_parquet(CACHE)


def freshness() -> dict:
    """For /api/health: archive presence, last event date, dropped-on-build count."""
    if not CACHE.exists():
        return {'available': False, 'note': 'event archive not built (events.py)'}
    df = load_events()
    return {'available': True, 'n_events': int(len(df)),
            'last_event': df['announce_date'].max() if len(df) else None,
            'symbols': int(df['symbol'].nunique()) if len(df) else 0,
            'pit_consensus_pct': 0.0}


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from terminal_in.data_ingest.instruments import KNOWN_TOKENS, registry
    registry.load_stubs()
    syms = sorted(s for s, t in KNOWN_TOKENS.items() if registry.sector(t) not in ('index',))
    summ = build_event_archive(syms, progress_cb=lambda f, s: log.info('  [%d%%] %s', int(f * 100), s))
    import json
    print(json.dumps(summ, indent=1, default=str))
