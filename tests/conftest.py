"""Shared pytest fixtures — tmp XDG dir, dotenv reset, rate-limiter reset."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from storygen.config import reset_dotenv_cache_for_tests


@pytest.fixture(autouse=True)
def reset_dotenv_cache() -> None:
    reset_dotenv_cache_for_tests()


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
