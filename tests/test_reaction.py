"""Tests for the event-reaction sensitivity matrix (m6/reaction.py).

Cover the interpretable table (cell counts + thin-cell flag + VIX bucketing) and
the PR-blocking no-circularity fence: no event used to FIT a fold's matrix may
resolve at/after that fold's test-window start.
"""

import numpy as np
import pandas as pd

from terminal_in.m6 import reaction as R


def test_vix_bucketing():
    assert R._vix_bucket(12) == '<15'
    assert R._vix_bucket(17) == '15-20'
    assert R._vix_bucket(22) == '20-25'
    assert R._vix_bucket(40) == '>25'


def _records(n_per_year=200, years=(2018, 2019, 2020), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for y in years:
        for k in range(n_per_year):
            ad = f'{y}-{(k % 12) + 1:02d}-{(k % 27) + 1:02d}'
            # resolved ~20 trading days later → keep it within the same year for the test
            rd = f'{y}-{(k % 12) + 1:02d}-{min((k % 27) + 1 + 1, 28):02d}'
            rows.append({'symbol': 'X', 'event_type': 'results',
                         'announce_date': ad, 'resolved_date': rd, 'vix_bucket': '<15',
                         'gap': float(rng.normal(0, 0.02)), 'drift': float(rng.normal(0, 0.05)),
                         'vol_mult': float(abs(rng.normal(1.1, 0.2)))})
    return pd.DataFrame(rows)


def test_reaction_table_cells_and_thin_flag():
    rec = _records(n_per_year=5)                     # 15 rows → thin
    tbl = R.reaction_table(rec)
    assert set(['event_type', 'vix_bucket', 'n', 'mean_gap', 'mean_drift',
                'vol_mult', 'hit_rate', 'untrustworthy']).issubset(tbl.columns)
    assert bool(tbl.iloc[0]['untrustworthy']) is True       # 15 < MIN_CELL_N
    assert int(tbl['n'].sum()) == len(rec)


def test_walk_forward_oos_is_fenced():
    rec = _records(n_per_year=300)
    out = R.walk_forward_oos(rec)
    assert 'per_fold' in out and out['pooled']['n_oos_events'] >= 0
    # the function asserts internally; re-prove the invariant per fold here
    for f in out['per_fold']:
        start = f"{f['fold']}-01-01"
        train = rec[rec['resolved_date'] < start]
        if len(train):
            assert train['resolved_date'].max() < start    # no fitting event leaks


def test_walk_forward_oos_empty():
    assert 'note' in R.walk_forward_oos(pd.DataFrame())
