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


# ── Trade execution → settlement pipeline (EQ + F&O) ────────────────────────────

_SETTLE_REASONS = {'eod_settlement', 'mis_square_off', 'expiry', 'time_exit'}


def _resolve(trade: dict) -> tuple[str, str]:
    """(segment, display_symbol) for a trade row — F&O uses its tradingsymbol."""
    import json as _json
    meta = trade.get('metadata') or {}
    if not meta and trade.get('metadata_json'):
        try:
            meta = _json.loads(trade['metadata_json'])
        except Exception:
            meta = {}
    if meta.get('segment') == 'FNO':
        return 'FNO', meta.get('tradingsymbol') or 'F&O'
    tok = int(trade.get('instrument_token') or trade.get('instrument_id') or 0)
    try:
        from terminal_in.data_ingest.instruments import KNOWN_TOKENS
        sym = {v: k for k, v in KNOWN_TOKENS.items()}.get(tok)
    except Exception:
        sym = None
    return 'EQ', sym or str(tok)


def _trade_item(t: dict, stage: str) -> dict:
    seg, sym = _resolve(t)
    exit_reason = t.get('exit_reason')
    return {
        'segment': seg, 'symbol': sym, 'strategy': t.get('strategy_id', ''),
        'side': t.get('side', ''), 'qty': t.get('quantity', 0),
        'entry': t.get('entry_price'), 'exit': t.get('exit_price'),
        'pnl': t.get('net_pnl'),
        'stage': ('settled' if (stage == 'closed' and exit_reason in _SETTLE_REASONS) else stage),
        'exit_reason': exit_reason,
        'opened_at': t.get('entry_time'), 'closed_at': t.get('exit_time'),
        'trade_id': t.get('trade_id'),
    }


@bp.route('/pipeline')
def pipeline():
    """The execution → settlement funnel for BOTH equities and F&O: signal counts,
    rejected/open/closed items with stage, segment, and P&L. Powers the pipeline UI."""
    if _db is None:
        return jsonify({'funnel': {}, 'items': []})
    limit = int(request.args.get('limit', 40))

    signals = _db.get_recent_signals(limit=limit)
    open_tr = _db.get_open_trades()
    closed  = _db.get_closed_trades(limit=limit)

    approved = sum(1 for s in signals if s.get('approved'))
    rejected = [s for s in signals if not s.get('approved')]

    funnel = {
        'signaled': len(signals),
        'approved': approved,
        'rejected': len(rejected),
        'open':     len(open_tr),
        'closed':   len(closed),
    }

    items: list[dict] = []
    # rejected signals (upstream — never became trades)
    for s in rejected[:limit]:
        seg, sym = _resolve(s)
        items.append({
            'segment': seg, 'symbol': sym, 'strategy': s.get('strategy_id', ''),
            'side': s.get('side', ''), 'qty': None, 'entry': None, 'exit': None,
            'pnl': None, 'stage': 'rejected', 'exit_reason': s.get('reason'),
            'opened_at': s.get('decided_at'), 'closed_at': None, 'trade_id': None,
        })
    items += [_trade_item(t, 'open') for t in open_tr]
    items += [_trade_item(t, 'closed') for t in closed]

    # newest first by whichever timestamp the item has
    items.sort(key=lambda x: (x.get('closed_at') or x.get('opened_at') or 0), reverse=True)
    return jsonify({'funnel': funnel, 'items': items[:limit * 2]})


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
