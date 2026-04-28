"""
S9 — Hawkes Process Continuation (intraday, 1m)
Models trade arrival intensity using a Hawkes process.
High intensity + direction persistence → continuation trade.
Valid regimes: strong_bull, bull, bear, strong_bear.
"""

import logging
from typing import Optional

import numpy as np

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

SYMBOL = 'NIFTY 50'
DECAY = 0.1              # exponential decay parameter
INTENSITY_THRESH = 3.0   # standard deviations above baseline
MIN_BARS = 30
ATR_MULT_SL = 1.0
ATR_MULT_TARGET = 2.0


def _hawkes_intensity(times: np.ndarray, decay: float) -> np.ndarray:
    """Compute recursive Hawkes intensity at each event time."""
    n = len(times)
    intensity = np.zeros(n)
    for i in range(1, n):
        dt = times[i] - times[i - 1]
        intensity[i] = (intensity[i - 1] + 1.0) * np.exp(-decay * dt)
    return intensity


class S9HawkesCont(Strategy):
    id = 'S9'
    timeframe = '1m'
    valid_regimes = ['strong_bull', 'bull', 'bear', 'strong_bear']
    symbol = SYMBOL

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        df = ctx.ohlcv(SYMBOL, '1m')
        if df.empty or len(df) < MIN_BARS:
            return None

        close = df['close'].values.astype(float)[-MIN_BARS:]
        # Derive event times as bar indices where |return| > 0
        returns = np.diff(close)
        event_idx = np.where(np.abs(returns) > 0)[0].astype(float)
        if len(event_idx) < 10:
            return None

        intensity = _hawkes_intensity(event_idx, DECAY)
        baseline = float(np.mean(intensity[:-5]))
        current = float(intensity[-1])
        std_i = float(np.std(intensity[:-5]))
        if std_i < 1e-8:
            return None

        z = (current - baseline) / std_i
        if z < INTENSITY_THRESH:
            return None

        # Direction: net return over last 5 bars
        direction = np.sign(close[-1] - close[-6]) if len(close) >= 6 else 0
        if direction == 0:
            return None

        price = ctx.last_price(SYMBOL)
        if price <= 0:
            return None

        token = ctx.instruments.get(SYMBOL, 0)
        atr = ctx.indicator(SYMBOL, 'atr_14', '1m')
        atr_val = float(atr[-1]) if len(atr) > 0 and atr[-1] == atr[-1] else price * 0.002

        side = 'BUY' if direction > 0 else 'SELL'
        sign = 1 if side == 'BUY' else -1
        confidence = min(0.5 + z * 0.04, 0.80)

        return Signal(
            strategy_id=self.id,
            instrument_id=token,
            side=side,
            quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
            order_type='MARKET',
            limit_price=None,
            stop_loss=price - sign * ATR_MULT_SL * atr_val,
            target=price + sign * ATR_MULT_TARGET * atr_val,
            confidence=confidence,
            regime=ctx.regime,
            metadata={'hawkes_z': round(z, 3), 'intensity': round(current, 4)},
        )
