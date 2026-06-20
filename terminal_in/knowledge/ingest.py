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

    def __init__(self, days: int = 30, max_symbols: int | None = None, delay_s: float = 0.4,
                 fetch_pdf: bool | None = None):
        self.days, self.max_symbols, self.delay_s = days, max_symbols, delay_s
        # opt-in attachment depth (slow + hits the hostile host harder) — default off
        self.fetch_pdf = (os.environ.get('KNOWLEDGE_FETCH_PDF', 'false').lower() == 'true'
                          if fetch_pdf is None else fetch_pdf)

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
        if self.fetch_pdf and out:
            bse.enrich_with_pdf(out)           # append attachment text (DEPTH)
        return out


class IrPdfAdapter:
    """REAL source (depth): firm investor-relations PDFs (MD&A, segments, guidance).
    Two real, offline-capable inputs (no bot-hostile API):
      (1) LOCAL FOLDER `data/knowledge/ir_docs/` — drop firm PDFs named
          `SYMBOL__YYYY-MM-DD__title.pdf` (or place them under `ir_docs/SYMBOL/...`).
          The turnkey path: download annual reports / results / concall decks and
          ingest them directly. This is the recommended way to add firm depth today.
      (2) `data/knowledge/ir_sources.json` `{symbol: [pdf_url, ...]}` — fetched when the
          URL is reachable; dated from the HTTP Last-Modified header.
    Text via pypdf (optional dep — `knowledge/pdf_extract.py`). Dates are FAIL-CLOSED:
    a PDF we cannot date (no filename date, no /CreationDate, no Last-Modified) is
    dropped, never guessed. doc_type is inferred from the title. With neither input it
    no-ops, so it ships inert and lights up the moment firm PDFs are supplied."""

    name = 'ir_pdf'
    LOCAL_DIR = 'data/knowledge/ir_docs'
    CONFIG = 'data/knowledge/ir_sources.json'

    def fetch(self, symbols: list[str]) -> list[dict]:
        from terminal_in.knowledge import pdf_extract
        wanted = {s.upper() for s in symbols}
        out = self._local(wanted, pdf_extract)
        out += self._urls(wanted, pdf_extract)
        if not out:
            log.info('ir_pdf: no firm PDFs (drop files in %s/ or configure %s)',
                     self.LOCAL_DIR, self.CONFIG)
        return out

    def _doc(self, sym: str, fd: str, title: str, text: str, url: str = '') -> dict:
        from terminal_in.data_ingest.bse_filings import doc_type_for
        return {'symbol': sym, 'filing_date': fd, 'doc_type': doc_type_for('', title) or 'business_profile',
                'source': self.name, 'url': url, 'title': title[:240], 'body': text, 'confidence': 0.9}

    def _local(self, wanted: set, pdf_extract) -> list[dict]:
        from pathlib import Path
        from terminal_in.data_ingest.bse_filings import _parse_dt
        base = Path(self.LOCAL_DIR)
        if not base.exists():
            return []
        out = []
        for p in sorted(base.rglob('*.pdf')):
            parts = p.stem.split('__')
            sym = (parts[0] or '').upper()
            if sym not in wanted and p.parent.name.upper() in wanted:
                sym = p.parent.name.upper()           # ir_docs/SYMBOL/file.pdf layout
            if sym not in wanted:
                continue
            title = parts[2].replace('-', ' ') if len(parts) >= 3 else p.stem.replace('_', ' ')
            data = p.read_bytes()
            fd = _parse_dt(parts[1]).isoformat() if len(parts) >= 2 and _parse_dt(parts[1]) else None
            if fd is None:
                fd = pdf_extract.pdf_creation_date(data)
            if not fd:                                # fail-closed: undatable → skip
                log.info('ir_pdf: skip undatable %s (name SYMBOL__YYYY-MM-DD__title.pdf)', p.name)
                continue
            text = pdf_extract.extract_text(data)
            if text:
                out.append(self._doc(sym, fd, title, text, url=p.as_uri()))
        return out

    def _urls(self, wanted: set, pdf_extract) -> list[dict]:
        from pathlib import Path
        import email.utils
        import json as _json
        cfg = Path(self.CONFIG)
        if not cfg.exists():
            return []
        try:
            sources = {str(k).upper(): v for k, v in _json.loads(cfg.read_text()).items()}
        except Exception:
            log.warning('ir_pdf: failed to read %s', self.CONFIG)
            return []
        try:
            import requests
        except ImportError:
            return []
        out = []
        for sym, urls in sources.items():
            if sym not in wanted:
                continue
            for url in (urls if isinstance(urls, list) else [urls]):
                try:
                    r = requests.get(url, timeout=20)
                    r.raise_for_status()
                    lm = r.headers.get('Last-Modified')
                    fd = email.utils.parsedate_to_datetime(lm).date().isoformat() if lm else \
                        pdf_extract.pdf_creation_date(r.content)
                    if not fd:                        # fail-closed: undatable → skip
                        continue
                    text = pdf_extract.extract_text(r.content)
                    if text:
                        out.append(self._doc(sym, fd, f'{sym} IR document ({fd})', text, url=url))
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
    # Firm-research REFRESH phase: for firms already PROFILED (via POST /api/knowledge/
    # research), re-check only their volatile/periodic links for deltas and ingest them.
    # Inert until a firm is profiled, so it adds no load by default. Profiling itself is
    # on-demand/weekly (heavy full crawl), not run here.
    research = {}
    if os.environ.get('KNOWLEDGE_RESEARCH_ENABLED', 'true').lower() != 'false':
        try:
            from terminal_in.data_ingest import firm_research as fr
            for s in symbols:
                if fr.load_profile(s):
                    try:
                        research[s] = fr.refresh_firm(s, store=store)
                    except Exception:
                        log.warning('knowledge: firm-research refresh failed for %s', s, exc_info=True)
        except Exception:
            log.debug('knowledge: firm_research unavailable', exc_info=True)

    comp = store.compact() if compact else {'compressed': 0, 'purged': 0}
    return {'ts': int(time.time() * 1000), 'ingested': total_in, 'dropped': total_drop,
            'compaction': comp, 'per_adapter': per_adapter,
            'research_refresh': {k: v.get('documents', 0) for k, v in research.items()},
            'coverage': store.coverage()}


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
