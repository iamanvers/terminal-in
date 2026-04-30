"""
YFLiveFeed — real market price feed using yfinance (15-min delayed).
Replaces the synthetic Gaussian noise paper tick feed.

Behaviour:
  - On startup: seeds prices from OHLCV DB (real historical close).
  - During NSE market hours (09:15–15:30 IST, Mon–Fri): fetches intraday
    1-minute bars via yf.download every POLL_OPEN_S seconds.
  - Outside market hours: emits frozen last-close prices every POLL_CLOSED_S
    seconds so the bus cache stays alive, but prices do not move.
  - change% is always (last_price – prev_close) / prev_close.
  - Falls back to last known DB price if yfinance fails.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from threading import Event

import pandas as pd

from terminal_in.bus import bus
from terminal_in.data_ingest.yf_fetcher import YF_MAP

log = logging.getLogger(__name__)

IST          = timezone(timedelta(hours=5, minutes=30))
POLL_OPEN_S  = 60    # poll interval during market hours
POLL_CLOSED_S = 300  # poll interval outside market hours


def _yf_sym(symbol: str) -> str:
    return YF_MAP.get(symbol, f'{symbol}.NS')


def _is_market_open() -> bool:
    t = datetime.now(IST)
    if t.weekday() >= 5:   # Saturday / Sunday
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 + 15 <= m <= 15 * 60 + 30


class YFLiveFeed:
    """Polls yfinance and emits ticks.{token} on the EventBus."""

    def __init__(self, instruments: dict[str, int], db=None):
        self._instruments = instruments          # symbol → token
        self._db = db
        # Build reverse maps
        self._token_to_sym: dict[int, str]    = {v: k for k, v in instruments.items()}
        self._token_to_yf:  dict[int, str]    = {v: _yf_sym(k) for k, v in instruments.items()}
        # Price cache: token → price
        self._prices:      dict[int, float]   = {}
        self._prev_closes: dict[int, float]   = {}
        self._opens:       dict[int, float]   = {}   # session open
        self._session_date: date | None       = None

    # ── Seed prices from DB so charts / strategies have data immediately ──────

    def _seed_from_db(self):
        if self._db is None:
            return
        for token in self._token_to_sym:
            try:
                df = self._db.get_ohlcv_1d(token=token, limit=2)
                if not df.empty:
                    self._prices[token]      = float(df['close'].iloc[-1])
                    self._prev_closes[token] = float(df['close'].iloc[-2]) if len(df) >= 2 else self._prices[token]
            except Exception:
                pass
        log.info('YFLiveFeed: seeded %d prices from DB', len(self._prices))

    # ── Batch download via yf.download ────────────────────────────────────────

    def _fetch_batch(self, yf_syms: list[str]) -> dict[str, float]:
        """Returns yf_ticker → latest close price."""
        try:
            import yfinance as yf
        except ImportError:
            log.warning('yfinance not installed — cannot fetch live prices')
            return {}

        market_open = _is_market_open()
        period   = '1d'
        interval = '1m' if market_open else '1d'

        try:
            syms_str = ' '.join(yf_syms)
            raw = yf.download(
                tickers=syms_str,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                group_by='ticker',
            )
            if raw.empty:
                return {}
        except Exception as exc:
            log.warning('YFLiveFeed: yf.download failed: %s', exc)
            return {}

        result: dict[str, float] = {}
        # Single ticker: flat columns; multiple: MultiIndex
        if len(yf_syms) == 1:
            sym = yf_syms[0]
            col_close = 'Close' if 'Close' in raw.columns else 'close'
            if col_close in raw.columns and not raw.empty:
                last = raw[col_close].dropna()
                if not last.empty:
                    result[sym] = float(last.iloc[-1])
        else:
            for sym in yf_syms:
                try:
                    sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                    col_close = 'Close' if 'Close' in sub.columns else 'close'
                    last = sub[col_close].dropna()
                    if not last.empty:
                        result[sym] = float(last.iloc[-1])
                except Exception:
                    pass

        return result

    # ── Fetch previous-day close for change% baseline ─────────────────────────

    def _fetch_prev_closes(self, yf_syms: list[str]) -> dict[str, float]:
        try:
            import yfinance as yf
            syms_str = ' '.join(yf_syms)
            raw = yf.download(
                tickers=syms_str,
                period='5d',
                interval='1d',
                progress=False,
                auto_adjust=True,
                group_by='ticker',
            )
            if raw.empty:
                return {}
        except Exception:
            return {}

        result: dict[str, float] = {}
        if len(yf_syms) == 1:
            sym = yf_syms[0]
            col_close = 'Close' if 'Close' in raw.columns else 'close'
            if col_close in raw.columns:
                closes = raw[col_close].dropna()
                if len(closes) >= 2:
                    result[sym] = float(closes.iloc[-2])
        else:
            for sym in yf_syms:
                try:
                    sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                    col_close = 'Close' if 'Close' in sub.columns else 'close'
                    closes = sub[col_close].dropna()
                    if len(closes) >= 2:
                        result[sym] = float(closes.iloc[-2])
                except Exception:
                    pass
        return result

    # ── Publish ───────────────────────────────────────────────────────────────

    def _publish_all(self, market_open: bool):
        today = date.today()
        if today != self._session_date:
            self._opens.clear()
            self._session_date = today

        now_ms = int(time.time() * 1000)
        for token, price in self._prices.items():
            if price <= 0:
                continue
            # session open — locked in on first publish of the day
            if token not in self._opens:
                self._opens[token] = price

            prev = self._prev_closes.get(token, self._opens.get(token, price))
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0

            bus.publish(f'ticks.{token}', {
                'instrument_token': token,
                'last_price':       round(price, 2),
                'change':           change_pct,
                'open':             round(self._opens.get(token, price), 2),
                'market_open':      market_open,
                'timestamp':        now_ms,
            })

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, stop_event: Event):
        log.info('YFLiveFeed starting — %d instruments', len(self._instruments))

        # Seed from DB so strategies have prices immediately on startup
        self._seed_from_db()
        self._publish_all(_is_market_open())

        all_yf_syms = list(self._token_to_yf.values())

        # Fetch previous closes once at startup
        prev = self._fetch_prev_closes(all_yf_syms)
        for token, yf_sym in self._token_to_yf.items():
            if yf_sym in prev:
                self._prev_closes[token] = prev[yf_sym]

        while not stop_event.is_set():
            market_open = _is_market_open()

            prices = self._fetch_batch(all_yf_syms)
            if prices:
                for token, yf_sym in self._token_to_yf.items():
                    if yf_sym in prices and prices[yf_sym] > 0:
                        self._prices[token] = prices[yf_sym]
                log.info('YFLiveFeed: updated %d/%d prices (market_open=%s)',
                         len(prices), len(all_yf_syms), market_open)
            else:
                log.debug('YFLiveFeed: no new prices fetched — using cached')

            self._publish_all(market_open)

            interval = POLL_OPEN_S if market_open else POLL_CLOSED_S
            stop_event.wait(timeout=interval)

        log.info('YFLiveFeed stopped')
