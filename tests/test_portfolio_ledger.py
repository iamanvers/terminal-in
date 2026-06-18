"""Tests for the portfolio statement assembly (reporting/portfolio_ledger.py).

Focus: the all-time return math (realized vs initial capital, and total incl.
open marks). Uses lightweight fakes — no DB, no broker process.
"""

from terminal_in.bus import bus
from terminal_in.reporting.portfolio_ledger import build_statement


class _FakeBroker:
    def __init__(self, initial, equity, positions=None):
        self.initial_capital = initial
        self.equity = equity
        self.available_capital = equity * 0.5
        self.capital_in_use = equity * 0.5
        self.peak_equity = max(equity, initial)
        self._positions = positions or []

    @property
    def open_positions(self):
        return self._positions


class _FakeDB:
    def get_closed_trades(self, limit=100):
        return []


def test_realized_all_time_tagged_to_initial_capital():
    # equity = initial + realized; nothing open → total == realized
    b = _FakeBroker(initial=1_000_000, equity=1_050_000)
    s = build_statement(_FakeDB(), b)
    assert s['initial_capital'] == 1_000_000
    assert s['realized_all_time'] == 50_000              # locked-in from closed trades
    assert s['realized_return_pct'] == 5.0
    assert s['unrealized'] == 0.0
    assert s['total_equity'] == 1_050_000                # no open marks
    assert s['total_return_pct'] == 5.0


def test_loss_is_negative_all_time_return():
    b = _FakeBroker(initial=1_000_000, equity=980_000)
    s = build_statement(_FakeDB(), b)
    assert s['realized_all_time'] == -20_000
    assert s['realized_return_pct'] == -2.0


def test_open_marks_flow_into_total_not_realized():
    # one open BUY: 10 @100, live mark 110 → +100 unrealized
    pos = [{'instrument_id': 738561, 'entry_price': 100.0, 'side': 'BUY',
            'quantity': 10, 'product': 'CNC', 'stop_loss': 95.0, 'target': 120.0,
            'entry_time': None, 'strategy_id': 'TEST'}]
    bus._cache['ticks.738561'] = {'last_price': 110.0}
    try:
        b = _FakeBroker(initial=1_000_000, equity=1_010_000, positions=pos)
        s = build_statement(_FakeDB(), b)
        # realized is unchanged by open marks; total folds the +100 in
        assert s['realized_all_time'] == 10_000
        assert s['unrealized'] == 100.0
        assert s['total_equity'] == 1_010_100
        assert round(s['total_return_pct'], 4) == round(10_100 / 1_000_000 * 100, 4)
    finally:
        bus._cache.pop('ticks.738561', None)
