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
    'TATAMOTORS':        'TATAMOTORS.NS',
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


def backfill_intraday(db, token_map: dict[int, str], interval: str = '5m') -> int:
    """
    Download intraday bars from yfinance and store in ohlcv_1m table.
    interval='5m' fetches last 60 days; interval='1m' fetches last 7 days.
    Uses INSERT OR REPLACE so real bars overwrite any synthetic GBM seeds.
    """
    try:
        import yfinance as yf
    except ImportError:
        return 0

    period_map = {'1m': '7d', '5m': '60d', '15m': '60d', '30m': '60d'}
    period = period_map.get(interval, '60d')
    count = 0

    # Skip index symbols that don't have intraday data on yfinance
    SKIP_YF = {'^INDIAVIX'}

    for token, symbol in token_map.items():
        ticker_str = _yf_ticker(symbol)
        if ticker_str in SKIP_YF:
            continue
        try:
            tk = yf.Ticker(ticker_str)
            hist = tk.history(period=period, interval=interval, auto_adjust=True)
            if hist.empty:
                log.debug('No intraday data for %s (%s)', symbol, ticker_str)
                continue

            bars = []
            for ts, row in hist.iterrows():
                try:
                    ts_ms = int(ts.timestamp() * 1000)
                except Exception:
                    ts_ms = int(ts.value // 1_000_000)
                bars.append({
                    'bucket_time':      ts_ms,
                    'instrument_token': token,
                    'open':   round(float(row['Open']),  4),
                    'high':   round(float(row['High']),  4),
                    'low':    round(float(row['Low']),   4),
                    'close':  round(float(row['Close']), 4),
                    'volume': int(row.get('Volume', 0) or 0),
                })
            if bars:
                db.insert_ohlcv_1m_batch(bars)
                log.info('yfinance intraday %s (%s) %s — stored %d bars', symbol, ticker_str, interval, len(bars))
                count += 1
        except Exception as exc:
            log.debug('intraday backfill failed %s (%s): %s', symbol, ticker_str, exc)

    return count
