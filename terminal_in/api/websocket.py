"""
WebSocket fan-out layer.
Subscribes to key EventBus topics, pushes updates to all connected SocketIO clients.
Tick events are throttled per token (500 ms min interval) to prevent flooding.
"""

import logging
import time

from flask_socketio import SocketIO

from terminal_in.bus import bus

log = logging.getLogger(__name__)

_sio: SocketIO = None

# Per-topic last-emit timestamps for throttling
_last_emit: dict[str, float] = {}
TICK_THROTTLE_S = 0.5  # min interval between tick emits per token

FORWARD_TOPICS = [
    'ticks.*',
    'regime.update',
    'strategy.signal',
    'order.approved',
    'order.rejected',
    'trade.opened',
    'trade.closed',
    'fno.trade.opened',
    'fno.trade.closed',
    'fno.signal.routed',
    'pnl.update',
    'scorecard.update',
    'news.signal',
    'learner.params_updated',
    'settlement.eod_close',
    'settlement.eod_reset',
    'settlement.day_open',
    'orchestrator.scan_done',
    'agent.status_changed',
    'agent.threshold_changed',
    'kill_switch.global_pause',
    'planner.verdict',
    'supervisor.state',
    'supervisor.throttle',
    'training.status',
    'system.error',
]


def init(sio: SocketIO):
    global _sio
    _sio = sio
    for topic in FORWARD_TOPICS:
        is_tick = topic == 'ticks.*'
        bus.subscribe(topic, _make_forwarder(topic, throttle=is_tick))
    log.info('WebSocket bridge subscribed to %d EventBus topics', len(FORWARD_TOPICS))


def _make_forwarder(topic: str, throttle: bool = False):
    event_name = topic.replace('.*', '').replace('.', '_')

    def _forward(payload):
        if _sio is None:
            return
        try:
            data = payload if isinstance(payload, dict) else {'data': str(payload)}
            if throttle:
                # Use token as the throttle key so each symbol is independent
                key = str(data.get('instrument_token', topic))
                now = time.monotonic()
                if now - _last_emit.get(key, 0.0) < TICK_THROTTLE_S:
                    return
                _last_emit[key] = now
            _sio.emit(event_name, data)
        except Exception:
            log.debug('WebSocket forward error for topic %s', topic)

    return _forward
