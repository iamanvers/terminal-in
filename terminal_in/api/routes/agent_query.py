"""
Financial agent query endpoint.
POST /api/agents/query   — run natural-language query against the financial agent
GET  /api/agents/symbols/search?q=...  — search NSE symbols
GET  /api/agents/ollama/status         — check if Ollama is online
"""

import logging
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

bp = Blueprint('agent_query', __name__, url_prefix='/api/agents')


@bp.route('/query', methods=['POST'])
def query():
    body = request.get_json(silent=True) or {}
    text = (body.get('query') or body.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'query required'}), 400

    history = body.get('history') or []

    try:
        from terminal_in.agents.financial_agent import get_agent
        agent  = get_agent()
        result = agent.query(text, history=history)
        return jsonify(result)
    except Exception as e:
        log.error(f'Agent query failed: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/query/stream', methods=['POST'])
def query_stream():
    """NDJSON streaming variant — one JSON event per line:
    {'type':'tool'|'token'|'done'|'error', ...}. The UI renders tokens as
    they arrive instead of waiting out the full generation."""
    body = request.get_json(silent=True) or {}
    text = (body.get('query') or body.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'query required'}), 400
    history = body.get('history') or []

    from flask import Response, stream_with_context
    import json as _json
    from terminal_in.agents.financial_agent import get_agent

    def gen():
        for event in get_agent().query_stream(text, history=history):
            yield _json.dumps(event) + '\n'

    return Response(stream_with_context(gen()), mimetype='application/x-ndjson',
                    headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


@bp.route('/symbols/search')
def symbol_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    try:
        from terminal_in.data_ingest.nse_symbols import search
        results = search(q, max_results=int(request.args.get('limit', 15)))
        return jsonify(results)
    except Exception as e:
        log.error(f'Symbol search failed: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/ollama/status')
def ollama_status():
    try:
        from terminal_in.agents.financial_agent import _ollama_available, OLLAMA_MODEL, OLLAMA_BASE
        online = _ollama_available()
        return jsonify({
            'online': online,
            'model':  OLLAMA_MODEL,
            'host':   OLLAMA_BASE,
        })
    except Exception as e:
        return jsonify({'online': False, 'error': str(e)}), 500
