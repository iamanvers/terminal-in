"""
In-memory EventBus ring buffer.
Subscribes to key topics and keeps the last N events for the dashboard's
EventBus inspector tab. No DB writes — pure in-process.

Call init() once after the Flask app is created.
"""

import time
from collections import deque

from terminal_in.bus import bus

_buffer: deque = deque(maxlen=500)

RECORDED_TOPICS = [
    'strategy.signal',
    'order.approved',
    'order.rejected',
    'trade.opened',
    'trade.closed',
    'pnl.update',
    'regime.update',
    'orchestrator.scan_done',
    'agent.status_changed',
    'agent.threshold_changed',
    'kill_switch.global_pause',
    'risk.kill_all',
    'settlement.eod_close',
    'settlement.eod_reset',
    'settlement.day_open',
]

# Human-readable severity per topic
_SEVERITY: dict[str, str] = {
    'strategy.signal':        'info',
    'order.approved':         'success',
    'order.rejected':         'warn',
    'trade.opened':           'success',
    'trade.closed':           'info',
    'pnl.update':             'info',
    'regime.update':          'info',
    'orchestrator.scan_done': 'info',
    'agent.status_changed':   'warn',
    'agent.threshold_changed':'info',
    'kill_switch.global_pause':'critical',
    'risk.kill_all':          'critical',
    'settlement.eod_close':   'info',
    'settlement.eod_reset':   'info',
    'settlement.day_open':    'info',
}


def _make_recorder(topic: str):
    sev = _SEVERITY.get(topic, 'info')

    def _record(payload):
        # Compact summary for each topic type
        summary = _summarise(topic, payload)
        _buffer.append({
            'ts':      int(time.time() * 1000),
            'topic':   topic,
            'severity': sev,
            'summary': summary,
            'payload': payload if isinstance(payload, dict) else {'data': str(payload)},
        })
    return _record


def _summarise(topic: str, p: dict) -> str:
    if not isinstance(p, dict):
        return str(p)[:80]
    if topic == 'strategy.signal':
        return (f"{p.get('strategy_id','?')} → {p.get('side','?')} "
                f"{p.get('instrument_id','?')} conf={p.get('confidence',0):.2f}")
    if topic == 'order.approved':
        return (f"{p.get('strategy_id','?')} {p.get('side','?')} "
                f"{p.get('instrument_id','?')} ×{p.get('quantity','?')}")
    if topic == 'order.rejected':
        return f"{p.get('strategy_id','?')} rejected: {p.get('reason','?')}"
    if topic == 'trade.opened':
        return (f"{p.get('strategy_id','?')} {p.get('side','?')} "
                f"{p.get('instrument_id','?')} ×{p.get('quantity','?')} "
                f"@{p.get('entry_price',0):.2f}")
    if topic == 'trade.closed':
        pnl = p.get('pnl', 0)
        return (f"{p.get('trade_id','?')} closed  pnl={pnl:+.0f}  "
                f"reason={p.get('exit_reason','?')}")
    if topic == 'pnl.update':
        return f"equity={p.get('equity',0):.0f}  daily={p.get('daily_pnl',0):+.0f}"
    if topic == 'regime.update':
        return f"regime={p.get('regime','?')}  vix={p.get('india_vix',0):.1f}"
    if topic == 'agent.status_changed':
        return f"{p.get('agent_id','?')} → {p.get('status','?')}"
    if topic == 'kill_switch.global_pause':
        return f"global_pause={'ON' if p.get('paused') else 'OFF'}  {p.get('reason','')}"
    return str(p)[:100]


def init():
    """Subscribe to all recorded topics. Call once at app startup."""
    for topic in RECORDED_TOPICS:
        bus.subscribe(topic, _make_recorder(topic))


def get_recent(limit: int = 200) -> list:
    """Return most-recent events first."""
    return list(reversed(list(_buffer)))[:limit]
