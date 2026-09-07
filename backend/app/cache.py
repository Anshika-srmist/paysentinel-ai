"""
In-process rate limiting + response caching.

Single-instance only, on purpose. If this service is ever run as multiple
instances, both pieces need a shared backend (Redis): the limiter to share
counters, the cache to stay coherent. Until then an in-process
implementation is simpler and does the job.
"""
import threading
from typing import Callable, TypeVar

from cachetools import TTLCache
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter — keyed on client IP. Applied per-route via @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address)

_T = TypeVar("_T")

# One short-lived cache for the recompute-heavy read endpoints (dashboard
# aggregates, model metrics, the network graph). 15s of staleness is
# invisible on a polling dashboard and turns a burst of identical requests
# into a single computation.
_TTL_SECONDS = 15
_store: TTLCache = TTLCache(maxsize=128, ttl=_TTL_SECONDS)
_lock = threading.Lock()


def cached(key: str, producer: Callable[[], _T]) -> _T:
    """Return the cached value for ``key``, else compute it with ``producer``
    and store it. The producer runs outside the lock, so a cache miss never
    blocks unrelated readers (at worst two concurrent misses both compute)."""
    with _lock:
        if key in _store:
            return _store[key]
    value = producer()
    with _lock:
        _store[key] = value
    return value


def cache_clear() -> None:
    """Drop everything — used by tests."""
    with _lock:
        _store.clear()
