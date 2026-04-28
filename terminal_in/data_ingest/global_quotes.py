"""
Global market quotes — indices, FX (vs INR), and commodities via yfinance.
Cached for 5 minutes. Called on-demand from the market API endpoint.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

# (display_label, yfinance_ticker, category)
_SYMBOLS = [
    # Global indices
    ('DOW',      '^DJI',     'global'),
    ('S&P 500',  '^GSPC',    'global'),
    ('NASDAQ',   '^IXIC',    'global'),
    ('FTSE 100', '^FTSE',    'global'),
    ('NIKKEI',   '^N225',    'global'),
    ('HANG SENG','^HSI',     'global'),
    ('DAX',      '^GDAXI',   'global'),
    # FX vs INR
    ('USD/INR',  'USDINR=X', 'fx'),
    ('EUR/INR',  'EURINR=X', 'fx'),
    ('GBP/INR',  'GBPINR=X', 'fx'),
    ('JPY/INR',  'JPYINR=X', 'fx'),
    ('AUD/INR',  'AUDINR=X', 'fx'),
    # Commodities
    ('GOLD',     'GC=F',     'commod'),
    ('SILVER',   'SI=F',     'commod'),
    ('CRUDE WTI','CL=F',     'commod'),
    ('NAT GAS',  'NG=F',     'commod'),
    ('COPPER',   'HG=F',     'commod'),
    # Risk
    ('US VIX',   '^VIX',     'risk'),
    ('INDIA VIX','^INDIAVIX','risk'),
    ('NIFTY BETA','NIFTYBEES.NS', 'risk'),  # ETF as beta proxy
    # BSE (only ^BSESN is reliably available on Yahoo Finance)
    ('SENSEX',   '^BSESN',   'bse'),
]

_cache_all: list = []
_last_fetch: float = 0
_lock = threading.Lock()
CACHE_TTL = 300  # 5 minutes


def _fetch_one(row: tuple) -> dict | None:
    label, sym, cat = row
    try:
        import yfinance as yf
        ticker = yf.Ticker(sym)
        hist = ticker.history(period='5d', interval='1d', auto_adjust=True)
        if hist.empty:
            return None
        closes = hist['Close'].dropna()
        if len(closes) < 1:
            return None
        price = float(closes.iloc[-1])
        prev  = float(closes.iloc[-2]) if len(closes) >= 2 else price
        chg   = (price - prev) / prev * 100 if prev else 0.0
        return {
            'label':    label,
            'symbol':   sym,
            'category': cat,
            'price':    round(price, 4),
            'change':   round(chg, 2),
            'updated':  int(time.time()),
        }
    except Exception as exc:
        log.debug('global_quotes: %s failed — %s', sym, exc)
        return None


def get_quotes(category: str | None = None) -> list[dict]:
    """Return cached global quotes, refreshing if stale."""
    global _cache_all, _last_fetch

    with _lock:
        if time.time() - _last_fetch < CACHE_TTL and _cache_all:
            data = _cache_all
        else:
            data = None

    if data is None:
        try:
            results = []
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(_fetch_one, row): row for row in _SYMBOLS}
                for fut in as_completed(futures, timeout=20):
                    r = fut.result()
                    if r:
                        results.append(r)
            # Restore original order
            order = {sym: i for i, (_, sym, _) in enumerate(_SYMBOLS)}
            results.sort(key=lambda r: order.get(r['symbol'], 99))
            with _lock:
                _cache_all = results
                _last_fetch = time.time()
            data = results
        except Exception:
            log.exception('global_quotes batch fetch failed')
            with _lock:
                data = _cache_all  # return stale cache on failure

    if category:
        return [r for r in data if r.get('category') == category]
    return data
