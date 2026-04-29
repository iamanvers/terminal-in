"""Portfolio and equity endpoints."""

from flask import Blueprint, jsonify, request

bp = Blueprint('portfolio', __name__, url_prefix='/api/portfolio')

_supervisor = None
_broker = None
_db = None


def init(supervisor, broker, db=None):
    global _supervisor, _broker, _db
    _supervisor = supervisor
    _broker = broker
    _db = db


@bp.route('/summary')
def summary():
    stats = _supervisor.daily_stats if _supervisor else {}
    equity = _broker.equity if _broker else stats.get('equity', 0)
    peak = getattr(_broker, 'peak_equity', None) or stats.get('peak_equity', equity)
    positions = _broker.open_positions if _broker else []
    drawdown = (peak - equity) / peak if peak > 0 else 0.0
    return jsonify({
        'equity': equity,
        'daily_pnl': stats.get('daily_pnl', _broker._daily_pnl if _broker else 0),
        'daily_trades': stats.get('daily_trades', 0),
        'drawdown': drawdown,
        'peak_equity': peak,
        'open_positions': len(positions),
        'india_vix': stats.get('india_vix', 0),
    })


@bp.route('/positions')
def positions():
    pos = _broker.open_positions if _broker else []
    return jsonify(pos)


@bp.route('/snapshots')
def snapshots():
    limit = int(request.args.get('limit', 90))
    rows = _db.get_portfolio_snapshots(limit=limit) if _db else []
    return jsonify(rows)
