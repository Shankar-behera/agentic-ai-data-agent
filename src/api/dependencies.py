import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Optional

from fastapi import Depends, Header, Request

from src.core.config import settings
from src.core.exceptions import AuthenticationError, RateLimitError


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Constant-time API-key check. No key configured (dev/test only) means open access."""
    expected = settings.api_key.get_secret_value() if settings.api_key else ""
    if not expected:  # unset or empty (e.g. `API_KEY=` in .env) means open access; production refuses to boot this way
        return
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise AuthenticationError()


class _SlidingWindowLimiter:
    """In-process limiter. With several replicas, enforce limits at the gateway as well."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 60.0) -> Optional[float]:
        """Return None if allowed, otherwise seconds until the next request is allowed."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                return window_s - (now - hits[0])
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = _SlidingWindowLimiter()


def rate_limit(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
    if settings.rate_limit_per_minute <= 0:
        return
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{(x_api_key or '')[:8]}"
    retry_after = limiter.check(key, settings.rate_limit_per_minute)
    if retry_after is not None:
        raise RateLimitError(details={"retry_after_s": round(retry_after, 1)})


# Bounds how many LLM-backed requests run at once. A local model on one box serves few at a time.
_query_slots = threading.BoundedSemaphore(settings.max_concurrent_queries)


def query_slot() -> Iterator[None]:
    if not _query_slots.acquire(timeout=settings.queue_timeout_s):
        raise RateLimitError("The server is busy, try again shortly", details={"retry_after_s": 5})
    try:
        yield
    finally:
        _query_slots.release()


__all__ = ["Depends", "require_api_key", "rate_limit", "query_slot", "limiter"]
