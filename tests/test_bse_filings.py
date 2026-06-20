"""BSE corporate-filings client (terminal_in/data_ingest/bse_filings.py).

Pure parsing/mapping + the fetch path against an INJECTED fake session — no network.
Guards the point-in-time + fail-closed discipline for the bot-hostile source.
"""

from terminal_in.data_ingest import bse_filings as bse


def test_scrip_code_known_and_unknown():
    assert bse.scrip_code('RELIANCE') == '500325'
    assert bse.scrip_code('reliance') == '500325'        # case-insensitive
    assert bse.scrip_code('NOSUCHSYMBOL') is None         # unmapped → fail-closed upstream


def test_doc_type_mapping():
    assert bse.doc_type_for('Result') == 'results'
    assert bse.doc_type_for('Board Meeting') == 'board_meeting'
    assert bse.doc_type_for('Dividend') == 'corp_action'
    assert bse.doc_type_for('Investor Presentation') == 'guidance'
    assert bse.doc_type_for('Regulation 30') == 'regulatory'
    assert bse.doc_type_for('Something Unmapped') == 'other'


def test_map_row_shapes_document():
    row = {'NEWS_DT': '2024-05-01T18:30:00', 'NEWSSUB': 'Audited Financial Results Q4',
           'MORE': 'The board approved the <b>audited</b> results for the quarter.',
           'CATEGORYNAME': 'Result', 'ATTACHMENTNAME': 'abc123.pdf'}
    doc = bse.map_row(row, 'RELIANCE')
    assert doc['symbol'] == 'RELIANCE' and doc['filing_date'] == '2024-05-01'
    assert doc['doc_type'] == 'results' and doc['source'] == 'bse_filings'
    assert 'audited' in doc['body'] and '<b>' not in doc['body']      # HTML stripped
    assert doc['url'].endswith('abc123.pdf') and doc['confidence'] == 1.0


def test_map_row_fail_closed_on_bad_date_or_empty_subject():
    assert bse.map_row({'NEWS_DT': 'not-a-date', 'NEWSSUB': 'x'}, 'TCS') is None
    assert bse.map_row({'NEWS_DT': '2024-05-01', 'NEWSSUB': ''}, 'TCS') is None


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []
    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        return _FakeResp(self._payload)


def test_fetch_announcements_with_injected_session():
    payload = {'Table': [
        {'NEWS_DT': '2024-05-01T18:30:00', 'NEWSSUB': 'Q4 Results', 'MORE': 'revenue grew',
         'CATEGORYNAME': 'Result', 'ATTACHMENTNAME': 'r.pdf'},
        {'NEWS_DT': 'garbage', 'NEWSSUB': 'dropme', 'CATEGORYNAME': 'Result'},   # fail-closed
    ]}
    sess = _FakeSession(payload)
    out = bse.fetch_announcements('RELIANCE', days=30, session=sess)
    assert len(out) == 1 and out[0]['doc_type'] == 'results'
    # it queried with RELIANCE's scrip code
    assert sess.calls and sess.calls[0][1]['strScrip'] == '500325'


def test_fetch_unmapped_symbol_never_queries():
    sess = _FakeSession({'Table': []})
    assert bse.fetch_announcements('NOSUCHSYMBOL', session=sess) == []
    assert sess.calls == []                              # no scrip code → no request made
