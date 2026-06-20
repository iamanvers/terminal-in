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


@bp.route('/research', methods=['POST'])
def research():
    """PROFILE phase — map a firm's site once and do the initial ingest. Crawls the whole
    sitemap, ranks URLs against the collection spec, persists the per-ticker profile, and
    ingests the most relevant documents across all categories. Heavy; run periodically.
    Body: {"symbol": "HINDUNILVR"} or {"symbols": [...], "max_docs": 16}."""
    body = request.get_json(silent=True) or {}
    syms = body.get('symbols') or ([body['symbol']] if body.get('symbol') else [])
    if not syms:
        return jsonify({'error': 'symbol or symbols required'}), 400
    max_docs = int(body.get('max_docs', 16))
    try:
        from terminal_in.data_ingest.firm_research import profile_firm
        return jsonify({'results': [profile_firm(s, max_docs=max_docs) for s in syms]})
    except Exception as e:
        log.error('knowledge research (profile) failed: %s', e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/research/refresh', methods=['POST'])
def research_refresh():
    """REFRESH phase — using each firm's stored profile, re-check only the volatile/periodic
    links (news, updates, results, disclosures) and ingest just the deltas. Cheap; runs
    automatically each session for profiled firms. Body optional: {"symbols": [...]}."""
    body = request.get_json(silent=True) or {}
    syms = body.get('symbols') or _symbols
    try:
        from terminal_in.data_ingest.firm_research import refresh_firm, load_profile
        out = [refresh_firm(s) for s in syms if load_profile(s)]
        return jsonify({'refreshed': out, 'count': len(out)})
    except Exception as e:
        log.error('knowledge research refresh failed: %s', e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/profile')
def profile():
    """The stored per-ticker site profile (URL→category map + ingest state)."""
    sym = (request.args.get('symbol') or '').strip()
    if not sym:
        return jsonify({'error': 'symbol required'}), 400
    from terminal_in.data_ingest.firm_research import load_profile
    return jsonify(load_profile(sym) or {'symbol': sym.upper(), 'profiled': False})


@bp.route('/spec')
def spec():
    """The collection instruction set (categories, priorities, signals)."""
    from terminal_in.data_ingest.firm_research import collection_spec
    return jsonify(collection_spec())


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
