"""PDF text extraction for the firm-knowledge plane (pypdf).

Pure, dependency-guarded helper shared by the IR-PDF and BSE-attachment ingest paths.
pypdf is an OPTIONAL dependency: if absent, extraction returns '' and the caller skips
(logged) rather than failing — the plane degrades, never fabricates.
"""

from __future__ import annotations

import io
import logging
import re

log = logging.getLogger(__name__)

_warned = False


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec('pypdf') is not None


def extract_text(data: bytes, max_chars: int = 12000) -> str:
    """Extract and normalise text from PDF bytes. Returns '' on any failure or if
    pypdf is not installed (caller treats empty as 'nothing to ingest')."""
    global _warned
    try:
        from pypdf import PdfReader
    except ImportError:
        if not _warned:
            log.info('pdf_extract: pypdf not installed — PDF depth disabled (pip install pypdf)')
            _warned = True
        return ''
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or '')
            if sum(len(p) for p in parts) >= max_chars:
                break
        return re.sub(r'\s+', ' ', ' '.join(parts)).strip()[:max_chars]
    except Exception:
        log.debug('pdf_extract: failed to parse PDF', exc_info=True)
        return ''


def pdf_creation_date(data: bytes) -> str | None:
    """The PDF's own /CreationDate as an ISO date (fail-closed None). A weak last-resort
    date source for documents lacking an explicit filing date — used only as fallback."""
    try:
        from pypdf import PdfReader
        meta = PdfReader(io.BytesIO(data)).metadata or {}
        raw = getattr(meta, 'creation_date', None)
        if raw is not None:
            return raw.date().isoformat()
        d = meta.get('/CreationDate')         # 'D:YYYYMMDD...'
        m = re.match(r'D:(\d{4})(\d{2})(\d{2})', str(d or ''))
        if m:
            from datetime import date
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except Exception:
        pass
    return None
