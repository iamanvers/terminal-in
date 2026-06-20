"""Firm-knowledge plane — vector-less PIT RAG store, ingest, and retrieval.

Guards the three hard properties: point-in-time no-lookahead, fail-closed dating,
and the rolling 5-year compress-then-purge retention. No network, no main DB.
"""

from datetime import date, timedelta

import pytest

from terminal_in.knowledge.firm_store import FirmStore
from terminal_in.knowledge import rag
from terminal_in.knowledge.ingest import EventsAdapter, run_ingest, BseFilingsAdapter, IrPdfAdapter


@pytest.fixture
def store(tmp_path):
    return FirmStore(tmp_path / 'fk.db')


def _doc(symbol, filing_date, title, body, **kw):
    return {'symbol': symbol, 'filing_date': filing_date, 'title': title, 'body': body,
            'source': kw.get('source', 'test'), 'doc_type': kw.get('doc_type', 'results'),
            'confidence': kw.get('confidence', 1.0)}


def test_record_and_bm25_retrieval_ranks_relevance(store):
    store.record_documents([
        _doc('RELIANCE', '2024-05-01', 'Q4 results', 'revenue growth strong jio retail margins'),
        _doc('RELIANCE', '2024-02-01', 'Board meeting', 'board approved capex for telecom rollout'),
    ])
    hits = store.retrieve('RELIANCE', 'revenue growth', k=5)
    assert hits and hits[0]['title'] == 'Q4 results'      # the revenue doc ranks first


def test_long_document_is_chunked(store):
    # a long heterogeneous body is split into overlapping chunks (one FTS row each),
    # so retrieval returns the relevant chunk, not the whole report
    body = (('Revenue analysis. ' * 60) + ('Margin commentary on guidance. ' * 60)
            + ('Debt and capex outlook. ' * 60))
    store.record_documents([_doc('RELIANCE', '2024-05-01', 'FY24 annual report', body)],
                           chunk_chars=400)
    rows = store.retrieve('RELIANCE', 'capex debt outlook', k=10)
    assert len(rows) >= 3                                   # chunked into several rows
    assert all('[' in r['title'] and '/' in r['title'] for r in rows)   # 'title [i/n]'
    # the chunk about capex/debt ranks at the top for that query
    assert 'debt' in rows[0]['text'].lower() or 'capex' in rows[0]['text'].lower()


def test_short_document_not_chunked(store):
    store.record_documents([_doc('TCS', '2024-05-01', 'short', 'revenue grew on deal wins')])
    rows = store.retrieve('TCS', 'revenue', k=5)
    assert len(rows) == 1 and '[' not in rows[0]['title']   # single row, no chunk suffix


def test_point_in_time_excludes_future_filings(store):
    store.record_documents([
        _doc('TCS', '2024-05-01', 'FY24 results', 'revenue up deal wins'),
        _doc('TCS', '2025-05-01', 'FY25 results', 'revenue up again'),
    ])
    # as-of before the 2025 filing → it must be invisible (no lookahead)
    hits = store.retrieve('TCS', 'revenue', as_of='2024-12-31', k=5)
    assert len(hits) == 1 and hits[0]['filing_date'] == '2024-05-01'
    # without as_of, both are visible
    assert len(store.retrieve('TCS', 'revenue', k=5)) == 2


def test_fail_closed_on_unparseable_date(store):
    res = store.record_documents([
        {'symbol': 'INFY', 'filing_date': 'not-a-date', 'title': 'x', 'body': 'revenue'},
        {'symbol': 'INFY', 'filing_date': None, 'title': 'y', 'body': 'revenue'},
        {'symbol': '', 'filing_date': '2024-01-01', 'title': 'z', 'body': 'revenue'},  # no symbol
        _doc('INFY', '2024-01-01', 'good', 'revenue rises'),
    ])
    assert res['ingested'] == 1 and res['dropped_unverifiable'] == 3


def test_idempotent_reingest_no_duplicates(store):
    d = _doc('SBIN', '2024-06-01', 'Results', 'net profit higher')
    store.record_documents([d])
    store.record_documents([d])           # same filing again
    assert store.count() == 1


def test_symbol_isolation(store):
    store.record_documents([
        _doc('A', '2024-01-01', 'r', 'revenue growth'),
        _doc('B', '2024-01-01', 'r', 'revenue growth'),
    ])
    hits = store.retrieve('A', 'revenue', k=5)
    assert len(hits) == 1 and hits[0]['symbol'] == 'A'


def test_compaction_compresses_mid_band_and_purges_beyond_horizon(store):
    today = date(2026, 6, 19)
    recent = today.isoformat()
    mid = (today - timedelta(days=800)).isoformat()       # in 13mo..5y band → compress
    old = (today - timedelta(days=2200)).isoformat()      # > 5y → purge
    store.record_documents([
        _doc('X', recent, 'recent', 'revenue alpha keyword'),
        _doc('X', mid, 'mid', 'revenue beta keyword'),
        _doc('X', old, 'old', 'revenue gamma keyword'),
    ])
    res = store.compact(now=today)
    assert res['purged'] == 1 and res['compressed'] == 1
    assert store.count() == 2                             # old purged
    # the compressed doc keeps a (searchable) summary but its body is dropped
    mid_hit = [h for h in store.retrieve('X', 'beta', k=5)]
    assert mid_hit and mid_hit[0]['compacted'] == 1 and mid_hit[0]['body'] == ''
    assert 'beta' in mid_hit[0]['summary']
    # the recent doc keeps full body
    rec_hit = store.retrieve('X', 'alpha', k=5)[0]
    assert rec_hit['compacted'] == 0 and 'revenue alpha keyword' in rec_hit['body']


