"""Unit tests for the alpha-validation harness (terminal_in/backtest/validation.py).

Exercise the PURE statistical truth-tellers on constructed return arrays — no DB,
no market data. These guard the maths (Deflated Sharpe, White Reality Check,
significance, concentration, survivorship), not the full walk-forward run.
"""

import numpy as np

from terminal_in.backtest import validation as V


def test_curve_stats_rising_curve_positive():
    eq = 1_000_000 * np.cumprod(1 + np.full(252, 0.001))   # steady +0.1%/day for 1y
    st = V._curve_stats(eq, n_years=1.0)
    assert st['cagr'] > 0.2
    assert st['sharpe'] > 5          # noiseless ramp → huge Sharpe
    assert st['max_dd'] == 0.0       # never below peak
    assert st['calmar'] == 0.0       # no drawdown → calmar undefined → 0


def test_curve_stats_flat_curve_zeros():
    st = V._curve_stats(np.full(100, 1_000_000.0), n_years=1.0)
    assert st['cagr'] == 0.0 and st['sharpe'] == 0.0 and st['sortino'] == 0.0


def test_trade_sharpe_sign_and_zero():
    rng = np.random.default_rng(0)
    pos = rng.normal(0.01, 0.02, 200)      # positive expectancy
    assert V._trade_sharpe(pos, n_years=2.0) > 0
    assert V._trade_sharpe(np.full(50, 0.01), n_years=2.0) == 0.0   # zero variance


def test_significance_flags_noise_not_signal():
    rng = np.random.default_rng(1)
    # strong, high-N signal — should NOT be flagged noise
    strong = {'S_strong': rng.normal(0.02, 0.01, 500)}
    out = V.significance(strong, n_years=2.0)
    assert out['S_strong']['noise'] is False
    assert out['S_strong']['t_stat'] > 2
    # weak, tiny-N — should be flagged noise
    weak = {'S_weak': rng.normal(0.001, 0.05, 6)}
    assert V.significance(weak, n_years=2.0)['S_weak']['noise'] is True


def test_deflated_sharpe_structure_and_haircut():
    rng = np.random.default_rng(2)
    per_lens = {
        'A': rng.normal(0.03, 0.01, 300),   # strong
        'B': rng.normal(0.000, 0.02, 300),  # ~zero
        'C': rng.normal(-0.01, 0.02, 300),  # negative
    }
    out = V.deflated_sharpe(per_lens, n_trials=8)
    assert out['sr0_haircut_per_trade'] > 0          # a real haircut is applied
    assert out['per_lens']['A']['dsr'] > out['per_lens']['B']['dsr']
    assert out['per_lens']['A']['survives'] is True
    assert out['per_lens']['C']['survives'] is False


def test_deflated_sharpe_needs_two_lenses():
    rng = np.random.default_rng(3)
    out = V.deflated_sharpe({'only': rng.normal(0.01, 0.02, 50)}, n_trials=8)
    assert 'note' in out                              # cannot deflate with <2 trials


def test_white_reality_check_pvalue_range():
    rng = np.random.default_rng(4)
    per_lens = {'A': rng.normal(0.0, 0.02, 200), 'B': rng.normal(0.0, 0.02, 200)}
    out = V.white_reality_check(per_lens, n_boot=500, rng=np.random.default_rng(5))
    assert 0.0 <= out['p_familywise_best'] <= 1.0
    for v in out['per_lens'].values():
        assert 0.0 <= v['p_familywise'] <= 1.0
    # pure-noise lenses should NOT survive a family-wise screen
    assert all(not v['survives'] for v in out['per_lens'].values())


def test_concentration_detects_one_year_dominance():
    result = {
        'days': 504,
        'walk_forward_years': {'2020': {'n': 50, 'total_pnl': 90_000},
                               '2021': {'n': 50, 'total_pnl': 10_000}},
        'per_regime': {'bull': {'n': 60, 'total_pnl': 80_000},
                       'sideways': {'n': 40, 'total_pnl': 20_000}},
        'equity_curve': [{'date': f'2020-{i:02d}', 'equity': 1_000_000 + i * 1000}
                         for i in range(1, 13)],
    }
    c = V.concentration(result)
    assert c['best_year'] == '2020'
    assert c['best_year_pnl_share'] == 0.9
    assert c['best_year_dominates'] is True
    assert c['best_regime'] == 'bull'
    assert c['best_regime_dominates'] is True


def test_sharpe_and_dsr_helpers():
    rng = np.random.default_rng(0)
    # a clearly positive return stream → positive Sharpe
    pos = rng.normal(0.01, 0.02, 200)
    assert V._sharpe(pos, ppy=12.6) > 0
    assert V._sharpe(np.full(50, 0.01), ppy=12.6) == 0.0          # zero variance
    # DSR is a probability in [0,1]; a strong single series beats a weak one,
    # and a larger trial count (more deflation) lowers it.
    strong = rng.normal(0.02, 0.02, 200)
    weak = rng.normal(0.002, 0.02, 200)
    srs = [s.mean() / s.std() for s in (strong, weak)]
    d_strong = V._dsr_single(strong, srs, n_trials=2)
    d_weak = V._dsr_single(weak, srs, n_trials=2)
    assert 0.0 <= d_weak <= d_strong <= 1.0
    assert V._dsr_single(strong, srs, n_trials=50) <= V._dsr_single(strong, srs, n_trials=2)


def test_net_series_regime_filter_stands_aside():
    recs = [{'date': '2020-01-01', 'spread': 0.05, 'tl': 1.0, 'ts': 1.0,
             'n_long': 10, 'n_short': 10, 'imp_l': 0.0, 'imp_s': 0.0, 'regime': 'strong_bull'},
            {'date': '2020-02-01', 'spread': 0.05, 'tl': 1.0, 'ts': 1.0,
             'n_long': 10, 'n_short': 10, 'imp_l': 0.0, 'imp_s': 0.0, 'regime': 'high_vol'}]
    out = V._net_series(recs, impact=False, regime_filter=('high_vol',))
    assert out[0] == 0.0                       # strong_bull → stood aside, no return/cost
    assert out[1] != 0.0                       # high_vol → traded


def test_xs_signal_reversal_vs_momentum_sign():
    import pandas as pd
    # name UP: rose recently AND over the year; name DOWN: fell on both.
    n = 300
    up = np.linspace(100, 200, n)
    down = np.linspace(200, 100, n)
    M = pd.DataFrame({'UP': up, 'DOWN': down})
    i = n - 1
    # reversal (k=21): negative of recent return → UP (a recent winner) ranks LOWER
    rev = V._xs_signal(M, i, 21, 'reversal_1m')
    assert rev['UP'] < rev['DOWN']
    # momentum 12-1 (k=252): formation return [i-252, i-21] → UP ranks HIGHER
    mom = V._xs_signal(M, i, 252, 'mom_12_1')
    assert mom['UP'] > mom['DOWN']


def test_survivorship_separates_floor_from_late_listers():
    # OLD/OLD2 sit at the data floor (2015-01); NEW1/NEW2 list materially later.
    first = {'OLD': '2015-01-01', 'OLD2': '2015-01-05',
             'NEW1': '2021-06-01', 'NEW2': '2023-03-20'}
    out = V.survivorship(first)                       # cutoff auto-anchored to floor
    assert out['data_floor'] == '2015-01-01'
    assert out['n_universe'] == 4
    assert out['n_at_data_floor'] == 2                # OLD, OLD2 at the boundary
    assert out['n_listed_after_floor'] == 2
    assert set(out['late_listers']) == {'NEW1', 'NEW2'}
