"""
S3 — Breakout scan (daily)
Entry: close > 20-day high + EMA50 slope positive + volume surge.
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

BREAKOUT_PERIOD = 20
ATR_MULT_SL     = 1.5
ATR_MULT_TARGET = 3.0
VOLUME_MULT     = 1.3


class S3MidcapBreakout(Strategy):
    id = 'S3'
    timeframe = '1d'
    valid_regimes = ['strong_bull', 'bull']
    symbol = 'NIFTY 50'  # default; iterates all equities at eval time

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        if ctx.regime not in self.valid_regimes:
            return None

        equity_symbols = [s for s in ctx.instruments if s not in _INDEX_NAMES]
        if not equity_symbols:
            return None

        best: Optional[Signal] = None
        best_score = 0.0

        for sym in equity_symbols:
            df = ctx.ohlcv(sym, '1d')
            if df.empty or len(df) < BREAKOUT_PERIOD + 2:
                continue

            close = df['close'].values.astype(float)
            price = ctx.last_price(sym)
            if price <= 0:
                continue

            high_20 = float(np.max(close[-(BREAKOUT_PERIOD + 1):-1]))
            if price <= high_20:
                continue

            ema50 = ctx.indicator(sym, 'ema_50', '1d')
            if len(ema50) < 3 or np.isnan(ema50[-1]) or np.isnan(ema50[-2]):
                continue
            if ema50[-1] <= ema50[-2]:
                continue

            vol = ctx.indicator(sym, 'volume', '1d')
            if len(vol) >= 20:
                avg_vol = float(vol[-20:].mean())
                if avg_vol > 0 and vol[-1] < avg_vol * VOLUME_MULT:
                    continue

            atr = ctx.indicator(sym, 'atr_14', '1d')
            atr_val = float(atr[-1]) if len(atr) > 0 and not np.isnan(atr[-1]) else price * 0.015

            breakout_pct = (price - high_20) / high_20
            vol_ratio = float(vol[-1]) / float(vol[-20:].mean()) if len(vol) >= 20 and vol[-20:].mean() > 0 else 1.0
            score = breakout_pct * vol_ratio

            if score > best_score:
                best_score = score
                token = ctx.instruments.get(sym, 0)
                qty = int((ctx.size_multiplier * 1_000_000 * 0.01) / max(atr_val, 0.01))
                best = Signal(
                    strategy_id=self.id,
                    instrument_id=token,
                    side='BUY',
                    quantity=max(qty, 1),
                    order_type='MARKET',
                    limit_price=None,
                    stop_loss=price - ATR_MULT_SL * atr_val,
                    target=price + ATR_MULT_TARGET * atr_val,
                    confidence=min(0.5 + score * 10, 0.9),
                    regime=ctx.regime,
                    metadata={'symbol': sym, 'high_20': high_20, 'breakout_pct': round(breakout_pct, 4)},
                )

        return best
