"""
Tests for RiskSupervisor (M2 gate).

Covers:
  - Paper mode daily trade limit (200, not 20)
  - Signal dedup: same instrument blocked for 5 minutes after approval
  - Duplicate position check: same instrument already open → reject
  - Event mask bypassed in paper mode
  - Capital (margin) check: order notional > 30% of equity → reject
  - Adaptive confidence via StrategyLearner integration
  - VIX hard stop
"""

import time
import uuid
from unittest.mock import MagicMock, patch


import pytest

from terminal_in.risk.gate import RiskSupervisor, MAX_DAILY_TRADES_PAPER, MIN_CONFIDENCE


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _Cfg:
    is_live          = False
    initial_capital  = 1_000_000
    max_dd           = 0.20
    daily_loss_cap   = 0.04


class _DB:
    def __init__(self, open_trades=None):
        self._open = open_trades or []

    def get_open_trades(self):
        return self._open

    def insert_risk_decision(self, d):
        pass

    def insert_signal_lineage(self, d):
        pass


def _make_gate(open_trades=None, learner=None):
    """Create a RiskSupervisor with bus subscriptions mocked out."""
    with patch('terminal_in.risk.gate.bus'):
        g = RiskSupervisor(db=_DB(open_trades), config=_Cfg(), learner=learner)
    # Reset equity to initial so PnL/drawdown checks start clean
    g._current_equity = 1_000_000
    g._peak_equity    = 1_000_000
    g._india_vix      = 14.0
    return g


def _signal(instrument_id=256265, strategy_id='S1', confidence=0.60,
            limit_price=22000.0, qty=1):
    return {
        'signal_id':     str(uuid.uuid4()),
        'strategy_id':   strategy_id,
        'instrument_id': instrument_id,
        'side':          'BUY',
        'quantity':      qty,
        'limit_price':   limit_price,
        'confidence':    confidence,
        'regime':        'bull',
    }


# ── Paper mode daily limit ────────────────────────────────────────────────────

def test_paper_mode_daily_limit_is_200():
    g = _make_gate()
    assert g._max_daily_trades == MAX_DAILY_TRADES_PAPER
    assert MAX_DAILY_TRADES_PAPER == 200


def test_paper_mode_allows_many_trades():
    g = _make_gate()
    approved = 0
    for i in range(30):
        # Use different instrument_ids and stagger timestamps so dedup doesn't trigger
        sig = _signal(instrument_id=100000 + i, limit_price=1000.0, qty=1)
        # Stamp last_approved in the past so dedup window doesn't block
        g._last_approved[100000 + i] = 0
        result = g.gate(sig)
        if result.approved:
            approved += 1
    assert approved == 30, f'Expected 30 approved, got {approved}'


def test_live_mode_daily_limit_is_20():
    class LiveCfg(_Cfg):
        is_live = True
    with patch('terminal_in.risk.gate.bus'):
        g = RiskSupervisor(db=_DB(), config=LiveCfg())
    assert g._max_daily_trades == 20


# ── Signal dedup ──────────────────────────────────────────────────────────────

def test_signal_dedup_blocks_within_5_min():
    g = _make_gate()
    token = 256265
    sig1 = _signal(instrument_id=token)
    r1 = g.gate(sig1)
    assert r1.approved, f'First signal should be approved, got: {r1.reason}'

    # Second signal immediately — should be blocked
    sig2 = _signal(instrument_id=token)
    r2 = g.gate(sig2)
    assert not r2.approved
    assert 'signal_too_recent' in (r2.reason or '')


def test_signal_dedup_allows_after_window():
    g = _make_gate()
    token = 256265
    # Pre-stamp as if the last signal was 6 minutes ago
    g._last_approved[token] = time.time() - 360
    sig = _signal(instrument_id=token)
    result = g.gate(sig)
    assert result.approved, f'Should be allowed after window, got: {result.reason}'


def test_signal_dedup_different_instruments_independent():
    g = _make_gate()
    r1 = g.gate(_signal(instrument_id=111111))
    r2 = g.gate(_signal(instrument_id=222222))
    assert r1.approved
    assert r2.approved


