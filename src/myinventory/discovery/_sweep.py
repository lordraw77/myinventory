"""Shared concurrency helper for host-discovery backends.

Runs ``probe`` over every address in parallel while honoring two limits the
orchestrator cares about: a launch **rate limit** and an overall **per-target
timeout**. Backends just supply a per-address probe and read the results.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TypeVar

from ..ratelimit import RateLimiter

T = TypeVar("T")


def sweep(
    addresses: Iterable[str],
    probe: Callable[[str], T],
    *,
    workers: int,
    rate_limit: float = 0.0,
    target_timeout: float | None = None,
) -> tuple[dict[str, T], bool]:
    """Probe every address concurrently.

    Returns ``(results_by_address, timed_out)``. ``timed_out`` is true when the
    ``target_timeout`` budget elapsed before every probe finished — partial
    results are still returned.
    """
    limiter = RateLimiter(rate_limit)
    deadline = time.monotonic() + target_timeout if target_timeout else None
    results: dict[str, T] = {}
    timed_out = False

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures: dict = {}
        for addr in addresses:
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                break
            limiter.acquire()
            futures[pool.submit(probe, addr)] = addr

        not_done = set(futures)
        remaining = None
        if deadline is not None:
            remaining = max(0.0, deadline - time.monotonic())
        try:
            for fut in as_completed(futures, timeout=remaining):
                not_done.discard(fut)
                addr = futures[fut]
                try:
                    results[addr] = fut.result()
                except Exception:  # noqa: BLE001 - one dead probe must not abort the sweep
                    continue
        except FutureTimeout:
            timed_out = True
        for fut in not_done:
            fut.cancel()

    return results, timed_out
