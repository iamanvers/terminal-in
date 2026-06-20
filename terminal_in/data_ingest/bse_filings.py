"""BSE corporate-filings client — REAL firm documents for the knowledge plane.

Pulls the BSE corporate-announcement feed (the breadth source: results, board
meetings, corp actions, investor presentations, regulatory filings) and shapes each
into a point-in-time document for the firm-knowledge RAG. Complementary to the NSE
announcement archive (`events.py`) already ingested — BSE carries the richer subject /
body text and a PDF attachment link per filing.

DATA HONESTY (same discipline as events.py / fundamentals.py):
  - The BSE API is bot-hostile (returns an empty sentinel to non-browser clients), so
    requests carry browser-like headers + the bseindia.com Referer and a polite timeout.
    Any block / non-JSON / parse error yields [] — NEVER a fabricated document.
  - FAIL-CLOSED dating: a filing whose timestamp can't be parsed is DROPPED, not guessed
    (a wrongly-dated doc would leak the future into a point-in-time query).
  - Symbol→scrip-code mapping is required to query per company; an UNMAPPED symbol is
    skipped (logged), never queried against a guessed code (a wrong code would attribute
    another company's filings). The seed map is verifiable and overridable via
    data/knowledge/bse_scrip_codes.json.
  - This forward-accumulates: there is no honest bulk history here, only what we fetch
    going forward (or what a licensed dataset provides).
"""

from __future__ import annotations

import html as _html
import json as _json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_API = 'https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Referer': 'https://www.bseindia.com/corporates/ann.html',
    'Accept': 'application/json, text/plain, */*',
}
_ATTACH_BASE = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/'
_SCRIP_OVERRIDE = Path('./data/knowledge/bse_scrip_codes.json')

# Seed BSE scrip codes for the large-cap universe (verify against the BSE scrip master;
# overridable via the JSON file above). FAIL-CLOSED: symbols absent here are not queried.
BSE_SCRIP_CODES: dict[str, str] = {
    'RELIANCE': '500325', 'TCS': '532540', 'HDFCBANK': '500180', 'INFY': '500209',
    'ICICIBANK': '532174', 'HINDUNILVR': '500696', 'SBIN': '500112', 'BHARTIARTL': '532454',
    'ITC': '500875', 'KOTAKBANK': '500247', 'LT': '500510', 'AXISBANK': '532215',
    'BAJFINANCE': '500034', 'ASIANPAINT': '500820', 'MARUTI': '532500', 'SUNPHARMA': '524715',
    'TITAN': '500114', 'ULTRACEMCO': '532538', 'WIPRO': '507685', 'NESTLEIND': '500790',
    'ONGC': '500312', 'NTPC': '532555', 'POWERGRID': '532898', 'TATAMOTORS': '500570',
    'TATASTEEL': '500470', 'JSWSTEEL': '500228', 'HCLTECH': '532281', 'TECHM': '532755',
    'ADANIPORTS': '532921', 'COALINDIA': '533278', 'BAJAJFINSV': '532978', 'DRREDDY': '500124',
    'CIPLA': '500087', 'GRASIM': '500300', 'HINDALCO': '500440', 'DIVISLAB': '532488',
    'BRITANNIA': '500825', 'EICHERMOT': '505200', 'HEROMOTOCO': '500182', 'BAJAJ-AUTO': '532977',
    'INDUSINDBK': '532187', 'ADANIENT': '512599', 'M&M': '500520', 'APOLLOHOSP': '508869',
    'BPCL': '500547', 'TATACONSUM': '500800', 'HDFCLIFE': '540777', 'SBILIFE': '540719',
}

# BSE category → firm_store doc_type
_CATEGORY_MAP = [
    ('result',                 'results'),
    ('board meeting',          'board_meeting'),
    ('dividend',               'corp_action'),
    ('bonus',                  'corp_action'),
    ('split',                  'corp_action'),
    ('buyback',                'corp_action'),
    ('buy back',               'corp_action'),
    ('corp. action',           'corp_action'),
    ('corporate action',       'corp_action'),
    ('agm',                    'corp_action'),
    ('egm',                    'corp_action'),
    ('investor presentation',  'guidance'),
    ('analyst',                'guidance'),
    ('investor',               'guidance'),
    ('press release',          'guidance'),
    ('integrated filing',      'results'),
    ('regulation 30',          'regulatory'),
    ('insider',                'regulatory'),
    ('sebi',                   'regulatory'),
    ('compliance',             'regulatory'),
]


