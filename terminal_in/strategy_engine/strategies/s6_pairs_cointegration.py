"""
S6 — Pairs Cointegration (daily)
Spread mean-reversion between correlated pairs.
Pairs are built dynamically from available equity instruments — no hardcoded tickers.
Valid regimes: all (market-neutral).
"""

import logging
from itertools import combinations
from typing import Optional

import numpy as np

from terminal_in.strategy_engine.context import MarketContext
from terminal_in.strategy_engine.strategies.base import Signal, Strategy

log = logging.getLogger(__name__)

_INDEX_NAMES = frozenset({
    'NIFTY 50', 'NIFTY BANK', 'BANKNIFTY', 'NIFTY FIN SERVICE', 'FINNIFTY',
    'INDIA VIX', 'NIFTYBEES',
})

ZSCORE_ENTRY = 2.0
ZSCORE_EXIT  = 0.5
LOOKBACK     = 60
MAX_PAIRS    = 10  # evaluate at most this many pairs per cycle


class S6PairsCointegration(Strategy):
    id = 'S6'
    timeframe = '1d'
    valid_regimes = ['strong_bull', 'bull', 'sideways', 'bear', 'strong_bear', 'high_vol']
    symbol = 'HDFCBANK'

    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        equity_syms = [s for s in ctx.instruments if s not in _INDEX_NAMES]
        if len(equity_syms) < 2:
            return None

        # Build candidate pairs — limit to avoid O(n²) blowup in live mode
        candidates = list(combinations(equity_syms[:10], 2))[:MAX_PAIRS]

        for sym_a, sym_b in candidates:
            sig = self._check_pair(ctx, sym_a, sym_b)
            if sig is not None:
                return sig
        return None

    def _check_pair(self, ctx: MarketContext, sym_a: str, sym_b: str) -> Optional[Signal]:
        df_a = ctx.ohlcv(sym_a, '1d')
        df_b = ctx.ohlcv(sym_b, '1d')
        if df_a.empty or df_b.empty:
            return None

        close_a = df_a['close'].values.astype(float)[-LOOKBACK:]
        close_b = df_b['close'].values.astype(float)[-LOOKBACK:]
        n = min(len(close_a), len(close_b))
        if n < 20:
            return None

        close_a = close_a[-n:]
        close_b = close_b[-n:]

        beta   = np.polyfit(close_b, close_a, 1)[0]
        spread = close_a - beta * close_b
        mean_s = float(np.mean(spread))
        std_s  = float(np.std(spread))
        if std_s < 1e-8:
            return None

        z = (spread[-1] - mean_s) / std_s
        if abs(z) < ZSCORE_ENTRY:
            return None

        price_a = ctx.last_price(sym_a)
        price_b = ctx.last_price(sym_b)
        if price_a <= 0 or price_b <= 0:
            return None

        token_a    = ctx.instruments.get(sym_a, 0)
        confidence = min(0.5 + abs(z) * 0.05, 0.85)
        side       = 'SELL' if z > 0 else 'BUY'
        atr_a      = ctx.indicator(sym_a, 'atr_14', '1d')
        atr_val    = float(atr_a[-1]) if len(atr_a) > 0 and not np.isnan(atr_a[-1]) else price_a * 0.015
        qty        = int((ctx.size_multiplier * 1_000_000 * 0.01) / max(atr_val, 0.01))

        return Signal(
            strategy_id=self.id,
            instrument_id=token_a,
            side=side,
            quantity=max(qty, 1),
            order_type='MARKET',
            limit_price=None,
            stop_loss=price_a + (1 if side == 'SELL' else -1) * 3.0 * atr_val,
            target=price_a + (-1 if side == 'SELL' else 1) * (abs(z) - ZSCORE_EXIT) / abs(z) * abs(spread[-1] - mean_s),
            confidence=confidence,
            regime=ctx.regime,
            metadata={
                'pair':         f'{sym_a}/{sym_b}',
                'zscore':       round(z, 3),
                'beta':         round(beta, 4),
                'hedge_symbol': sym_b,
                'hedge_side':   'BUY' if side == 'SELL' else 'SELL',
            },
        )
