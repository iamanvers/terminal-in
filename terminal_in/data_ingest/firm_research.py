"""Firm-research collector — an autonomous firm-intelligence gatherer.

Given a firm (symbol + corporate domain) this reads the site's robots.txt and
sitemap(s), RANKS every URL against an explicit, exhaustive collection spec, fetches
the most relevant documents (annual reports, results, presentations, transcripts, press
releases, disclosures, corporate actions, ratings, governance, ...), extracts their
text, dates them POINT-IN-TIME, chunks them, and writes them into the firm-knowledge
store for the RAG.

Two-phase cadence (every firm's sitemap differs, so we learn its shape once then watch
the volatile parts):
  - PROFILE (run periodically, e.g. weekly): crawl the whole sitemap, map which URL
    patterns hold which data category, persist that per-ticker profile, and do the
    initial ingest. This figures out the firm's "map pattern".
  - REFRESH (every session): using the stored profile, re-check only the VOLATILE /
    PERIODIC links (news, firm updates, results, disclosures — not annual reports) for
    new or newer items, and ingest just the deltas. Cheap and frequent.

Fetching uses `curl_cffi` with a real browser TLS profile so WAF-protected corporate
sites (Akamai/Cloudflare) serve the page; it falls back to plain requests.

HARD RULES (never violated — same discipline as events.py / fundamentals.py):
  - REAL DATA ONLY: store exactly what the firm published; never synthesise content.
  - POINT-IN-TIME, FAIL-CLOSED: every document needs a real date (sitemap <lastmod> →
    PDF /CreationDate → HTTP Last-Modified). Undatable ⇒ DROPPED, never guessed.
  - POLITE: obey robots.txt, identify honestly, rate-limit, bound the crawl. Read-only.
  - DOMAIN MUST BE KNOWN: an unmapped firm is skipped — never guess a domain.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

# ── The instruction set: an exhaustive map of firm-intelligence categories ──────────
# Each: priority (ranking weight), doc_type (→ firm_store), cadence (how often it
# changes → drives what REFRESH re-checks), and signals (URL/link-text keywords).
#   cadence: 'volatile' = check every session · 'periodic' = quarterly-ish · 'static' = rare
COLLECTION_SPEC: dict[str, dict] = {
    'annual_report':         {'priority': 100, 'doc_type': 'results', 'cadence': 'static',
                              'keywords': ('annual-report', 'annual report', 'integrated-report',
                                           'integrated annual', 'annualreport')},
    'financial_results':     {'priority': 96, 'doc_type': 'results', 'cadence': 'periodic',
                              'keywords': ('financial-result', 'financial results', 'quarterly-result',
                                           'quarterly results', 'earnings', 'q1fy', 'q2fy', 'q3fy',
                                           'q4fy', 'results-', 'financial-statement', 'balance-sheet',
                                           'profit-and-loss', 'income-statement')},
    'investor_presentation': {'priority': 88, 'doc_type': 'guidance', 'cadence': 'periodic',
                              'keywords': ('investor-presentation', 'investor presentation',
                                           'analyst-presentation', 'investor-day', 'investor day',
                                           'earnings-presentation', 'investor-update', 'factsheet')},
    'earnings_transcript':   {'priority': 84, 'doc_type': 'guidance', 'cadence': 'periodic',
                              'keywords': ('transcript', 'earnings-call', 'earnings call', 'concall',
                                           'conference-call', 'conference call', 'con-call', 'audio')},
    'regulatory_disclosure': {'priority': 78, 'doc_type': 'regulatory', 'cadence': 'volatile',
                              'keywords': ('disclosure', 'intimation', 'regulation-30', 'reg-30',
                                           'stock-exchange', 'sebi', 'lodr', 'compliance',
                                           'corporate-announcement')},
    'corporate_action':      {'priority': 72, 'doc_type': 'corp_action', 'cadence': 'periodic',
                              'keywords': ('dividend', 'bonus', 'buyback', 'buy-back', 'stock-split',
                                           'sub-division', 'record-date', 'scheme-of-arrangement',
                                           'rights-issue', 'demerger')},
    'mergers_acquisitions':  {'priority': 70, 'doc_type': 'news', 'cadence': 'volatile',
                              'keywords': ('acquisition', 'merger', 'amalgamation', 'divest',
                                           'stake-sale', 'stake-acquisition', 'joint-venture')},
    'management_change':     {'priority': 66, 'doc_type': 'news', 'cadence': 'volatile',
                              'keywords': ('appointment', 'resignation', 'cessation', 'board-change',
                                           'new-ceo', 'new-cfo', 'kmp', 'reconstitution')},
    'press_release':         {'priority': 62, 'doc_type': 'news', 'cadence': 'volatile',
                              'keywords': ('press-release', 'press release', 'media-release',
                                           'news-release', 'newsroom', 'press-note', '/news/', 'media-center')},
    'product_launch':        {'priority': 58, 'doc_type': 'news', 'cadence': 'volatile',
                              'keywords': ('launch', 'new-product', 'product-launch', 'unveil', 'introduces')},
    'credit_rating':         {'priority': 55, 'doc_type': 'rating_change', 'cadence': 'periodic',
                              'keywords': ('credit-rating', 'credit rating', 'rating-rationale', 'ratings')},
    'shareholding_pattern':  {'priority': 50, 'doc_type': 'regulatory', 'cadence': 'periodic',
                              'keywords': ('shareholding', 'shareholding-pattern', 'ownership')},
    'agm_egm':               {'priority': 48, 'doc_type': 'corp_action', 'cadence': 'periodic',
                              'keywords': ('agm', 'egm', 'postal-ballot', 'notice-of-meeting',
                                           'annual-general-meeting', 'extraordinary-general')},
    'governance_policy':     {'priority': 42, 'doc_type': 'regulatory', 'cadence': 'static',
                              'keywords': ('corporate-governance', 'code-of-conduct', 'policy', 'policies',
                                           'board-of-director', 'committee', 'whistle-blower')},
    'sustainability_esg':    {'priority': 40, 'doc_type': 'business_profile', 'cadence': 'static',
                              'keywords': ('sustainability', 'esg', 'responsibility', 'brsr', 'csr',
                                           'sustainability-report')},
    'business_profile':      {'priority': 30, 'doc_type': 'business_profile', 'cadence': 'static',
                              'keywords': ('about-us', 'our-business', 'segment', 'brands', 'products',
                                           'strategy', 'business-overview', 'our-company')},
}
_VOLATILE = {'volatile', 'periodic'}          # what REFRESH re-checks each session

# Seed firm → corporate domain (verify; override/extend via data/knowledge/firm_domains.json).
# FAIL-CLOSED: a symbol absent here (and from the override) is NOT crawled.
FIRM_DOMAINS: dict[str, str] = {
    'HINDUNILVR': 'hul.co.in', 'RELIANCE': 'ril.com', 'TCS': 'tcs.com', 'INFY': 'infosys.com',
    'WIPRO': 'wipro.com', 'HCLTECH': 'hcltech.com', 'TECHM': 'techmahindra.com',
    'ITC': 'itcportal.com', 'MARUTI': 'marutisuzuki.com', 'TITAN': 'titancompany.in',
    'ASIANPAINT': 'asianpaints.com', 'NESTLEIND': 'nestle.in', 'SUNPHARMA': 'sunpharma.com',
    'DRREDDY': 'drreddys.com', 'CIPLA': 'cipla.com', 'TATASTEEL': 'tatasteel.com',
    'TATAMOTORS': 'tatamotors.com', 'LT': 'larsentoubro.com', 'BHARTIARTL': 'airtel.in',
}
_DOMAIN_OVERRIDE = Path('./data/knowledge/firm_domains.json')
PROFILE_DIR = Path('./data/knowledge/profiles')

_BROWSER_PROFILE = 'chrome'    # curl_cffi TLS profile (clears Akamai/Cloudflare WAFs)
_MAX_SITEMAP_DOCS = 25_000
_MAX_PDF_BYTES = 45 * 1024 * 1024
_PDF_RE = re.compile(r'\.pdf($|[?#])', re.I)


def collection_spec() -> dict:
    """Expose the instruction set (categories, priorities, cadence, doc_types, signals)."""
    return {k: {'priority': v['priority'], 'doc_type': v['doc_type'], 'cadence': v['cadence'],
                'signals': list(v['keywords'])} for k, v in COLLECTION_SPEC.items()}


def firm_domain(symbol: str) -> str | None:
    codes = dict(FIRM_DOMAINS)
    if _DOMAIN_OVERRIDE.exists():
        try:
            codes.update({str(k).upper(): str(v) for k, v in
                          json.loads(_DOMAIN_OVERRIDE.read_text()).items()})
        except Exception:
            log.warning('firm_research: failed to read %s', _DOMAIN_OVERRIDE)
    return codes.get(str(symbol).upper())


# ── HTTP (clears WAFs via a real browser TLS profile) ──────────────────────────────
def _get(url: str, timeout: int = 25, binary: bool = False):
    """Fetch via curl_cffi with a browser TLS profile (so WAF-protected sites respond),
    falling back to requests. Returns (status, content_or_text, headers) or (None, None, {})."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, impersonate=_BROWSER_PROFILE, timeout=timeout, allow_redirects=True)
        return r.status_code, (r.content if binary else r.text), dict(r.headers)
    except Exception:
        pass
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'})
        return r.status_code, (r.content if binary else r.text), dict(r.headers)
    except Exception:
        log.debug('firm_research: fetch failed %s', url, exc_info=True)
        return None, None, {}


