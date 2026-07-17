"""Tests for ENH-008 — API observability (request-timing middleware + agent latency).

Pins the contract:
- Every HTTP request emits one INFO ``request`` record with method, route
  template path, status, and a numeric ``duration_ms``.
- Each pydantic-ai adapter (beat / illustration / summary) emits a DEBUG
  ``agent call`` record with ``duration_ms`` and token counts after its agent
  invocation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from starlette.testclient import TestClient

from storygen_api.main import (  # tested in isolation; _configure_logging's contract is worth pinning directly
    _configure_logging,  # pyright: ignore[reportPrivateUsage]
)


@pytest.fixture
def app_client(
    xdg_tmp: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """Build a TestClient (no token → loopback trusted)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("STORYGEN_API_TOKEN", raising=False)
    from storygen_api.security import reset_token_cache

    reset_token_cache()
    from storygen_api import deps

    deps.get_app_config.cache_clear()
    from storygen_api.main import create_app

    app = create_app()
    return TestClient(app)


def test_request_timing_middleware_logs_one_record_per_request(
    app_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A GET to /api/health produces exactly one INFO 'request' log record."""
    caplog.set_level(logging.INFO, logger="storygen_api.main")
    # The health endpoint is unauthenticated and side-effect-free.
    response = app_client.get("/api/health")
    assert response.status_code == 200

    request_records = [r for r in caplog.records if r.getMessage() == "request"]
    assert len(request_records) == 1, "expected exactly one 'request' log record"
    record: Any = request_records[0]
    assert record.levelno == logging.INFO
    # Structured fields ride on the record via extra={} (dynamic attributes).
    assert record.method == "GET"
    assert record.path == "/api/health"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0.0


def test_request_timing_middleware_logs_failure_status(
    app_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A 404 still produces a 'request' record carrying the failing status."""
    caplog.set_level(logging.INFO, logger="storygen_api.main")
    response = app_client.get("/api/does-not-exist")
    assert response.status_code == 404

    request_records = [r for r in caplog.records if r.getMessage() == "request"]
    assert len(request_records) == 1
    record: Any = request_records[0]
    assert record.status == 404


def test_beat_adapter_logs_agent_call_latency(caplog: pytest.LogCaptureFixture) -> None:
    """BeatAgentAdapter emits a DEBUG 'agent call' record with timing + tokens."""
    from storygen.runtime.adapters import BeatAgentAdapter

    class _Usage:
        input_tokens = 120
        output_tokens = 45

    class _Result:
        output = type("Beat", (), {"narration": "It was a dark night."})()
        usage = _Usage()

        def all_messages_json(self) -> str:
            return "[]"

    class _FakeAgent:
        async def run(self, prompt: object) -> _Result:
            return _Result()

    caplog.set_level(logging.DEBUG, logger="storygen.runtime.adapters")
    adapter = BeatAgentAdapter(_FakeAgent())  # type: ignore[arg-type]

    async def _drive() -> None:
        async def _delta(text: str) -> None:
            return None

        await adapter.run("prompt", _delta)  # type: ignore[no-untyped-call]

    asyncio.run(_drive())

    agent_records = [r for r in caplog.records if r.getMessage() == "agent call"]
    assert len(agent_records) == 1
    record: Any = agent_records[0]
    assert record.levelno == logging.DEBUG
    assert record.agent == "beat"
    assert isinstance(record.duration_ms, float)
    assert record.input_tokens == 120
    assert record.output_tokens == 45


def test_log_level_configured_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_configure_logging`` reads STORYGEN_LOG_LEVEL for both loggers."""
    monkeypatch.setenv("STORYGEN_LOG_LEVEL", "DEBUG")
    _configure_logging()
    assert logging.getLogger("storygen_api").level == logging.DEBUG
    assert logging.getLogger("storygen").level == logging.DEBUG

    monkeypatch.delenv("STORYGEN_LOG_LEVEL", raising=False)
    _configure_logging()
    assert logging.getLogger("storygen_api").level == logging.INFO
    assert logging.getLogger("storygen").level == logging.WARNING
