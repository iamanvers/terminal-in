"""
PaperTickAggregator — aggregates paper-mode ticks into 1-minute OHLCV bars.

Subscribes to 'ticks.*' on the EventBus. On each tick:
  - Updates the current in-progress 1m bar in memory.
  - When the minute rolls over, flushes the completed bar to ohlcv_1m.
  - Upserts the current partial bar every tick so the chart gets live updates.
"""

import logging
import time
from threading import Lock

from terminal_in.bus import bus

log = logging.getLogger(__name__)


class PaperTickAggregator:
    def __init__(self, db):
        self._db = db
        self._lock = Lock()
        # token → current partial bar dict
        self._bars: dict[int, dict] = {}
        bus.subscribe('ticks.*', self._on_tick)
        log.info('PaperTickAggregator started')

    @staticmethod
    def _is_market_open() -> bool:
        from datetime import datetime, timezone, timedelta
        t = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        if t.weekday() >= 5:
            return False
        m = t.hour * 60 + t.minute
        return 9 * 60 + 15 <= m <= 15 * 60 + 30

    def _on_tick(self, payload: dict):
        if not self._is_market_open():
            return  # never write bars outside NSE market hours
        token = payload.get('instrument_token') or payload.get('token')
        price = payload.get('last_price')
        if token is None or price is None:
            return
        price = float(price)

        # Current 1-minute bucket (seconds, floor to minute boundary)
        now_s = time.time()
        bucket_s = int(now_s) - (int(now_s) % 60)
        bucket_ms = bucket_s * 1000

        with self._lock:
            existing = self._bars.get(token)

            if existing is None or existing['bucket_ms'] != bucket_ms:
                # Minute rolled over — flush the completed bar, start fresh
                if existing is not None and existing['bucket_ms'] != bucket_ms:
                    self._flush(existing)
                # Start a new bar
                self._bars[token] = {
                    'bucket_ms':       bucket_ms,
                    'instrument_token': token,
                    'open':  price,
                    'high':  price,
                    'low':   price,
                    'close': price,
                    'volume': int(payload.get('volume') or 0),
                }
            else:
                # Update current bar
                bar = existing
                bar['high']  = max(bar['high'], price)
                bar['low']   = min(bar['low'],  price)
                bar['close'] = price
                bar['volume'] += int(payload.get('volume') or 0)

            # Upsert partial bar for live chart updates
            bar = self._bars[token]
            self._upsert(bar)

    def _flush(self, bar: dict):
        self._upsert(bar)

    def _upsert(self, bar: dict):
        try:
            self._db.insert_ohlcv_1m_batch([{
                'bucket_time':     bar['bucket_ms'],
                'instrument_token': bar['instrument_token'],
                'open':   bar['open'],
                'high':   bar['high'],
                'low':    bar['low'],
                'close':  bar['close'],
                'volume': bar['volume'],
            }])
        except Exception:
            log.debug('PaperTickAggregator: failed to upsert bar for token=%d', bar['instrument_token'])
