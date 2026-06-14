"""Backtest endpoints (PRD P2) — run the v2 engine over real OHLCV and serve
results to the BACKTEST module. The compute lives in terminal_in.backtest.engine;
this is a thin async wrapper (runs in a worker thread, poll for status) plus
loaders for the most-recent persisted result.
"""

import json
import logging
import time
from pathlib import Path
from threading import Thread

from flask import Blueprint, jsonify, request

bp  = Blueprint('backtest', __name__, url_prefix='/api/backtest')
log = logging.getLogger(__name__)

_db = None
OUT_DIR = Path('./data/backtests')

# Single in-flight run (the engine is CPU-heavy; one at a time is intentional).
_run = {'active': False, 'result': None, 'error': None,
        'started_ms': None, 'params': None}


def init(db=None):
    global _db
    _db = db


def _latest_file() -> Path | None:
    if not OUT_DIR.exists():
        return None
    files = sorted(OUT_DIR.glob('backtest_*.json'), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return files[0] if files else None


@bp.route('/run', methods=['POST'])
def run():
    """Kick off a backtest. Body: {"days": 730, "symbols": ["TCS",...]?}.
    Returns immediately; poll GET /api/backtest/run for status + result."""
    if _run['active']:
        return jsonify({'ok': False, 'error': 'a backtest is already running'}), 409
    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get('days', 730))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'invalid days'}), 400
    days = max(120, min(days, 3650))           # clamp 4mo–10y
    symbols = body.get('symbols') or None
    if symbols is not None and not isinstance(symbols, list):
        return jsonify({'ok': False, 'error': 'symbols must be a list'}), 400

    from terminal_in.backtest.engine import run_backtest

    def _work():
        t0 = time.time()
        try:
            _run['result'] = run_backtest(db=_db, days=days, symbols=symbols)
            log.info('backtest done in %.1fs (%d trades)', time.time() - t0,
                     _run['result'].get('trades', {}).get('n', 0))
        except Exception as e:
            log.exception('backtest failed')
            _run['error'] = str(e)[:400]
        finally:
            _run['active'] = False

    _run.update(active=True, result=None, error=None,
                started_ms=int(time.time() * 1000),
                params={'days': days, 'symbols': symbols})
    Thread(target=_work, daemon=True, name='backtest').start()
    return jsonify({'ok': True, 'params': _run['params']})


@bp.route('/run', methods=['GET'])
def run_status():
    """Status of the in-flight (or last) run. While active, result is null."""
    return jsonify({
        'active':     _run['active'],
        'error':      _run['error'],
        'started_ms': _run['started_ms'],
        'params':     _run['params'],
        'result':     _run['result'],
    })


@bp.route('/latest')
def latest():
    """Most-recent persisted backtest result (survives restarts; the run-status
    endpoint only holds the current process's last run)."""
    f = _latest_file()
    if f is None:
        return jsonify({'available': False})
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
    except Exception as e:
        return jsonify({'available': False, 'error': str(e)[:200]})
    return jsonify({'available': True, **data})
