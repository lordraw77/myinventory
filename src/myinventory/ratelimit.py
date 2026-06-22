"""A tiny thread-safe rate limiter.

Used by the discovery backends to cap how fast probes are launched, so a sweep
stays friendly to the network (and to intrusion-detection systems). A rate of
``0`` (or less) means *unlimited* — :meth:`acquire` returns immediately.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Spaces out calls so they happen at most ``rate`` times per second.

    Implemented as a single-token scheduler: each :meth:`acquire` reserves the
    next slot and sleeps until it arrives. Safe to share across threads.
    """

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next = time.monotonic()

    @property
    def unlimited(self) -> bool:
        return self._rate <= 0

    def acquire(self) -> None:
        """Block until the caller is allowed to proceed."""
        if self.unlimited:
            return
        with self._lock:
            now = time.monotonic()
            if now >= self._next:
                self._next = now + self._interval
                wait = 0.0
            else:
                wait = self._next - now
                self._next += self._interval
        if wait > 0:
            time.sleep(wait)
