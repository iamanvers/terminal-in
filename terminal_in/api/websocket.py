"""
WebSocket fan-out layer.
Subscribes to key EventBus topics, pushes updates to all connected SocketIO clients.
"""

import logging

from flask_socketio import SocketIO

from terminal_in.bus import bus

log = logging.getLogger(__name__)

_sio: SocketIO = None

FORWARD_TOPICS = [
    'ticks.*',
    'regime.update',
    'strategy.signal',
    'order.approved',
    'order.rejected',
    'trade.opened',
    'trade.closed',
    'pnl.update',
    'scorecard.update',
    'news.signal',
    'learner.params_updated',
    'settlement.eod_close',
    'settlement.eod_reset',
    'settlement.day_open',
]


def init(sio: SocketIO):
    global _sio
    _sio = sio
    for topic in FORWARD_TOPICS:
        bus.subscribe(topic, _make_forwarder(topic))
    log.info('WebSocket bridge subscribed to %d EventBus topics', len(FORWARD_TOPICS))


def _make_forwarder(topic: str):
    # Use the wildcard base as the SocketIO event name
    event_name = topic.replace('.*', '').replace('.', '_')

    def _forward(payload):
        if _sio is None:
            return
        try:
            data = payload if isinstance(payload, dict) else {'data': str(payload)}
            _sio.emit(event_name, data)
        except Exception:
            log.debug('WebSocket forward error for topic %s', topic)

    return _forward
