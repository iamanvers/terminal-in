"""Vector-less, point-in-time firm-knowledge store (SQLite FTS5 / BM25).

Storage + retrieval in one FTS5 table — no embeddings, no vector index (the owner's
"tensored-vector-less" RAG). Each row is one firm document with a filing_date anchor.

Retention is a rolling 5-year horizon with two stages (the owner's "compression and
deleting timelines"):
  - RAW band (≤ KNOWLEDGE_RAW_DAYS, default 400d ≈ 13mo): full title+body kept.
  - COMPRESSED band (RAW_DAYS .. HORIZON_DAYS): body is dropped, a short summary is
    kept and stays searchable — the document's gist survives, the bulk does not.
  - PURGED (> KNOWLEDGE_HORIZON_DAYS, default 1826d = 5y): row deleted entirely.

`compact()` is idempotent and runs on every ingest; the store stays small forever.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB = Path('./data/knowledge/firm_knowledge.db')
RAW_DAYS = int(os.environ.get('KNOWLEDGE_RAW_DAYS', '400'))          # full-text retention
HORIZON_DAYS = int(os.environ.get('KNOWLEDGE_HORIZON_DAYS', '1826'))  # 5-year memory
SUMMARY_CHARS = 320                                                  # compressed-band digest length

# document types we recognise (open set — unknown types stored as 'other')
DOC_TYPES = frozenset({'results', 'guidance', 'corp_action', 'rating_change', 'regulatory',
                       'board_meeting', 'news', 'business_profile', 'relationship', 'other'})

_FTS_COLS = ('doc_id', 'symbol', 'doc_type', 'source', 'url', 'filing_date',
             'period_end', 'ingested_at', 'confidence', 'compacted', 'title', 'body', 'summary')
# columns that must NOT be tokenised (metadata, not searchable text)
_UNINDEXED = {'doc_id', 'symbol', 'doc_type', 'source', 'url', 'filing_date',
              'period_end', 'ingested_at', 'confidence', 'compacted'}


def _parse_date(v) -> date | None:
    """FAIL-CLOSED date parse — None on anything unparseable (mirrors fundamentals.py)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    s = s.split('T')[0].split(' ')[0] if ('T' in s or ' ' in s) and len(s) > 10 else s
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d-%b-%Y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        import pandas as pd
        return pd.to_datetime(str(v), errors='raise').date()
    except Exception:
        return None


def _doc_id(symbol: str, source: str, filing_date: str, title: str) -> str:
    """Stable id so re-ingesting the same filing is idempotent (no duplicates)."""
    key = f'{symbol}|{source}|{filing_date}|{title}'.encode('utf-8', 'replace')
    return hashlib.sha1(key).hexdigest()[:16]


