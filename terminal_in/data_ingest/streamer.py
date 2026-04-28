"""
KiteStreamer — subscribes to Kite WebSocket, publishes ticks to EventBus,
batch-inserts into SQLite every 1s.
"""

import logging
import time
from threading import Event

from terminal_in.bus import bus
from terminal_in.db import DB

log = logging.getLogger(__name__)


class KiteStreamer:
    def __init__(self, api_key: str, access_token: str,
                 instrument_tokens: list[int], db: DB):
        from kiteconnect import KiteTicker
        self.kt = KiteTicker(api_key, access_token)
        self.tokens = instrument_tokens
        self.db = db
        self._buffer: list[dict] = []
        self._last_flush = time.time()
        self._stop = Event()

        self.kt.on_connect = self._on_connect
        self.kt.on_ticks = self._on_ticks
        self.kt.on_close = self._on_close
        self.kt.on_error = self._on_error

    def _on_connect(self, ws, response):
        log.info('Kite WebSocket connected. Subscribing %d instruments.', len(self.tokens))
        ws.subscribe(self.tokens)
        ws.set_mode(ws.MODE_FULL, self.tokens)

    def _on_ticks(self, ws, ticks):
        for t in ticks:
            if 'timestamp' in t and t['timestamp']:
                t['time_ms'] = int(t['timestamp'].timestamp() * 1000)
            else:
                t['time_ms'] = int(time.time() * 1000)

            bus.publish(f"ticks.{t['instrument_token']}", t)
            self._buffer.append(t)

        now = time.time()
        if now - self._last_flush > 1.0 or len(self._buffer) > 500:
            self._flush()

    def _flush(self):
        if not self._buffer:
            return
        try:
            self.db.insert_ticks_batch(self._buffer)
        except Exception:
            log.exception('Tick batch insert failed')
        self._buffer.clear()
        self._last_flush = time.time()

    def _on_close(self, ws, code, reason):
        log.warning('Kite WebSocket closed: %s %s. Will auto-reconnect.', code, reason)

    def _on_error(self, ws, code, reason):
        log.error('Kite WebSocket error: %s %s', code, reason)

    def run(self):
        self.kt.connect(threaded=True)
        while not self._stop.is_set():
            time.sleep(1)
            if self._buffer:
                self._flush()

    def stop(self):
        self._stop.set()
        try:
            self.kt.stop()
        except Exception:
            pass