# ── sitemap discovery ───────────────────────────────────────────────────────────
def _sitemap_urls_from_robots(base: str) -> list[str]:
    rp = RobotFileParser()
    status, text, _ = _get(urljoin(base, '/robots.txt'), timeout=15)
    maps = []
    if status == 200 and text:
        try:
            rp.parse(text.splitlines())
            maps = list(rp.site_maps() or [])
        except Exception:
            maps = [ln.split(':', 1)[1].strip() for ln in text.splitlines()
                    if ln.lower().startswith('sitemap:')]
    return maps or [urljoin(base, '/sitemap.xml')]


def _parse_sitemap(content: bytes | str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Return (urls_with_lastmod, child_sitemaps). Handles .gz; parses PER <url> block so
    a URL lacking <lastmod> can't inherit a neighbour's date."""
    if isinstance(content, bytes):
        if content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        content = content.decode('utf-8', 'replace') if isinstance(content, bytes) else content
    children = []
    for block in re.findall(r'(?is)<sitemap\b.*?</sitemap>', content):
        m = re.search(r'<loc>\s*([^<]+?)\s*</loc>', block, re.I)
        if m:
            children.append(m.group(1).strip())
    pairs = []
    for block in re.findall(r'(?is)<url\b.*?</url>', content):
        m = re.search(r'<loc>\s*([^<]+?)\s*</loc>', block, re.I)
        if not m:
            continue
        loc = m.group(1).strip()
        if loc.lower().endswith(('.xml', '.xml.gz')):
            children.append(loc)
            continue
        lm = re.search(r'<lastmod>\s*([^<]+?)\s*</lastmod>', block, re.I)
        pairs.append((loc, lm.group(1).strip() if lm else None))
    return pairs, children


def discover_urls(domain: str, max_urls: int = _MAX_SITEMAP_DOCS) -> list[tuple[str, str | None]]:
    """Enumerate the firm site's URLs (+ <lastmod>) via robots → sitemap(s), following one
    level of sitemap-index nesting. Bounded and fail-soft."""
    base = f'https://{domain}'
    seen, out, queue, visited = set(), [], list(_sitemap_urls_from_robots(base)), 0
    while queue and len(out) < max_urls and visited < 60:
        sm = queue.pop(0)
        visited += 1
        status, content, _ = _get(sm, timeout=20, binary=sm.lower().endswith('.gz'))
        if status != 200 or not content:
            continue
        pairs, children = _parse_sitemap(content)
        for u, lm in pairs:
            if u not in seen:
                seen.add(u)
                out.append((u, lm))
        queue.extend(c for c in children if c not in seen)
    return out[:max_urls]


# ── relevance ranking ──────────────────────────────────────────────────────────
def classify(url: str, link_text: str = '') -> tuple[str | None, int]:
    """Best (category, priority) for a URL/link by the COLLECTION_SPEC signals; (None,0)
    if irrelevant. PDFs get a small boost (richer than a landing page)."""
    hay = (url + ' ' + link_text).lower()
    best_cat, best_pri = None, 0
    for cat, spec in COLLECTION_SPEC.items():
        if any(k in hay for k in spec['keywords']) and spec['priority'] > best_pri:
            best_cat, best_pri = cat, spec['priority']
    if best_cat and _PDF_RE.search(url):
        best_pri += 5
    return best_cat, best_pri


def cadence_of(category: str) -> str:
    return COLLECTION_SPEC.get(category, {}).get('cadence', 'static')


# ── extraction + dating ─────────────────────────────────────────────────────────
def _pdf_links(html: str, base_url: str) -> list[str]:
    return [urljoin(base_url, h) for h in
            re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)]


def _html_to_text(html: str, max_chars: int = 12000) -> str:
    html = re.sub(r'(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>', ' ', html)
    text = re.sub(r'(?s)<[^>]+>', ' ', html)
    import html as _h
    return re.sub(r'\s+', ' ', _h.unescape(text)).strip()[:max_chars]


def _iso_date(v) -> str | None:
    if not v:
        return None
    s = str(v).strip().split('T')[0].split(' ')[0]
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d %b %Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _http_last_modified(headers: dict) -> str | None:
    lm = headers.get('Last-Modified') or headers.get('last-modified')
    if not lm:
        return None
    try:
        import email.utils
        return email.utils.parsedate_to_datetime(lm).date().isoformat()
    except Exception:
        return None


# ── the crawl+ingest workhorse (shared by profile + refresh) ───────────────────────
def _ingest_items(sym: str, items: list[tuple[int, str, str | None, str]], store,
                  max_docs: int, delay_s: float) -> dict:
    """Fetch ranked (pri,url,lastmod,category) items, extract+date+store them. HTML pages
    also yield their linked PDFs (the actual reports — usually not in the sitemap),
    fetched depth-first. Returns counts + the set of URLs that produced documents."""
    from terminal_in.knowledge import pdf_extract
    worklist, seen, docs, dropped, fetched, ingested_urls = list(items), set(), [], 0, 0, []
    while worklist and len(ingested_urls) < max_docs and fetched < max_docs * 5:
        pri, url, lm, cat = worklist.pop(0)
        if url in seen:
            continue
        seen.add(url)
        is_pdf = bool(_PDF_RE.search(url))
        status, content, headers = _get(url, binary=is_pdf)
        fetched += 1
        if status != 200 or not content:
            continue
        if is_pdf:
            raw = content if isinstance(content, bytes) else content.encode('utf-8', 'replace')
            if len(raw) > _MAX_PDF_BYTES:
                continue
            text = pdf_extract.extract_text(raw)
            fd = _iso_date(lm) or pdf_extract.pdf_creation_date(raw) or _http_last_modified(headers)
        else:
            html = content if isinstance(content, str) else content.decode('utf-8', 'replace')
            text = _html_to_text(html)
            fd = _iso_date(lm) or _http_last_modified(headers)
            for pu in _pdf_links(html, url):
                if pu not in seen:
                    worklist.insert(0, (COLLECTION_SPEC[cat]['priority'] + 5, pu, lm, cat))
        if not text:
            continue
        if not fd:                                  # FAIL-CLOSED: undatable → drop
            dropped += 1
            continue
        title = re.sub(r'[-_/]+', ' ', urlparse(url).path.rsplit('/', 1)[-1] or cat).strip() or cat
        docs.append({'symbol': sym, 'filing_date': fd, 'doc_type': COLLECTION_SPEC[cat]['doc_type'],
                     'source': 'firm_site', 'url': url, 'title': f'{cat}: {title}'[:240],
                     'body': text, 'confidence': 0.85})
        ingested_urls.append(url)
        if delay_s:
            time.sleep(delay_s)
    res = store.record_documents(docs) if docs else {'ingested': 0, 'dropped_unverifiable': 0}
    return {'chunks_ingested': res['ingested'], 'documents': len(docs),
            'dropped_undated': dropped, 'fetched': fetched, 'ingested_urls': ingested_urls}


# ── profile persistence (per ticker) ──────────────────────────────────────────────
def _profile_path(symbol: str) -> Path:
    return PROFILE_DIR / f'{symbol.upper()}.json'


def load_profile(symbol: str) -> dict | None:
    p = _profile_path(symbol)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save_profile(profile: dict) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _profile_path(profile['symbol']).write_text(json.dumps(profile, indent=1))


# ── PHASE 1: profile (map the firm's site) + initial ingest ────────────────────────
def profile_firm(symbol: str, domain: str | None = None, store=None, max_docs: int = 16,
                 min_priority: int = 40, delay_s: float = 0.5) -> dict:
    """Crawl the whole sitemap, learn the firm's URL→category MAP, persist it per ticker,
    and do the initial ingest. Run periodically (e.g. weekly)."""
    from terminal_in.knowledge.firm_store import default_store
    sym = str(symbol).upper()
    domain = domain or firm_domain(sym)
    if not domain:
        return {'symbol': sym, 'error': 'no_domain', 'documents': 0,
                'note': 'firm domain unknown — add to firm_domains.json (never guessed)'}
    store = store or default_store()

    urls = discover_urls(domain)
    category_urls: dict[str, list] = {}
    ranked = []
    for u, lm in urls:
        cat, pri = classify(u)
        if not cat:
            continue
        category_urls.setdefault(cat, []).append(u)
        if pri >= min_priority:
            ranked.append((pri, u, lm, cat))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    res = _ingest_items(sym, ranked, store, max_docs=max_docs, delay_s=delay_s)
    lastmods = {u: lm for u, lm in urls if lm}
    profile = {
        'symbol': sym, 'domain': domain, 'profiled_at': datetime.now().isoformat(timespec='seconds'),
        'sitemap_urls': len(urls), 'category_urls': category_urls,
        'ingested_urls': sorted(set(res['ingested_urls'])),
        'lastmod_seen': {u: lastmods[u] for u in lastmods if classify(u)[0]},
    }
    _save_profile(profile)
    return {'symbol': sym, 'domain': domain, 'sitemap_urls': len(urls),
            'categories_found': {c: len(v) for c, v in category_urls.items()},
            'documents': res['documents'], 'chunks_ingested': res['chunks_ingested'],
            'dropped_undated': res['dropped_undated'], 'profiled': True}


# ── PHASE 2: refresh (watch the volatile links for deltas) ─────────────────────────
def refresh_firm(symbol: str, store=None, max_docs: int = 10, delay_s: float = 0.4) -> dict:
    """Using the stored profile, re-check only the VOLATILE/PERIODIC links (news, updates,
    results, disclosures — not annual reports) and ingest just the new/updated items. Run
    every session. Profiles the firm first if no profile exists yet."""
    from terminal_in.knowledge.firm_store import default_store
    sym = str(symbol).upper()
    profile = load_profile(sym)
    if profile is None:
        return profile_firm(sym, store=store)        # first run → full profile
    store = store or default_store()
    domain = profile['domain']
    seen_urls = set(profile.get('ingested_urls', []))
    lastmod_seen = dict(profile.get('lastmod_seen', {}))

    deltas = []
    for u, lm in discover_urls(domain):
        cat, pri = classify(u)
        if not cat or cadence_of(cat) not in _VOLATILE:    # skip static (annual reports etc.)
            continue
        is_new = u not in seen_urls
        is_updated = lm and _iso_date(lm) and _iso_date(lm) != _iso_date(lastmod_seen.get(u))
        if is_new or is_updated:
            deltas.append((pri, u, lm, cat))
        if lm:
            lastmod_seen[u] = lm
    deltas.sort(key=lambda x: (-x[0], x[1]))

    res = _ingest_items(sym, deltas, store, max_docs=max_docs, delay_s=delay_s)
    profile['ingested_urls'] = sorted(set(profile.get('ingested_urls', [])) | set(res['ingested_urls']))
    profile['lastmod_seen'] = lastmod_seen
    profile['refreshed_at'] = datetime.now().isoformat(timespec='seconds')
    _save_profile(profile)
    return {'symbol': sym, 'domain': domain, 'deltas_found': len(deltas),
            'documents': res['documents'], 'chunks_ingested': res['chunks_ingested'],
            'dropped_undated': res['dropped_undated'], 'refreshed': True}


# Back-compat alias: the on-demand "research this firm" entry point = full profile + ingest.
def collect_firm(symbol: str, domain: str | None = None, store=None, max_docs: int = 12,
                 min_priority: int = 55, delay_s: float = 0.6, since: str | None = None) -> dict:
    return profile_firm(symbol, domain=domain, store=store, max_docs=max_docs,
                        min_priority=min_priority, delay_s=delay_s)
