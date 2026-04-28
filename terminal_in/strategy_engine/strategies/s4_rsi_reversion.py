"""
S4 — RSI Mean Reversion (daily)
Entry: RSI-14 < 35 (oversold) in bull regime; RSI-14 > 65 (overbought) for shorts in bear.
Valid regimes: bull, sideways, bear.
"""

import logging
from typing import Optional

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

SYMBOL = 'NIFTY 50'
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
ATR_MULT_SL = 1.5
ATR_MULT_TARGET = 2.5


class S4RSIReversion(Strategy):
    id = 'S4'
    timeframe = '1d'
    valid_regimes = ['bull', 'sideways', 'bear']
    symbol = SYMBOL

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        rsi = ctx.indicator(SYMBOL, 'rsi_14', '1d')
        if len(rsi) == 0 or rsi[-1] != rsi[-1]:
            return None

        rsi_val = float(rsi[-1])
        price = ctx.last_price(SYMBOL)
        if price <= 0:
            return None

        token = ctx.instruments.get(SYMBOL, 0)
        atr = ctx.indicator(SYMBOL, 'atr_14', '1d')
        atr_val = float(atr[-1]) if len(atr) > 0 and atr[-1] == atr[-1] else price * 0.015

        if rsi_val < RSI_OVERSOLD and ctx.regime in ('bull', 'sideways'):
            confidence = min(0.45 + (RSI_OVERSOLD - rsi_val) / RSI_OVERSOLD * 0.4, 0.85)
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='BUY',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='LIMIT',
                limit_price=price,
                stop_loss=price - ATR_MULT_SL * atr_val,
                target=price + ATR_MULT_TARGET * atr_val,
                confidence=confidence,
                regime=ctx.regime,
                metadata={'rsi': rsi_val},
            )

        if rsi_val > RSI_OVERBOUGHT and ctx.regime == 'bear':
            confidence = min(0.45 + (rsi_val - RSI_OVERBOUGHT) / (100 - RSI_OVERBOUGHT) * 0.4, 0.85)
            return Signal(
                strategy_id=self.id,
                instrument_id=token,
                side='SELL',
                quantity=self.position_size(ctx.size_multiplier * 1_000_000, ctx),
                order_type='LIMIT',
                limit_price=price,
                stop_loss=price + ATR_MULT_SL * atr_val,
                target=price - ATR_MULT_TARGET * atr_val,
                confidence=confidence,
                regime=ctx.regime,
                metadata={'rsi': rsi_val},
            )

        return None
