"""Agent control, decision feed, signal lineage, EventBus inspector endpoints."""

import json
import logging
from flask import Blueprint, jsonify, request

from terminal_in.agents.control import registry, kill_switch

bp  = Blueprint('agents', __name__, url_prefix='/api/agents')
log = logging.getLogger(__name__)

_engine = None
_db     = None


def init(engine=None, db=None):
    global _engine, _db
    _engine = engine
    _db     = db


# ── Agent registry ─────────────────────────────────────────────────────────

@bp.route('/')
def list_agents():
    return jsonify(registry.get_all())


@bp.route('/<agent_id>')
def get_agent(agent_id: str):
    state = registry.get(agent_id)
    if state is None:
        return jsonify({'error': 'not_found'}), 404
    return jsonify(state)


@bp.route('/<agent_id>/pause', methods=['POST'])
def pause_agent(agent_id: str):
    if registry.get(agent_id) is None:
        return jsonify({'error': 'not_found'}), 404
    registry.pause(agent_id)
    return jsonify({'ok': True, 'agent_id': agent_id, 'status': 'paused'})


@bp.route('/<agent_id>/resume', methods=['POST'])
def resume_agent(agent_id: str):
    if registry.get(agent_id) is None:
        return jsonify({'error': 'not_found'}), 404
    registry.resume(agent_id)
    return jsonify({'ok': True, 'agent_id': agent_id, 'status': 'running'})


@bp.route('/<agent_id>/force-eval', methods=['POST'])
def force_eval(agent_id: str):
    if agent_id == 'ENGINE' and _engine is not None:
        _engine.force_evaluate()
        return jsonify({'ok': True, 'agent_id': agent_id, 'action': 'force_eval'})
    return jsonify({'error': 'not_supported'}), 400


@bp.route('/<agent_id>/threshold', methods=['PATCH'])
def set_threshold(agent_id: str):
    body = request.get_json(silent=True) or {}
    threshold = body.get('threshold')
    if threshold is None:
        return jsonify({'error': 'missing threshold'}), 400
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid threshold'}), 400
    if registry.get(agent_id) is None:
        return jsonify({'error': 'not_found'}), 404
    registry.set_threshold(agent_id, threshold)
    return jsonify({'ok': True, 'agent_id': agent_id, 'threshold': round(threshold, 3)})


# ── Kill switch ─────────────────────────────────────────────────────────────

@bp.route('/risk/state')
def risk_state():
    return jsonify(kill_switch.get_state())


@bp.route('/risk/global-pause', methods=['POST'])
def global_pause():
    body = request.get_json(silent=True) or {}
    kill_switch.engage_global_pause(body.get('reason', 'manual'))
    return jsonify({'ok': True, 'global_pause': True})


@bp.route('/risk/global-resume', methods=['POST'])
def global_resume():
    body = request.get_json(silent=True) or {}
    kill_switch.disengage_global_pause(body.get('reason', 'manual'))
    return jsonify({'ok': True, 'global_pause': False})


@bp.route('/risk/block-symbol', methods=['POST'])
def block_symbol():
    body = request.get_json(silent=True) or {}
    token = body.get('token')
    if token is None:
        return jsonify({'error': 'missing token'}), 400
    kill_switch.block_symbol(int(token), body.get('reason', 'manual'))
    return jsonify({'ok': True, 'blocked': int(token)})


@bp.route('/risk/unblock-symbol', methods=['POST'])
def unblock_symbol():
    body = request.get_json(silent=True) or {}
    token = body.get('token')
    if token is None:
        return jsonify({'error': 'missing token'}), 400
    kill_switch.unblock_symbol(int(token))
    return jsonify({'ok': True, 'unblocked': int(token)})


@bp.route('/risk/kill-all', methods=['POST'])
def kill_all():
    from terminal_in.bus import bus
    kill_switch.engage_global_pause('kill_all')
    bus.publish('risk.kill_all', {'reason': 'kill_all_triggered'})
    return jsonify({'ok': True, 'action': 'kill_all'})


@bp.route('/audit')
def audit():
    limit = int(request.args.get('limit', 100))
    return jsonify(kill_switch.get_audit(limit))


# ── System health ────────────────────────────────────────────────────────────

@bp.route('/health')
def health():
    agents   = registry.get_all()
    healthy  = sum(1 for a in agents if a['status'] == 'running')
    errored  = sum(1 for a in agents if a['status'] == 'error')
    paused   = sum(1 for a in agents if a['status'] == 'paused')
    stale    = sum(1 for a in agents if a['heartbeat_age_s'] > 120)
    total    = len(agents)
    return jsonify({
        'healthy':      healthy,
        'errored':      errored,
        'paused':       paused,
        'stale':        stale,
        'total':        total,
        'health_pct':   round(healthy / max(total, 1) * 100),
        'global_pause': kill_switch.global_pause,
    })


# ── Decision feed ─────────────────────────────────────────────────────────────

@bp.route('/decisions')
def decisions():
    if _db is None:
        return jsonify([])
    limit = int(request.args.get('limit', 60))
    strategy_id = request.args.get('strategy_id')
    rows = _db.get_recent_signals(limit=limit)
    # Optionally filter by strategy
    if strategy_id:
        rows = [r for r in rows if r.get('strategy_id') == strategy_id]
    return jsonify(rows)


# ── Signal lineage ───────────────────────────────────────────────────────────

@bp.route('/lineage/<signal_id>')
def lineage(signal_id: str):
    if _db is None:
        return jsonify({'error': 'no_db'}), 503
    rec = _db.get_signal_lineage(signal_id)
    if rec is None:
        return jsonify({'error': 'not_found'}), 404
    # Deserialise JSON columns
    for col in ('indicators_json', 'risk_checks_json'):
        if rec.get(col):
            try:
                rec[col.replace('_json', '')] = json.loads(rec[col])
            except Exception:
                rec[col.replace('_json', '')] = {}
    # Attach trade outcome if available
    if rec.get('trade_id') and _db:
        match = _db.get_trade_by_id(rec['trade_id'])
        if match:
            rec['trade'] = {
                'entry_price': match.get('entry_price'),
                'exit_price':  match.get('exit_price'),
                'net_pnl':     match.get('net_pnl'),
                'exit_reason': match.get('exit_reason'),
                'side':        match.get('side'),
                'quantity':    match.get('quantity'),
            }
    return jsonify(rec)


# ── EventBus inspector ────────────────────────────────────────────────────────

@bp.route('/events')
def events():
    from terminal_in.api.event_buffer import get_recent
    limit = int(request.args.get('limit', 200))
    return jsonify(get_recent(limit))