def _load_scrip_codes() -> dict[str, str]:
    codes = dict(BSE_SCRIP_CODES)
    if _SCRIP_OVERRIDE.exists():
        try:
            codes.update({str(k).upper(): str(v) for k, v in
                          _json.loads(_SCRIP_OVERRIDE.read_text()).items()})
        except Exception:
            log.warning('bse_filings: failed to read scrip-code override %s', _SCRIP_OVERRIDE)
    return codes


def scrip_code(symbol: str) -> str | None:
    return _load_scrip_codes().get(str(symbol).upper())


def doc_type_for(category: str, subject: str = '') -> str:
    t = (category or '').lower() or (subject or '').lower()
    for key, dtype in _CATEGORY_MAP:
        if key in t:
            return dtype
    return 'other'


def _parse_dt(v) -> date | None:
    """FAIL-CLOSED parse of a BSE filing timestamp to a date."""
    if not v:
        return None
    s = str(v).strip()
    s = s.split('T')[0].split(' ')[0] if ('T' in s or ' ' in s) else s
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d %b %Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', _html.unescape(text or ''))).strip()


def map_row(row: dict, symbol: str) -> dict | None:
    """Shape one BSE announcement row into a firm-knowledge document. Returns None
    (fail-closed) when the filing date is unparseable or there is no usable subject."""
    fd = _parse_dt(row.get('NEWS_DT') or row.get('DT_TM') or row.get('News_submission_dt')
                   or row.get('dt_tm'))
    subject = _clean(row.get('NEWSSUB') or row.get('HEADLINE') or '')
    if fd is None or not subject:
        return None
    body = _clean(row.get('MORE') or row.get('HEADLINE') or subject)
    category = row.get('CATEGORYNAME') or row.get('Category') or ''
    attach = (row.get('ATTACHMENTNAME') or '').strip()
    url = (_ATTACH_BASE + attach) if attach else ''
    return {
        'symbol': str(symbol).upper(), 'filing_date': fd.isoformat(),
        'doc_type': doc_type_for(category, subject), 'source': 'bse_filings',
        'title': subject[:240], 'body': body, 'url': url, 'confidence': 1.0,
    }


def enrich_with_pdf(docs: list[dict], session=None, max_chars: int = 12000) -> list[dict]:
    """Optional DEPTH: for filing docs that carry a PDF attachment URL, fetch the PDF and
    append its extracted text to the body (so the RAG sees the actual results/MD&A, not
    just the subject line). Best-effort + fail-soft — a blocked/oversized/garbled PDF
    leaves the doc unchanged. Requires pypdf (else no-op). Mutates docs in place."""
    from terminal_in.knowledge import pdf_extract
    if not pdf_extract.available():
        return docs
    try:
        import requests
    except ImportError:
        return docs
    sess = session or requests
    for d in docs:
        url = d.get('url') or ''
        if not url.lower().endswith('.pdf'):
            continue
        try:
            r = sess.get(url, headers=_HEADERS, timeout=20)
            r.raise_for_status()
            text = pdf_extract.extract_text(r.content, max_chars=max_chars)
            if text:
                d['body'] = (d.get('body', '') + '\n\n' + text).strip()[:max_chars]
        except Exception:
            log.debug('bse_filings: attachment fetch/parse failed for %s', url)
    return docs


def fetch_announcements(symbol: str, days: int = 30, session=None) -> list[dict]:
    """Fetch recent BSE corporate filings for `symbol` as point-in-time documents.
    Returns [] (graceful) for an unmapped symbol or any fetch/parse failure — the
    bot-hostile source is allowed to fail; it is never substituted with fabricated data."""
    code = scrip_code(symbol)
    if not code:
        return []
    try:
        import requests
    except ImportError:
        return []
    sess = session or requests
    today = date.today()
    params = {
        'pageno': 1, 'strCat': '-1', 'strType': 'C', 'strSearch': 'P',
        'strPrevDate': (today - timedelta(days=days)).strftime('%Y%m%d'),
        'strToDate': today.strftime('%Y%m%d'), 'strScrip': code,
    }
    try:
        r = sess.get(_API, params=params, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.debug('bse_filings: fetch failed for %s (%s): %s', symbol, code, str(e)[:90])
        return []
    rows = data.get('Table') or [] if isinstance(data, dict) else []
    out = []
    for row in rows:
        doc = map_row(row, symbol)
        if doc is not None:
            out.append(doc)
    log.info('bse_filings: %s (%s) → %d filings in last %dd', symbol, code, len(out), days)
    return out
