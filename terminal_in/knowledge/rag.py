"""RAG read surface over the firm-knowledge store.

Assembles a COMPACT, point-in-time, citation-tagged context block from the vector-less
store — the grounded "critical info" the AI analyst (and, later, the M6 judge) reads
before reasoning about a firm. Lexical BM25 retrieval (no embeddings); every snippet
is stamped with its source, filing date, and a confidence label so the model — and the
reader — can see provenance and never mistake a news rumour for a filed result.

POINT-IN-TIME: pass `as_of` for any backtest/decision-time call so the context can
never contain a document filed after the decision date.
"""

from __future__ import annotations

from terminal_in.knowledge.firm_store import FirmStore, default_store

_CONF_LABEL = [(0.9, 'filed'), (0.6, 'reported'), (0.0, 'unverified')]


def _conf_label(c: float) -> str:
    for thr, lab in _CONF_LABEL:
        if c >= thr:
            return lab
    return 'unverified'


def build_context(symbol: str, query: str, as_of=None, k: int = 6,
                  budget_chars: int = 2000, store: FirmStore | None = None,
                  doc_types: tuple[str, ...] | None = None) -> dict:
    """Retrieve the top-k firm documents for (symbol, query) and assemble a grounded
    context block within `budget_chars`. Returns:
      {context: str, citations: [...], n: int, as_of: str|None, truncated: bool}
    `context` is empty (with a note) when nothing relevant is on file — honest, never
    a hallucinated filler."""
    store = store or default_store()
    docs = store.retrieve(symbol, query, as_of=as_of, k=k, doc_types=doc_types)
    if not docs:
        return {'context': '', 'citations': [], 'n': 0,
                'as_of': str(as_of) if as_of is not None else None, 'truncated': False,
                'note': f'no firm documents on file for {symbol} matching the query'
                        + (f' as of {as_of}' if as_of is not None else '')}
    lines, cites, used, truncated = [], [], 0, False
    header = f'FIRM CONTEXT — {symbol.upper()} (retrieved, point-in-time' + (
        f' as of {as_of}' if as_of is not None else '') + '):'
    for i, d in enumerate(docs, 1):
        text = (d.get('text') or '').strip()
        if not text:
            continue
        tag = f"[{i}] {d['filing_date']} · {d['doc_type']} · {d['source']} · {_conf_label(d['confidence'])}"
        block = f'{tag}\n{text}'
        if used + len(block) > budget_chars and lines:
            truncated = True
            break
        lines.append(block)
        used += len(block)
        cites.append({'n': i, 'doc_id': d['doc_id'], 'filing_date': d['filing_date'],
                      'doc_type': d['doc_type'], 'source': d['source'], 'url': d.get('url', ''),
                      'confidence': d['confidence']})
    context = header + '\n\n' + '\n\n'.join(lines) if lines else ''
    return {'context': context, 'citations': cites, 'n': len(cites),
            'as_of': str(as_of) if as_of is not None else None, 'truncated': truncated}
