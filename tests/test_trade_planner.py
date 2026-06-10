"""Unit tests for the TradePlanner LLM judge (all Ollama calls mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from terminal_in.agents.trade_planner import (
    TradePlanner, Verdict,
    MAX_APPROVED, DEGRADED_MIN_EV, DEGRADED_MIN_PERSISTENCE, DEGRADED_MIN_CONF,
    SIZE_FACTOR_MIN, SIZE_FACTOR_MAX,
)


def _planner(memory=None):
    cfg = MagicMock()
    cfg.planner_enabled = True
    return TradePlanner(db=MagicMock(), config=cfg, memory=memory, learner=None)


def _cand(symbol='RELIANCE', side='BUY', ev=2.0, conf=0.6, persistence=2):
    return {
        'symbol': symbol, 'side': side, 'ev': ev, 'confidence': conf,
        'conf_smoothed': conf, 'persistence': persistence, 'token': 738561,
        'price': 1450.0, 'rr': 1.7, 'rsi': 55.0, 'vol_factor': 1.4,
        'lenses': [{'strategy': 'S2'}, {'strategy': 'MOM'}],
        'signal': {
            'strategy_id': 'ORCHESTRATOR', 'instrument_id': 738561,
            'side': side, 'quantity': 10, 'limit_price': 1450.0,
            'metadata': {'lenses': ['S2', 'MOM']},
        },
    }


def _batch(candidates):
    return {'scan_id': 7, 'regime': 'bull', 'india_vix': 14.0,
            'equity': 1_000_000.0, 'throttle': 0, 'open_positions': [],
            'candidates': candidates}


# ── _validate ─────────────────────────────────────────────────────────────────

def test_validate_good_json():
    p = _planner()
    cands = [_cand('RELIANCE'), _cand('TCS')]
    raw = json.dumps({'decisions': [
        {'symbol': 'RELIANCE', 'action': 'approve', 'size_factor': 0.8, 'reason': 'strong'},
        {'symbol': 'TCS', 'action': 'reject', 'reason': 'weak'},
    ]})
    verdicts = p._validate(raw, cands)
    by_sym = {v.symbol: v for v in verdicts}
    assert by_sym['RELIANCE'].action == 'approve'
    assert by_sym['RELIANCE'].size_factor == pytest.approx(0.8)
    assert by_sym['TCS'].action == 'reject'


def test_validate_rejects_malformed_json():
    p = _planner()
    assert p._validate('not json at all', [_cand()]) is None
    assert p._validate('{"foo": 1}', [_cand()]) is None


def test_validate_drops_hallucinated_symbols():
    p = _planner()
    raw = json.dumps({'decisions': [
        {'symbol': 'FAKESYM', 'action': 'approve', 'reason': 'x'},
    ]})
    # only hallucinated symbols → nothing valid → None (triggers retry/degraded)
    assert p._validate(raw, [_cand('RELIANCE')]) is None


def test_validate_unruled_candidates_default_to_reject():
    p = _planner()
    raw = json.dumps({'decisions': [
        {'symbol': 'RELIANCE', 'action': 'approve', 'reason': 'x'},
    ]})
    verdicts = p._validate(raw, [_cand('RELIANCE'), _cand('TCS')])
    by_sym = {v.symbol: v for v in verdicts}
    assert by_sym['TCS'].action == 'reject'


def test_validate_clamps_size_factor():
    p = _planner()
    raw = json.dumps({'decisions': [
        {'symbol': 'RELIANCE', 'action': 'approve', 'size_factor': 99, 'reason': 'x'},
        {'symbol': 'TCS', 'action': 'approve', 'size_factor': -1, 'reason': 'x'},
    ]})
    verdicts = p._validate(raw, [_cand('RELIANCE'), _cand('TCS')])
    by_sym = {v.symbol: v for v in verdicts}
    assert by_sym['RELIANCE'].size_factor == SIZE_FACTOR_MAX
    assert by_sym['TCS'].size_factor == SIZE_FACTOR_MIN


def test_validate_enforces_approve_cap():
    p = _planner()
    cands = [_cand(s, ev=e) for s, e in
             [('A', 3.0), ('B', 2.5), ('C', 2.0), ('D', 1.5), ('E', 1.4)]]
    raw = json.dumps({'decisions': [
        {'symbol': s, 'action': 'approve', 'reason': 'x'} for s in 'ABCDE'
    ]})
    verdicts = p._validate(raw, cands)
    approved = [v for v in verdicts if v.action == 'approve']
    assert len(approved) == MAX_APPROVED
    # highest-EV approvals kept
    assert {v.symbol for v in approved} == {'A', 'B', 'C'}


# ── Degraded mode ─────────────────────────────────────────────────────────────

def test_degraded_approves_only_high_bar():
    p = _planner()
    good = _cand('GOOD', ev=DEGRADED_MIN_EV + 0.1, conf=DEGRADED_MIN_CONF + 0.05,
                 persistence=DEGRADED_MIN_PERSISTENCE)
    low_ev   = _cand('LOWEV', ev=DEGRADED_MIN_EV - 0.2, conf=0.7, persistence=3)
    low_pers = _cand('LOWP', ev=2.5, conf=0.7, persistence=1)
    verdicts = p._degraded_verdicts([good, low_ev, low_pers])
    by_sym = {v.symbol: v for v in verdicts}
    assert by_sym['GOOD'].action == 'approve'
    assert by_sym['LOWEV'].action == 'reject'
    assert by_sym['LOWP'].action == 'reject'
    assert all('degraded' in v.reason for v in verdicts)


# ── Planning round ────────────────────────────────────────────────────────────

@patch('terminal_in.agents.trade_planner.bus')
def test_plan_llm_mode_emits_approved_signal(mock_bus):
    p = _planner()
    raw = json.dumps({'decisions': [
        {'symbol': 'RELIANCE', 'action': 'approve', 'size_factor': 0.5, 'reason': 'good setup'},
    ]})
    with patch.object(p, '_ollama_available', return_value=True), \
         patch.object(p, '_call_llm', return_value=raw):
        p._plan(_batch([_cand('RELIANCE')]))

    assert p.get_state()['mode'] == 'llm'
    published = {call.args[0]: call.args[1] for call in mock_bus.publish.call_args_list}
    assert 'strategy.signal' in published
    sig = published['strategy.signal']
    assert sig['quantity'] == 5                      # 10 × 0.5 size factor
    assert sig['metadata']['planner']['mode'] == 'llm'
    assert 'planner.verdict' in published


@patch('terminal_in.agents.trade_planner.bus')
def test_plan_falls_to_degraded_when_ollama_down(mock_bus):
    p = _planner()
    strong = _cand('RELIANCE', ev=2.0, conf=0.65, persistence=3)
    with patch.object(p, '_ollama_available', return_value=False):
        p._plan(_batch([strong]))

    assert p.get_state()['mode'] == 'degraded'
    published = {call.args[0]: call.args[1] for call in mock_bus.publish.call_args_list}
    assert published['planner.verdict']['mode'] == 'degraded'
    # strong candidate passes the high bar even degraded
    assert 'strategy.signal' in published
    assert published['strategy.signal']['metadata']['planner']['mode'] == 'degraded'


@patch('terminal_in.agents.trade_planner.bus')
def test_plan_retries_once_then_degrades_on_bad_output(mock_bus):
    p = _planner()
    weak = _cand('RELIANCE', ev=1.3, conf=0.5, persistence=2)  # below degraded bar
    with patch.object(p, '_ollama_available', return_value=True), \
         patch.object(p, '_call_llm', return_value='garbage') as mock_llm:
        p._plan(_batch([weak]))
    assert mock_llm.call_count == 2                  # initial + one retry
    assert p.get_state()['mode'] == 'degraded'
    published = {call.args[0]: call.args[1] for call in mock_bus.publish.call_args_list}
    assert 'strategy.signal' not in published        # weak candidate rejected


@patch('terminal_in.agents.trade_planner.bus')
def test_rejected_verdicts_recorded_to_memory(mock_bus):
    memory = MagicMock()
    p = _planner(memory=memory)
    raw = json.dumps({'decisions': [
        {'symbol': 'RELIANCE', 'action': 'reject', 'reason': 'crowded'},
    ]})
    with patch.object(p, '_ollama_available', return_value=True), \
         patch.object(p, '_call_llm', return_value=raw):
        p._plan(_batch([_cand('RELIANCE')]))
    memory.record_scan.assert_called_once()
    kwargs = memory.record_scan.call_args.kwargs
    assert kwargs['verdicts']['RELIANCE']['action'] == 'reject'
    assert kwargs['mode'] == 'llm'


# ── Latest-wins queue ─────────────────────────────────────────────────────────

def test_enqueue_latest_wins():
    p = _planner()
    p._enqueue({'scan_id': 1, 'candidates': []})
    p._enqueue({'scan_id': 2, 'candidates': []})
    assert p._pending['scan_id'] == 2
