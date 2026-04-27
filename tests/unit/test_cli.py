"""Unit test: CLI has the expected commands and version flag."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from storygen.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.2.0" in _strip_ansi(result.stdout)


def test_cli_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in _strip_ansi(result.stdout)


def test_cli_run_help_documents_resume() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--resume" in _strip_ansi(result.stdout)
