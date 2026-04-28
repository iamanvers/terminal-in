"""
S5 — Pullback to EMA20 (daily)
Entry: uptrend (price > EMA50) + pullback to EMA20 + RSI 40-58.
Valid regimes: strong_bull, bull.
Scans all equity instruments available in context — no hardcoded tickers.
"""

import logging
from typing import Optional

import numpy as np

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

_INDEX_NAMES = frozenset({
    'NIFTY 50', 'NIFTY BANK', 'BANKNIFTY', 'NIFTY FIN SERVICE', 'FINNIFTY',
    'INDIA VIX', 'NIFTYBEES',
})

EMA_PROXIMITY_PCT = 0.02
RSI_LO            = 40
RSI_HI            = 58
ATR_MULT_SL       = 1.5
ATR_MULT_TARGET   = 3.0


class S5MidPullback(Strategy):
    id = 'S5'
    timeframe = '1d'
    valid_regimes = ['strong_bull', 'bull']
    symbol = 'HDFCBANK'

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        equity_symbols = [s for s in ctx.instruments if s not in _INDEX_NAMES]
        if not equity_symbols:
            return None

        best = None
        best_confidence = 0.0

        for sym in equity_symbols:
            price = ctx.last_price(sym)
            if price <= 0:
                continue

            ema20 = ctx.indicator(sym, 'ema_20', '1d')
            ema50 = ctx.indicator(sym, 'ema_50', '1d')
            rsi   = ctx.indicator(sym, 'rsi_14', '1d')

            if len(ema20) == 0 or np.isnan(ema20[-1]): continue
            if len(ema50) == 0 or np.isnan(ema50[-1]): continue
            if len(rsi)   == 0 or np.isnan(rsi[-1]):   continue

            ema20_val = float(ema20[-1])
            ema50_val = float(ema50[-1])
            rsi_val   = float(rsi[-1])

            if price <= ema50_val: continue
            if abs(price - ema20_val) / ema20_val > EMA_PROXIMITY_PCT: continue
            if not (RSI_LO <= rsi_val <= RSI_HI): continue

            atr = ctx.indicator(sym, 'atr_14', '1d')
            atr_val = float(atr[-1]) if len(atr) > 0 and not np.isnan(atr[-1]) else price * 0.015

            proximity  = 1.0 - abs(price - ema20_val) / ema20_val / EMA_PROXIMITY_PCT
            confidence = 0.55 + proximity * 0.15

            if confidence > best_confidence:
                best_confidence = confidence
                token = ctx.instruments.get(sym, 0)
                qty   = int((ctx.size_multiplier * 1_000_000 * 0.01) / max(atr_val, 0.01))
                best  = Signal(
                    strategy_id=self.id,
                    instrument_id=token,
                    side='BUY',
                    quantity=max(qty, 1),
                    order_type='LIMIT',
                    limit_price=price,
                    stop_loss=price - ATR_MULT_SL * atr_val,
                    target=price + ATR_MULT_TARGET * atr_val,
                    confidence=confidence,
                    regime=ctx.regime,
                    metadata={'symbol': sym, 'ema20': round(ema20_val, 2), 'ema50': round(ema50_val, 2), 'rsi': round(rsi_val, 1)},
                )

        return best
