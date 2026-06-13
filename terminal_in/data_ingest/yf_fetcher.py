"""
yfinance-based OHLCV downloader for NSE/BSE instruments.
Replaces bhavcopy downloader — works without NSE website authentication.
Symbol mapping: NSE equity → SYMBOL.NS, indices → ^NSEI etc.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# Concurrent symbol downloads. Network-bound (GIL released), so this cuts a
# 72-symbol backfill from minutes to tens of seconds while staying polite
# to Yahoo (bounded fan-out, not 72 simultaneous connections).
_FETCH_WORKERS = 6

# Map internal symbol → yfinance ticker
YF_MAP: dict[str, str] = {
    'NIFTY 50':          '^NSEI',
    'NIFTY BANK':        '^NSEBANK',
    'BANKNIFTY':         '^NSEBANK',
    'NIFTY FIN SERVICE': 'NIFTY_FIN_SERVICE.NS',
    'FINNIFTY':          'NIFTY_FIN_SERVICE.NS',
    'INDIA VIX':         '^INDIAVIX',
    'NIFTYBEES':         'NIFTYBEES.NS',
    # Tata Motors demerged in 2025 — TATAMOTORS.NS was delisted on Yahoo;
    # the passenger-vehicles entity TMPV.NS carries the listing forward.
    'TATAMOTORS':        'TMPV.NS',
}


def _yf_ticker(symbol: str) -> str:
    """Convert internal symbol name to yfinance ticker."""
    if symbol in YF_MAP:
        return YF_MAP[symbol]
    # Default: append .NS for NSE equities
    return f'{symbol}.NS'


def backfill(db, token_map: dict[int, str], days: int = 730) -> int:
    """
    Smart gap-aware daily OHLCV backfill.
    For each token, checks the last stored date and only fetches missing days.
    Falls back to full `days`-day fetch when no data exists at all.
    Returns count of symbols successfully updated.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning('yfinance not installed — skipping OHLCV download. Run: pip install yfinance')
        return 0

    today    = date.today()
    # yfinance end is EXCLUSIVE — use tomorrow so today's close is included
    end_dt   = today + timedelta(days=1)
    full_start = end_dt - timedelta(days=days + 1)

    # Query last stored date for all tokens in one shot
    last_dates = db.get_ohlcv_last_dates(list(token_map.keys()))

    # Decide what to fetch per symbol (skip up-to-date ones)
    work: list[tuple[int, str, date]] = []
    for token, symbol in token_map.items():
        last_str = last_dates.get(token)
        if last_str:
            last_date = date.fromisoformat(last_str)
            if (today - last_date).days == 0:
                log.debug('yfinance %s — already up to date (%s)', symbol, last_str)
                continue
            work.append((token, symbol, last_date + timedelta(days=1)))
        else:
            log.info('yfinance %s — no data, full backfill from %s', symbol, full_start)
            work.append((token, symbol, full_start))

    def _fetch_one(item: tuple[int, str, date]) -> int:
        token, symbol, start_dt = item
        ticker_str = _yf_ticker(symbol)
        try:
            tk   = yf.Ticker(ticker_str)
            hist = tk.history(start=start_dt.isoformat(), end=end_dt.isoformat(),
                              interval='1d', auto_adjust=True)
            if hist.empty:
                log.debug('No yfinance data for %s (%s)', symbol, ticker_str)
                return 0
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
            if not bars:
                return 0
            db.insert_ohlcv_1d_batch(bars)
            real_dates = {b['date'] for b in bars}
            purged = db.purge_nontrading_ohlcv_1d(token, bars[0]['date'], real_dates)
            if purged:
                log.debug('yfinance %s — purged %d synthetic holiday bars', symbol, purged)
            log.info('yfinance %s (%s) — stored %d daily bars (latest: %s)',
                     symbol, ticker_str, len(bars), bars[-1]['date'])
            return 1
        except Exception:
            log.warning('yfinance fetch failed for %s (%s)', symbol, ticker_str)
            return 0

    if not work:
        return 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS, thread_name_prefix='yf-daily') as pool:
        return sum(pool.map(_fetch_one, work))


def backfill_history(db, token_map: dict[int, str], days: int = 3650) -> int:
    """
    Deep-history backfill (backdated data for HMM training + backtests).
    The regular backfill() only fills FORWARD from each symbol's last stored
    bar — symbols never grow history backward. This pass checks each token's
    EARLIEST stored date and fetches the missing [target_start, first_date)
    window. Gap-aware and idempotent: once a symbol reaches the target depth
    (or yfinance has nothing older) subsequent runs are no-ops.
    Returns count of symbols that gained older bars.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning('yfinance not installed — skipping deep-history backfill')
        return 0

    target_start = date.today() - timedelta(days=days)
    first_dates = db.get_ohlcv_first_dates(list(token_map.keys()))

    work: list[tuple[int, str, date]] = []
    for token, symbol in token_map.items():
        first_str = first_dates.get(token)
        if not first_str:
            continue   # no data at all — the regular backfill() owns that case
        first_date = date.fromisoformat(first_str)
        # 7-day slack: yfinance listings rarely start exactly at the target
        if first_date <= target_start + timedelta(days=7):
            continue
        work.append((token, symbol, first_date))

    def _fetch_one(item: tuple[int, str, date]) -> int:
        token, symbol, first_date = item
        ticker_str = _yf_ticker(symbol)
        try:
            tk   = yf.Ticker(ticker_str)
            hist = tk.history(start=target_start.isoformat(), end=first_date.isoformat(),
                              interval='1d', auto_adjust=True)
            if hist.empty:
                return 0
            bars = [{
                'date':             str(idx.date()),
                'instrument_token': token,
                'open':             float(row['Open']),
                'high':             float(row['High']),
                'low':              float(row['Low']),
                'close':            float(row['Close']),
                'volume':           int(row['Volume']),
            } for idx, row in hist.iterrows()]
            db.insert_ohlcv_1d_batch(bars)
            log.info('yfinance history %s (%s) — %d backdated bars (%s → %s)',
                     symbol, ticker_str, len(bars), bars[0]['date'], bars[-1]['date'])
            return 1
        except Exception:
            log.warning('yfinance history fetch failed for %s (%s)', symbol, ticker_str)
            return 0

    if not work:
        return 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS, thread_name_prefix='yf-hist') as pool:
        return sum(pool.map(_fetch_one, work))


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

    # Skip index symbols that don't have intraday data on yfinance
    SKIP_YF = {'^INDIAVIX'}

    def _fetch_one(item: tuple[int, str]) -> int:
        token, symbol = item
        ticker_str = _yf_ticker(symbol)
        if ticker_str in SKIP_YF:
            return 0
        try:
            tk = yf.Ticker(ticker_str)
            hist = tk.history(period=period, interval=interval, auto_adjust=True)
            if hist.empty:
                log.debug('No intraday data for %s (%s)', symbol, ticker_str)
                return 0
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
                return 1
            return 0
        except Exception as exc:
            log.debug('intraday backfill failed %s (%s): %s', symbol, ticker_str, exc)
            return 0

    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS, thread_name_prefix='yf-intra') as pool:
        return sum(pool.map(_fetch_one, token_map.items()))