# ── Duplicate position check ──────────────────────────────────────────────────

def test_duplicate_position_rejected():
    open_trades = [{'instrument_token': 256265, 'strategy_id': 'S1'}]
    g = _make_gate(open_trades=open_trades)
    result = g.gate(_signal(instrument_id=256265))
    assert not result.approved
    assert 'duplicate_instrument' in (result.reason or '')


def test_different_instrument_passes_duplicate_check():
    open_trades = [{'instrument_token': 256265, 'strategy_id': 'S1'}]
    g = _make_gate(open_trades=open_trades)
    result = g.gate(_signal(instrument_id=260105))
    assert result.approved or result.reason not in ('duplicate_instrument', None)


# ── Event mask bypassed in paper mode ────────────────────────────────────────

def test_event_mask_bypassed_in_paper_mode():
    g = _make_gate()
    result = g.gate(_signal())
    # If event mask were checked, it might block (mask returns 0 on busy days)
    # In paper mode, check should always pass
    assert result.checks.get('event_mask') is True


# ── VIX hard stop ─────────────────────────────────────────────────────────────

def test_vix_hard_stop_blocks():
    g = _make_gate()
    g._india_vix = 40.0
    result = g.gate(_signal())
    assert not result.approved
    assert 'vix_too_high' in (result.reason or '')


# ── Margin / capital check ────────────────────────────────────────────────────

def test_margin_check_blocks_oversized_order():
    g = _make_gate()
    # 40% of ₹10L = ₹4L notional per trade — over 30% limit (₹3L max)
    # qty=1, price=400000 → notional = 400000 > 300000
    sig = _signal(instrument_id=999999, limit_price=400_000.0, qty=1)
    result = g.gate(sig)
    assert not result.approved
    assert 'notional_too_large' in (result.reason or '')


def test_margin_check_passes_reasonable_order():
    g = _make_gate()
    # 2% of ₹10L = ₹20k notional — well under 30% limit
    sig = _signal(instrument_id=999998, limit_price=20_000.0, qty=1)
    result = g.gate(sig)
    assert result.approved, f'Should be approved: {result.reason}'


def test_margin_check_skipped_when_no_price():
    g = _make_gate()
    sig = _signal(instrument_id=999997)
    sig['limit_price'] = 0
    sig['stop_loss']   = 0
    result = g.gate(sig)
    # No price → margin check skipped (can't compute notional)
    assert result.checks.get('margin_ok') is True


# ── Adaptive confidence via learner ──────────────────────────────────────────

def test_learner_confidence_threshold_applied():
    learner = MagicMock()
    learner.get_params.return_value = {'min_confidence': 0.70}
    g = _make_gate(learner=learner)

    # Confidence 0.65 would normally pass (>= default 0.45) but learner says 0.70
    sig = _signal(confidence=0.65)
    result = g.gate(sig)
    assert not result.approved
    assert 'low_confidence' in (result.reason or '')


def test_learner_low_threshold_lets_marginal_signal_through():
    learner = MagicMock()
    learner.get_params.return_value = {'min_confidence': 0.30}
    g = _make_gate(learner=learner)

    sig = _signal(confidence=0.35)
    result = g.gate(sig)
    assert result.approved, f'Should be approved with low learner threshold: {result.reason}'


# ── Daily counters reset ──────────────────────────────────────────────────────

def test_reset_daily_clears_dedup():
    g = _make_gate()
    token = 256265
    g.gate(_signal(instrument_id=token))  # approve once, stamp dedup
    assert token in g._last_approved

    g.reset_daily()
    assert g._last_approved == {}
    assert g._daily_trades == 0


# ── Gate returns GateResult shape ────────────────────────────────────────────

def test_gate_result_has_checks_dict():
    g = _make_gate()
    result = g.gate(_signal())
    assert isinstance(result.checks, dict)
    assert 'event_mask' in result.checks
    assert 'vix_hard_stop' in result.checks
    assert 'confidence_ok' in result.checks
    assert 'no_duplicate' in result.checks
    assert 'margin_ok' in result.checks
