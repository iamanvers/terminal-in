"""Unit tests for the TradingSupervisor closed-loop control system."""

from unittest.mock import MagicMock, patch

import pytest

from terminal_in.agents.supervisor import (
    TradingSupervisor,
    LENS_CONSEC_LOSSES, THROTTLE_CONSEC_LOSSES, HARD_STOP_CONSEC_LOSSES,
)


def _supervisor():
    cfg = MagicMock()
    cfg.initial_capital = 1_000_000.0
    cfg.daily_loss_cap = 0.04
    return TradingSupervisor(db=None, config=cfg)


def _closed_trade(pnl: float, lenses=('S2',)):
    return {
        'strategy_id': 'ORCHESTRATOR',
        'pnl': pnl,
        'metadata': {'lenses': list(lenses)},
    }


@patch('terminal_in.agents.supervisor.bus')
def test_lens_suppressed_after_consecutive_losses(mock_bus):
    s = _supervisor()
    for _ in range(LENS_CONSEC_LOSSES):
        s._on_trade_closed(_closed_trade(-500.0, lenses=('S2',)))
    state = s.get_state()
    assert 'S2' in state['suppressed_lenses']
    assert state['suppressed_lenses']['S2'] > 0     # seconds remaining


@patch('terminal_in.agents.supervisor.bus')
def test_win_resets_lens_streak(mock_bus):
    s = _supervisor()
    for _ in range(LENS_CONSEC_LOSSES - 1):
        s._on_trade_closed(_closed_trade(-500.0, lenses=('S4',)))
    s._on_trade_closed(_closed_trade(+800.0, lenses=('S4',)))
    s._on_trade_closed(_closed_trade(-500.0, lenses=('S4',)))
    assert 'S4' not in s.get_state()['suppressed_lenses']


@patch('terminal_in.agents.supervisor.bus')
def test_non_orchestrator_trades_ignored(mock_bus):
    s = _supervisor()
    for _ in range(10):
        s._on_trade_closed({'strategy_id': 'S1', 'pnl': -500.0,
                            'metadata': {'lenses': ['S2']}})
    assert s.get_state()['consec_losses'] == 0


@patch('terminal_in.agents.supervisor.bus')
def test_throttle_engages_after_consecutive_losses(mock_bus):
    s = _supervisor()
    for i in range(THROTTLE_CONSEC_LOSSES):
        s._on_trade_closed(_closed_trade(-100.0, lenses=(f'L{i}',)))
    assert s.get_state()['throttle_level'] == 1
    throttle_events = [c.args[1] for c in mock_bus.publish.call_args_list
                       if c.args[0] == 'supervisor.throttle']
    assert any(e['level'] == 1 for e in throttle_events)


@patch('terminal_in.agents.supervisor.kill_switch')
@patch('terminal_in.agents.supervisor.bus')
def test_hard_stop_engages_kill_switch(mock_bus, mock_kill):
    s = _supervisor()
    for i in range(HARD_STOP_CONSEC_LOSSES):
        s._on_trade_closed(_closed_trade(-100.0, lenses=(f'L{i % 2}x',)))
    mock_kill.engage_global_pause.assert_called_once()
    assert 'consecutive-loss' in mock_kill.engage_global_pause.call_args.args[0]


@patch('terminal_in.agents.supervisor.bus')
def test_day_open_resets_throttle(mock_bus):
    s = _supervisor()
    for i in range(THROTTLE_CONSEC_LOSSES):
        s._on_trade_closed(_closed_trade(-100.0, lenses=(f'M{i}',)))
    assert s.get_state()['throttle_level'] == 1
    s._on_day_open()
    assert s.get_state()['throttle_level'] == 0
    assert s.get_state()['consec_losses'] == 0


@patch('terminal_in.agents.supervisor.bus')
def test_metadata_json_string_parsed(mock_bus):
    s = _supervisor()
    trade = {'strategy_id': 'ORCHESTRATOR', 'pnl': -100.0,
             'metadata': '{"lenses": ["NEWS"]}'}
    for _ in range(LENS_CONSEC_LOSSES):
        s._on_trade_closed(dict(trade))
    assert 'NEWS' in s.get_state()['suppressed_lenses']


@patch('terminal_in.agents.supervisor.bus')
def test_daily_loss_proximity_throttles(mock_bus):
    s = _supervisor()
    # daily loss cap = 4% of 1M = 40k; 60% of that = 24k
    mock_bus.get_cached.return_value = {'daily_pnl': -25_000.0, 'equity': 1_000_000.0}
    s._tick()
    assert s.get_state()['throttle_level'] == 1
