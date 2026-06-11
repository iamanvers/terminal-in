"""
Multi-source news fetcher.

Sources (all fetched concurrently):
  1. RSS feeds — free Indian financial press, no API keys, no rate limits.
     Polled every RSS_POLL_S (15 min). Parsed with stdlib xml.etree.
  2. NewsAPI — polled every NEWSAPI_POLL_S (2 h; free tier = 100 req/day).
     Optional: the fetcher runs RSS-only when no API key is configured.

Every article is FinBERT-scored, instrument-tagged, deduped by URL and by
normalized headline (same story syndicated across outlets), persisted, and
published on 'news.signal'.
"""

import email.utils
import html as _html
import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Optional

import requests

from terminal_in.bus import bus
from terminal_in.db import DB
from terminal_in.news import parser, sentiment

log = logging.getLogger(__name__)

RSS_POLL_S     = 900    # 15 min — RSS is free
NEWSAPI_POLL_S = 7200   # 2 h — 2 queries × 12 polls/day = 24 req/day (100/day limit)
NEWSAPI_URL = 'https://newsapi.org/v2/everything'

QUERIES = [
    'NSE NIFTY India stock market',
    'RBI SEBI BSE India economy',
]
PAGE_SIZE = 10  # articles per query per poll

# Free Indian financial press RSS feeds (no keys, no limits).
# All verified working 2026-06-10. Moneycontrol and Business Standard RSS
# return 403 to non-browser clients — don't re-add without a workaround.
RSS_FEEDS: list[tuple[str, str]] = [
    ('ET Markets',       'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms'),
    ('ET Stocks',        'https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms'),
    ('LiveMint Markets', 'https://www.livemint.com/rss/markets'),
    ('BusinessLine',     'https://www.thehindubusinessline.com/markets/feeder/default.rss'),
    ('NDTV Profit',      'https://feeds.feedburner.com/ndtvprofit-latest'),
]

_RSS_HEADERS = {'User-Agent': 'Mozilla/5.0 (terminal-in news fetcher)'}


def _norm_headline(headline: str) -> str:
    """Normalized headline for cross-source dedup of syndicated stories."""
    return re.sub(r'[^a-z0-9 ]', '', headline.lower()).strip()[:120]


class NewsFetcher:
    def __init__(self, api_key: str, db: DB):
        self.api_key = api_key
        self.db = db
        self._stop = Event()
        self._seen_urls: set[str] = set()
        self._seen_headlines: set[str] = set()
        self._session = requests.Session()   # connection reuse across polls
        self._session.headers.update(_RSS_HEADERS)

    def _fetch_query(self, query: str) -> list[dict]:
        if not self.api_key:
            return []
        try:
            r = self._session.get(
                NEWSAPI_URL,
                params={
                    'q': query,
                    'language': 'en',
                    'sortBy': 'publishedAt',
                    'pageSize': PAGE_SIZE,
                    'apiKey': self.api_key,
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get('articles', [])
        except Exception:
            log.warning('NewsAPI fetch failed for query: %s', query)
            return []

    # ── RSS ────────────────────────────────────────────────────────────────

    def _fetch_rss(self, source: str, url: str) -> list[dict]:
        """Fetch one RSS feed and shape items like NewsAPI articles."""
        try:
            r = self._session.get(url, timeout=10)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            log.debug('RSS fetch failed %s: %s', source, str(e)[:80])
            return []

        articles = []
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link  = (item.findtext('link') or '').strip()
            desc  = (item.findtext('description') or '').strip()
            # strip HTML tags some feeds embed in descriptions
            desc  = re.sub(r'<[^>]+>', ' ', desc)[:400].strip()
            pub   = (item.findtext('pubDate') or '').strip()
            if not title or not link:
                continue
            published_iso = ''
            try:
                published_iso = email.utils.parsedate_to_datetime(pub).isoformat()
            except Exception:
                pass
            articles.append({
                'title':       title,
                'description': desc,
                'url':         link,
                'publishedAt': published_iso,
                'source':      {'name': source},
            })
        return articles

    def _fetch_all_rss(self) -> list[dict]:
        """All feeds concurrently — one slow outlet must not stall the poll."""
        out: list[dict] = []
        with ThreadPoolExecutor(max_workers=len(RSS_FEEDS), thread_name_prefix='rss') as pool:
            for articles in pool.map(lambda f: self._fetch_rss(*f), RSS_FEEDS):
                out.extend(articles)
        return out

    def _process_article(self, article: dict) -> Optional[dict]:
        url = article.get('url', '')
        if url in self._seen_urls:
            return None
        self._seen_urls.add(url)

        # Feeds emit HTML entities (&amp;, &#039;) — unescape once here so
        # headlines render clean in every card, popup, and prompt downstream
        headline = _html.unescape(article.get('title', '') or '')
        body = _html.unescape(article.get('description', '') or '')

        # Cross-source dedup: the same story syndicated by multiple outlets
        norm = _norm_headline(headline)
        if norm and norm in self._seen_headlines:
            return None
        self._seen_headlines.add(norm)

        result = sentiment.score(f'{headline}. {body}')
        instruments = parser.extract_instruments(headline, body)
        impact = parser.classify_impact(result['score'], result['sentiment'])

        published_raw = article.get('publishedAt', '')
        try:
            from datetime import datetime, timezone
            published_at = int(
                datetime.fromisoformat(published_raw.replace('Z', '+00:00'))
                .timestamp() * 1000
            )
        except Exception:
            published_at = int(time.time() * 1000)

        return {
            'published_at': published_at,
            'fetched_at': int(time.time() * 1000),
            'headline': headline,
            'source': (article.get('source') or {}).get('name', ''),
            'url': url,
            'sentiment': result['sentiment'],
            'score': result['score'],
            'instruments': instruments,
            'impact': impact,
        }

    def _ingest(self, raw_articles: list[dict]) -> int:
        processed_count = 0
        for raw in raw_articles:
            processed = self._process_article(raw)
            if processed is None:
                continue
            try:
                self.db.insert_news(processed)
            except Exception:
                log.exception('Failed to persist news article')
            bus.publish('news.signal', processed)
            processed_count += 1
        return processed_count

    def _poll_rss(self):
        n = self._ingest(self._fetch_all_rss())
        if n:
            log.info('RSS poll: %d new articles from %d feeds', n, len(RSS_FEEDS))

    def _poll_newsapi(self):
        n = 0
        for query in QUERIES:
            n += self._ingest(self._fetch_query(query))
        if n:
            log.info('NewsAPI poll: %d new articles', n)

    def run(self):
        log.info('News fetcher started — %d RSS feeds every %ds%s',
                 len(RSS_FEEDS), RSS_POLL_S,
                 f', NewsAPI every {NEWSAPI_POLL_S}s' if self.api_key else ' (no NewsAPI key — RSS only)')
        last_newsapi = 0.0
        # Initial poll
        self._poll_rss()
        if self.api_key:
            self._poll_newsapi()
            last_newsapi = time.time()
        while not self._stop.is_set():
            self._stop.wait(timeout=RSS_POLL_S)
            if self._stop.is_set():
                break
            try:
                self._poll_rss()
                if self.api_key and time.time() - last_newsapi >= NEWSAPI_POLL_S:
                    self._poll_newsapi()
                    last_newsapi = time.time()
            except Exception:
                log.exception('News poll cycle failed (non-fatal)')

    def stop(self):
        self._stop.set()
