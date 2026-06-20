"""Firm-research collector (terminal_in/data_ingest/firm_research.py).

Sitemap parsing, relevance ranking, cadence, the profile→refresh two-phase pipeline,
and chunked storage — all against a MOCKED fetcher (no network).
"""

import io

from terminal_in.data_ingest import firm_research as fr
from terminal_in.knowledge.firm_store import FirmStore


def _make_pdf(text: str) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 740, text)
    c.save()
    return buf.getvalue()


def test_classify_ranks_by_spec():
    assert fr.classify('https://x.com/annual-report-2025.pdf')[0] == 'annual_report'
    assert fr.classify('https://x.com/investors/quarterly-results-q4fy25')[0] == 'financial_results'
    assert fr.classify('https://x.com/news/press-release/foo')[0] == 'press_release'
    assert fr.classify('https://x.com/contact-us') == (None, 0)
    assert fr.classify('https://x/annual-report.pdf')[1] > fr.classify('https://x/press-release/a')[1]


def test_cadence_drives_refresh_scope():
    assert fr.cadence_of('annual_report') == 'static'         # not re-checked each session
    assert fr.cadence_of('press_release') == 'volatile'       # re-checked each session
    assert fr.cadence_of('financial_results') == 'periodic'


def test_collection_spec_exhaustive_and_exposed():
    spec = fr.collection_spec()
    # a broad, exhaustive set of firm-intelligence categories
    for cat in ('annual_report', 'financial_results', 'press_release', 'regulatory_disclosure',
                'corporate_action', 'credit_rating', 'management_change', 'sustainability_esg'):
        assert cat in spec and 'cadence' in spec[cat] and spec[cat]['signals']


def test_parse_sitemap_per_block_dating():
    xml = ('<urlset><url><loc>https://x.com/a.pdf</loc><lastmod>2025-07-01</lastmod></url>'
           '<url><loc>https://x.com/b</loc></url>'                       # no lastmod → must stay None
           '<sitemap><loc>https://x.com/child.xml</loc></sitemap></urlset>')
    pairs, children = fr._parse_sitemap(xml)
    assert ('https://x.com/a.pdf', '2025-07-01') in pairs
    assert ('https://x.com/b', None) in pairs                            # no date inherited
    assert 'https://x.com/child.xml' in children


def test_firm_domain_known_and_unknown():
    assert fr.firm_domain('HINDUNILVR') == 'hul.co.in'
    assert fr.firm_domain('NOSUCHFIRM') is None


def test_html_to_text_strips_markup():
    t = fr._html_to_text('<html><script>x=1</script><p>Revenue grew &amp; margins rose</p></html>')
    assert 'Revenue grew & margins rose' in t and 'x=1' not in t


def _fake_get_factory(pdf_bytes, sitemap):
    def _fake_get(url, timeout=25, binary=False):
        if url.endswith('robots.txt'):
            return 200, 'Sitemap: https://x.com/sitemap.xml\n', {}
        if url.endswith('sitemap.xml'):
            return 200, sitemap, {}
        if url.endswith('.pdf'):
            return 200, pdf_bytes, {}
        if 'press-release' in url or '/news/' in url:
            return 200, '<html><p>press release: profit rose on retail strength</p></html>', {}
        if 'results-undated' in url:
            return 200, '<html><p>results page with no date anywhere</p></html>', {}
        return 404, None, {}
    return _fake_get


_SITEMAP = ('<urlset>'
            '<url><loc>https://x.com/annual-report-2025.pdf</loc><lastmod>2025-07-01</lastmod></url>'
            '<url><loc>https://x.com/news/press-release/q4</loc><lastmod>2025-06-01</lastmod></url>'
            '<url><loc>https://x.com/investors/results-undated</loc></url>'
            '<url><loc>https://x.com/contact</loc><lastmod>2025-01-01</lastmod></url>'
            '</urlset>')


def test_profile_firm_maps_and_ingests(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, 'PROFILE_DIR', tmp_path / 'profiles')
    monkeypatch.setattr(fr, '_get', _fake_get_factory(_make_pdf('annual report: revenue and profit grew'), _SITEMAP))
    store = FirmStore(tmp_path / 'kb.db')
    summary = fr.profile_firm('TESTCO', domain='x.com', store=store, delay_s=0, min_priority=55)
    # annual_report (pdf, dated) + press_release (html, dated) ingested; undated results dropped
    assert summary['documents'] == 2 and summary['dropped_undated'] == 1
    assert 'annual_report' in summary['categories_found']
    # the per-ticker profile was persisted with the URL→category map
    prof = fr.load_profile('TESTCO')
    assert prof['domain'] == 'x.com' and prof['ingested_urls']
    assert store.retrieve('TESTCO', 'revenue profit', k=5)


def test_refresh_only_volatile_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, 'PROFILE_DIR', tmp_path / 'profiles')
    store = FirmStore(tmp_path / 'kb.db')
    # seed a profile: annual report already ingested, press release seen at 2025-06-01
    (tmp_path / 'profiles').mkdir()
    import json
    (tmp_path / 'profiles' / 'TESTCO.json').write_text(json.dumps({
        'symbol': 'TESTCO', 'domain': 'x.com',
        'ingested_urls': ['https://x.com/annual-report-2025.pdf'],
        'lastmod_seen': {'https://x.com/news/press-release/q4': '2025-06-01'},
    }))
    # sitemap now shows the press release UPDATED (newer lastmod) + the static annual report
    updated = ('<urlset>'
               '<url><loc>https://x.com/annual-report-2025.pdf</loc><lastmod>2025-08-01</lastmod></url>'
               '<url><loc>https://x.com/news/press-release/q4</loc><lastmod>2025-06-20</lastmod></url>'
               '</urlset>')
    monkeypatch.setattr(fr, '_get', _fake_get_factory(_make_pdf('x'), updated))
    res = fr.refresh_firm('TESTCO', store=store, delay_s=0)
    # the updated VOLATILE press release is re-ingested; the STATIC annual report is skipped
    assert res['documents'] == 1 and res['refreshed'] is True


def test_collect_firm_unknown_domain_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, 'PROFILE_DIR', tmp_path / 'profiles')
    store = FirmStore(tmp_path / 'kb.db')
    res = fr.collect_firm('NOSUCHFIRM', store=store)
    assert res['error'] == 'no_domain' and res['documents'] == 0
