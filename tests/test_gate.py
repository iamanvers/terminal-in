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

from terminal_in.risk.gate import (
    RiskSupervisor, MAX_DAILY_TRADES_PAPER, MIN_CONFIDENCE,
    NON_TRADEABLE,
)
from terminal_in.data_ingest.instruments import registry, SECTOR_MAP, KNOWN_TOKENS

# Sector checks resolve token → symbol → sector through the registry
registry.load_stubs()


@pytest.fixture(autouse=True)
def _market_always_open(monkeypatch):
    """Gate enforces NSE market hours; tests must not depend on wall clock."""
    monkeypatch.setattr('terminal_in.risk.gate._market_open', lambda: True)


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


def _signal(instrument_id=500001, strategy_id='S1', confidence=0.60,
            limit_price=500.0, qty=1):
    """Build a test signal. Default token 500001 is not in NON_TRADEABLE and not in _SECTOR_MAP."""
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
    token = 2800641  # NIFTYBEES — tradeable ETF
    sig1 = _signal(instrument_id=token, limit_price=100.0)
    r1 = g.gate(sig1)
    assert r1.approved, f'First signal should be approved, got: {r1.reason}'

    # Second signal immediately — should be blocked
    sig2 = _signal(instrument_id=token, limit_price=100.0)
    r2 = g.gate(sig2)
    assert not r2.approved
    assert 'signal_too_recent' in (r2.reason or '')


def test_signal_dedup_allows_after_window():
    g = _make_gate()
    token = 2800641  # NIFTYBEES — tradeable ETF
    # Pre-stamp as if the last signal was 6 minutes ago
    g._last_approved[token] = time.time() - 360
    sig = _signal(instrument_id=token, limit_price=100.0)
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
    open_trades = [{'instrument_token': 738561, 'strategy_id': 'S1'}]  # RELIANCE
    g = _make_gate(open_trades=open_trades)
    result = g.gate(_signal(instrument_id=738561, limit_price=1200.0))
    assert not result.approved
    assert 'duplicate_instrument' in (result.reason or '')


def test_different_instrument_passes_duplicate_check():
    open_trades = [{'instrument_token': 738561, 'strategy_id': 'S1'}]  # RELIANCE
    g = _make_gate(open_trades=open_trades)
    result = g.gate(_signal(instrument_id=500001))
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
    result = g.gate(_signal(instrument_id=500002))
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


def test_margin_check_rejects_when_no_price():
    g = _make_gate()
    sig = _signal(instrument_id=999997)
    sig['limit_price'] = 0
    sig['stop_loss']   = 0
    result = g.gate(sig)
    # No resolvable price (no live tick, no limit/SL) → an unknown notional
    # must never pass the margin check
    assert not result.approved
    assert result.checks.get('margin_ok') is False
    assert 'no_price_for_margin_check' in (result.reason or '')


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
    token = 500001
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


# ── Non-tradeable instruments blocked ─────────────────────────────────────────

@pytest.mark.parametrize('token,name', [
    (264969, 'INDIA_VIX'),
    (256265, 'NIFTY_50'),
    (260105, 'BANKNIFTY'),
    (257801, 'FINNIFTY'),
])
def test_non_tradeable_blocked(token, name):
    g = _make_gate()
    result = g.gate(_signal(instrument_id=token))
    assert not result.approved, f'{name} should be blocked'
    assert 'non_tradeable' in (result.reason or ''), f'Expected non_tradeable reason, got: {result.reason}'


def test_niftybees_is_tradeable():
    """NIFTYBEES (ETF token 2800641) must NOT be blocked — it trades on cash segment."""
    g = _make_gate()
    result = g.gate(_signal(instrument_id=2800641, limit_price=100.0, qty=1))
    assert result.approved, f'NIFTYBEES should be tradeable, reason: {result.reason}'


