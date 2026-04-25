"""Unit tests for the raw LLM exchange sidecar cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from storygen.storage import paths
from storygen.storage.llm_cache import (
    dump_llm_exchange,
    llm_cache_dir,
    llm_exchange_path,
    read_llm_exchange,
)


def test_llm_exchange_path_is_pure_path_math(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = llm_exchange_path("game-xyz", "node-abc", "beat")
    assert path == paths.game_dir("game-xyz") / "llm" / "node-abc-beat.json"


def test_llm_cache_dir_under_game_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert llm_cache_dir("g1") == paths.game_dir("g1") / "llm"


def test_dump_and_read_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    raw = b'{"messages": [{"role": "user", "content": "hi"}]}'
    dump_llm_exchange("gA", "nodeA", "beat", raw)

    # Sidecar exists and matches.
    path = llm_exchange_path("gA", "nodeA", "beat")
    assert path.exists()
    assert path.read_bytes() == raw

    # read_llm_exchange round-trips.
    assert read_llm_exchange("gA", "nodeA", "beat") == raw


def test_dump_overwrites_previous(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Second dump for the same (node, agent) replaces the first atomically."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    dump_llm_exchange("g", "n", "beat", b"first")
    dump_llm_exchange("g", "n", "beat", b"second")
    assert llm_exchange_path("g", "n", "beat").read_bytes() == b"second"


def test_dump_cleans_up_stale_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A stale .json.tmp sitting next to the sidecar is replaced, not left over."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    dump_llm_exchange("g", "n", "beat", b"payload")
    path = llm_exchange_path("g", "n", "beat")
    tmp = path.with_suffix(".json.tmp")
    # Pre-seed a stale tmp file and re-dump — atomic write should land the new
    # payload at the real path with no leftover .tmp.
    tmp.write_bytes(b"stale")
    dump_llm_exchange("g", "n", "beat", b"fresh")
    assert path.read_bytes() == b"fresh"
    assert not tmp.exists()


def test_read_missing_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert read_llm_exchange("nope", "missing", "beat") is None


def test_dump_swallows_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Debug cache must never raise into gameplay — monkeypatch write_bytes to
    simulate an OSError and confirm dump_llm_exchange returns silently."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def _boom(self: Path, _data: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)
    # Must not raise.
    dump_llm_exchange("g", "n", "beat", b"payload")
    # Real file wasn't written.
    assert not llm_exchange_path("g", "n", "beat").exists()
    # And no .tmp left behind.
    assert not llm_exchange_path("g", "n", "beat").with_suffix(".json.tmp").exists()


def test_dump_creates_parent_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # The llm/ directory doesn't exist yet.
    assert not llm_cache_dir("g2").exists()
    dump_llm_exchange("g2", "nX", "illustration", b"{}")
    assert llm_cache_dir("g2").is_dir()
    assert llm_exchange_path("g2", "nX", "illustration").exists()
