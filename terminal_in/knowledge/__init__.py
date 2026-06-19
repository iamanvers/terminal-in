"""Firm-knowledge plane — a vector-less, point-in-time RAG over firm documents.

The orthogonal-signal substrate for grounding strategies in firm reality (see
docs/ALPHA_FINDINGS.md: price-only factors are exhausted; the one untested lever is
real point-in-time firm information). This package stores critical firm text
(filings, announcements, news, curated profiles) in a LIGHTWEIGHT SQLite-FTS5 store
— BM25 lexical retrieval, no embedding vectors, no tensor index — and serves it as a
compact grounded context to the analyst/judge.

Three hard properties, inherited from the rest of the system:
  - POINT-IN-TIME: every document carries a filing_date; retrieval is as-of bounded
    (a query dated D can never see a document filed after D) — mirrors fundamentals.py.
  - FAIL-CLOSED: an undatable document is dropped, never guessed.
  - ROLLING 5-YEAR HORIZON: recent docs keep full text; the 13mo–5yr band is COMPRESSED
    to summaries (body dropped); anything past the horizon is PURGED. Keeps the store
    small and laptop-local while preserving a 5-year memory.
"""

from terminal_in.knowledge.firm_store import FirmStore, default_store  # noqa: F401
