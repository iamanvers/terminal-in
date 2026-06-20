"""
Research universe + point-in-time index membership (fundamentals plane, Stage 2).

Expands the ticker base beyond the live 72-symbol cockpit with a curated Nifty
Midcap 150 set, for CROSS-SECTIONAL research/backtest (more names = more dispersion
to rank). Kept SEPARATE from the live `instruments.KNOWN_TOKENS` on purpose: the
orchestrator scan, watchlist, and live feed stay at 72 — this universe is for the
backtest/fundamentals layers only (synthetic tokens in a 92xxxxxx band, no live tick).

SURVIVORSHIP — the trap this module exists to manage. A cross-sectional backtest on
*today's* midcap list is survivor-skewed (the names that died/were relegated are
missing). The honest fix is point-in-time membership: `members_as_of(index, date)`
returns who was a member ON THAT DATE, including names since removed. The model
supports that (effective_from/effective_to per name) — BUT the seed below is a
CURRENT SNAPSHOT (every name effective_from the data floor, effective_to=None), so
`SURVIVORSHIP_CORRECTED is False`. Until NSE's dated reconstitution history (incl.
delisted names) is loaded, any mid/small result carries this bias — flagged, never
hidden. The curated list is also a STARTER subset, not the official full 150.

Prices: `backfill_research_prices(db)` fetches each name's daily history via the
shared yf_fetcher (SYMBOL.NS) into ohlcv_1d under its research token — run on demand.
"""

import logging
import zlib
from datetime import date, datetime

log = logging.getLogger(__name__)

_TOKEN_BASE = 920_000_000          # research-universe synthetic token band (≠ live 91xxxxxx)
DATA_FLOOR = '2016-01-01'          # backfill floor; also the snapshot effective_from
SURVIVORSHIP_CORRECTED = False     # current snapshot only — see module docstring

# Curated Nifty Midcap-150 STARTER set (current snapshot; NOT the official full 150,
# NOT point-in-time). Excludes names already in the live large-cap universe. symbol → sector.
MIDCAP_SECTORS: dict[str, str] = {
    # Pharma / healthcare
    'LUPIN': 'pharma', 'AUROPHARMA': 'pharma', 'BIOCON': 'pharma', 'TORNTPHARM': 'pharma',
    'ALKEM': 'pharma', 'GLENMARK': 'pharma', 'ZYDUSLIFE': 'pharma', 'IPCALAB': 'pharma',
    'LAURUSLABS': 'pharma', 'MAXHEALTH': 'pharma', 'FORTIS': 'pharma', 'ABBOTINDIA': 'pharma',
    # Financials
    'LICHSGFIN': 'financials', 'PNB': 'financials', 'CANBK': 'financials', 'UNIONBANK': 'financials',
    'IDFCFIRSTB': 'financials', 'FEDERALBNK': 'financials', 'BANDHANBNK': 'financials',
    'AUBANK': 'financials', 'RBLBANK': 'financials', 'MUTHOOTFIN': 'financials',
    'MANAPPURAM': 'financials', 'PFC': 'financials', 'RECLTD': 'financials',
    'MFSL': 'financials', 'ABCAPITAL': 'financials',
    # Auto & ancillaries
    'ASHOKLEY': 'auto', 'BHARATFORG': 'auto', 'MOTHERSON': 'auto', 'BALKRISIND': 'auto',
    'MRF': 'auto', 'BOSCHLTD': 'auto', 'EXIDEIND': 'auto',
    # IT
    'PERSISTENT': 'it', 'COFORGE': 'it', 'MPHASIS': 'it', 'OFSS': 'it', 'KPITTECH': 'it',
    # Consumer / retail / realty-consumer
    'PAGEIND': 'consumer', 'COLPAL': 'fmcg', 'MARICO': 'fmcg', 'UBL': 'fmcg',
    'JUBLFOOD': 'consumer', 'GODREJPROP': 'infra', 'OBEROIRLTY': 'infra', 'PHOENIXLTD': 'infra',
    # Industrials / capital goods
    'CGPOWER': 'infra', 'POLYCAB': 'infra', 'KEI': 'infra', 'SUPREMEIND': 'infra',
    'ASTRAL': 'infra', 'APLAPOLLO': 'metals', 'VOLTAS': 'consumer', 'DIXON': 'consumer',
    'CUMMINSIND': 'infra', 'THERMAX': 'infra',
    # Energy / utilities
    'PETRONET': 'energy', 'IGL': 'energy', 'GUJGASLTD': 'energy',
    'HINDPETRO': 'energy', 'TATAPOWER': 'energy', 'TORNTPOWER': 'energy',
    'NHPC': 'energy', 'ADANIPOWER': 'energy',
    # Metals / chemicals
    'SAIL': 'metals', 'NMDC': 'metals', 'NATIONALUM': 'metals', 'HINDZINC': 'metals',
    'SRF': 'chemicals', 'PIIND': 'chemicals', 'DEEPAKNTR': 'chemicals', 'AARTIIND': 'chemicals',
    'NAVINFLUOR': 'chemicals', 'COROMANDEL': 'chemicals', 'UPL': 'chemicals', 'TATACHEM': 'chemicals',
    # Transport / infra / media / misc
    'IRCTC': 'infra', 'IRFC': 'financials', 'CONCOR': 'infra', 'INDHOTEL': 'consumer',
    'SUNTV': 'media', 'PEL': 'financials', 'TATAELXSI': 'it', 'TATACOMM': 'telecom',
}

