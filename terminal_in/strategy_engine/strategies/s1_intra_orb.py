"""
S1 — Intraday Opening Range Breakout (5m)
Entry: price breaks above/below first 30-min high/low after open.
Valid regimes: strong_bull, bull, sideways, bear, strong_bear (all except high_vol).
Exit: EOD or stop hit.
"""

import logging
from datetime import time
from typing import Optional

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

SYMBOL = 'NIFTY 50'
ORB_MINUTES = 30
ATR_MULT_SL = 1.5
ATR_MULT_TARGET = 3.0


class S1IntraORB(Strategy):
    id = 'S1'
    timeframe = '5m'
    valid_regimes = ['strong_bull', 'bull', 'sideways', 'bear', 'strong_bear']
    symbol = SYMBOL

    def __init__(self):
        self._orb_high: Optional[float] = None
        self._orb_low: Optional[float] = None
        self._orb_date: Optional[object] = None
        self._signal_given: bool = False

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime == 'high_vol':
            return None

        now = ctx.now
        market_open = time(9, 15)
        orb_end = time(9, 45)

        if now.time() < market_open:
            return None

        # Reset on new day
        today = now.date()
        if self._orb_date != today:
            self._orb_high = None
            self._orb_low = None
            self._orb_date = today
            self._signal_given = False

        df = ctx.ohlcv(SYMBOL, '5m')
        if df.empty:
            return None

        if now.time() <= orb_end:
            today_bars = df[df.index.date == today] if hasattr(df.index, 'date') else df
            if len(today_bars) > 0:
                self._orb_high = float(today_bars['high'].max())
                self._orb_low = float(today_bars['low'].min())
            return None

        if self._orb_high is None or self._orb_low is None:
            return None
        if self._signal_given:
            return None

        price = ctx.last_price(SYMBOL)
        if price <= 0:
            return None

        token = ctx.instruments.get(SYMBOL, 0)
        atr = ctx.indicator(SYMBOL, 'atr_14', '5m')
        atr_val = float(atr[-1]) if len(atr) > 0 and atr[-1] == atr[-1] else (self._orb_high - self._orb_low)

        if price > self._orb_high * 1.001:
            self._signal_given = True
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='BUY',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='SL-M',
                limit_price=None,
                stop_loss=price - ATR_MULT_SL * atr_val,
                target=price + ATR_MULT_TARGET * atr_val,
                confidence=0.6,
                regime=ctx.regime,
                metadata={'orb_high': self._orb_high, 'orb_low': self._orb_low},
            )

        if price < self._orb_low * 0.999:
            self._signal_given = True
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='SELL',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='SL-M',
                limit_price=None,
                stop_loss=price + ATR_MULT_SL * atr_val,
                target=price - ATR_MULT_TARGET * atr_val,
                confidence=0.6,
                regime=ctx.regime,
                metadata={'orb_high': self._orb_high, 'orb_low': self._orb_low},
            )

        return None
