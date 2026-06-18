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
    'HPCL': 'energy', 'PETRONET': 'energy', 'IGL': 'energy', 'GUJGASLTD': 'energy',
    'TATAPOWER': 'energy', 'TORNTPOWER': 'energy', 'NHPC': 'energy', 'ADANIPOWER': 'energy',
    # Metals / chemicals
    'SAIL': 'metals', 'NMDC': 'metals', 'NATIONALUM': 'metals', 'HINDZINC': 'metals',
    'SRF': 'chemicals', 'PIIND': 'chemicals', 'DEEPAKNTR': 'chemicals', 'AARTIIND': 'chemicals',
    'NAVINFLUOR': 'chemicals', 'COROMANDEL': 'chemicals', 'UPL': 'chemicals', 'TATACHEM': 'chemicals',
    # Transport / infra / media / misc
    'IRCTC': 'infra', 'IRFC': 'financials', 'CONCOR': 'infra', 'INDHOTEL': 'consumer',
    'SUNTV': 'media', 'PEL': 'financials', 'TATAELXSI': 'it', 'TATACOMM': 'telecom',
}

# symbol → research token (stable: assigned by sorted order so re-runs don't churn)
RESEARCH_TOKENS: dict[str, int] = {
    sym: _TOKEN_BASE + i for i, sym in enumerate(sorted(MIDCAP_SECTORS))
}
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


def backfill_research_prices(db, days: int = 3650) -> int:
    """Fetch daily history for the research universe via the shared yf_fetcher
    (SYMBOL.NS) into ohlcv_1d under research tokens. On-demand (not auto at boot).
    Returns symbols updated. yfinance simply skips a bad/delisted ticker (logged)."""
    from terminal_in.data_ingest.yf_fetcher import backfill_history
    token_map = dict(RESEARCH_BY_TOKEN)
    n = backfill_history(db, token_map, days=days)
    log.info('research universe: backfilled %d/%d midcap symbols', n, len(token_map))
    return n


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from terminal_in.config import load_config
    from terminal_in.db import DB
    print('coverage:', coverage())
    backfill_research_prices(DB(load_config().sqlite_path))