# symbol → research token. STABLE per-symbol (crc32) so adding/removing/renaming a
# name never reshuffles other tokens — the stored OHLCV stays correctly mapped as the
# universe grows. crc32 is deterministic across runs (unlike hash()); collisions
# across this set are asserted absent in the tests.
def _stable_token(symbol: str) -> int:
    return _TOKEN_BASE + (zlib.crc32(symbol.encode()) % 9_000_000)


RESEARCH_TOKENS: dict[str, int] = {s: _stable_token(s) for s in MIDCAP_SECTORS}
RESEARCH_BY_TOKEN: dict[int, str] = {t: s for s, t in RESEARCH_TOKENS.items()}

# Point-in-time membership rows: (symbol, effective_from, effective_to|None). The
# SEED is a current snapshot — effective_from the data floor, still-a-member.
_MEMBERSHIP: dict[str, list[tuple[str, str, str | None]]] = {
    'NIFTY MIDCAP 150': [(s, DATA_FLOOR, None) for s in sorted(MIDCAP_SECTORS)],
}


def members_as_of(index: str, as_of: str) -> set[str]:
    """Symbols that were members of `index` on `as_of` (ISO date) — the
    survivorship-correct universe query. With the current-snapshot seed this returns
    all names from the data floor on; once dated reconstitution is loaded it will
    correctly include/exclude names by date (and `SURVIVORSHIP_CORRECTED` flips)."""
    rows = _MEMBERSHIP.get(index.upper(), [])
    return {sym for sym, frm, to in rows if frm <= as_of and (to is None or as_of < to)}


def load_reconstitution(rows: list[dict], index: str = 'NIFTY MIDCAP 150') -> dict:
    """Load DATED index-membership history (incl. delisted/relegated names) — the
    survivorship fix. Each row: {symbol, effective_from, effective_to|None, sector?}.
    `effective_to=None` means still a member. This REPLACES the current-snapshot seed
    for `index` with real point-in-time spans and flips SURVIVORSHIP_CORRECTED to True,
    so `members_as_of` becomes honest and the cross-sectional backtest stops being
    upward-biased.

    FAIL-CLOSED (mirrors fundamentals.py/events.py): a row without a parseable
    effective_from or a symbol is DROPPED, never guessed — a wrongly-dated membership
    span would leak survivorship back in. Newly-seen symbols (delisted names absent from
    the live snapshot) get a STABLE crc32 research token so their OHLCV maps correctly
    once backfilled. Returns ingest honesty counts.

    NOTE: this only LOADS membership; the dated reconstitution data itself is a separate
    acquisition (NSE semi-annual index press releases incl. removed names — bot-hostile,
    so forward-accumulate or license). Until called with real data the store stays on the
    flagged current snapshot."""
    global SURVIVORSHIP_CORRECTED
    kept, dropped, new_syms = [], 0, []
    for r in rows:
        sym = str(r.get('symbol', '')).upper().strip()
        frm = _norm_date(r.get('effective_from'))
        to = _norm_date(r.get('effective_to')) if r.get('effective_to') else None
        if not sym or frm is None:
            dropped += 1                       # no symbol / unparseable date ⇒ never guess
            continue
        kept.append((sym, frm, to))
        if sym not in MIDCAP_SECTORS:
            MIDCAP_SECTORS[sym] = str(r.get('sector', 'other')).lower()
            tok = _stable_token(sym)
            RESEARCH_TOKENS[sym] = tok
            RESEARCH_BY_TOKEN[tok] = sym
            new_syms.append(sym)
    if kept:
        _MEMBERSHIP[index.upper()] = kept
        SURVIVORSHIP_CORRECTED = True
    log.info('index membership: loaded %d dated spans for %s (%d new/delisted names), '
             'dropped %d unverifiable; survivorship_corrected=%s',
             len(kept), index, len(new_syms), dropped, SURVIVORSHIP_CORRECTED)
    return {'loaded': len(kept), 'dropped_unverifiable': dropped,
            'new_symbols': new_syms, 'survivorship_corrected': SURVIVORSHIP_CORRECTED}


