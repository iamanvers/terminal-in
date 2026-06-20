"""
Firm-knowledge RAG endpoints.

GET  /api/knowledge/coverage          — store coverage + honesty report
GET  /api/knowledge/search?symbol=&q= — point-in-time retrieval (debug/inspection)
POST /api/knowledge/ingest            — run the ingest adapters now (on-demand; the
                                        KnowledgeIngestor otherwise runs on a 24h cadence)
"""

import logging
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

bp = Blueprint('knowledge', __name__, url_prefix='/api/knowledge')

_db = None
_symbols: list[str] = []


def init(db=None, symbols=None):
    global _db, _symbols
    _db = db
    _symbols = list(symbols or [])


@bp.route('/coverage')
def coverage():
    try:
        from terminal_in.knowledge.firm_store import default_store
        return jsonify(default_store().coverage())
    except Exception as e:
        log.warning('knowledge coverage failed: %s', e)
        return jsonify({'rows': 0, 'error': str(e)}), 500


@bp.route('/search')
def search():
    symbol = (request.args.get('symbol') or '').strip() or None
    q = (request.args.get('q') or '').strip()
    as_of = (request.args.get('as_of') or '').strip() or None
    k = int(request.args.get('k', 6))
    if not q:
        return jsonify({'error': 'q required'}), 400
    from terminal_in.knowledge.rag import build_context
    return jsonify(build_context(symbol or '', q, as_of=as_of, k=k))


@bp.route('/ingest', methods=['POST'])
def ingest():
    """Run the firm-knowledge ingest adapters once, now. Returns the per-adapter +
    compaction honesty summary. Optional JSON body: {"symbols": [...]} to scope it."""
    body = request.get_json(silent=True) or {}
    symbols = body.get('symbols') or _symbols
    try:
        from terminal_in.knowledge.ingest import run_ingest
        return jsonify(run_ingest(symbols, db=_db))
    except Exception as e:
        log.error('knowledge ingest failed: %s', e, exc_info=True)
        return jsonify({'error': str(e)}), 500