def test_non_tradeable_set_contains_expected_tokens():
    assert 264969 in NON_TRADEABLE, 'VIX must be non-tradeable'
    assert 256265 in NON_TRADEABLE, 'NIFTY 50 must be non-tradeable'
    assert 260105 in NON_TRADEABLE, 'BANKNIFTY must be non-tradeable'
    assert 257801 in NON_TRADEABLE, 'FINNIFTY must be non-tradeable'
    assert 2800641 not in NON_TRADEABLE, 'NIFTYBEES (ETF) must be tradeable'


# ── Kill switch ───────────────────────────────────────────────────────────────

def test_kill_switch_global_pause_blocks_all():
    g = _make_gate()
    from terminal_in.agents.control import kill_switch
    kill_switch.engage_global_pause('test')
    try:
        result = g.gate(_signal(instrument_id=999999))
        assert not result.approved
        assert 'global_pause_engaged' == result.reason
    finally:
        kill_switch.disengage_global_pause('test')


def test_kill_switch_symbol_block():
    g = _make_gate()
    from terminal_in.agents.control import kill_switch
    token = 999888
    kill_switch.block_symbol(token, 'test_block')
    try:
        result = g.gate(_signal(instrument_id=token))
        assert not result.approved
        assert 'symbol_blocked' in (result.reason or '')
    finally:
        kill_switch.unblock_symbol(token)


# ── Drawdown circuit breaker ──────────────────────────────────────────────────

def test_drawdown_breaker_blocks_when_exceeded():
    g = _make_gate()
    # Simulate 25% drawdown on a 20% max_dd config
    g._peak_equity    = 1_000_000
    g._current_equity = 750_000
    result = g.gate(_signal(instrument_id=999777))
    assert not result.approved
    assert 'max_dd_breached' in (result.reason or '')


def test_drawdown_breaker_passes_within_limit():
    g = _make_gate()
    g._peak_equity    = 1_000_000
    g._current_equity = 900_000   # 10% drawdown, limit is 20%
    result = g.gate(_signal(instrument_id=999776))
    # Should not fail on drawdown check (may fail other checks)
    assert result.checks.get('drawdown_ok') is True


# ── Daily loss cap ────────────────────────────────────────────────────────────

def test_daily_loss_cap_blocks_when_exceeded():
    g = _make_gate()
    g._daily_loss = -50_000   # 5% of ₹10L, limit is 4%
    g._current_equity = 1_000_000
    result = g.gate(_signal(instrument_id=999775))
    assert not result.approved
    assert 'daily_loss_cap' in (result.reason or '')


def test_daily_loss_cap_passes_within_limit():
    g = _make_gate()
    g._daily_loss = -30_000   # 3% of ₹10L — under 4% cap
    g._current_equity = 1_000_000
    result = g.gate(_signal(instrument_id=999774))
    assert result.checks.get('daily_loss_ok') is True


# ── Sector concentration ──────────────────────────────────────────────────────

def test_sector_concentration_blocks_when_exceeded():
    """Adding a 4th financials position when 3 are open should breach the 40% cap."""
    # 3 financials out of 3 open = 100% concentration → way above 40%
    financials_tokens = [341249, 1270529, 779521]  # HDFCBANK, ICICIBANK, SBIN
    open_trades = [{'instrument_token': t} for t in financials_tokens]
    g = _make_gate(open_trades=open_trades)
    # Try to add a 4th financials instrument
    result = g.gate(_signal(instrument_id=1510401, limit_price=800.0, qty=1))  # AXISBANK
    assert not result.approved
    assert 'sector_concentration_limit' in (result.reason or '')


def test_sector_concentration_allows_index_instruments():
    """Index instruments are exempt from the sector cap."""
    # 3 financials open — but adding NIFTYBEES (index) should pass sector check
    open_trades = [
        {'instrument_token': 341249},
        {'instrument_token': 1270529},
        {'instrument_token': 779521},
    ]
    g = _make_gate(open_trades=open_trades)
    # NIFTYBEES is in 'index' sector → exempt
    result = g.gate(_signal(instrument_id=2800641, limit_price=100.0, qty=1))
    assert result.checks.get('sector_ok') is True


