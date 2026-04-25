"""Shared pytest fixtures — tmp XDG dir, dotenv reset."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from storygen.config import reset_dotenv_cache_for_tests


@pytest.fixture(autouse=True)
def reset_dotenv_cache() -> None:
    reset_dotenv_cache_for_tests()


@pytest.fixture
def xdg_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    yield tmp_path
