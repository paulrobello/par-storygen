"""Tests for cross-cutting utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from storygen.util import open_in_system_viewer


def test_open_in_system_viewer_noop_for_missing_path(tmp_path: Path) -> None:
    """Non-existent path returns immediately without spawning any subprocess."""
    missing = tmp_path / "nope.png"
    with patch("storygen.util.subprocess.Popen") as mock_popen:
        open_in_system_viewer(missing)
    mock_popen.assert_not_called()


def test_open_in_system_viewer_opens_on_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Darwin, spawns `open` via Popen."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n")
    with (
        patch("storygen.util.platform.system", return_value="Darwin"),
        patch("storygen.util.subprocess.Popen") as mock_popen,
    ):
        open_in_system_viewer(f)
    mock_popen.assert_called_once_with(["open", str(f)])


def test_open_in_system_viewer_opens_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Linux, spawns `xdg-open` via Popen."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n")
    with (
        patch("storygen.util.platform.system", return_value="Linux"),
        patch("storygen.util.subprocess.Popen") as mock_popen,
    ):
        open_in_system_viewer(f)
    mock_popen.assert_called_once_with(["xdg-open", str(f)])


def test_open_in_system_viewer_swallows_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError from the viewer binary is silently caught."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n")
    with (
        patch("storygen.util.platform.system", return_value="Darwin"),
        patch("storygen.util.subprocess.Popen", side_effect=OSError("no `open`")),
    ):
        open_in_system_viewer(f)  # should not raise
