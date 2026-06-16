"""
Phase C — calibrated directional competence + abstention (no new ML).

Generalises Zhu et al. 2026's model-selection idea: for each (lens × direction ×
regime) track the TRAILING hit rate (target-before-stop). The judge down-weights /
abstains on a lens that has been unreliable lately IN THIS REGIME, and abstains
when no source clears the competence threshold.

Direction is always BUY in the long-only cash backtest, so the key is
(lens, regime). Everything is POINT-IN-TIME: the hit rate at decision date `d`
uses only candidates whose outcome resolved STRICTLY BEFORE `d`.

This is wired as an EV multiplier / veto into eligibility — it can shrink or
abstain, never bypass the M2 gate.
"""

from __future__ import annotations

import bisect
import logging

import numpy as np

from terminal_in.m6.dataset import LENS_COLS

log = logging.getLogger(__name__)

THRESHOLD_DEFAULT = 0.55      # competence bar; a constant, NOT tuned (doc start)
WINDOW_DEFAULT    = 100       # trailing resolved candidates per (lens, regime)
MIN_OBS_DEFAULT   = 20        # below this, competence is UNKNOWN (pass through)


class CompetenceTable:
    """Point-in-time trailing hit-rate per (lens, regime), built from the
    candidate dataset. Query with the decision date; only outcomes resolved
    before that date are counted (no leakage)."""

    def __init__(self, df, window: int = WINDOW_DEFAULT,
                 threshold: float = THRESHOLD_DEFAULT, min_obs: int = MIN_OBS_DEFAULT):
        self.window, self.threshold, self.min_obs = window, threshold, min_obs
        # per (lens, regime): outcome_dates (sorted) + aligned outcomes
        self._od: dict[tuple, list[str]] = {}
        self._oc: dict[tuple, np.ndarray] = {}
        if df is None or len(df) == 0:
            return
        d = df.sort_values('outcome_date')
        for lens in LENS_COLS:
            sub = d[d[lens] == 1]
            for regime, g in sub.groupby('regime'):
                self._od[(lens, regime)] = g['outcome_date'].tolist()
                self._oc[(lens, regime)] = g['outcome'].to_numpy(dtype=float)

    def hit_rate(self, lens: str, regime: str, date: str) -> float | None:
        """Trailing HR for (lens, regime) over outcomes resolved before `date`.
        None if fewer than min_obs resolved observations (UNKNOWN)."""
        od = self._od.get((lens, regime))
        if not od:
            return None
        pos = bisect.bisect_left(od, date)          # rows with outcome_date < date
        lo = max(0, pos - self.window)
        if pos - lo < self.min_obs:
            return None
        return float(self._oc[(lens, regime)][lo:pos].mean())

    def assess(self, lens_names, regime: str, date: str) -> tuple[float | None, bool]:
        """Return (best_known_HR, abstain). A candidate is credited with the BEST
        of its member lenses' competence (the most reliable source). UNKNOWN (too
        little history) → pass through, never abstain on ignorance."""
        hrs = [self.hit_rate(l, regime, date) for l in lens_names]
        known = [h for h in hrs if h is not None]
        if not known:
            return None, False                      # unknown → pass through
        best = max(known)
        return best, best < self.threshold

    def gate(self, mode: str = 'veto'):
        """Closure for engine.run_backtest(competence_gate=...).
        Returns weight: 0.0 = abstain; None = no change (pass / unknown);
        in 'weight' mode returns best_HR as a down-weighting multiplier."""
        def _fn(lens_names, regime, date):
            best, abstain = self.assess(lens_names, regime, date)
            if abstain:
                return 0.0
            if mode == 'weight' and best is not None:
                return best
            return None
        return _fn

    def annotate(self, df):
        """Add point-in-time `comp_hr` and `comp_abstain` columns to a COPY of the
        candidate dataset (for the abstention-attribution report). Each row is
        assessed using only outcomes resolved before its own decision `date`."""
        out = df.copy()
        hrs, abst = [], []
        for r in out.itertuples(index=False):
            lens_names = [L for L in LENS_COLS if getattr(r, L) == 1]
            best, ab = self.assess(lens_names, r.regime, r.date)
            hrs.append(best)
            abst.append(ab)
        out['comp_hr'] = hrs
        out['comp_abstain'] = abst
        return out
