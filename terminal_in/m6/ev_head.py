"""
Phase D₀ — gradient-boosted forward EV head, trained per walk-forward fold.

Replaces the heuristic EV (conf·RR·vol·convergence) with a LightGBM model that
maps the candidate feature vector → realized forward outcome, emitting a
CALIBRATED P(target before stop) (isotonic) and E[net return]. Trains in seconds
on CPU. The heuristic EV remains the fallback (ev_source = gbt | heuristic).

*** WALK-FORWARD FENCING (PR-blocking) ***
The head that scores fold k's test window is trained ONLY on candidates whose
outcome resolved strictly BEFORE fold k's test-window start. `WalkForwardEV`
asserts this per fold and refuses to build on a leak. There is deliberately NO
train-on-all / score-on-all path.

*** FEEDBACK-ECHO GUARD ***
`fit_echo_pair` trains two heads per fold — on ALL candidates vs FIRED-only — so
we can measure whether the loop is learning its own selection bias rather than the
market. The all-candidates head is authoritative.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
    _HAVE_LGB = True
except Exception:                       # pragma: no cover - dependency guard
    _HAVE_LGB = False

from sklearn.isotonic import IsotonicRegression

from terminal_in.m6.dataset import LENS_COLS

log = logging.getLogger(__name__)

# Fixed categorical vocab so train/predict encodings never drift.
REGIMES = ('strong_bull', 'bull', 'sideways', 'bear', 'strong_bear', 'high_vol')
NUM_FEATURES = ['ev', 'confidence', 'persistence', 'rr', 'rsi', 'vol_factor',
                'vix', 'n_lenses'] + list(LENS_COLS)
MIN_TRAIN_ROWS = 400        # below this a fold falls back to heuristic EV (flagged)
CALIB_FRAC = 0.2            # last 20% of train (by outcome_date) held out to calibrate


def available() -> bool:
    return _HAVE_LGB


class GBTEvHead:
    """One trained head: classifier → calibrated P(target before stop), regressor
    → E[net return]. Categoricals (regime, sector) are integer-coded against a
    fixed/observed vocab. Predicts from a feature dict (the engine's candidate)."""

    def __init__(self, seed: int = 7):
        self.seed = seed
        self.clf = self.reg = self.iso = None
        self.sectors: list[str] = []
        self.cols: list[str] = []

    # ── encoding ──
    def _regime_code(self, r): return REGIMES.index(r) if r in REGIMES else -1

    def _sector_code(self, s): return self.sectors.index(s) if s in self.sectors else -1

    def _matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[NUM_FEATURES].astype(float).copy()
        X['regime_c'] = [self._regime_code(r) for r in df['regime']]
        X['sector_c'] = [self._sector_code(s) for s in df['sector']]
        return X

    def _vec(self, feat: dict) -> pd.DataFrame:
        row = {k: float(feat.get(k, 0.0)) for k in NUM_FEATURES if k not in LENS_COLS}
        lens_set = set(str(feat.get('lens_set', '')).split('+'))
        for L in LENS_COLS:
            row[L] = 1.0 if L in lens_set else 0.0
        row['regime_c'] = self._regime_code(feat.get('regime'))
        row['sector_c'] = self._sector_code(feat.get('sector'))
        return pd.DataFrame([row])[self.cols]

    def fit(self, df: pd.DataFrame) -> 'GBTEvHead':
        if not _HAVE_LGB:
            raise RuntimeError('lightgbm unavailable — EV head cannot train')
        self.sectors = sorted(df['sector'].astype(str).unique().tolist())
        d = df.sort_values('outcome_date')
        X = self._matrix(d)
        self.cols = X.columns.tolist()
        cat = ['regime_c', 'sector_c']
        y_cls, y_ret = d['outcome'].to_numpy(float), d['ret_net'].to_numpy(float)

        # temporal fit/calibrate split — calibrate on the LATER slice, never in-sample
        cut = max(1, int(len(d) * (1 - CALIB_FRAC)))
        params = dict(n_estimators=300, learning_rate=0.05, num_leaves=15,
                      min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
                      reg_lambda=1.0, random_state=self.seed, n_jobs=-1, verbosity=-1)
        self.clf = lgb.LGBMClassifier(**params)
        self.clf.fit(X.iloc[:cut], y_cls[:cut], categorical_feature=cat)
        self.reg = lgb.LGBMRegressor(**params)
        self.reg.fit(X.iloc[:cut], y_ret[:cut], categorical_feature=cat)

        raw = self.clf.predict_proba(X.iloc[cut:])[:, 1]
        self.iso = IsotonicRegression(out_of_bounds='clip')
        if len(set(y_cls[cut:])) > 1 and len(raw) >= 20:
            self.iso.fit(raw, y_cls[cut:])
        else:                                   # too little calib data → identity
            self.iso.fit([0.0, 1.0], [0.0, 1.0])
        return self

    def predict(self, feat: dict) -> tuple[float, float]:
        v = self._vec(feat)
        p_raw = float(self.clf.predict_proba(v)[:, 1][0])
        p_win = float(self.iso.predict([p_raw])[0])
        e_ret = float(self.reg.predict(v)[0])
        return p_win, e_ret

    def feature_importance(self) -> dict:
        if self.clf is None:
            return {}
        imp = self.clf.feature_importances_
        tot = imp.sum() or 1
        return {c: round(float(i / tot), 4)
                for c, i in sorted(zip(self.cols, imp), key=lambda kv: -kv[1])}

    def calibration(self, df: pd.DataFrame, bins: int = 10) -> list[dict]:
        """Predicted P(win) vs realized, in deciles — calibrated or confidently wrong?"""
        X = self._matrix(df)
        raw = self.clf.predict_proba(X)[:, 1]
        pw = self.iso.predict(raw)
        y = df['outcome'].to_numpy(float)
        out = []
        edges = np.linspace(0, 1, bins + 1)
        for a, b in zip(edges[:-1], edges[1:]):
            m = (pw >= a) & (pw < b if b < 1 else pw <= b)
            if m.sum() >= 10:
                out.append({'bin': f'{a:.1f}-{b:.1f}', 'pred': round(float(pw[m].mean()), 3),
                            'realized': round(float(y[m].mean()), 3), 'n': int(m.sum())})
        return out


def _fold_bounds(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Calendar-year walk-forward folds: (year, test_start, test_end_exclusive)."""
    years = sorted({d[:4] for d in df['date']})
    return [(y, f'{y}-01-01', f'{int(y) + 1}-01-01') for y in years]


def assert_fold_fenced(train: pd.DataFrame, test_start: str) -> None:
    """PR-BLOCKING: not one training outcome may resolve at/after the test
    window's start. Raises AssertionError on a single leaked row."""
    if len(train) and train['outcome_date'].max() >= test_start:
        raise AssertionError(
            f'LEAK: train max outcome_date {train["outcome_date"].max()} '
            f'>= test start {test_start}')


class WalkForwardEV:
    """Trains one fenced GBTEvHead per calendar-year fold and exposes an
    ev_override closure that routes each candidate to the model trained strictly
    before that candidate's fold."""

    def __init__(self, df: pd.DataFrame, min_train: int = MIN_TRAIN_ROWS, seed: int = 7):
        self.df, self.min_train, self.seed = df, min_train, seed
        self.models: dict[str, GBTEvHead | None] = {}
        self.folds: list[dict] = []

    def train_folds(self) -> list[dict]:
        for year, start, end in _fold_bounds(self.df):
            train = self.df[self.df['outcome_date'] < start]
            assert_fold_fenced(train, start)        # PR-blocking leak guard
            cutoff_ok = (not len(train)) or train['outcome_date'].max() < start
            model, n = None, len(train)
            if n >= self.min_train and _HAVE_LGB:
                model = GBTEvHead(self.seed).fit(train)
            self.models[year] = model
            self.folds.append({'fold': year, 'train_cutoff': start,
                               'test_span': f'{start}..{end}', 'n_train': n,
                               'trained': model is not None, 'cutoff_ok': cutoff_ok})
            log.info('m6 fold %s: train<%s n=%d trained=%s', year, start, n, model is not None)
        return self.folds

    def ev_override(self):
        def _fn(feat, date):
            m = self.models.get(date[:4])
            if m is None:
                return None                      # heuristic fallback (flagged)
            p_win, _e_ret = m.predict(feat)
            return p_win
        return _fn


def fit_echo_pair(train: pd.DataFrame, seed: int = 7):
    """Echo guard: head on ALL candidates vs FIRED-only. Returns (all_head,
    fired_head_or_None). The all-candidates head is authoritative; a large
    divergence means the loop is learning its own selection bias (§8)."""
    all_head = GBTEvHead(seed).fit(train) if _HAVE_LGB and len(train) >= MIN_TRAIN_ROWS else None
    fired = train[train['fired'] == 1]
    fired_head = GBTEvHead(seed).fit(fired) if _HAVE_LGB and len(fired) >= MIN_TRAIN_ROWS else None
    return all_head, fired_head
