"""
NSE Bhavcopy downloader — daily EOD OHLCV for all NSE equities.
Used for historical backfill and nightly data updates.
"""

import io
import logging
import time
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

from terminal_in.db import DB

log = logging.getLogger(__name__)

NSE_BHAV_URL = (
    'https://archives.nseindia.com/content/historical/EQUITIES/'
    '{year}/{month}/cm{date}bhav.csv.zip'
)
HEADERS = {'User-Agent': 'Mozilla/5.0'}
REQUEST_DELAY = 1.5  # seconds between requests to avoid rate limiting


def download_bhavcopy(dt: date) -> pd.DataFrame | None:
    url = NSE_BHAV_URL.format(
        year=dt.year,
        month=dt.strftime('%b').upper(),
        date=dt.strftime('%d%b%Y').upper(),
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        df.columns = df.columns.str.strip()
        df['DATE'] = dt.isoformat()
        return df
    except Exception:
        log.exception('Failed to download bhavcopy for %s', dt)
        return None


def backfill(db: DB, start: date, end: date,
             token_map: dict[str, int] | None = None) -> int:
    """
    Downloads and stores daily OHLCV from start to end (inclusive).
    token_map: symbol → instrument_token. If None, skips DB insert.
    Returns count of days processed.
    """
    count = 0
    d = start
    while d <= end:
        if d.weekday() >= 5:  # skip weekends
            d += timedelta(days=1)
            continue

        df = download_bhavcopy(d)
        if df is not None and token_map:
            bars = []
            for _, row in df.iterrows():
                symbol = str(row.get('SYMBOL', '')).strip()
                token = token_map.get(symbol)
                if token is None:
                    continue
                bars.append({
                    'date': row['DATE'],
                    'instrument_token': token,
                    'open': float(row['OPEN']),
                    'high': float(row['HIGH']),
                    'low': float(row['LOW']),
                    'close': float(row['CLOSE']),
                    'volume': int(row['TOTTRDQTY']),
                    'delivery_pct': None,
                })
            if bars:
                db.insert_ohlcv_1d_batch(bars)
                log.info('Bhavcopy %s — stored %d bars', d, len(bars))
            count += 1

        time.sleep(REQUEST_DELAY)
        d += timedelta(days=1)

    return count
