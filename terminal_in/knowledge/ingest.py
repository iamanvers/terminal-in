"""Periodic firm-knowledge ingestion + source adapters.

An adapter turns a real source into point-in-time documents for the FirmStore. We
ingest from sources we ALREADY have honestly (the NSE event archive today; firm news
when persisted) and scaffold the bot-hostile external sources (BSE XBRL, firm-IR
PDFs) as forward-accumulate adapters with a clear interface — they return nothing
until real fetching is wired, never a fabricated history (same discipline as
events.py / fundamentals.py).

`KnowledgeIngestor` runs the adapters on a cadence (KNOWLEDGE_INGEST_INTERVAL_H),
records to the store, then compacts (compress 13mo–5y, purge >5y). It publishes a
`knowledge.ingest` summary on the EventBus so the UI can surface coverage + honesty.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Protocol

from terminal_in.knowledge.firm_store import FirmStore, default_store

log = logging.getLogger(__name__)


class KnowledgeAdapter(Protocol):
    name: str

    def fetch(self, symbols: list[str]) -> list[dict]:
        """Return point-in-time document rows (see FirmStore.record_documents)."""
        ...


class EventsAdapter:
    """REAL source: the NSE corporate-announcement archive (data_ingest/events.py).
    Honest — we have the event + its precise filing date, not the figures (those live
    in the attached PDF). doc body = the announcement subject; confidence = 1.0 (the
    filing certainly happened)."""

    name = 'nse_events'

    def fetch(self, symbols: list[str]) -> list[dict]:
        from terminal_in.data_ingest.events import load_events
        df = load_events()
        if not len(df):
            return []
        wanted = {s.upper() for s in symbols} if symbols else None
        out = []
        for _, r in df.iterrows():
            sym = str(r['symbol']).upper()
            if wanted and sym not in wanted:
                continue
            subj = str(r.get('subject', '') or '').strip()
            if not subj:
                continue
            out.append({
                'symbol': sym, 'filing_date': r.get('announce_date'),
                'doc_type': str(r.get('event_type', 'other')),
                'source': self.name, 'title': subj, 'body': subj, 'confidence': 1.0,
            })
        return out


class NewsAdapter:
    """REAL source: persisted firm news headlines (NewsAPI), if an archive table exists.
    No-ops cleanly when no queryable news archive is present (we do not fabricate one)."""

    name = 'news'

    def __init__(self, db=None):
        self.db = db

    def fetch(self, symbols: list[str]) -> list[dict]:
        if self.db is None:
            return []
        getter = getattr(self.db, 'get_news_archive', None)
        if not callable(getter):
            log.info('news adapter: no get_news_archive on DB — skipping (forward-accumulate)')
            return []
        try:
            items = getter(symbols) or []
        except Exception:
            log.warning('news adapter: archive read failed', exc_info=True)
            return []
        out = []
        for it in items:
            sym = str(it.get('symbol', '')).upper()
            title = str(it.get('title', '') or '').strip()
            fd = it.get('published_at') or it.get('date')
            if not sym or not title or not fd:
                continue
            out.append({
                'symbol': sym, 'filing_date': fd, 'doc_type': 'news', 'source': self.name,
                'title': title, 'body': str(it.get('description', '') or ''),
                'url': str(it.get('url', '') or ''),
                'confidence': float(it.get('confidence', 0.7)),  # news < filings
            })
        return out


class BseFilingsAdapter:
    """REAL source (breadth): BSE corporate filings via `data_ingest/bse_filings.py`.
    Polite, browser-headered, fail-closed; the bot-hostile API may block, in which case
    it returns nothing rather than fabricating. Forward-accumulating: each run adds the
    last `days` of filings for symbols with a known BSE scrip code (others are skipped)."""

    name = 'bse_filings'

    def __init__(self, days: int = 30, max_symbols: int | None = None, delay_s: float = 0.4):
        self.days, self.max_symbols, self.delay_s = days, max_symbols, delay_s

    def fetch(self, symbols: list[str]) -> list[dict]:
        from terminal_in.data_ingest import bse_filings as bse
        out, n = [], 0
        for s in symbols:
            if not bse.scrip_code(s):          # unmapped → never queried against a guess
                continue
            out.extend(bse.fetch_announcements(s, self.days))
            n += 1
            if self.max_symbols and n >= self.max_symbols:
                break
            if self.delay_s:
                time.sleep(self.delay_s)       # be polite to BSE
        return out


class IrPdfAdapter:
    """REAL source (depth): firm investor-relations PDFs (MD&A, segments, guidance).
    Config-driven and forward-accumulating — reads `data/knowledge/ir_sources.json`
    ({symbol: [pdf_url, ...]}); fetches each, extracts text via pypdf IF INSTALLED (else
    skips, logged — optional dep), and dates fail-closed from the HTTP Last-Modified
    header (a PDF we can't date is dropped, never guessed). With no config it no-ops, so
    it ships inert and lights up once IR sources are supplied."""

    name = 'ir_pdf'
    CONFIG = 'data/knowledge/ir_sources.json'

    def _sources(self) -> dict:
        from pathlib import Path
        import json as _json
        p = Path(self.CONFIG)
        if not p.exists():
            return {}
        try:
            return {str(k).upper(): v for k, v in _json.loads(p.read_text()).items()}
        except Exception:
            log.warning('ir_pdf: failed to read %s', self.CONFIG)
            return {}

    def fetch(self, symbols: list[str]) -> list[dict]:
        sources = self._sources()
        if not sources:
            log.info('ir_pdf: no %s — forward-accumulate, supply IR PDF URLs to enable',
                     self.CONFIG)
            return []
        try:
            import requests
            from pypdf import PdfReader   # optional dep
        except ImportError:
            log.info('ir_pdf: pypdf not installed — skipping PDF depth (pip install pypdf)')
            return []
        import email.utils
        import io
        wanted = {s.upper() for s in symbols}
        out = []
        for sym, urls in sources.items():
            if sym not in wanted:
                continue
            for url in (urls if isinstance(urls, list) else [urls]):
                try:
                    r = requests.get(url, timeout=20)
                    r.raise_for_status()
                    lm = r.headers.get('Last-Modified')
                    fd = email.utils.parsedate_to_datetime(lm).date().isoformat() if lm else None
                    if not fd:                    # fail-closed: undatable PDF dropped
                        continue
                    reader = PdfReader(io.BytesIO(r.content))
                    text = ' '.join((pg.extract_text() or '') for pg in reader.pages)[:8000]
                    if not text.strip():
                        continue
                    out.append({'symbol': sym, 'filing_date': fd, 'doc_type': 'business_profile',
                                'source': self.name, 'url': url,
                                'title': f'{sym} IR document ({fd})', 'body': text,
                                'confidence': 0.9})
                except Exception:
                    log.debug('ir_pdf: fetch/parse failed for %s %s', sym, url, exc_info=True)
        return out


def default_adapters(db=None) -> list[KnowledgeAdapter]:
    return [EventsAdapter(), NewsAdapter(db), BseFilingsAdapter(), IrPdfAdapter()]


def run_ingest(symbols: list[str], store: FirmStore | None = None,
               adapters: list[KnowledgeAdapter] | None = None, db=None,
               compact: bool = True) -> dict:
    """Run every adapter, record into the store, then compact the rolling horizon.
    Returns a per-adapter + compaction honesty summary."""
    store = store or default_store()
    adapters = adapters or default_adapters(db)
    per_adapter, total_in, total_drop = {}, 0, 0
    for a in adapters:
        try:
            rows = a.fetch(symbols)
        except Exception:
            log.warning('knowledge ingest: adapter %s failed', getattr(a, 'name', a), exc_info=True)
            per_adapter[getattr(a, 'name', 'unknown')] = {'error': True}
            continue
        res = store.record_documents(rows) if rows else {'ingested': 0, 'dropped_unverifiable': 0}
        per_adapter[a.name] = {'fetched': len(rows), 'ingested': res['ingested'],
                               'dropped': res['dropped_unverifiable']}
        total_in += res['ingested']
        total_drop += res['dropped_unverifiable']
    comp = store.compact() if compact else {'compressed': 0, 'purged': 0}
    return {'ts': int(time.time() * 1000), 'ingested': total_in, 'dropped': total_drop,
            'compaction': comp, 'per_adapter': per_adapter, 'coverage': store.coverage()}


class KnowledgeIngestor(threading.Thread):
    """Background thread: periodic firm-knowledge ingest + compaction."""

    def __init__(self, symbols: list[str], db=None, bus=None,
                 interval_h: float | None = None, store: FirmStore | None = None):
        super().__init__(name='knowledge-ingest', daemon=True)
        self.symbols = symbols
        self.db = db
        self.bus = bus
        self.store = store or default_store()
        self.interval_s = float(interval_h if interval_h is not None
                                else os.environ.get('KNOWLEDGE_INGEST_INTERVAL_H', '24')) * 3600
        self._stop = threading.Event()

    def run(self):
        # small initial delay so boot isn't contended
        if self._stop.wait(20):
            return
        while not self._stop.is_set():
            try:
                summary = run_ingest(self.symbols, store=self.store, db=self.db)
                if self.bus is not None:
                    try:
                        self.bus.publish('knowledge.ingest', summary)
                    except Exception:
                        log.debug('knowledge ingest: bus publish failed', exc_info=True)
            except Exception:
                log.warning('knowledge ingest cycle failed', exc_info=True)
            self._stop.wait(self.interval_s)

    def stop(self):
        self._stop.set()
