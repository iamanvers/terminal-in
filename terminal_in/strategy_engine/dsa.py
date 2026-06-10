"""
DSA — Dynamic Strategy Allocator.
Monthly rebalance. Score = 0.40×regime_fit + 0.30×Bayesian_WR + 0.30×rolling_Sharpe.
Allocation gradient capped at ±15% per rebalance. Min allocation 0.05.
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

STRATEGY_IDS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S8', 'S9']

# Which regimes each strategy performs best in (regime_fit score 1.0 if current, 0.5 partial, 0.0 none)
REGIME_FIT: dict[str, dict[str, float]] = {
    'S1': {'strong_bull': 1.0, 'bull': 0.9, 'sideways': 0.6, 'bear': 0.6, 'strong_bear': 0.5, 'high_vol': 0.0},
    'S2': {'strong_bull': 1.0, 'bull': 0.8, 'sideways': 0.2, 'bear': 0.0, 'strong_bear': 0.0, 'high_vol': 0.0},
    'S3': {'strong_bull': 1.0, 'bull': 0.8, 'sideways': 0.2, 'bear': 0.0, 'strong_bear': 0.0, 'high_vol': 0.1},
    'S4': {'strong_bull': 0.3, 'bull': 0.7, 'sideways': 1.0, 'bear': 0.7, 'strong_bear': 0.3, 'high_vol': 0.4},
    'S5': {'strong_bull': 1.0, 'bull': 0.9, 'sideways': 0.4, 'bear': 0.1, 'strong_bear': 0.0, 'high_vol': 0.2},
    'S6': {'strong_bull': 0.6, 'bull': 0.7, 'sideways': 0.9, 'bear': 0.8, 'strong_bear': 0.7, 'high_vol': 0.5},
    'S8': {'strong_bull': 0.1, 'bull': 0.2, 'sideways': 0.3, 'bear': 0.8, 'strong_bear': 1.0, 'high_vol': 1.0},
    'S9': {'strong_bull': 0.9, 'bull': 0.8, 'sideways': 0.3, 'bear': 0.7, 'strong_bear': 0.8, 'high_vol': 0.2},
}

GRADIENT_CAP = 0.15
MIN_ALLOC = 0.05
REBALANCE_DAY = 1       # first trading day of each month
SHARPE_WINDOW = 60      # days for rolling Sharpe


class DSA:
    def __init__(self, db=None):
        self._db = db
        self._allocations: dict[str, float] = {s: 1.0 / len(STRATEGY_IDS) for s in STRATEGY_IDS}
        self._last_rebalance: Optional[datetime] = None
        self._load_state()

    def _load_state(self):
        if self._db is None:
            return
        try:
            state = self._db.load_dsa_state()
            if state:
                for sid, alloc in state.items():
                    if sid in self._allocations:
                        self._allocations[sid] = float(alloc)
                log.info('DSA state loaded: %s', self._allocations)
        except Exception:
            log.exception('Failed to load DSA state')

    def _save_state(self):
        if self._db is None:
            return
        try:
            self._db.save_dsa_state(self._allocations)
        except Exception:
            log.exception('Failed to save DSA state')

    def allocation(self, strategy_id: str) -> float:
        return self._allocations.get(strategy_id, 1.0 / len(STRATEGY_IDS))

    def maybe_rebalance(self, now: datetime, regime: str):
        """Call daily — rebalances on first day of each new month."""
        if self._last_rebalance is not None:
            same_month = (now.year == self._last_rebalance.year and
                          now.month == self._last_rebalance.month)
            if same_month:
                return

        log.info('DSA rebalancing for %s/%s, regime=%s', now.year, now.month, regime)
        self._rebalance(now, regime)
        self._last_rebalance = now

    def _rebalance(self, now: datetime, regime: str):
        scores = {}
        uninformed = []
        for sid in STRATEGY_IDS:
            regime_score = REGIME_FIT.get(sid, {}).get(regime, 0.3)
            bayes_wr = self._bayesian_wr(sid)
            sharpe = self._rolling_sharpe(sid)
            if bayes_wr == 0.5 and sharpe == 0.5:
                uninformed.append(sid)
            scores[sid] = 0.40 * regime_score + 0.30 * bayes_wr + 0.30 * sharpe
        if uninformed:
            log.warning('DSA: %s scored on uninformed priors (WR=0.5, no trade history) — '
                        'allocations for these are regime-fit only', uninformed)

        # Normalise scores to allocations
        total = sum(scores.values())
        if total <= 0:
            return
        target = {sid: max(scores[sid] / total, MIN_ALLOC) for sid in STRATEGY_IDS}

        # Re-normalise after floor application
        target_total = sum(target.values())
        target = {sid: v / target_total for sid, v in target.items()}

        # Apply gradient cap
        new_alloc = {}
        for sid in STRATEGY_IDS:
            current = self._allocations[sid]
            desired = target[sid]
            delta = np.clip(desired - current, -GRADIENT_CAP, GRADIENT_CAP)
            new_alloc[sid] = max(current + delta, MIN_ALLOC)

        # Final normalise
        total_new = sum(new_alloc.values())
        self._allocations = {sid: v / total_new for sid, v in new_alloc.items()}
        log.info('DSA new allocations: %s', {k: round(v, 3) for k, v in self._allocations.items()})
        self._save_state()

    def _bayesian_wr(self, strategy_id: str) -> float:
        """Beta(alpha, beta) posterior mean. Falls back to 0.5 if no trades."""
        if self._db is None:
            return 0.5
        try:
            trades = self._db.get_trades(strategy_id=strategy_id, limit=200)
            if not trades:
                return 0.5
            wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
            losses = len(trades) - wins
            # Beta posterior with uniform prior (alpha=1, beta=1)
            return (wins + 1) / (len(trades) + 2)
        except Exception:
            return 0.5

    def _rolling_sharpe(self, strategy_id: str) -> float:
        """Rolling Sharpe over last SHARPE_WINDOW trades, normalised to [0,1]."""
        if self._db is None:
            return 0.5
        try:
            trades = self._db.get_trades(strategy_id=strategy_id, limit=SHARPE_WINDOW)
            if len(trades) < 5:
                return 0.5
            pnls = np.array([t.get('pnl', 0) for t in trades], dtype=float)
            mean_pnl = np.mean(pnls)
            std_pnl = np.std(pnls)
            if std_pnl < 1e-8:
                return 0.5
            sharpe = mean_pnl / std_pnl * np.sqrt(252)
            # Normalise: clip at [-2, 3] then map to [0, 1]
            normalised = (np.clip(sharpe, -2.0, 3.0) + 2.0) / 5.0
            return float(normalised)
        except Exception:
            return 0.5
