"""
Strategy base classes — all strategies inherit Strategy and emit Signal objects.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from terminal_in.strategy_engine.context import MarketContext


@dataclass
class Signal:
    strategy_id: str
    instrument_id: int
    side: Literal['BUY', 'SELL']
    quantity: int
    order_type: Literal['MARKET', 'LIMIT', 'SL', 'SL-M']
    limit_price: Optional[float]
    stop_loss: float
    target: float
    confidence: float
    regime: str
    time_exit: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


class Strategy(ABC):
    id: str
    timeframe: str
    valid_regimes: list[str]

    @abstractmethod
    def evaluate(self, ctx: MarketContext) -> Optional[Signal]:
        """Return a Signal if conditions are met, else None."""

    def position_size(self, capital: float, ctx: MarketContext) -> int:
        """
        Default ATR-based 1% risk sizing.
        Override in strategies that need a different approach.
        """
        symbol = getattr(self, 'symbol', None)
        if symbol is None:
            return 0
        price = ctx.last_price(symbol)
        if price <= 0:
            return 0
        atr = ctx.indicator(symbol, 'atr_14', self.timeframe)
        if len(atr) == 0 or atr[-1] != atr[-1]:  # nan check
            return 0
        risk_per_trade = capital * 0.01
        qty = int(risk_per_trade / max(atr[-1], 0.01))
        return max(qty, 1)