def load_reconstitution_file(path: str, index: str = 'NIFTY MIDCAP 150') -> dict:
    """Load dated membership from a CSV or JSON file. CSV header:
    symbol,effective_from,effective_to[,sector] (blank effective_to = current member)."""
    import csv
    import json as _json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        log.warning('index membership: reconstitution file not found: %s', path)
        return {'loaded': 0, 'dropped_unverifiable': 0, 'new_symbols': [],
                'survivorship_corrected': SURVIVORSHIP_CORRECTED}
    if p.suffix.lower() == '.json':
        rows = _json.loads(p.read_text())
    else:
        with p.open(newline='') as f:
            rows = [{k: (v or None) for k, v in row.items()} for row in csv.DictReader(f)]
    return load_reconstitution(rows, index=index)


def _norm_date(v) -> str | None:
    """Parse a membership date FAIL-CLOSED to ISO 'YYYY-MM-DD' (None if unparseable)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d-%b-%Y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def research_symbols() -> list[str]:
    return sorted(MIDCAP_SECTORS)


def sector_of(symbol: str) -> str:
    return MIDCAP_SECTORS.get(symbol.upper(), 'other')


def coverage() -> dict:
    """Honesty report — surfaced so a backtest never silently trusts a biased list."""
    return {
        'index': 'NIFTY MIDCAP 150', 'curated_names': len(MIDCAP_SECTORS),
        'official_full': 150, 'survivorship_corrected': SURVIVORSHIP_CORRECTED,
        'note': 'current-snapshot starter subset; load NSE dated reconstitution '
                '(incl. delisted) to fix survivorship before trusting mid/small results',
    }


def backfill_research_prices(db, start: str = DATA_FLOOR) -> int:
    """Fetch FULL daily history (start→today) for the research universe into
    ohlcv_1d under research tokens. These are brand-new tokens, so this does a
    direct fetch — yf_fetcher.backfill_history is backward-gap-only and skips
    tokens with no existing data. On-demand (not auto at boot). Returns symbols
    fetched; a bad/delisted ticker simply yields nothing (logged), never crashes."""
    from concurrent.futures import ThreadPoolExecutor
    from terminal_in.data_ingest.yf_fetcher import _yf_ticker
    try:
        import yfinance as yf
    except ImportError:
        log.warning('yfinance not installed — cannot backfill research universe')
        return 0
    today = date.today().isoformat()

    def _one(item: tuple[int, str]) -> int:
        token, symbol = item
        ticker_str = _yf_ticker(symbol)
        try:
            hist = yf.Ticker(ticker_str).history(start=start, end=today, interval='1d',
                                                 auto_adjust=True)
            if hist.empty:
                log.warning('research backfill: no data for %s (%s)', symbol, ticker_str)
                return 0
            bars = [{
                'date': str(idx.date()), 'instrument_token': token,
                'open': float(r['Open']), 'high': float(r['High']),
                'low': float(r['Low']), 'close': float(r['Close']),
                'volume': int(r['Volume']),
            } for idx, r in hist.iterrows()]
            db.insert_ohlcv_1d_batch(bars)
            log.info('research backfill %s (%s): %d bars (%s → %s)', symbol, ticker_str,
                     len(bars), bars[0]['date'], bars[-1]['date'])
            return 1
        except Exception:
            log.warning('research backfill failed for %s (%s)', symbol, ticker_str)
            return 0

    items = list(RESEARCH_BY_TOKEN.items())
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix='yf-research') as pool:
        n = sum(pool.map(_one, items))
    log.info('research universe: backfilled %d/%d midcap symbols', n, len(items))
    return n


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from terminal_in.config import load_config
    from terminal_in.db import DB
    print('coverage:', coverage())
    backfill_research_prices(DB(load_config().sqlite_path))