_QUERY_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _match_query(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression: OR of quoted tokens, so a
    user string with punctuation/operators can never inject FTS syntax."""
    toks = [t for t in _QUERY_TOKEN.findall(query or '') if len(t) > 1]
    return ' OR '.join(f'"{t}"' for t in toks)


class FirmStore:
    """A single FTS5-backed firm-document store. Thread-safe via a per-call connection
    (SQLite handles concurrent readers; writes are serialised by a lock)."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else Path(
            os.environ.get('KNOWLEDGE_DB_PATH', str(DEFAULT_DB)))
        self._write_lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _ensure_schema(self):
        cols = ', '.join(c + (' UNINDEXED' if c in _UNINDEXED else '') for c in _FTS_COLS)
        with self._conn() as c:
            c.execute(f'CREATE VIRTUAL TABLE IF NOT EXISTS firm_docs USING fts5({cols})')

    # ── ingest ────────────────────────────────────────────────────────────────
    def record_documents(self, rows: list[dict]) -> dict:
        """Append firm documents. Each row needs symbol, filing_date, title (and ideally
        body/source/doc_type/url/confidence). FAIL-CLOSED: rows without a parseable
        filing_date or without symbol+title are DROPPED and counted. Idempotent on
        doc_id (re-ingesting a filing replaces it). Returns honesty counts."""
        kept, dropped = [], 0
        now = datetime.now(UTC).date().isoformat()
        for r in rows:
            fd = _parse_date(r.get('filing_date'))
            sym = str(r.get('symbol', '')).upper().strip()
            title = str(r.get('title', '')).strip()
            if fd is None or not sym or not title:
                dropped += 1
                continue
            body = str(r.get('body', '') or '').strip()
            dtype = str(r.get('doc_type', 'other')).lower()
            if dtype not in DOC_TYPES:
                dtype = 'other'
            summary = str(r.get('summary', '') or '').strip() or _digest(title, body)
            conf = r.get('confidence', 1.0)
            try:
                conf = max(0.0, min(1.0, float(conf)))
            except (TypeError, ValueError):
                conf = 1.0
            did = _doc_id(sym, str(r.get('source', 'unknown')), fd.isoformat(), title)
            kept.append({
                'doc_id': did, 'symbol': sym, 'doc_type': dtype,
                'source': str(r.get('source', 'unknown')), 'url': str(r.get('url', '') or ''),
                'filing_date': fd.isoformat(), 'period_end': (_parse_date(r.get('period_end')).isoformat()
                                                              if _parse_date(r.get('period_end')) else ''),
                'ingested_at': now, 'confidence': conf, 'compacted': 0,
                'title': title, 'body': body, 'summary': summary,
            })
        if kept:
            with self._write_lock, self._conn() as c:
                for d in kept:
                    c.execute('DELETE FROM firm_docs WHERE doc_id = ?', (d['doc_id'],))
                    c.execute(
                        f"INSERT INTO firm_docs ({','.join(_FTS_COLS)}) "
                        f"VALUES ({','.join('?' * len(_FTS_COLS))})",
                        tuple(d[c2] for c2 in _FTS_COLS))
        summary = {'ingested': len(kept), 'dropped_unverifiable': dropped, 'total_rows': self.count()}
        log.info('firm_knowledge: ingested %d, dropped %d (no/bad date or missing fields), total %d',
                 summary['ingested'], summary['dropped_unverifiable'], summary['total_rows'])
        return summary

    # ── retrieval (the RAG read path) ───────────────────────────────────────────
    def retrieve(self, symbol: str | None, query: str, as_of=None, k: int = 6,
                 doc_types: tuple[str, ...] | None = None) -> list[dict]:
        """BM25-ranked documents matching `query`. POINT-IN-TIME: when `as_of` is given,
        only documents with filing_date <= as_of are returned (no-lookahead). Optionally
        scoped to one symbol and/or doc_types. Returns citation-ready dicts."""
        match = _match_query(query)
        if not match:
            return []
        where, params = ['firm_docs MATCH ?'], [match]
        if symbol:
            where.append('symbol = ?'); params.append(str(symbol).upper())
        as_of_d = _parse_date(as_of) if as_of is not None else None
        if as_of_d is not None:
            where.append('filing_date <= ?'); params.append(as_of_d.isoformat())
        if doc_types:
            where.append('doc_type IN (%s)' % ','.join('?' * len(doc_types)))
            params.extend([t.lower() for t in doc_types])
        sql = (f"SELECT doc_id, symbol, doc_type, source, url, filing_date, period_end, "
               f"confidence, compacted, title, body, summary, bm25(firm_docs) AS score "
               f"FROM firm_docs WHERE {' AND '.join(where)} ORDER BY bm25(firm_docs) LIMIT ?")
        params.append(int(k))
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, params)]
        for r in rows:
            r['text'] = r['body'] if (r['body'] and not r['compacted']) else r['summary']
        return rows

    # ── retention: compress then purge (the rolling 5-year memory) ──────────────
    def compact(self, now=None, raw_days: int = RAW_DAYS, horizon_days: int = HORIZON_DAYS) -> dict:
        """Stage the rolling horizon. Returns counts {compressed, purged}."""
        today = _parse_date(now) or datetime.now(UTC).date()
        raw_cut = (today - timedelta(days=raw_days)).isoformat()
        horizon_cut = (today - timedelta(days=horizon_days)).isoformat()
        with self._write_lock, self._conn() as c:
            purged = c.execute('DELETE FROM firm_docs WHERE filing_date < ?',
                               (horizon_cut,)).rowcount
            # compress the mid band: keep summary, drop body, mark compacted
            to_compress = c.execute(
                'SELECT doc_id, title, body, summary FROM firm_docs '
                'WHERE filing_date < ? AND filing_date >= ? AND compacted = 0',
                (raw_cut, horizon_cut)).fetchall()
            for row in to_compress:
                summ = row['summary'] or _digest(row['title'], row['body'])
                c.execute('UPDATE firm_docs SET body = ?, summary = ?, compacted = 1 '
                          'WHERE doc_id = ?', ('', summ, row['doc_id']))
        log.info('firm_knowledge: compaction compressed %d, purged %d (>5y)',
                 len(to_compress), purged)
        return {'compressed': len(to_compress), 'purged': purged}

    # ── honesty / introspection ─────────────────────────────────────────────────
    def count(self) -> int:
        with self._conn() as c:
            return int(c.execute('SELECT count(*) FROM firm_docs').fetchone()[0])

    def coverage(self) -> dict:
        with self._conn() as c:
            n = int(c.execute('SELECT count(*) FROM firm_docs').fetchone()[0])
            if not n:
                return {'rows': 0, 'symbols': 0, 'note': 'empty — no firm documents ingested yet',
                        'horizon_days': HORIZON_DAYS, 'raw_days': RAW_DAYS}
            syms = int(c.execute('SELECT count(DISTINCT symbol) FROM firm_docs').fetchone()[0])
            comp = int(c.execute('SELECT count(*) FROM firm_docs WHERE compacted = 1').fetchone()[0])
            latest = c.execute('SELECT max(filing_date) FROM firm_docs').fetchone()[0]
            earliest = c.execute('SELECT min(filing_date) FROM firm_docs').fetchone()[0]
            by_src = {r['source']: r['n'] for r in c.execute(
                'SELECT source, count(*) AS n FROM firm_docs GROUP BY source')}
        return {'rows': n, 'symbols': syms, 'compressed_rows': comp,
                'earliest_filing': earliest, 'latest_filing': latest, 'by_source': by_src,
                'horizon_days': HORIZON_DAYS, 'raw_days': RAW_DAYS}


def _digest(title: str, body: str) -> str:
    """Cheap extractive summary for the compressed band — the lead of title+body. NOT
    an LLM summary (that can be wired later); honest and deterministic for now."""
    text = (title + '. ' + body).strip() if body else title
    text = re.sub(r'\s+', ' ', text)
    return text[:SUMMARY_CHARS]


_DEFAULT: FirmStore | None = None


def default_store() -> FirmStore:
    """Process-wide store at the configured path."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FirmStore()
    return _DEFAULT
