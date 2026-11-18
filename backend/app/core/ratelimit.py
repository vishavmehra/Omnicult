"""A small sliding-window rate limiter for endpoints that take no sign-in.

State is process memory, so each running instance keeps its own counts. # ponytail: per-instance counters; move them to
the database or a shared cache when the API runs on several instances and a hard global cap matters. The number of keys
is bounded, so a flood of distinct keys cannot grow memory without limit.
"""

import time
from collections import deque

from app.core.errors import RateLimited

MAX_KEYS = 10_000


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Count one request for `key`; False when the key has already used its allowance in the window."""
        now = time.monotonic() if now is None else now
        if len(self._hits) >= MAX_KEYS and key not in self._hits:
            self._evict(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def check(self, key: str) -> None:
        if not self.allow(key):
            raise RateLimited("Too many requests. Wait a minute and try again.")

    def _evict(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[key]
        if len(self._hits) >= MAX_KEYS:  # every key is live: drop the oldest half rather than refuse everyone
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[: MAX_KEYS // 2]:
                del self._hits[key]