def test_sector_small_book_never_deadlocks():
    """With 1 open position, a 2nd trade in ANY sector must pass the sector
    check (2026-06-12 bug: proportional cap blocked 80 signals in a row —
    (0+1)/(1+1)=50% > 40% for every sector on a 1-position book)."""
    one_open = [{'instrument_token': 738561}]   # RELIANCE (energy)
    g = _make_gate(open_trades=one_open)
    # different sector: full gate path must clear the sector check
    r = g.gate(_signal(instrument_id=341249, limit_price=900.0, qty=1))   # HDFCBANK
    assert r.checks.get('sector_ok') is True
    # same sector: the floor allows a 2nd position per sector
    assert g._check_sector(738561, one_open)
    # the cap still bites on bigger books: 3rd financial in a 3-book = 100%
    three_fin = [{'instrument_token': t} for t in (341249, 1270529, 779521)]
    g3 = _make_gate(open_trades=three_fin)
    assert not g3._check_sector(1510401, three_fin)   # AXISBANK blocked


def test_sector_floor_disabled_restores_strict_cap(monkeypatch):
    """SECTOR_SMALL_BOOK_FLOOR=false removes the small-book carve-out, so the
    strict proportional cap applies from the 2nd same-sector position:
    (1+1)/(1+1) = 50% > 40% → blocked. This is the pre-2026-06-12 behavior,
    kept available via the env switch."""
    monkeypatch.setenv('SECTOR_SMALL_BOOK_FLOOR', 'false')
    one_fin = [{'instrument_token': 341249}]              # HDFCBANK (financials)
    g = _make_gate(open_trades=one_fin)
    # 2nd financial on a 1-position book: floor off → strict cap blocks it
    assert not g._check_sector(1270529, one_fin)          # ICICIBANK blocked
    # default (floor on) would have allowed it — guard against regression
    monkeypatch.setenv('SECTOR_SMALL_BOOK_FLOOR', 'true')
    assert g._check_sector(1270529, one_fin)


def test_sector_map_covers_all_instruments():
    """Every known instrument symbol must have a sector mapping."""
    missing = [s for s in KNOWN_TOKENS if s not in SECTOR_MAP]
    assert not missing, f'Symbols without sector mapping: {missing}'
    for symbol, sector in SECTOR_MAP.items():
        assert isinstance(sector, str) and sector


# ── Directional correlation / crowding ────────────────────────────────────────

def test_directional_crowding_blocks_when_3_same_side_sector():
    """3 open BUY positions in financials → 4th BUY in financials is blocked."""
    open_trades = [
        {'instrument_token': 341249,  'side': 'BUY'},  # HDFCBANK financials
        {'instrument_token': 1270529, 'side': 'BUY'},  # ICICIBANK financials
        {'instrument_token': 779521,  'side': 'BUY'},  # SBIN financials
    ]
    g = _make_gate(open_trades=open_trades)
    # Attempting 4th BUY in financials
    sig = _signal(instrument_id=1510401, limit_price=800.0, qty=1)  # AXISBANK
    sig['side'] = 'BUY'
    result = g.gate(sig)
    assert not result.approved
    # Could fail on sector_concentration first; either is acceptable
    assert result.reason in ('directional_crowding_in_sector', 'sector_concentration_limit=40%')


def test_directional_crowding_allows_opposite_direction():
    """3 open BUY positions in financials → SELL in financials passes the crowding check.

    We need enough open trades so sector concentration check doesn't fire first.
    With 9 total open trades and 3 in financials, adding a 4th gives 4/10=40% which
    exactly meets the 40% cap (projected_pct <= MAX_SECTOR_PCT), so sector passes.
    """
    # 6 'other' sector trades + 3 financials BUY = 9 total
    other_trades = [{'instrument_token': 600000 + i, 'side': 'BUY'} for i in range(6)]
    financials_buys = [
        {'instrument_token': 341249,  'side': 'BUY'},
        {'instrument_token': 1270529, 'side': 'BUY'},
        {'instrument_token': 779521,  'side': 'BUY'},
    ]
    open_trades = other_trades + financials_buys
    g = _make_gate(open_trades=open_trades)
    sig = _signal(instrument_id=1510401, limit_price=800.0, qty=1)  # AXISBANK financials
    sig['side'] = 'SELL'
    result = g.gate(sig)
    # Sector check: (3+1)/(9+1) = 40% — exactly at the cap, so passes (<=)
    assert result.checks.get('sector_ok') is True, f'sector check failed: {result.checks}'
    # Crowding check: 0 same-sector SELL positions → not crowded
    assert result.checks.get('correlation_ok') is True


