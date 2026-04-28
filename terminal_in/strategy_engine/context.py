"""
MarketContext — snapshot of market state passed to every strategy on each evaluation.
Provides indicators, prices, regime, and event mask without strategies touching the DB directly.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class MarketContext:
    now: datetime
    regime: str
    regime_confidence: float
    india_vix: float
    event_mask: float               # 0.0 = blackout, 1.0 = fully open
    size_multiplier: float          # from regime classifier
    instruments: dict[str, int]     # symbol → token

    # Internal data store (token → DataFrame of OHLCV bars)
    _ohlcv: dict[int, dict[str, pd.DataFrame]] = field(default_factory=dict, repr=False)
    _last_prices: dict[int, float] = field(default_factory=dict, repr=False)

    def last_price(self, symbol: str) -> float:
        token = self.instruments.get(symbol)
        if token is None:
            return 0.0
        return self._last_prices.get(token, 0.0)

    def ohlcv(self, symbol: str, timeframe: str = '1d') -> pd.DataFrame:
        token = self.instruments.get(symbol)
        if token is None:
            return pd.DataFrame()
        return self._ohlcv.get(token, {}).get(timeframe, pd.DataFrame())

    def indicator(self, symbol: str, name: str, timeframe: str = '1d') -> np.ndarray:
        df = self.ohlcv(symbol, timeframe)
        if df.empty or len(df) < 2:
            return np.array([])

        close = df['close'].values.astype(float)

        if name.startswith('rsi_'):
            period = int(name.split('_')[1])
            return _rsi(close, period)

        if name.startswith('atr_'):
            period = int(name.split('_')[1])
            high = df['high'].values.astype(float)
            low = df['low'].values.astype(float)
            return _atr(high, low, close, period)

        if name.startswith('ema_'):
            period = int(name.split('_')[1])
            return _ema(close, period)

        if name.startswith('sma_'):
            period = int(name.split('_')[1])
            return _sma(close, period)

        if name == 'volume':
            return df['volume'].values.astype(float)

        if name == 'high_52w':
            return np.array([df['high'].tail(252).max()])

        if name == 'low_52w':
            return np.array([df['low'].tail(252).min()])

        log.warning('Unknown indicator: %s', name)
        return np.array([])


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    if len(close) < period + 1:
        return np.full(len(close), np.nan)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    rsi = np.full(len(close), np.nan)
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else np.inf
        rsi[i + 1] = 100 - 100 / (1 + rs)
    return rsi


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         period: int = 14) -> np.ndarray:
    n = len(close)
    if n < 2:
        return np.zeros(n)
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(abs(high[1:] - close[:-1]),
                    abs(low[1:] - close[:-1])))
    atr = np.full(n, np.nan)
    if len(tr) >= period:
        atr[period] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr[i + 1] = (atr[i] * (period - 1) + tr[i]) / period
    return atr


def _ema(close: np.ndarray, period: int) -> np.ndarray:
    if len(close) < period:
        return np.full(len(close), np.nan)
    k = 2 / (period + 1)
    ema = np.full(len(close), np.nan)
    ema[period - 1] = np.mean(close[:period])
    for i in range(period, len(close)):
        ema[i] = close[i] * k + ema[i - 1] * (1 - k)
    return ema


def _sma(close: np.ndarray, period: int) -> np.ndarray:
    if len(close) < period:
        return np.full(len(close), np.nan)
    sma = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        sma[i] = np.mean(close[i - period + 1:i + 1])
    return sma
