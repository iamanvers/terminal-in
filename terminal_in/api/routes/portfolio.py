"""Portfolio and equity endpoints."""

from flask import Blueprint, jsonify

bp = Blueprint('portfolio', __name__, url_prefix='/api/portfolio')

_supervisor = None
_broker = None


def init(supervisor, broker):
    global _supervisor, _broker
    _supervisor = supervisor
    _broker = broker


@bp.route('/summary')
def summary():
    stats = _supervisor.daily_stats if _supervisor else {}
    equity = _broker.equity if _broker else stats.get('equity', 0)
    positions = _broker.open_positions if _broker else []
    return jsonify({
        'equity': equity,
        'daily_pnl': stats.get('daily_pnl', 0),
        'daily_trades': stats.get('daily_trades', 0),
        'drawdown': stats.get('drawdown', 0),
        'peak_equity': stats.get('peak_equity', equity),
        'open_positions': len(positions),
        'india_vix': stats.get('india_vix', 0),
    })


@bp.route('/positions')
def positions():
    pos = _broker.open_positions if _broker else []
    return jsonify(pos)
