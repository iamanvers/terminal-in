"""
Central error handling.

Three layers:
  1. install_thread_hook() — catches uncaught exceptions in ANY thread
     (threading.excepthook), logs them, and records them in the ring buffer.
     Without this, a crashed daemon thread dies silently and the component
     just stops working with no trace.
  2. record()/recent() — in-memory ring buffer of the last errors, surfaced
     via /api/health and the agents page so failures are visible in the UI.
  3. install_flask_handlers(app) — JSON error responses with an error id
     instead of HTML tracebacks; every 500 is logged with its id so a UI
     report can be matched to the log line.
"""

import logging
import threading
import time
import traceback
import uuid
from collections import deque
from threading import Lock

log = logging.getLogger(__name__)

_buffer: deque = deque(maxlen=100)
_lock = Lock()


def record(source: str, message: str, exc: BaseException | None = None) -> str:
    """Add an error to the ring buffer. Returns the error id."""
    err_id = uuid.uuid4().hex[:8]
    entry = {
        'id':      err_id,
        'ts':      int(time.time() * 1000),
        'source':  source,
        'message': str(message)[:500],
        'trace':   ''.join(traceback.format_exception(exc))[-2000:] if exc else None,
    }
    with _lock:
        _buffer.append(entry)
    try:
        from terminal_in.bus import bus
        bus.publish('system.error', {k: entry[k] for k in ('id', 'ts', 'source', 'message')})
    except Exception:
        pass
    return err_id


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        entries = list(_buffer)
    return list(reversed(entries))[:limit]


def install_thread_hook() -> None:
    """Log + record uncaught exceptions from any thread instead of letting
    daemon threads die silently."""
    original = threading.excepthook

    def _hook(args: threading.ExceptHookArgs):
        thread_name = args.thread.name if args.thread else '?'
        err_id = record(f'thread:{thread_name}',
                        f'{args.exc_type.__name__}: {args.exc_value}',
                        args.exc_value)
        log.critical('UNCAUGHT EXCEPTION in thread %s [err=%s]: %s',
                     thread_name, err_id, args.exc_value,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        # registry: flag the agent as errored if the thread maps to one
        try:
            from terminal_in.agents.control import registry
            agent_id = thread_name.upper().split('-')[0]
            if registry.get(agent_id) is not None:
                registry.record_error(agent_id, str(args.exc_value)[:200])
        except Exception:
            pass
        original(args)

    threading.excepthook = _hook
    log.info('Thread exception hook installed')


def install_flask_handlers(app) -> None:
    """JSON error responses with traceable ids; no HTML tracebacks."""
    from flask import jsonify
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        # expected HTTP errors (404, 405, …) — clean JSON, not recorded
        return jsonify({'error': e.name, 'status': e.code}), e.code

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        err_id = record('api', f'{type(e).__name__}: {e}', e)
        log.exception('Unhandled API error [err=%s]', err_id)
        return jsonify({
            'error': 'internal_error',
            'error_id': err_id,
            'detail': str(e)[:200],
        }), 500
