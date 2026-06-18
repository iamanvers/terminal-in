"""F&O Stage 5 — FnOSignalRouter: index strategy signals → ATM option orders."""

import pytest

from terminal_in.execution import fno_signal_router as rt
from terminal_in.execution.fno_signal_router import FnOSignalRouter
from terminal_in.agents.control import kill_switch

NIFTY = 256265
RELIANCE = 738561


class FakeBroker:
    def __init__(self):
        self.orders = []
        self.combos = []
    def _current_spot(self, token):
        return 22000.0
    def place_order(self, order):
        self.orders.append(order)
        return {'ok': True, 'tradingsymbol': 'NIFTY26XYZ', 'premium': 150.0, 'margin': 11250.0}
    def place_combo(self, legs, meta=None):
        self.combos.append((legs, meta))
        return {'ok': True, 'combo_id': 'COMBO_TEST', 'n_legs': len(legs), 'margin': 9000.0}


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setattr(rt, 'is_market_open', lambda: True)   # pretend session is live
    monkeypatch.setenv('FNO_DIRECTIONAL_STRUCTURE', 'option')  # these tests cover the naked path
    if kill_switch.global_pause:
        kill_switch.disengage_global_pause('test')
    b = FakeBroker()
    return FnOSignalRouter(fno_broker=b, config=None), b


@pytest.fixture
def spread_router(monkeypatch):
    monkeypatch.setattr(rt, 'is_market_open', lambda: True)
    monkeypatch.setenv('FNO_DIRECTIONAL_STRUCTURE', 'spread')
    if kill_switch.global_pause:
        kill_switch.disengage_global_pause('test')
    b = FakeBroker()
    return FnOSignalRouter(fno_broker=b, config=None), b


def test_buy_index_routes_to_atm_call(router):
    r, b = router
    r._on_signal({'strategy_id': 'S8', 'instrument_id': NIFTY, 'side': 'BUY'})
    assert len(b.orders) == 1
    o = b.orders[0]
    assert o['underlying'] == 'NIFTY' and o['opt_type'] == 'CE' and o['side'] == 'BUY'
    assert o['strike'] == 22000 and o['lots'] == 1


def test_sell_index_routes_to_atm_put(router):
    r, b = router
    r._on_signal({'strategy_id': 'S1', 'instrument_id': NIFTY, 'side': 'SELL'})
    assert b.orders[0]['opt_type'] == 'PE' and b.orders[0]['side'] == 'BUY'


def test_non_index_signal_ignored(router):
    r, b = router
    r._on_signal({'strategy_id': 'S8', 'instrument_id': RELIANCE, 'side': 'BUY'})
    assert b.orders == []


def test_non_eligible_strategy_ignored(router):
    r, b = router
    r._on_signal({'strategy_id': 'S2', 'instrument_id': NIFTY, 'side': 'BUY'})
    assert b.orders == []


def test_lots_from_metadata(router):
    r, b = router
    r._on_signal({'strategy_id': 'S8', 'instrument_id': NIFTY, 'side': 'BUY',
                  'metadata': {'fno_lots': 3}})
    assert b.orders[0]['lots'] == 3


def test_skips_when_market_closed(monkeypatch):
    monkeypatch.setattr(rt, 'is_market_open', lambda: False)
    b = FakeBroker()
    r = FnOSignalRouter(fno_broker=b, config=None)
    r._on_signal({'strategy_id': 'S8', 'instrument_id': NIFTY, 'side': 'BUY'})
    assert b.orders == []


def test_skips_when_kill_switch_engaged(monkeypatch):
    monkeypatch.setattr(rt, 'is_market_open', lambda: True)
    b = FakeBroker()
    r = FnOSignalRouter(fno_broker=b, config=None)
    kill_switch.engage_global_pause('test')
    try:
        r._on_signal({'strategy_id': 'S8', 'instrument_id': NIFTY, 'side': 'BUY'})
        assert b.orders == [] and b.combos == []
    finally:
        kill_switch.disengage_global_pause('test')


# ── default (risk-defined spread) routing ────────────────────────────────────────

def test_buy_index_routes_to_bull_call_spread(spread_router):
    r, b = spread_router
    r._on_signal({'strategy_id': 'S8', 'instrument_id': NIFTY, 'side': 'BUY'})
    assert b.orders == [] and len(b.combos) == 1          # a combo, not a naked order
    legs, meta = b.combos[0]
    assert meta['kind'] == 'bull_spread' and len(legs) == 2
    assert all(l['opt_type'] == 'CE' for l in legs)
    buy = [l for l in legs if l['side'] == 'BUY'][0]
    sell = [l for l in legs if l['side'] == 'SELL'][0]
    assert sell['strike'] > buy['strike']                 # debit spread: sell higher call


def test_sell_index_routes_to_bear_put_spread(spread_router):
    r, b = spread_router
    r._on_signal({'strategy_id': 'S1', 'instrument_id': NIFTY, 'side': 'SELL'})
    legs, meta = b.combos[0]
    assert meta['kind'] == 'bear_spread'
    assert all(l['opt_type'] == 'PE' for l in legs)
