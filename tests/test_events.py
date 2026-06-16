"""Tests for the point-in-time event plane (data_ingest/events.py + m6/event_features.py).

The PR-blocking invariant: an event feature at a decision date `d` may use ONLY
events whose announce_date <= d, and price bars up to d — no event row may
post-date its own usage. Also fail-closed dating: unparseable timestamps drop.
"""

import numpy as np
import pandas as pd
import pytest

from terminal_in.data_ingest import events as EV
from terminal_in.m6 import event_features as EF


# ── fail-closed dating + classification ───────────────────────────────────────

def test_parse_ts_fail_closed():
    assert EV._parse_ts('31-Mar-2020 22:02:00') is not None
    assert EV._parse_ts('31-Mar-2020') is not None
    assert EV._parse_ts('') is None              # missing → drop, never guess
    assert EV._parse_ts('Q3 FY20') is None       # period label → drop (not a date)
    assert EV._parse_ts('garbage') is None


def test_classify_uses_official_category():
    assert EV.classify('Financial Result Updates') == 'results'
    assert EV.classify('Outcome of Board Meeting') == 'results'
    assert EV.classify('Analysts/Institutional Investor Meet') == 'guidance'
    assert EV.classify('Credit Rating') == 'rating_change'
    assert EV.classify('Dividend') == 'corp_action'
    assert EV.classify('Loss of Share Certificates') == 'other'


# ── point-in-time event features ──────────────────────────────────────────────

class _FakeDB:
    """Minimal db stub: one symbol's bars + a flat NIFTY, via get_ohlcv_1d_all."""
    def __init__(self, tok, df):
        self._tok, self._df = tok, df

    def get_ohlcv_1d_all(self, tokens, limit=4000):
        out = {}
        for t in tokens:
            if t == self._tok:
                out[t] = self._df
            else:                                # NIFTY (flat → abnormal == raw)
                out[t] = pd.DataFrame({'close': np.ones(len(self._df))}, index=self._df.index)
        return out


def test_event_features_are_point_in_time(monkeypatch):
    idx = pd.date_range('2024-01-01', periods=40, freq='B')
    close = 100 + np.arange(40) * 1.0            # steady uptrend
    df = pd.DataFrame({'open': close, 'high': close + 0.5, 'low': close - 0.5,
                       'close': close}, index=idx)
    tok = 111
    monkeypatch.setattr(EF, 'KNOWN_TOKENS', {'X': tok, 'NIFTY 50': 999}, raising=False)

    # patch the instruments import used inside add_event_features
    import terminal_in.data_ingest.instruments as INST
    monkeypatch.setattr(INST, 'KNOWN_TOKENS', {'X': tok, 'NIFTY 50': 999}, raising=False)

    # one results event mid-series (announce on the 2024-02-01 bar)
    ev_date = str(idx[20])[:10]
    events = pd.DataFrame([{'symbol': 'X', 'announce_ts': ev_date + 'T18:00:00',
                            'announce_date': ev_date, 'event_type': 'results',
                            'subject': 'Financial Result', 'as_reported': None,
                            'consensus': None}])
    # candidates: one BEFORE the event, one well AFTER
    before, after = str(idx[10])[:10], str(idx[30])[:10]
    cand = pd.DataFrame([
        {'symbol': 'X', 'date': before}, {'symbol': 'X', 'date': after}])

    out = EF.add_event_features(cand, _FakeDB(tok, df), events)
    pre, post = out.iloc[0], out.iloc[1]
    # the candidate BEFORE the event must see NO results (point-in-time)
    assert pre['evt_days_since_results'] == EF.DSR_CAP
    assert pre['evt_drift_so_far'] == 0.0 and pre['evt_in_drift_window'] == 0.0
    # the candidate AFTER sees the event and a positive drift (uptrend, flat bench)
    assert post['evt_days_since_results'] == 10
    assert post['evt_in_drift_window'] == 1.0
    assert post['evt_drift_so_far'] > 0.0
    # consensus stays null + flagged — never backfilled
    assert np.isnan(post['earnings_surprise']) and post['evt_has_consensus'] == 0
    assert EF.event_consensus_coverage(out) == 0.0
