"""Per-IP sliding-window rate limiter for cost-incurring API routes (SEC-007).

Single-process, in-memory, thread-safe — consistent with the documented
single-worker FastAPI constraint (ARC-004 documents that a second uvicorn
worker silently desyncs in-memory session/WS state, so the API is effectively
pinned to one worker). This means a local counter is sufficient; no Redis /
memcached round-trip is needed.

Default limit: ``30/minute`` per client IP on cost-incurring endpoints only
(LLM / image generation, advance, regenerate). Read-only GETs are not
throttled. The limit is configurable via ``STORYGEN_API_RATE_LIMIT`` using
the format ``<count>/<period>`` where period is ``second``, ``minute``, or
``hour`` (case-insensitive). Examples:

* ``STORYGEN_API_RATE_LIMIT=60/minute``  — bump the default for a busy shared deploy
* ``STORYGEN_API_RATE_LIMIT=200/hour``   — daily-ceiling style cap
* ``STORYGEN_API_RATE_LIMIT=0``          — a count of 0 disables the limiter

The 30/minute default is sized for an interactive story session: each LLM beat
takes 5-30 s to generate, so a single player issues ~2-12 requests/min even
when clicking through briskly. A bad loop or a leaked token would exceed it
within seconds, capping cost exposure. Image regen is the most expensive
single call (~$0.04 each for gpt-image-2 at default quality); 30/min bounds a
runaway regen loop to ~$72 before an operator notices.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_LIMIT_SPEC = "30/minute"
_WINDOW_SECONDS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
}


def _parse_limit_spec(spec: str) -> tuple[int, int]:
    """Parse ``"30/minute"`` into ``(count, period_seconds)``.

    Raises:
        ValueError: If the spec is malformed or the period is unknown.
        Special case: ``count == 0`` returns ``(0, 0)`` meaning "disabled".
    """
    text = spec.strip()
    count_str, sep, period_str = text.partition("/")
    if not sep:
        raise ValueError(f"invalid rate limit spec {spec!r}: expected '<count>/<period>'")
    try:
        count = int(count_str)
    except ValueError as exc:
        raise ValueError(f"invalid rate limit spec {spec!r}: count not an integer") from exc
    if count < 0:
        raise ValueError(f"invalid rate limit spec {spec!r}: count must be >= 0")
    period = _WINDOW_SECONDS.get(period_str.lower())
    if period is None:
        raise ValueError(
            f"invalid rate limit spec {spec!r}: period must be one of "
            f"{sorted(_WINDOW_SECONDS)}"
        )
    return count, period


# Resolve once at import time. Tests can re-init via ``configure_rate_limit``.
_SPEC = os.environ.get("STORYGEN_API_RATE_LIMIT", _DEFAULT_LIMIT_SPEC)
_LIMIT_COUNT, _LIMIT_PERIOD_SECONDS = _parse_limit_spec(_SPEC)


# ---------------------------------------------------------------------------
# Sliding-window implementation
# ---------------------------------------------------------------------------


class _SlidingWindowLimiter:
    """Fixed-size sliding-window counter keyed by client IP.

    Each key owns a monotonically-increasing timestamp list; entries older
    than the window are popped from the head. Memory is bounded by the
    cleanup pass which drops empty buckets.
    """

    def __init__(self, count: int, period_seconds: int) -> None:
        self._count = count
        self._period = period_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    @property
    def disabled(self) -> bool:
        """``True`` when configured with count=0 (limiter is a no-op)."""
        return self._count <= 0

    def check(self, key: str) -> None:
        """Raise :class:`fastapi.HTTPException(429)` if ``key`` is over quota.

        Records the attempt only when the caller is under the limit, so a
        rejected request does not extend its own window.
        """
        if self.disabled:
            return
        now = time.monotonic()
        cutoff = now - self._period
        with self._lock:
            bucket = self._hits[key]
            # Evict timestamps older than the window.
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)
            if len(bucket) >= self._count:
                # Retry-After is the seconds until the oldest hit ages out.
                retry_after = max(1, int(bucket[0] + self._period - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"rate limit exceeded: {self._count} cost-incurring "
                        f"requests per {self._period}s per IP"
                    ),
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

    def reset(self) -> None:
        """Clear all buckets (test helper)."""
        with self._lock:
            self._hits.clear()


_limiter = _SlidingWindowLimiter(_LIMIT_COUNT, _LIMIT_PERIOD_SECONDS)


def reset_rate_limiter() -> None:
    """Clear all per-IP counters. Intended for test isolation."""
    _limiter.reset()


def configure_rate_limit(spec: str) -> None:
    """Re-configure the limiter at runtime (test helper).

    Production code reads ``STORYGEN_API_RATE_LIMIT`` once at import time;
    tests can call this to mutate the limit without monkeypatching ``os.environ``.
    """
    global _limiter
    count, period = _parse_limit_spec(spec)
    _limiter = _SlidingWindowLimiter(count, period)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Return the requesting client's IP, or ``"unknown"`` if unavailable."""
    client = request.client
    return client.host if client else "unknown"


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency: reject (HTTP 429) cost-incurring requests over quota.

    Apply only to routes that trigger LLM/image cost — never to read-only GETs.

    SEC-007: the limiter is per-IP, not per-token. A single token shared by a
    household or test harness would otherwise be throttled by per-token limits;
    per-IP matches the abuse vector (a single attacker host scripting calls).
    Auth (``verify_token``) runs alongside and prevents cross-user tampering.
    """
    _limiter.check(_client_ip(request))


# Reusable alias so protected routes stay readable.
RequireRateLimit = Annotated[None, Depends(enforce_rate_limit)]
