"""Firm-knowledge plane — vector-less PIT RAG store, ingest, and retrieval.

Guards the three hard properties: point-in-time no-lookahead, fail-closed dating,
and the rolling 5-year compress-then-purge retention. No network, no main DB.
"""

from datetime import date, timedelta

import pytest

from terminal_in.knowledge.firm_store import FirmStore
from terminal_in.knowledge import rag
from terminal_in.knowledge.ingest import EventsAdapter, run_ingest, BseXbrlAdapter


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


def test_forward_accumulate_stub_returns_nothing(store):
    # the bot-hostile sources never fabricate history
    assert BseXbrlAdapter().fetch(['RELIANCE']) == []
