"""Operator settings endpoints (PRD 5b.2) — schema, values, updates."""

import logging

from flask import Blueprint, jsonify, request

from terminal_in import app_settings

bp  = Blueprint('settings', __name__, url_prefix='/api/settings')
log = logging.getLogger(__name__)

_db = None


def init(db=None):
    global _db
    _db = db


@bp.route('', methods=['GET'])
def get_settings():
    if _db is None:
        return jsonify({'error': 'settings unavailable'}), 503
    return jsonify({'settings': app_settings.describe(_db)})


@bp.route('', methods=['POST'])
def post_settings():
    if _db is None:
        return jsonify({'error': 'settings unavailable'}), 503
    changes = request.get_json(silent=True) or {}
    if not isinstance(changes, dict) or not changes:
        return jsonify({'error': 'expected a JSON object of {ENV_KEY: value}'}), 400
    try:
        result = app_settings.update(_db, changes)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, **result})
