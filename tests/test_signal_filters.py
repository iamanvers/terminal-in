"""Unit tests for the noise-reduction layer (signal_filters.py)."""

import pandas as pd
import pytest

from terminal_in.agents.signal_filters import (
    CandidateTracker, RegimeHysteresis, data_quality,
    MIN_DAILY_BARS,
)


def _cand(token=1, side='BUY', ev=2.0, conf=0.6, symbol='RELIANCE'):
    return {'token': token, 'side': side, 'ev': ev, 'confidence': conf, 'symbol': symbol}


def _df(n=60, days_ago_last=0):
    end = pd.Timestamp.now().normalize() - pd.Timedelta(days=days_ago_last)
    idx = pd.date_range(end=end, periods=n, freq='D')
    return pd.DataFrame({
        'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 1000,
    }, index=idx)


# ── data_quality ──────────────────────────────────────────────────────────────

def test_dq_rejects_empty():
    ok, reason = data_quality(None, 100.0)
    assert not ok and reason == 'no_ohlcv'


def test_dq_rejects_thin_history():
    ok, reason = data_quality(_df(n=MIN_DAILY_BARS - 1), 100.0)
    assert not ok and 'thin_history' in reason


def test_dq_rejects_stale_bars():
    ok, reason = data_quality(_df(n=60, days_ago_last=15), 100.0)
    assert not ok and 'stale_bars' in reason


def test_dq_rejects_no_live_price():
    ok, reason = data_quality(_df(), 0.0)
    assert not ok and reason == 'no_live_price'


def test_dq_rejects_stale_tick():
    ok, reason = data_quality(_df(), 100.0, tick_age_s=3600)
    assert not ok and 'stale_tick' in reason


def test_dq_passes_good_data():
    ok, reason = data_quality(_df(), 100.0, tick_age_s=5)
    assert ok and reason == ''


# ── CandidateTracker ──────────────────────────────────────────────────────────

def test_first_scan_not_eligible():
    t = CandidateTracker()
    [c] = t.update([_cand()], now=0.0)
    assert c['persistence'] == 1
    assert not c['eligible']
    assert 'persistence' in c['filter_reason']


def test_second_consecutive_scan_eligible():
    t = CandidateTracker()
    t.update([_cand()], now=0.0)
    [c] = t.update([_cand()], now=120.0)
    assert c['persistence'] == 2
    assert c['eligible'], c['filter_reason']


def test_streak_resets_when_setup_vanishes():
    t = CandidateTracker()
    t.update([_cand()], now=0.0)
    t.update([], now=120.0)                       # setup gone this scan
    [c] = t.update([_cand()], now=240.0)
    assert c['persistence'] == 1
    assert not c['eligible']


def test_conf_ema_smooths_spikes():
    t = CandidateTracker(alpha=0.4)
    t.update([_cand(conf=0.30)], now=0.0)
    [c] = t.update([_cand(conf=0.90)], now=120.0)
    # EMA = 0.4*0.9 + 0.6*0.3 = 0.54 — not the raw 0.9
    assert c['conf_smoothed'] == pytest.approx(0.54, abs=0.01)


def test_low_smoothed_conf_blocks():
    t = CandidateTracker(min_conf=0.45)
    t.update([_cand(conf=0.30)], now=0.0)
    [c] = t.update([_cand(conf=0.46)], now=120.0)
    assert not c['eligible']
    assert 'conf_ema' in c['filter_reason']


def test_ev_hysteresis_enter_and_exit():
    t = CandidateTracker(ev_enter=1.2, ev_exit=1.0)
    t.update([_cand(ev=1.3)], now=0.0)
    [c] = t.update([_cand(ev=1.1)], now=120.0)   # between exit and enter: stays active
    assert c['eligible'], c['filter_reason']
    [c] = t.update([_cand(ev=0.9)], now=240.0)   # below exit: deactivates
    assert not c['eligible']
    assert 'ev_hysteresis' in c['filter_reason']
    [c] = t.update([_cand(ev=1.1)], now=360.0)   # below enter: stays inactive
    assert not c['eligible']


def test_sides_tracked_independently():
    t = CandidateTracker()
    t.update([_cand(side='BUY')], now=0.0)
    [c] = t.update([_cand(side='SELL')], now=120.0)
    assert c['persistence'] == 1                  # SELL is a fresh streak


def test_neutral_and_skip_ignored():
    t = CandidateTracker()
    out = t.update([{'token': 1, 'side': 'NEUTRAL'}, {'token': 2, 'side': 'SKIP'}], now=0.0)
    assert all('eligible' not in c for c in out)


# ── RegimeHysteresis ──────────────────────────────────────────────────────────

def test_regime_holds_until_persistent():
    h = RegimeHysteresis(required=2)
    assert h.update('bull') == 'bull'             # first observation locks in
    assert h.update('bear') == 'bull'             # flap 1 — held
    assert h.update('bear') == 'bear'             # flap 2 — switches
    assert h.update('bull') == 'bear'             # single flap back — held
    assert h.update('bear') == 'bear'


def test_regime_flapping_never_switches():
    h = RegimeHysteresis(required=2)
    h.update('sideways')
    for r in ['bull', 'bear', 'bull', 'bear']:
        assert h.update(r) == 'sideways'
