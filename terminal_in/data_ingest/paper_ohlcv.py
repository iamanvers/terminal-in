"""
Synthetic OHLCV seeder for paper mode.
Generates ~300 daily + 390 1-minute bars per instrument using geometric
Brownian motion so the chart panel has something to display on first run.
Only writes if the DB has no existing OHLCV rows for that token.
"""

import logging
import math
import random
from datetime import date, timedelta, datetime, timezone

log = logging.getLogger(__name__)

# Approximate prices in ₹ for Indian markets (April 2026 ballpark)
_SEED_PRICES: dict[int, float] = {
    256265:  23500.0,   # NIFTY 50
    260105:  51000.0,   # NIFTY BANK / BANKNIFTY
    257801:  23200.0,   # NIFTY FIN SERVICE / FINNIFTY
    264969:     13.5,   # INDIA VIX
    2800641:   240.0,   # NIFTYBEES
    738561:   1290.0,   # RELIANCE
    341249:   1680.0,   # HDFCBANK
    2953217:  3350.0,   # TCS
    408065:   1480.0,   # INFY
    1270529:  1230.0,   # ICICIBANK
    492033:   1900.0,   # KOTAKBANK
    356865:   2260.0,   # HINDUNILVR
    779521:    840.0,   # SBIN
    4267265:  8400.0,   # BAJFINANCE
    1510401:  1170.0,   # AXISBANK
    969473:    600.0,   # WIPRO
}

_DAILY_VOL = 0.011   # ~1.1% daily sigma (reasonable for large-cap India)
_INTRADAY_VOL = 0.0015  # per 1-minute bar


def _gbm_bars_daily(start_price: float, n: int) -> list[tuple]:
    """Return list of (date_str, o, h, l, c, vol)."""
    bars = []
    end = date.today()
    # Work backwards n trading days (rough: skip weekends)
    day = end
    days = []
    while len(days) < n:
        if day.weekday() < 5:  # Mon-Fri
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()

    price = start_price * math.exp(-_DAILY_VOL * math.sqrt(n) * 0.5)  # start slightly below
    for d in days:
        ret = random.gauss(0, _DAILY_VOL)
        o = price
        c = price * math.exp(ret)
        h = max(o, c) * (1 + abs(random.gauss(0, _DAILY_VOL * 0.5)))
        l = min(o, c) * (1 - abs(random.gauss(0, _DAILY_VOL * 0.5)))
        vol = int(abs(random.gauss(5_000_000, 2_000_000)))
        bars.append((d.isoformat(), round(o, 2), round(h, 2), round(l, 2), round(c, 2), vol))
        price = c

    return bars


def _gbm_bars_1m(start_price: float, n: int) -> list[tuple]:
    """Return list of (unix_ms, o, h, l, c, vol) for n 1-minute bars ending now."""
    bars = []
    # End at last market close (15:30 IST = 10:00 UTC)
    now = datetime.now(timezone.utc)
    # Round down to last minute
    last_ts = int(now.timestamp()) - (int(now.timestamp()) % 60)
    price = start_price

    for i in range(n, 0, -1):
        ts_ms = (last_ts - i * 60) * 1000
        ret = random.gauss(0, _INTRADAY_VOL)
        o = price
        c = price * math.exp(ret)
        h = max(o, c) * (1 + abs(random.gauss(0, _INTRADAY_VOL * 0.5)))
        l = min(o, c) * (1 - abs(random.gauss(0, _INTRADAY_VOL * 0.5)))
        vol = int(abs(random.gauss(50_000, 20_000)))
        bars.append((ts_ms, round(o, 2), round(h, 2), round(l, 2), round(c, 2), vol))
        price = c

    return bars


def seed(db, tokens: list[int]) -> None:
    """Seed synthetic OHLCV data for each token if DB is empty."""
    for token in tokens:
        seed_price = _SEED_PRICES.get(token)
        if seed_price is None:
            continue

        # Check if already has data
        df_check = db.get_ohlcv_1d(token, limit=1)
        if not df_check.empty:
            continue

        log.info('Seeding synthetic OHLCV for token=%d (price~%.0f)', token, seed_price)

        daily = _gbm_bars_daily(seed_price, 300)
        db.insert_ohlcv_1d_batch([
            {'date': b[0], 'instrument_token': token,
             'open': b[1], 'high': b[2], 'low': b[3], 'close': b[4], 'volume': b[5]}
            for b in daily
        ])

        intraday = _gbm_bars_1m(seed_price, 390)
        db.insert_ohlcv_1m_batch([
            {'bucket_time': b[0], 'instrument_token': token,
             'open': b[1], 'high': b[2], 'low': b[3], 'close': b[4], 'volume': b[5]}
            for b in intraday
        ])

    log.info('Paper OHLCV seed complete')
