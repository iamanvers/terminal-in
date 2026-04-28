"""
S8 — VIX Asymmetry (daily)
Trades volatility regime transitions.
High VIX spike → buy Nifty (panic reversal), Low VIX collapse → buy protective puts equivalent.
Valid regimes: high_vol, bear, strong_bear.
"""

import logging
from typing import Optional

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

SYMBOL = 'NIFTY 50'
VIX_HIGH_THRESHOLD = 25.0
VIX_LOW_THRESHOLD = 12.0
ATR_MULT_SL = 2.0
ATR_MULT_TARGET = 4.0


class S8VIXAsymmetry(Strategy):
    id = 'S8'
    timeframe = '1d'
    valid_regimes = ['high_vol', 'bear', 'strong_bear']
    symbol = SYMBOL

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        vix = ctx.india_vix
        price = ctx.last_price(SYMBOL)
        if price <= 0:
            return None

        token = ctx.instruments.get(SYMBOL, 0)
        atr = ctx.indicator(SYMBOL, 'atr_14', '1d')
        atr_val = float(atr[-1]) if len(atr) > 0 and atr[-1] == atr[-1] else price * 0.015

        # VIX spike → market likely to rebound (buy the fear)
        if vix > VIX_HIGH_THRESHOLD and ctx.regime == 'high_vol':
            confidence = min(0.5 + (vix - VIX_HIGH_THRESHOLD) / 10.0 * 0.2, 0.75)
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='BUY',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='MARKET',
                limit_price=None,
                stop_loss=price - ATR_MULT_SL * atr_val,
                target=price + ATR_MULT_TARGET * atr_val,
                confidence=confidence,
                regime=ctx.regime,
                metadata={'india_vix': vix, 'signal': 'vix_spike_reversal'},
            )

        # VIX very low in bear regime → complacency, prepare for downmove (short)
        if vix < VIX_LOW_THRESHOLD and ctx.regime in ('bear', 'strong_bear'):
            confidence = min(0.5 + (VIX_LOW_THRESHOLD - vix) / 5.0 * 0.15, 0.70)
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='SELL',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='MARKET',
                limit_price=None,
                stop_loss=price + ATR_MULT_SL * atr_val,
                target=price - ATR_MULT_TARGET * atr_val,
                confidence=confidence,
                regime=ctx.regime,
                metadata={'india_vix': vix, 'signal': 'vix_complacency_short'},
            )

        return None
