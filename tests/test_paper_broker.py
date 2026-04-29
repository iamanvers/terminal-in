"""
Tests for PaperBroker — capital tracking, fill logic, close logic.

Covers:
  - Capital in use increases when a position is opened
  - Capital in use decreases when a position is closed
  - Order rejected when insufficient capital
  - PnL correctly computed on close (long and short)
  - equity updates after close
  - daily_pnl tracks within-session P&L
"""

import time
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

class _Cfg:
    initial_capital = 1_000_000
    is_live         = False


class _DB:
    def __init__(self):
        self._trades: dict[str, dict] = {}

    def get_trades(self, limit=10_000):
        return list(self._trades.values())

    def get_open_trades(self):
        return [t for t in self._trades.values() if t.get('exit_price') is None]

    def insert_trade(self, t):
        self._trades[t['trade_id']] = dict(t)

    def close_trade(self, trade_id, data):
        if trade_id in self._trades:
            self._trades[trade_id].update(data)

    def update_signal_lineage(self, *a, **k):
        pass

    def upsert_trade_journal(self, d):
        pass


@pytest.fixture
def mock_bus():
    mb = MagicMock()
    mb.get_cached.return_value = None
    mb.subscribe = MagicMock()
    mb.publish   = MagicMock()
    return mb


@pytest.fixture
def broker(mock_bus):
    """PaperBroker with bus patched for the full test lifetime."""
    with patch('terminal_in.execution.paper_broker.bus', mock_bus):
        from terminal_in.execution.paper_broker import PaperBroker
        b = PaperBroker(db=_DB(), config=_Cfg())
        yield b, mock_bus


def _order(instrument_id=256265, side='BUY', qty=1,
           price=22000.0, sl=0.0, target=0.0):
    return {
        'strategy_id':   'S1',
        'signal_id':     'sig-001',
        'instrument_id': instrument_id,
        'side':          side,
        'quantity':      qty,
        'limit_price':   price,
        'stop_loss':     sl,
        'target':        target,
        'confidence':    0.70,
        'regime':        'bull',
        'metadata':      {},
    }


# ── Capital tracking on open ──────────────────────────────────────────────────

def test_capital_in_use_increases_on_fill(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(instrument_id=256265, qty=10, price=100.0))

    assert b.capital_in_use > 0
    assert b.capital_in_use == pytest.approx(10 * 100.0 * 1.0003, rel=0.01)


def test_available_capital_reduced_after_fill(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100_000.0}

    b._on_order(_order(qty=1, price=100_000.0))

    assert b.available_capital < 1_000_000
    assert b.available_capital == pytest.approx(1_000_000 - b.capital_in_use, abs=1.0)


# ── Capital check ─────────────────────────────────────────────────────────────

def test_order_rejected_when_insufficient_capital(broker):
    b, bus = broker
    # Override equity so capital is tight
    b._equity = 100_000
    bus.get_cached.return_value = {'last_price': 200_000.0}

    b._on_order(_order(qty=1, price=200_000.0))

    assert len(b.open_positions) == 0   # no fill
    assert b.capital_in_use == 0.0


def test_order_accepted_within_capital(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 22000.0}

    b._on_order(_order(qty=1, price=22000.0))

    assert len(b.open_positions) == 1
    assert b.capital_in_use > 0


# ── Capital freed on close ────────────────────────────────────────────────────

def test_capital_freed_on_close(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(qty=1, price=100.0))
    assert b.capital_in_use > 0

    trade_id = b.open_positions[0]['trade_id']
    b._on_close_requested({'trade_id': trade_id, 'reason': 'manual'})

    assert b.capital_in_use == pytest.approx(0.0, abs=1.0)
    assert len(b.open_positions) == 0


# ── PnL calculation ───────────────────────────────────────────────────────────

def test_long_trade_profit_pnl(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(qty=100, price=100.0))

    trade_id = b.open_positions[0]['trade_id']
    bus.get_cached.return_value = {'last_price': 110.0}  # price rose
    b._on_close_requested({'trade_id': trade_id})

    # Net PnL ≈ (110*0.9997 - 100*1.0003)*100 - 40 ≈ +954
    assert b.equity > 1_000_000
    assert b.daily_pnl > 0


def test_long_trade_loss_pnl(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(qty=100, price=100.0))

    trade_id = b.open_positions[0]['trade_id']
    bus.get_cached.return_value = {'last_price': 90.0}  # price fell
    b._on_close_requested({'trade_id': trade_id})

    assert b.equity < 1_000_000
    assert b.daily_pnl < 0


def test_short_trade_profit_pnl(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(side='SELL', qty=100, price=100.0))

    trade_id = b.open_positions[0]['trade_id']
    bus.get_cached.return_value = {'last_price': 90.0}  # price fell → short wins
    b._on_close_requested({'trade_id': trade_id})

    assert b.equity > 1_000_000
    assert b.daily_pnl > 0


# ── SL/target auto-close ─────────────────────────────────────────────────────

def test_stop_loss_triggers_close(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(qty=10, price=100.0, sl=95.0))
    assert len(b.open_positions) == 1

    b._on_tick({'instrument_token': 256265, 'last_price': 94.0})

    assert len(b.open_positions) == 0


def test_target_triggers_close(broker):
    b, bus = broker
    bus.get_cached.return_value = {'last_price': 100.0}

    b._on_order(_order(qty=10, price=100.0, target=115.0))
    assert len(b.open_positions) == 1

    b._on_tick({'instrument_token': 256265, 'last_price': 116.0})

    assert len(b.open_positions) == 0


# ── Multiple positions ────────────────────────────────────────────────────────

def test_multiple_positions_track_capital_separately(broker):
    b, bus = broker
    b._equity = 2_000_000  # give more room

    bus.get_cached.return_value = {'last_price': 100.0}
    b._on_order(_order(instrument_id=111, qty=100, price=100.0))

    bus.get_cached.return_value = {'last_price': 200.0}
    b._on_order(_order(instrument_id=222, qty=50, price=200.0))

    assert len(b.open_positions) == 2
    # capital ≈ 100*100 + 50*200 = 20000 (+ tiny slippage)
    assert b.capital_in_use == pytest.approx(20_000, rel=0.02)


# ── daily_pnl property ────────────────────────────────────────────────────────

def test_daily_pnl_property_exists(broker):
    b, _ = broker
    assert b.daily_pnl == 0.0


def test_reset_daily_pnl(broker):
    b, bus = broker
    b._daily_pnl = -5000.0
    b.reset_daily_pnl()
    assert b.daily_pnl == 0.0