# ── VIX reduce (non-blocking) ─────────────────────────────────────────────────

def test_vix_reduce_halves_quantity_above_threshold():
    g = _make_gate()
    g._india_vix = 28.0   # above VIX_REDUCE_THRESHOLD=25
    sig = _signal(instrument_id=999700, limit_price=1000.0, qty=10)
    result = g.gate(sig)
    assert result.approved
    assert result.checks.get('vix_size_reduced') is True
    assert sig['quantity'] == 5   # halved


def test_vix_reduce_not_applied_below_threshold():
    g = _make_gate()
    g._india_vix = 18.0
    sig = _signal(instrument_id=999699, limit_price=1000.0, qty=10)
    result = g.gate(sig)
    assert result.approved
    assert result.checks.get('vix_size_reduced') is False
    assert sig['quantity'] == 10  # unchanged


# ── Max open positions ────────────────────────────────────────────────────────

def test_max_open_positions_blocks_when_full():
    # 10 unique open positions = at limit
    open_trades = [{'instrument_token': 100000 + i} for i in range(10)]
    g = _make_gate(open_trades=open_trades)
    result = g.gate(_signal(instrument_id=999600))
    assert not result.approved
    assert 'max_positions' in (result.reason or '')


# ── Market hours ──────────────────────────────────────────────────────────────

def test_market_closed_rejects_everything(monkeypatch):
    """No fills outside the real NSE session — paper or live."""
    monkeypatch.setattr('terminal_in.risk.gate._market_open', lambda: False)
    g = _make_gate()
    result = g.gate(_signal(instrument_id=2800641, limit_price=100.0))
    assert not result.approved
    assert 'market_closed' in (result.reason or '')
    assert result.checks.get('market_open') is False


# ── Concurrency: trade-count cap holds under parallel dispatch ────────────────

def test_concurrent_gate_respects_trade_cap_exactly():
    """The EventBus dispatches callbacks synchronously in the publishing thread,
    so gate() runs from multiple producer threads at once. The gate lock must
    make the trade-count cap (check-then-increment) atomic: firing many more
    distinct-instrument signals than the cap, concurrently, must approve EXACTLY
    the cap and never overshoot — and must not deadlock."""
    import threading

    g = _make_gate()
    cap = g._max_daily_trades          # 200 in paper
    n = cap + 100
    approvals = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()                  # release all at once to maximize contention
        sig = _signal(instrument_id=300000 + i, limit_price=100.0, qty=1)
        g._last_approved[300000 + i] = 0   # pre-stamp so dedup never blocks
        res = g.gate(sig)
        if res.approved:
            with lock:
                approvals.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert all(not t.is_alive() for t in threads), 'gate() deadlocked under concurrency'
    assert len(approvals) == cap, f'expected exactly {cap} approvals, got {len(approvals)}'
    assert g._daily_trades == cap, f'_daily_trades miscounted: {g._daily_trades} != {cap}'


# ── Auto-trade (advise-only) ────────────────────────────────────────────────────

def test_auto_trade_off_blocks_fills(monkeypatch):
    """OFF = advise-only: the gate rejects 'auto_trade_off' (signals still shown)."""
    monkeypatch.setattr('terminal_in.risk.gate._market_open', lambda: True)
    from terminal_in.agents.control import trading_mode
    trading_mode.set_auto_trade(False, 'test')
    try:
        g = _make_gate()
        result = g.gate(_signal(instrument_id=2800641, limit_price=100.0))
        assert not result.approved
        assert result.reason == 'auto_trade_off'
        assert result.checks.get('auto_trade_on') is False
    finally:
        trading_mode.set_auto_trade(True, 'test')
