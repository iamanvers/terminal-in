"""
yfinance-based OHLCV downloader for NSE/BSE instruments.
Replaces bhavcopy downloader — works without NSE website authentication.
Symbol mapping: NSE equity → SYMBOL.NS, indices → ^NSEI etc.
"""

import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# Map internal symbol → yfinance ticker
YF_MAP: dict[str, str] = {
    'NIFTY 50':          '^NSEI',
    'NIFTY BANK':        '^NSEBANK',
    'BANKNIFTY':         '^NSEBANK',
    'NIFTY FIN SERVICE': 'NIFTY_FIN_SERVICE.NS',
    'FINNIFTY':          'NIFTY_FIN_SERVICE.NS',
    'INDIA VIX':         '^INDIAVIX',
    'NIFTYBEES':         'NIFTYBEES.NS',
    'TATAMOTORS':        'TATAMOTORS.BO',  # yfinance uses BSE ticker for this
}


def _yf_ticker(symbol: str) -> str:
    """Convert internal symbol name to yfinance ticker."""
    if symbol in YF_MAP:
        return YF_MAP[symbol]
    # Default: append .NS for NSE equities
    return f'{symbol}.NS'


def backfill(db, token_map: dict[int, str], days: int = 365) -> int:
    """
    Download and store daily OHLCV for each token in token_map.
    token_map: instrument_token → symbol_name
    Returns count of symbols successfully downloaded.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning('yfinance not installed — skipping OHLCV download. Run: pip install yfinance')
        return 0

    # yfinance end is EXCLUSIVE — use tomorrow so today's completed session is included
    end_dt   = date.today() + timedelta(days=1)
    start_dt = end_dt - timedelta(days=days + 1)
    count = 0

    for token, symbol in token_map.items():
        ticker_str = _yf_ticker(symbol)
        try:
            tk = yf.Ticker(ticker_str)
            hist = tk.history(start=start_dt.isoformat(), end=end_dt.isoformat(), interval='1d', auto_adjust=True)
            if hist.empty:
                log.debug('No yfinance data for %s (%s)', symbol, ticker_str)
                continue

            bars = []
            for idx, row in hist.iterrows():
                bars.append({
                    'date':             str(idx.date()),
                    'instrument_token': token,
                    'open':             float(row['Open']),
                    'high':             float(row['High']),
                    'low':              float(row['Low']),
                    'close':            float(row['Close']),
                    'volume':           int(row['Volume']),
                })
            if bars:
                db.insert_ohlcv_1d_batch(bars)
                # Remove any synthetic seed bars on market holidays within the same range
                real_dates = {b['date'] for b in bars}
                purged = db.purge_nontrading_ohlcv_1d(token, bars[0]['date'], real_dates)
                if purged:
                    log.info('yfinance %s — purged %d synthetic holiday bars', symbol, purged)
                log.info('yfinance %s (%s) — stored %d daily bars', symbol, ticker_str, len(bars))
                count += 1
        except Exception:
            log.warning('yfinance fetch failed for %s (%s)', symbol, ticker_str)

    return count
