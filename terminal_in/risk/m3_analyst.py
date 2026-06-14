"""
M3 — Trade Analyst. 9-class outcome scorecard + Bayesian WR posterior updates.
Subscribes to 'trade.closed', classifies outcome, updates scorecard in DB,
publishes 'scorecard.update' for UI.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from terminal_in.bus import bus

log = logging.getLogger(__name__)

# 9 outcome classes
OUTCOME_CLASSES = [
    'large_win',       # PnL > 2R
    'medium_win',      # PnL in (1R, 2R]
    'small_win',       # PnL in (0, 1R]
    'scratch',         # PnL ≈ 0 (within 0.1R)
    'small_loss',      # PnL in (-1R, 0)
    'medium_loss',     # PnL in (-2R, -1R]
    'large_loss',      # PnL < -2R (stop blown)
    'time_exit',       # closed by time_exit, not SL/target
    'manual_exit',     # manually closed
]


@dataclass
class Scorecard:
    strategy_id: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    # Bayesian posterior parameters (Beta distribution)
    alpha: float = 1.0  # prior: uniform Beta(1,1)
    beta: float = 1.0
    outcome_counts: dict = None
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0

    def __post_init__(self):
        if self.outcome_counts is None:
            self.outcome_counts = {k: 0 for k in OUTCOME_CLASSES}

    @property
    def bayesian_wr(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades


def _classify_outcome(trade: dict) -> str:
    exit_reason = trade.get('exit_reason', '')
    if exit_reason == 'manual':
        return 'manual_exit'
    if exit_reason == 'time_exit':
        return 'time_exit'

    pnl = float(trade.get('pnl', 0))
    r_value = _estimate_r(trade)
    if r_value <= 0:
        return 'small_win' if pnl > 0 else 'small_loss'

    ratio = pnl / r_value
    if ratio > 2.0:
        return 'large_win'
    if ratio > 1.0:
        return 'medium_win'
    if ratio > 0.1:
        return 'small_win'
    if ratio >= -0.1:
        return 'scratch'
    if ratio >= -1.0:
        return 'small_loss'
    if ratio >= -2.0:
        return 'medium_loss'
    return 'large_loss'


def _estimate_r(trade: dict) -> float:
    """Estimate R (initial risk) from stop_loss and entry_price."""
    entry = float(trade.get('entry_price', 0))
    stop = float(trade.get('stop_loss', 0))
    qty = int(trade.get('quantity', 1))
    if entry <= 0 or stop <= 0 or qty <= 0:
        return 0.0
    return abs(entry - stop) * qty


class TradeAnalyst:
    def __init__(self, db):
        self._db = db
        self._scorecards: dict[str, Scorecard] = {}
        self._load_scorecards()
        bus.subscribe('trade.closed', self._on_trade_closed)
        bus.subscribe('fno.trade.closed', self._on_trade_closed)   # score F&O too
        log.info('TradeAnalyst initialised')

    def _load_scorecards(self):
        try:
            rows = self._db.get_all_scorecards() if hasattr(self._db, 'get_all_scorecards') else []
            for row in rows:
                sc = Scorecard(
                    strategy_id=row['strategy_id'],
                    total_trades=row.get('total_trades', 0),
                    wins=row.get('wins', 0),
                    losses=row.get('losses', 0),
                    alpha=row.get('alpha', 1.0),
                    beta=row.get('beta', 1.0),
                    total_pnl=row.get('total_pnl', 0.0),
                    avg_win=row.get('avg_win', 0.0),
                    avg_loss=row.get('avg_loss', 0.0),
                    expectancy=row.get('expectancy', 0.0),
                )
                if row.get('outcome_counts'):
                    import json
                    try:
                        sc.outcome_counts = json.loads(row['outcome_counts'])
                    except Exception:
                        pass
                self._scorecards[row['strategy_id']] = sc
        except Exception:
            log.exception('Failed to load scorecards')

    def _on_trade_closed(self, trade: dict):
        sid = trade.get('strategy_id', 'UNKNOWN')
        sc = self._scorecards.setdefault(sid, Scorecard(strategy_id=sid))

        outcome = _classify_outcome(trade)
        pnl = float(trade.get('pnl', 0))

        sc.total_trades += 1
        sc.outcome_counts[outcome] = sc.outcome_counts.get(outcome, 0) + 1
        sc.total_pnl += pnl

        is_win = pnl > 0
        if is_win:
            sc.wins += 1
            sc.alpha += 1
            # Rolling average win
            sc.avg_win = (sc.avg_win * (sc.wins - 1) + pnl) / sc.wins
        else:
            sc.losses += 1
            sc.beta += 1
            sc.avg_loss = (sc.avg_loss * (sc.losses - 1) + pnl) / sc.losses

        wr = sc.bayesian_wr
        sc.expectancy = wr * sc.avg_win + (1 - wr) * sc.avg_loss

        log.info('Trade analyst: %s outcome=%s pnl=%.2f bayes_wr=%.3f',
                 sid, outcome, pnl, sc.bayesian_wr)

        self._persist(sc)

        bus.publish('scorecard.update', {
            'strategy_id': sid,
            'total_trades': sc.total_trades,
            'win_rate': round(sc.win_rate, 4),
            'bayesian_wr': round(sc.bayesian_wr, 4),
            'expectancy': round(sc.expectancy, 2),
            'total_pnl': round(sc.total_pnl, 2),
            'outcome': outcome,
        })

    def _persist(self, sc: Scorecard):
        import json
        try:
            self._db.upsert_scorecard({
                'strategy_id': sc.strategy_id,
                'total_trades': sc.total_trades,
                'wins': sc.wins,
                'losses': sc.losses,
                'alpha': sc.alpha,
                'beta': sc.beta,
                'total_pnl': sc.total_pnl,
                'avg_win': sc.avg_win,
                'avg_loss': sc.avg_loss,
                'expectancy': sc.expectancy,
                'outcome_counts': json.dumps(sc.outcome_counts),
            })
        except Exception:
            log.exception('Failed to persist scorecard for %s', sc.strategy_id)

    def get_scorecard(self, strategy_id: str) -> Optional[dict]:
        sc = self._scorecards.get(strategy_id)
        if sc is None:
            return None
        return {
            'strategy_id': sc.strategy_id,
            'total_trades': sc.total_trades,
            'wins': sc.wins,
            'losses': sc.losses,
            'win_rate': round(sc.win_rate, 4),
            'bayesian_wr': round(sc.bayesian_wr, 4),
            'expectancy': round(sc.expectancy, 2),
            'total_pnl': round(sc.total_pnl, 2),
            'avg_win': round(sc.avg_win, 2),
            'avg_loss': round(sc.avg_loss, 2),
            'outcome_counts': sc.outcome_counts,
        }

    def all_scorecards(self) -> list[dict]:
        return [self.get_scorecard(sid) for sid in self._scorecards if self.get_scorecard(sid)]
