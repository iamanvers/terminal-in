"""
EventBus — in-process pub/sub replacing Redis.
Singleton. Thread-safe. Supports glob patterns: 'ticks.*' matches 'ticks.NIFTY'.
Hot cache stores latest payload per topic (replaces Redis GET tick:X:current).
"""

import logging
from collections import defaultdict
from threading import Lock
from typing import Any, Callable

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._lock = Lock()
        self._cache: dict[str, Any] = {}

    def subscribe(self, pattern: str, callback: Callable) -> None:
        with self._lock:
            self._subs[pattern].append(callback)

    def unsubscribe(self, pattern: str, callback: Callable) -> None:
        with self._lock:
            subs = self._subs.get(pattern, [])
            try:
                subs.remove(callback)
            except ValueError:
                pass

    def publish(self, topic: str, payload: Any) -> None:
        self._cache[topic] = payload
        with self._lock:
            patterns = list(self._subs.keys())
        for pattern in patterns:
            if self._matches(topic, pattern):
                with self._lock:
                    callbacks = list(self._subs[pattern])
                for cb in callbacks:
                    try:
                        cb(payload)
                    except Exception:
                        log.exception('Subscriber error on topic=%s pattern=%s', topic, pattern)

    def get_cached(self, topic: str) -> Any:
        return self._cache.get(topic)

    def get_all_cached(self, pattern: str) -> dict[str, Any]:
        return {
            k: v for k, v in self._cache.items()
            if self._matches(k, pattern)
        }

    @staticmethod
    def _matches(topic: str, pattern: str) -> bool:
        if pattern == topic:
            return True
        if pattern.endswith('*'):
            return topic.startswith(pattern[:-1])
        return False


bus = EventBus()
