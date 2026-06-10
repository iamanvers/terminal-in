"""Recursive model-training endpoints (Module 4)."""

import json
import logging

from flask import Blueprint, jsonify, request

bp  = Blueprint('training', __name__, url_prefix='/api/training')
log = logging.getLogger(__name__)

_trainer = None


def init(trainer=None):
    global _trainer
    _trainer = trainer


@bp.route('/status')
def status():
    if _trainer is None:
        return jsonify({'state': 'unavailable'})
    return jsonify(_trainer.get_state())


@bp.route('/runs')
def runs():
    if _trainer is None:
        return jsonify([])
    limit = int(request.args.get('limit', 20))
    rows = _trainer.get_runs(limit=limit)
    for r in rows:
        if r.get('dataset_counts_json'):
            try:
                r['dataset_counts'] = json.loads(r['dataset_counts_json'])
            except Exception:
                pass
        r.pop('dataset_counts_json', None)
    return jsonify(rows)


@bp.route('/start', methods=['POST'])
def start():
    if _trainer is None:
        return jsonify({'ok': False, 'error': 'trainer unavailable'}), 503
    body = request.get_json(silent=True) or {}
    try:
        max_steps = int(body.get('max_steps', -1))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'invalid max_steps'}), 400
    result = _trainer.start(max_steps=max_steps)
    return jsonify(result), (200 if result.get('ok') else 409)


@bp.route('/stop', methods=['POST'])
def stop():
    if _trainer is None:
        return jsonify({'ok': False, 'error': 'trainer unavailable'}), 503
    return jsonify(_trainer.stop())
