"""Tests for ``storygen_api.main`` startup guards (ARC-004).

Covers ``_enforce_single_worker`` — the lifespan-time check that refuses to
serve when the process manager signals more than one uvicorn worker. The
server holds in-process state (SessionManager pipeline registry,
WebSocketManager connection lists, TTS player) that does not survive a
second worker, so multi-worker deploys silently desync game state.
"""

from __future__ import annotations

import pytest

from storygen_api.main import (
    _enforce_single_worker,  # pyright: ignore[reportPrivateUsage] - tested in isolation; the function is private but the startup guard has a load-bearing contract worth pinning directly
)


def test_enforce_single_worker_passes_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No WEB_CONCURRENCY → no raise (single-worker is the default assumption)."""
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    _enforce_single_worker()  # must not raise


def test_enforce_single_worker_passes_when_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WEB_CONCURRENCY=1 → no raise (explicit single worker)."""
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    _enforce_single_worker()


def test_enforce_single_worker_raises_when_multiple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WEB_CONCURRENCY>1 → RuntimeError with a message pointing at the cause."""
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError) as excinfo:
        _enforce_single_worker()
    msg = str(excinfo.value)
    assert "WEB_CONCURRENCY=4" in msg
    assert "single worker" in msg or "single-worker" in msg


def test_enforce_single_worker_tolerates_malformed_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-integer WEB_CONCURRENCY must not crash startup (fail open to 1)."""
    monkeypatch.setenv("WEB_CONCURRENCY", "not-a-number")
    _enforce_single_worker()  # must not raise
