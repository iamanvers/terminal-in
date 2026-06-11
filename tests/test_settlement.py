"""Settlement mechanics: only MIS squares off at EOD; CNC carries overnight."""

from unittest.mock import MagicMock, patch

from terminal_in.execution.paper_broker import _product_for
from terminal_in.execution.settlement import SettlementService


def test_product_s1_is_intraday():
    assert _product_for({'strategy_id': 'S1'}) == 'MIS'


def test_product_time_exit_is_intraday():
    assert _product_for({'strategy_id': 'S4', 'time_exit': '2026-06-11T10:00:00'}) == 'MIS'


def test_product_explicit_mis():
    assert _product_for({'strategy_id': 'S5', 'metadata': {'product': 'MIS'}}) == 'MIS'


def test_product_default_is_delivery():
    for sid in ('S2', 'S4', 'S5', 'ORCHESTRATOR', 'manual'):
        assert _product_for({'strategy_id': sid}) == 'CNC'


@patch('terminal_in.execution.settlement.bus')
def test_eod_squares_off_only_mis(mock_bus):
    broker = MagicMock()
    broker.open_positions = [
        {'trade_id': 'T1', 'product': 'MIS', 'instrument_id': 1, 'side': 'BUY',
         'quantity': 1, 'entry_price': 100.0},
        {'trade_id': 'T2', 'product': 'CNC', 'instrument_id': 2, 'side': 'BUY',
         'quantity': 1, 'entry_price': 100.0},
        {'trade_id': 'T3', 'product': 'CNC', 'instrument_id': 3, 'side': 'SELL',
         'quantity': 1, 'entry_price': 100.0},
    ]
    svc = SettlementService(db=MagicMock(), broker=broker, supervisor=None)
    svc._on_eod_close('2026-06-11')

    close_requests = [c.args[1] for c in mock_bus.publish.call_args_list
                      if c.args[0] == 'trade.close_requested']
    assert [r['trade_id'] for r in close_requests] == ['T1']
    assert close_requests[0]['reason'] == 'mis_square_off'

    eod_events = [c.args[1] for c in mock_bus.publish.call_args_list
                  if c.args[0] == 'settlement.eod_close']
    assert eod_events[0]['positions_closed'] == 1
    assert eod_events[0]['positions_carried'] == 2


def test_build_statement_marks_and_account():
    """HOLDINGS assembly (PRD P2): account block + per-position unrealized."""
    from terminal_in.reporting.portfolio_ledger import build_statement
    broker = MagicMock()
    broker.open_positions = [
        {'trade_id': 'T1', 'instrument_id': 738561, 'side': 'BUY', 'product': 'CNC',
         'quantity': 10, 'entry_price': 100.0, 'stop_loss': 95.0, 'target': 110.0},
        {'trade_id': 'T2', 'instrument_id': 408065, 'side': 'SELL', 'product': 'MIS',
         'quantity': 5, 'entry_price': 200.0, 'stop_loss': 210.0, 'target': 180.0},
    ]
    broker.equity = 1_000_500.0
    broker.available_capital = 990_000.0
    broker.capital_in_use = 2_000.0
    broker.peak_equity = 1_001_000.0
    db = MagicMock()
    db.get_closed_trades.return_value = []

    s = build_statement(db, broker)
    assert s['equity'] == 1_000_500.0
    assert len(s['holdings']) == 2
    by_id = {h['token']: h for h in s['holdings']}
    # no live tick in the bus cache -> mark falls back to entry, upnl 0
    long = by_id[738561]
    assert long['product'] == 'CNC' and long['mark'] >= 0
    sign = 1 if long['side'] == 'BUY' else -1
    expected = sign * (long['mark'] - long['entry_price']) * long['quantity']
    assert abs(long['unrealized'] - expected) < 1e-6
    short = by_id[408065]
    assert short['product'] == 'MIS' and short['side'] == 'SELL'
