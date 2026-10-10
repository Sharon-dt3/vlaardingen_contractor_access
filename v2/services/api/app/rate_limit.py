"""A small in-process request limiter for public endpoints.

It is per process, so with several API workers each keeps its own count. That is
enough to stop a single client flooding the registration form during the pilot.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Allow at most ``limit`` hits per ``window_seconds`` for each key."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a hit and say whether it is within the limit."""

        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        """Forget all hits (used by tests)."""

        with self._lock:
            self._hits.clear()
