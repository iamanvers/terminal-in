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
    def _current_spot(self, token):
        return 22000.0
    def place_order(self, order):
        self.orders.append(order)
        return {'ok': True, 'tradingsymbol': 'NIFTY26XYZ', 'premium': 150.0, 'margin': 11250.0}


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setattr(rt, 'is_market_open', lambda: True)   # pretend session is live
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
        assert b.orders == []
    finally:
        kill_switch.disengage_global_pause('test')