def test_query_sanitised_against_fts_injection(store):
    store.record_documents([_doc('Q', '2024-01-01', 'r', 'revenue growth')])
    # punctuation/operators in the query must not raise or inject FTS syntax
    assert store.retrieve('Q', 'revenue) OR "', k=5)                     # still finds it
    assert store.retrieve('Q', '*** ^^^ ()', k=5) == []                  # no real tokens → empty


def test_rag_build_context_citations_and_pit(store):
    store.record_documents([
        _doc('HDFCBANK', '2024-04-20', 'Q4 results', 'net interest income grew, deposits strong'),
        _doc('HDFCBANK', '2025-04-20', 'Q1 results', 'net interest income grew again'),
    ])
    ctx = rag.build_context('HDFCBANK', 'net interest income', as_of='2024-12-31', store=store)
    assert ctx['n'] == 1                                    # PIT: 2025 filing excluded
    assert 'FIRM CONTEXT' in ctx['context'] and 'HDFCBANK' in ctx['context']
    assert ctx['citations'][0]['filing_date'] == '2024-04-20'


def test_rag_empty_is_honest_not_hallucinated(store):
    ctx = rag.build_context('NOBODY', 'revenue', store=store)
    assert ctx['n'] == 0 and ctx['context'] == '' and 'no firm documents' in ctx['note']


def test_events_adapter_maps_archive_rows(monkeypatch, store):
    import pandas as pd
    from terminal_in.data_ingest import events as ev
    fake = pd.DataFrame([
        {'symbol': 'RELIANCE', 'announce_ts': '2024-05-01T18:00:00', 'announce_date': '2024-05-01',
         'event_type': 'results', 'subject': 'Audited financial results for Q4', 'as_reported': None,
         'consensus': None},
        {'symbol': 'RELIANCE', 'announce_ts': '2024-03-01T10:00:00', 'announce_date': '2024-03-01',
         'event_type': 'corp_action', 'subject': 'Dividend declared', 'as_reported': None,
         'consensus': None},
    ])
    monkeypatch.setattr(ev, 'load_events', lambda: fake)
    rows = EventsAdapter().fetch(['RELIANCE'])
    assert len(rows) == 2 and all(r['source'] == 'nse_events' for r in rows)
    res = run_ingest(['RELIANCE'], store=store, adapters=[EventsAdapter()])
    assert res['ingested'] == 2
    assert store.retrieve('RELIANCE', 'dividend', k=5)


def test_adapters_degrade_gracefully_without_data(store, tmp_path, monkeypatch):
    # unmapped symbol → BSE adapter never queries (no scrip code), returns nothing
    assert BseFilingsAdapter().fetch(['NOSUCHSYMBOL']) == []
    # IR-PDF adapter is config/folder-driven; with neither present it no-ops
    monkeypatch.setattr(IrPdfAdapter, 'LOCAL_DIR', str(tmp_path / 'empty'))
    monkeypatch.setattr(IrPdfAdapter, 'CONFIG', str(tmp_path / 'none.json'))
    assert IrPdfAdapter().fetch(['RELIANCE']) == []


def _make_pdf(text: str) -> bytes:
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, line in enumerate(text.split('\n')):
        c.drawString(72, 740 - i * 16, line)
    c.save()
    return buf.getvalue()


def test_pdf_extract_roundtrip():
    from terminal_in.knowledge import pdf_extract
    assert pdf_extract.available()
    txt = pdf_extract.extract_text(_make_pdf('Quarterly revenue grew on retail and telecom'))
    assert 'revenue grew' in txt.lower()


def test_ir_pdf_local_folder_ingest(tmp_path, monkeypatch, store):
    """Turnkey firm-specific ingest: a real PDF dropped in the local folder is
    extracted, dated from its filename (fail-closed), classified, and stored/retrievable."""
    docs = tmp_path / 'ir_docs'
    docs.mkdir()
    (docs / 'RELIANCE__2024-05-06__Q4-results.pdf').write_bytes(
        _make_pdf('Consolidated net profit rose; Jio and retail drove revenue growth'))
    (docs / 'UNDATABLE_noformat.pdf').write_bytes(_make_pdf('no date in name'))  # fail-closed skip
    monkeypatch.setattr(IrPdfAdapter, 'LOCAL_DIR', str(docs))
    monkeypatch.setattr(IrPdfAdapter, 'CONFIG', str(tmp_path / 'none.json'))

    rows = IrPdfAdapter().fetch(['RELIANCE'])
    assert len(rows) == 1
    d = rows[0]
    assert d['symbol'] == 'RELIANCE' and d['filing_date'] == '2024-05-06'
    assert d['doc_type'] == 'results' and 'profit' in d['body'].lower()
    # end-to-end: store + RAG retrieval
    res = run_ingest(['RELIANCE'], store=store, adapters=[IrPdfAdapter()])
    assert res['ingested'] == 1
    assert store.retrieve('RELIANCE', 'jio retail revenue', k=3)


def test_analyst_injects_firm_context(monkeypatch, store):
    """The AI analyst grounds firm questions in the RAG block, and stays silent
    (no block) when nothing matches — without calling Ollama."""
    from terminal_in.knowledge import rag
    from terminal_in.agents import financial_agent as fa
    store.record_documents([_doc('RELIANCE', '2024-05-01', 'Q4 results',
                                  'consolidated revenue grew on jio and retail')])
    monkeypatch.setattr(rag, 'default_store', lambda: store)
    monkeypatch.setattr(fa, 'get_all_symbols', lambda: ['RELIANCE', 'TCS'])

    block = fa._firm_context('what is the revenue outlook for RELIANCE?')
    assert 'FIRM CONTEXT' in block and 'RELIANCE' in block and 'revenue' in block.lower()
    # no firm named → no firm block
    assert fa._firm_context('how does the regime classifier work?') == ''
