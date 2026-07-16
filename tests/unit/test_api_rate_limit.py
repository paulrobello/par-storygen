"""Tests for the per-IP rate limiter on cost-incurring API routes (SEC-007).

Verifies:
1. The sliding-window counter accepts requests under the limit and rejects
   with 429 + ``Retry-After`` once exceeded.
2. ``configure_rate_limit`` / ``reset_rate_limiter`` work as test helpers.
3. The HTTP-level integration: an authed POST to a cost-incurring wizard
   route succeeds N times and returns 429 on the (N+1)th call within the
   window. Read-only GETs are not throttled.
4. Per-IP isolation: a second client IP is not penalised for the first's
   over-budget calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from storygen_api import rate_limit as rl
from storygen_api.rate_limit import (
    _parse_limit_spec,  # pyright: ignore[reportPrivateUsage]
    _SlidingWindowLimiter,  # pyright: ignore[reportPrivateUsage]
    configure_rate_limit,
    reset_rate_limiter,
)

# ---------------------------------------------------------------------------
# Unit tests for the sliding-window counter
# ---------------------------------------------------------------------------


def test_parse_limit_spec_accepts_standard_periods() -> None:
    assert _parse_limit_spec("30/minute") == (30, 60)
    assert _parse_limit_spec("5/second") == (5, 1)
    assert _parse_limit_spec("100/hour") == (100, 3600)


def test_parse_limit_spec_disables_on_zero_count() -> None:
    assert _parse_limit_spec("0/minute") == (0, 60)


@pytest.mark.parametrize("spec", ["", "30", "30/", "/minute", "abc/minute", "30/century", "-1/minute"])
def test_parse_limit_spec_rejects_malformed(spec: str) -> None:
    with pytest.raises(ValueError):
        _parse_limit_spec(spec)


def test_limiter_disabled_when_count_zero() -> None:
    """``count=0`` disables the limiter (no-op)."""
    lim = _SlidingWindowLimiter(0, 60)
    assert lim.disabled
    for _ in range(100):
        lim.check("1.2.3.4")  # no raise


def test_limiter_allows_under_limit() -> None:
    lim = _SlidingWindowLimiter(3, 60)
    for _ in range(3):
        lim.check("client-a")


def test_limiter_rejects_over_limit_with_retry_after() -> None:
    lim = _SlidingWindowLimiter(2, 60)
    lim.check("client-a")
    lim.check("client-a")
    with pytest.raises(rl.HTTPException) as exc_info:
        lim.check("client-a")
    assert exc_info.value.status_code == 429
    headers = exc_info.value.headers
    assert headers is not None
    assert "Retry-After" in headers
    # Retry-After is bounded by the window length.
    retry_after = int(headers["Retry-After"])
    assert 1 <= retry_after <= 60


def test_limiter_keys_isolated_per_ip() -> None:
    """Per-IP isolation: one IP burning its budget doesn't throttle another."""
    lim = _SlidingWindowLimiter(1, 60)
    lim.check("1.1.1.1")
    with pytest.raises(rl.HTTPException):
        lim.check("1.1.1.1")
    # A different IP is still under budget.
    lim.check("2.2.2.2")


def test_limiter_reset_clears_state() -> None:
    lim = _SlidingWindowLimiter(1, 60)
    lim.check("client")
    with pytest.raises(rl.HTTPException):
        lim.check("client")
    lim.reset()
    # After reset, the same client is under budget again.
    lim.check("client")


# ---------------------------------------------------------------------------
# Test isolation: clear the shared limiter before/after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_limiter_between_tests() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_rate_limiter()
    # Restore the production default after each test in case it was reconfigured.
    yield
    configure_rate_limit("30/minute")
    reset_rate_limiter()


# ---------------------------------------------------------------------------
# HTTP-level integration via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Build a TestClient with auth + a tight 3/min rate limit for fast tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STORYGEN_API_TOKEN", "rate-test-token")
    # Tighten the limit so the test doesn't have to fire 30 calls.
    configure_rate_limit("3/minute")
    reset_rate_limiter()

    from storygen_api.security import reset_token_cache

    reset_token_cache()
    from storygen_api import deps

    deps.get_app_config.cache_clear()

    from storygen_api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    reset_token_cache()
    deps.get_app_config.cache_clear()


_AUTH = {"Authorization": "Bearer rate-test-token"}


def test_cost_incurring_route_returns_429_when_over_budget(app_client: TestClient) -> None:
    """SEC-007: a cost-incurring POST is throttled past the limit.

    Uses ``POST /api/images/{game_id}/scene/{node_id}/retry`` with a
    nonexistent (but valid-format) game_id. The handler returns 404 each
    time, but the rate-limit dependency runs FIRST — so the counter still
    increments. With a 3/minute cap, the 4th call returns 429 + Retry-After.
    """
    fake_game = "0" * 32  # valid 32-hex UUID format, no such save exists
    statuses: list[int] = []
    for _ in range(3):
        r = app_client.post(
            f"/api/images/{fake_game}/scene/root/retry",
            headers=_AUTH,
        )
        statuses.append(r.status_code)
    # First 3 calls pass the rate limit (404 because no such save), never 429.
    assert all(s == 404 for s in statuses), (
        f"first 3 should pass the limiter and 404, got {statuses}"
    )

    # 4th call within the window is throttled before the handler runs.
    r = app_client.post(
        f"/api/images/{fake_game}/scene/root/retry",
        headers=_AUTH,
    )
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_read_only_get_is_not_rate_limited(app_client: TestClient) -> None:
    """SEC-007: GET /api/games is read-only and must NOT be throttled."""
    for _ in range(10):
        r = app_client.get("/api/games", headers=_AUTH)
        assert r.status_code == 200


def test_rate_limit_is_per_ip_not_per_token(app_client: TestClient) -> None:
    """The throttle key is the client IP, so a second IP is unaffected.

    Starlette's TestClient always presents the same loopback IP, so we
    can't trivially change it; instead this test documents the design
    by checking that ``_client_ip`` reads ``request.client.host``.
    """
    from fastapi import Request

    from storygen_api.rate_limit import _client_ip  # pyright: ignore[reportPrivateUsage]

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": ("203.0.113.7", 5000),
        "headers": [],
    }
    request = Request(scope)
    assert _client_ip(request) == "203.0.113.7"
