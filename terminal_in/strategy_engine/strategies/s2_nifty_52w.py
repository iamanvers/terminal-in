"""
S2 — Nifty 52-week Breakout (daily)
Entry: close > 52-week high with above-average volume.
Valid regimes: strong_bull, bull.
"""

import logging
from typing import Optional

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

SYMBOL = 'NIFTY 50'
VOLUME_MULT = 1.5       # require 1.5x average volume
ATR_MULT_SL = 2.0
ATR_MULT_TARGET = 4.0


class S2Nifty52W(Strategy):
    id = 'S2'
    timeframe = '1d'
    valid_regimes = ['strong_bull', 'bull']
    symbol = SYMBOL

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        high_52w = ctx.indicator(SYMBOL, 'high_52w', '1d')
        if len(high_52w) == 0:
            return None

        price = ctx.last_price(SYMBOL)
        if price <= 0:
            return None

        if price <= high_52w[0]:
            return None

        # Volume confirmation
        vol = ctx.indicator(SYMBOL, 'volume', '1d')
        if len(vol) >= 20:
            avg_vol = float(vol[-20:].mean())
            if vol[-1] < avg_vol * VOLUME_MULT:
                return None

        token = ctx.instruments.get(SYMBOL, 0)
        atr = ctx.indicator(SYMBOL, 'atr_14', '1d')
        atr_val = float(atr[-1]) if len(atr) > 0 and atr[-1] == atr[-1] else price * 0.015

        return Signal(
            strategy_id=self.id,
            instrument_id=token,
            side='BUY',
            quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
            order_type='MARKET',
            limit_price=None,
            stop_loss=price - ATR_MULT_SL * atr_val,
            target=price + ATR_MULT_TARGET * atr_val,
            confidence=0.65,
            regime=ctx.regime,
            metadata={'high_52w': float(high_52w[0])},
        )
