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


def _ollama_models() -> list[str]:
    """Installed Ollama models for the model dropdown. [] when offline."""
    import os

    import requests
    try:
        base = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
        r = requests.get(f'{base}/api/tags', timeout=2)
        return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        return []


@bp.route('', methods=['GET'])
def get_settings():
    if _db is None:
        return jsonify({'error': 'settings unavailable'}), 503
    items = app_settings.describe(_db)
    # Upgrade the model field to a dropdown of installed models when Ollama
    # is reachable (free text otherwise — validation stays permissive)
    models = _ollama_models()
    if models:
        for item in items:
            if item['env'] == 'OLLAMA_MODEL':
                if item['value'] not in models:
                    models = [item['value'], *models]
                item['type'] = 'select'
                item['options'] = models
    return jsonify({'settings': items})


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
