"""Shared pytest fixtures — tmp XDG dir, dotenv reset, rate-limiter reset."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from storygen.config import reset_dotenv_cache_for_tests


@pytest.fixture(autouse=True)
def reset_dotenv_cache() -> None:
    reset_dotenv_cache_for_tests()


@pytest.fixture(autouse=True)
def _scrub_storygen_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop ambient ``STORYGEN_*`` env vars before each test.

    Config-defaults tests failed on machines that had provider overrides
    exported in the shell (issue #23, reported on Windows). Tests that need a
    ``STORYGEN_*`` var set their own via monkeypatch, which wins over this
    scrub.
    """
    for name in list(os.environ):
        if name.startswith("STORYGEN_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _reset_api_rate_limiter() -> None:  # pyright: ignore[reportUnusedFunction]
    """Clear per-IP rate-limit counters before each test (SEC-007 isolation).

    Lazy import so non-API test runs (where ``storygen_api`` may be absent)
    don't fail at collection time.
    """
    try:
        from storygen_api.rate_limit import reset_rate_limiter

        reset_rate_limiter()
    except ImportError:
        pass


@pytest.fixture
def xdg_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    yield tmp_path
