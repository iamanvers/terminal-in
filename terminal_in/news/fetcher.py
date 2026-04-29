"""
NewsAPI fetcher — polls every 5 minutes for Indian market news.
Scores each article with FinBERT, publishes to EventBus, persists to SQLite.
"""

import logging
import time
from threading import Event
from typing import Optional

import requests

from terminal_in.bus import bus
from terminal_in.db import DB
from terminal_in.news import parser, sentiment

log = logging.getLogger(__name__)

POLL_INTERVAL = 7200  # 2 hours — 2 queries × 12 polls/day = 24 requests/day (100/day limit)
NEWSAPI_URL = 'https://newsapi.org/v2/everything'

QUERIES = [
    'NSE NIFTY India stock market',
    'RBI SEBI BSE India economy',
]
PAGE_SIZE = 10  # articles per query per poll


class NewsFetcher:
    def __init__(self, api_key: str, db: DB):
        self.api_key = api_key
        self.db = db
        self._stop = Event()
        self._seen_urls: set[str] = set()

    def _fetch_query(self, query: str) -> list[dict]:
        if not self.api_key:
            return []
        try:
            r = requests.get(
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
            log.exception('NewsAPI fetch failed for query: %s', query)
            return []

    def _process_article(self, article: dict) -> Optional[dict]:
        url = article.get('url', '')
        if url in self._seen_urls:
            return None
        self._seen_urls.add(url)

        headline = article.get('title', '') or ''
        body = article.get('description', '') or ''

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

    def _poll(self):
        articles_processed = 0
        for query in QUERIES:
            raw_articles = self._fetch_query(query)
            for raw in raw_articles:
                processed = self._process_article(raw)
                if processed is None:
                    continue
                try:
                    self.db.insert_news(processed)
                except Exception:
                    log.exception('Failed to persist news article')

                bus.publish('news.signal', processed)
                articles_processed += 1

        if articles_processed:
            log.info('News poll: %d new articles processed', articles_processed)

    def run(self):
        log.info('News fetcher started (poll interval: %ds)', POLL_INTERVAL)
        # Initial poll
        self._poll()
        while not self._stop.is_set():
            self._stop.wait(timeout=POLL_INTERVAL)
            if not self._stop.is_set():
                self._poll()

    def stop(self):
        self._stop.set()
