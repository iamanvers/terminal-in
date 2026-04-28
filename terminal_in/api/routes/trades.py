"""Trade history endpoints."""

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
