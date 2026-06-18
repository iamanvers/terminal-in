"""FnOStrategyManager — pure triggers + scan firing through place_combo."""

import numpy as np
import pytest

from terminal_in.execution import fno_strategy_manager as M
from terminal_in.execution.fno_strategy_manager import FnOStrategyManager


# ── pure triggers ────────────────────────────────────────────────────────────────

def test_variance_harvest_only_in_calm_range_with_sane_vix():
    assert M.variance_harvest_due('sideways', 16.0, has_condor=False) is True
    assert M.variance_harvest_due('sideways', 16.0, has_condor=True) is False   # no stacking
    assert M.variance_harvest_due('strong_bull', 16.0, has_condor=False) is False
    assert M.variance_harvest_due('sideways', 9.0, has_condor=False) is False   # too little premium
    assert M.variance_harvest_due('sideways', 30.0, has_condor=False) is False  # vol stress


def test_cointegration_z_detects_divergence():
    rng = np.random.default_rng(0)
    b = np.cumsum(rng.normal(0, 1, 80)) + 100
    a = 2.0 * b + rng.normal(0, 1, 80)   # cointegrated with noise (spread std ~1)
    assert M.cointegration_z(a, b) is not None
    a2 = a.copy(); a2[-1] += 12.0        # shock A far above its beta·B fair value
    z = M.cointegration_z(a2, b)
    assert z is not None and z > 2.0


def test_cointegration_z_none_when_too_short():
    assert M.cointegration_z([1, 2, 3], [1, 2, 3]) is None


def test_event_straddle_due_only_near_event():
    assert M.event_straddle_due(0.5, has_straddle=False) is True
    assert M.event_straddle_due(0.5, has_straddle=True) is False
    assert M.event_straddle_due(1.0, has_straddle=False) is False   # no event near
    assert M.event_straddle_due(0.0, has_straddle=False) is False   # full blackout


def test_covered_call_candidates_filters():
    holdings = [
        {'symbol': 'RELIANCE', 'side': 'BUY', 'quantity': 1000},   # F&O name, >=1 lot
        {'symbol': 'RELIANCE', 'side': 'SELL', 'quantity': 1000},  # short — skip
        {'symbol': 'NOTFNO',   'side': 'BUY', 'quantity': 1000},   # not F&O — skip
        {'symbol': 'INFY',     'side': 'BUY', 'quantity': 1},      # < 1 lot — skip
    ]
    lots = {'RELIANCE': 500, 'INFY': 400}
    out = M.covered_call_candidates(holdings, {'RELIANCE', 'INFY'}, lots)
    assert out == [('RELIANCE', 2)]


# ── scan firing ──────────────────────────────────────────────────────────────────

class FakeFnO:
    def __init__(self):
        self.combos = []
        self._book = []
        self._vix = 16.0
    def positions(self):
        return self._book
    def _current_spot(self, token):
        return 22000.0
    def place_combo(self, legs, meta=None):
        self.combos.append(meta or {})
        return {'ok': True, 'combo_id': f'C{len(self.combos)}'}


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(M, 'is_market_open', lambda: True)
    M.trading_mode.set_auto_trade(True, 'test')
    if M.kill_switch.global_pause:
        M.kill_switch.disengage_global_pause('test')
    monkeypatch.setattr(M.event_cal, 'mask', lambda *a, **k: 1.0)   # no event by default
    # calm sideways regime, sane VIX
    monkeypatch.setattr(M.bus, 'get_cached', lambda topic: {'regime': 'sideways', 'india_vix': 16.0})
    # no pairs / no covered calls unless a test sets them
    monkeypatch.setattr(FnOStrategyManager, '_fire_pair', lambda self: None)
    monkeypatch.setattr(FnOStrategyManager, '_fire_covered_calls', lambda self, book: None)
    fno = FakeFnO()
    return FnOStrategyManager(db=None, fno_broker=fno, cash_broker=None), fno


def test_scan_fires_condor_in_calm_range(mgr, monkeypatch):
    m, fno = mgr
    monkeypatch.setenv('FNO_PAIR', 'false')      # isolate the harvester
    out = m.scan()
    assert 'iron_condor' in out['fired']
    assert any(c.get('kind') == 'iron_condor' for c in fno.combos)


def test_scan_does_not_stack_condor(mgr):
    m, fno = mgr
    # a short NIFTY option already on the book ⇒ no second condor
    fno._book = [{'underlying': 'NIFTY', 'side': 'SELL', 'opt_type': 'CE'}]
    out = m.scan()
    assert 'iron_condor' not in out.get('fired', {})


def test_scan_skips_when_gate_closed(mgr, monkeypatch):
    m, fno = mgr
    monkeypatch.setattr(M, 'is_market_open', lambda: False)
    assert m.scan() == {'skipped': 'gate'}
    assert fno.combos == []
