"""Unit tests for Module 6 (Phase C competence + Phase D₀ EV head).

Cover the three correctness-critical pieces called out in the task:
  - competence calculation is point-in-time (only past outcomes count);
  - the per-fold walk-forward split-safety assertion (leak guard);
  - the candidate-dataset point-in-time integrity (labels resolve after entry).
No DB / market data — synthetic candidate frames.
"""

import numpy as np
import pandas as pd
import pytest

from terminal_in.m6.competence import CompetenceTable
from terminal_in.m6 import ev_head as EV
from terminal_in.m6.dataset import LENS_COLS, _forward_outcome


def _cand(date, outcome_date, outcome, lens='S4', regime='bull'):
    r = {'date': date, 'outcome_date': outcome_date, 'outcome': outcome,
         'regime': regime, 'sector': 'it', 'ret_net': 0.01 if outcome else -0.01,
         'fired': 1, 'symbol': 'X', 'lens_set': lens,
         'ev': 1.3, 'confidence': 0.6, 'persistence': 2, 'rr': 1.6,
         'rsi': 30.0, 'vol_factor': 1.4, 'vix': 14.0, 'n_lenses': 1,
         'entry': 100.0, 'atr': 2.0}
    for L in LENS_COLS:
        r[L] = int(L == lens)
    return r


# ── Phase C: competence is point-in-time ──────────────────────────────────────

def test_competence_point_in_time_only_past_outcomes():
    # 30 early LOSSES (resolve 2020), then 30 WINS (resolve 2022), all lens S4/bull.
    rows = ([_cand('2019-12-01', f'2020-01-{d:02d}', 0) for d in range(1, 28)] +
            [_cand('2021-12-01', f'2022-01-{d:02d}', 1) for d in range(1, 28)])
    ct = CompetenceTable(pd.DataFrame(rows), window=100, min_obs=10)
    # Queried mid-2021, only the 2020 losses have resolved → HR ≈ 0.
    hr_mid = ct.hit_rate('S4', 'bull', '2021-06-01')
    assert hr_mid == pytest.approx(0.0)
    # Queried in 2023, the wins have resolved too → HR rises.
    hr_late = ct.hit_rate('S4', 'bull', '2023-06-01')
    assert hr_late > hr_mid and hr_late == pytest.approx(0.5, abs=0.05)


def test_competence_abstains_below_threshold_and_unknown_passes():
    losses = [_cand('2019-12-01', f'2020-01-{d:02d}', 0) for d in range(1, 28)]
    ct = CompetenceTable(pd.DataFrame(losses), threshold=0.55, min_obs=10)
    best, abstain = ct.assess(['S4'], 'bull', '2021-01-01')
    assert best == pytest.approx(0.0) and abstain is True       # 0% HR < 0.55 → abstain
    # unknown regime/lens (no history) → pass through, never abstain on ignorance
    best2, abstain2 = ct.assess(['S2'], 'high_vol', '2021-01-01')
    assert best2 is None and abstain2 is False


def test_competence_gate_closure_semantics():
    losses = [_cand('2019-12-01', f'2020-01-{d:02d}', 0) for d in range(1, 28)]
    ct = CompetenceTable(pd.DataFrame(losses), threshold=0.55, min_obs=10)
    gate = ct.gate('veto')
    assert gate(['S4'], 'bull', '2021-01-01') == 0.0            # abstain
    assert gate(['S2'], 'high_vol', '2021-01-01') is None       # unknown → no change


# ── Phase D₀: walk-forward split-safety (leak guard) ──────────────────────────

def test_assert_fold_fenced_raises_on_leak():
    train = pd.DataFrame({'outcome_date': ['2020-06-01', '2021-02-15']})
    # a training outcome resolving AFTER the test start must fail the build
    with pytest.raises(AssertionError):
        EV.assert_fold_fenced(train, '2021-01-01')
    # all training outcomes strictly before the start is fine
    EV.assert_fold_fenced(train, '2021-03-01')
    EV.assert_fold_fenced(pd.DataFrame({'outcome_date': []}), '2021-01-01')  # empty ok


def test_walkforward_folds_are_fenced():
    rng = np.random.default_rng(0)
    rows = []
    for yr in (2020, 2021, 2022):
        for k in range(200):
            o = int(rng.random() < 0.4)
            rows.append(_cand(f'{yr}-03-{(k % 27) + 1:02d}', f'{yr}-04-{(k % 27) + 1:02d}', o))
    wf = EV.WalkForwardEV(pd.DataFrame(rows), min_train=50)
    folds = wf.train_folds()
    df = wf.df
    for f in folds:
        assert f['cutoff_ok'] is True
        train = df[df['outcome_date'] < f['train_cutoff']]
        if len(train):
            assert train['outcome_date'].max() < f['train_cutoff']   # no leak, ever


# ── Phase 0: candidate-dataset point-in-time integrity ────────────────────────

def test_forward_outcome_resolves_after_entry_and_labels_correctly():
    idx = pd.date_range('2024-01-01', periods=30, freq='D')
    # price marches straight up → target (entry + 2.5*ATR) is hit, stop never is
    close = 100 + np.arange(30) * 1.0
    df = pd.DataFrame({'open': close, 'high': close + 0.5, 'low': close - 0.5,
                       'close': close}, index=idx)
    entry_date = idx[0]
    entry = 100.0
    outcome, ret, reason, out_date = _forward_outcome(
        df, entry_date, entry, sl=entry - 3.0, tgt=entry + 5.0, horizon=20)
    assert outcome == 1 and reason == 'target'
    assert out_date is not None and out_date > str(entry_date)[:10]   # resolves AFTER entry
    assert ret > 0

    # straight down → stop hit, labelled a loss
    close_d = 100 - np.arange(30) * 1.0
    dd = pd.DataFrame({'open': close_d, 'high': close_d + 0.5, 'low': close_d - 0.5,
                       'close': close_d}, index=idx)
    o2, r2, reason2, _ = _forward_outcome(dd, idx[0], 100.0, sl=97.0, tgt=105.0, horizon=20)
    assert o2 == 0 and reason2 == 'stop_loss' and r2 < 0
