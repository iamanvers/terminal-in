"""Trade endpoints: history, stats, closed trades, manual order."""

import time
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

bp = Blueprint('trades', __name__, url_prefix='/api/trades')

_db = None


def init(db):
    global _db
    _db = db


@bp.route('/')
def list_trades():
    limit = int(request.args.get('limit', 100))
    strategy_id = request.args.get('strategy_id')
    trades = _db.get_trades(strategy_id=strategy_id, limit=limit) if _db else []
    return jsonify(trades)


@bp.route('/open')
def open_trades():
    trades = _db.get_open_trades() if _db else []
    return jsonify(trades)


@bp.route('/closed')
def closed_trades():
    limit = int(request.args.get('limit', 50))
    strategy_id = request.args.get('strategy_id')
    closed = _db.get_closed_trades(limit=limit, strategy_id=strategy_id) if _db else []
    return jsonify(closed)


@bp.route('/stats')
def trade_stats():
    if _db is None:
        return jsonify(_empty_stats())
    return jsonify(_db.get_trade_stats_sql())


@bp.route('/manual', methods=['POST'])
def manual_order():
    data = request.get_json(silent=True) or {}
    symbol   = (data.get('symbol') or '').strip().upper()
    side     = (data.get('side') or 'BUY').upper()
    quantity = int(data.get('quantity') or 0)

    if not symbol:
        return jsonify({'error': 'symbol required'}), 400
    if quantity <= 0:
        return jsonify({'error': 'quantity must be > 0'}), 400
    if side not in ('BUY', 'SELL'):
        return jsonify({'error': 'side must be BUY or SELL'}), 400

    from terminal_in.data_ingest.instruments import registry
    token = registry.token(symbol)
    if not token:
        return jsonify({'error': f'unknown symbol: {symbol}'}), 400

    from terminal_in.bus import bus
    signal_id = str(uuid.uuid4())
    payload = {
        'signal_id':   signal_id,
        'strategy_id': 'MANUAL',
        'instrument_id': token,
        'side':        side,
        'quantity':    quantity,
        'limit_price': float(data.get('limit_price') or 0),
        'stop_loss':   float(data.get('stop_loss') or 0),
        'target':      float(data.get('target') or 0),
        'confidence':  1.0,
        'regime':      'manual',
        'generated_at': int(time.time() * 1000),
        'metadata':    {'source': 'manual_order'},
    }
    bus.publish('order.approved', payload)
    return jsonify({'ok': True, 'signal_id': signal_id, 'symbol': symbol, 'token': token})


@bp.route('/signals')
def signals():
    """Recent risk decisions with signal lineage — powers the recommendations feed."""
    if _db is None:
        return jsonify([])
    limit = int(request.args.get('limit', 40))
    rows = _db.get_recent_signals(limit=limit)
    # Enrich with symbol name
    from terminal_in.data_ingest.instruments import registry
    for row in rows:
        token = row.get('instrument_token')
        row['symbol'] = registry.symbol(token) if token else None
    return jsonify(rows)


@bp.route('/<trade_id>/close', methods=['POST'])
def close_trade(trade_id: str):
    """Manually close an open position at current market price."""
    from terminal_in.bus import bus
    bus.publish('trade.close_requested', {'trade_id': trade_id})
    return jsonify({'ok': True, 'trade_id': trade_id})


@bp.route('/journal')
def journal():
    if _db is None:
        return jsonify([])
    limit = int(request.args.get('limit', 50))
    return jsonify(_db.get_all_journal_entries(limit=limit))


def _empty_stats() -> dict:
    return {
        'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0,
        'total_pnl': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0,
        'best_trade_pnl': 0.0, 'worst_trade_pnl': 0.0,
        'today_trades': 0, 'today_pnl': 0.0, 'by_strategy': {},
    }
