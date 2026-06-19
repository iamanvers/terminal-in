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


class _ForwardAccumulateAdapter:
    """Base for the bot-hostile external sources. Returns [] until real fetching is
    wired — NEVER a synthesised/restated history (BSE/NSE programmatic access blocks
    bots; a trustworthy 10y archive must be accumulated forward or licensed). The
    interface is here so wiring a real fetch later is a drop-in."""

    name = 'external'
    note = 'forward-accumulate stub — no historical fetch wired'

    def fetch(self, symbols: list[str]) -> list[dict]:
        log.info('%s adapter: %s', self.name, self.note)
        return []


class BseXbrlAdapter(_ForwardAccumulateAdapter):
    name = 'bse_xbrl'
    note = ('forward-accumulate: BSE XBRL gives breadth (structured financials) but the '
            'API is bot-hostile — wire a polite, robots-respecting fetch, accumulate forward')


class IrPdfAdapter(_ForwardAccumulateAdapter):
    name = 'ir_pdf'
    note = ('forward-accumulate: firm investor-relations PDFs give depth (MD&A, segments, '
            'guidance) — fetch per firm IR page, extract text, date by publication')


def default_adapters(db=None) -> list[KnowledgeAdapter]:
    return [EventsAdapter(), NewsAdapter(db), BseXbrlAdapter(), IrPdfAdapter()]


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
