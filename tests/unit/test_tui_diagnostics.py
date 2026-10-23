"""Private, rotating TUI image diagnostics must never use console handlers."""

from __future__ import annotations

import json
import logging
import stat
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import PermissionDeniedError
from pydantic_ai.exceptions import ModelHTTPError
from textual.app import App

from storygen import diagnostics
from storygen.core.models import ImageProviderConfig
from storygen.images import provider_factory
from storygen.images.base import ImageProvider
from storygen.screens._create_char_modal import CreateCharRequest
from storygen.screens.library_browser import CharacterCatalogScreen


def _provider_error() -> PermissionDeniedError:
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": "Bearer sk-PRIVATE-TEST"},
        json={"prompt": "PRIVATE PROMPT", "image": "PRIVATE IMAGE DATA"},
    )
    response = httpx.Response(403, request=request, headers={"x-request-id": "req_local_test"})
    return PermissionDeniedError(
        "PRIVATE PROMPT Bearer sk-PRIVATE-TEST PRIVATE IMAGE DATA",
        response=response,
        body={"code": "permission_denied", "message": "PRIVATE PROMPT"},
    )


def _fail() -> None:
    try:
        raise ValueError("PRIVATE INNER MESSAGE")
    except ValueError as inner:
        raise _provider_error() from inner


def test_file_contains_safe_traceback_and_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    root = logging.getLogger()
    console = logging.StreamHandler(sys.stderr)
    child = logging.getLogger("storygen.screens.library_browser")
    child_console = logging.StreamHandler(sys.stdout)
    root.addHandler(console)
    child.addHandler(child_console)
    previous_propagate = child.propagate
    child.propagate = False
    try:
        with diagnostics.tui_diagnostic_logging() as path:
            assert path == tmp_path / "storygen/logs/tui.log"
            try:
                _fail()
            except PermissionDeniedError as error:
                diagnostics.log_image_failure(
                    error,
                    provider="openai",
                    model="gpt-image-2",
                    operation="portrait",
                    reference_count=0,
                )
                # Existing application and SDK exception paths must also stay
                # off the console and out of the sanitized diagnostic file.
                child.exception("PRIVATE APPLICATION MESSAGE")
                logging.getLogger("openai._base_client").error("PRIVATE SDK BODY")
                logging.getLogger("new.nonpropagating.logger").propagate = False
                logging.getLogger("new.nonpropagating.logger").error("PRIVATE FALLBACK")
            assert path is not None
            content = path.read_text()
        assert "PRIVATE" not in content
        assert "Bearer" not in content
        assert "sk-" not in content
        records = [json.loads(line) for line in content.splitlines()]
        event = next(record for record in records if record["event"] == "image_generation_failed")
        captured_exception = next(
            record for record in records if record["event"] == "tui_exception"
        )
        assert captured_exception["exceptions"][0]["http_status"] == 403
        assert event["event"] == "image_generation_failed"
        assert event["provider"] == "openai"
        assert event["model"] == "gpt-image-2"
        assert event["operation"] == "portrait"
        assert event["reference_count"] == 0
        assert datetime.fromisoformat(event["timestamp"]).utcoffset() is not None
        error = event["exceptions"][0]
        assert error["type"] == "PermissionDeniedError"
        assert error["http_status"] == 403
        assert error["error_code"] == "permission_denied"
        assert error["request_id"] == "req_local_test"
        assert error["traceback"][-1]["function"] == "_fail"
        assert event["exceptions"][1]["type"] == "ValueError"
        assert console in root.handlers
        assert child_console in child.handlers
        assert child.propagate is False
    finally:
        root.removeHandler(console)
        child.removeHandler(child_console)
        child.propagate = previous_propagate
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_metadata_rejects_secrets_and_multiline_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    error = _provider_error()
    error.code = "sk-PRIVATE-TEST"
    error.request_id = "PRIVATE PROMPT\nAuthorization: Bearer sk-PRIVATE-TEST"
    with diagnostics.tui_diagnostic_logging() as path:
        diagnostics.log_image_failure(
            error,
            provider="openai",
            model="PRIVATE PROMPT\nsk-PRIVATE-TEST",
            operation="portrait",
            reference_count=1,
        )
    assert path is not None
    content = path.read_text()
    assert "PRIVATE" not in content
    assert "[redacted]" in content


def test_existing_debug_exception_is_recorded_without_console_or_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    application_logger = logging.getLogger("storygen")
    old_level = application_logger.level
    with diagnostics.tui_diagnostic_logging() as path:
        try:
            _fail()
        except PermissionDeniedError:
            logging.getLogger("storygen.screens.library_browser").debug(
                "PRIVATE CHARACTER PROMPT",
                exc_info=True,
            )
    assert application_logger.level == old_level
    assert path is not None
    content = path.read_text()
    event = json.loads(content.splitlines()[-1])
    assert event["event"] == "tui_exception"
    assert event["exceptions"][0]["request_id"] == "req_local_test"
    assert "PRIVATE" not in content
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["failed", "authentication_failed", "empty_output", "invalid_output"]
)
async def test_catalog_failure_before_portrait_is_logged(
    xdg_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_tmp / "state"))
    agent = MagicMock()
    agent.run = AsyncMock(
        return_value=SimpleNamespace(
            output=[] if outcome == "empty_output" else ["PRIVATE OUTPUT"],
        )
    )
    if outcome == "failed":
        agent.run.side_effect = _provider_error()
    elif outcome == "authentication_failed":
        agent.run.side_effect = ModelHTTPError(
            status_code=401,
            model_name="gpt-6-luna",
            body={"message": "PRIVATE RESPONSE BODY"},
        )
    image_provider = MagicMock()
    image_provider.generate_portrait = AsyncMock()

    class Harness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                CharacterCatalogScreen(
                    browse=True,
                    character_agent_factory=lambda: agent,
                    image_provider=image_provider,
                    text_provider_label="openai",
                    text_model="gpt-6-luna",
                    image_provider_label="openai",
                    image_model="gpt-image-2",
                )
            )

    with diagnostics.tui_diagnostic_logging() as path:
        app = Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, CharacterCatalogScreen)
            notifications: list[str] = []

            def record_notification(message: str, **_: object) -> None:
                notifications.append(message)

            monkeypatch.setattr(screen, "notify", record_notification)
            worker = screen._create_character_worker(  # pyright: ignore[reportPrivateUsage]
                CreateCharRequest(name="PRIVATE NAME", concept="PRIVATE PROMPT"),
            )
            await worker.wait()
    image_provider.generate_portrait.assert_not_awaited()
    assert path is not None
    content = path.read_text()
    events = [json.loads(line) for line in content.splitlines()]
    expected_outcome = "failed" if outcome == "authentication_failed" else outcome
    event = next(item for item in events if item.get("outcome") == expected_outcome)
    assert event["stage"] == "text_generation"
    assert event["model"] == "gpt-6-luna"
    assert event["reference_count"] == 0
    if outcome == "failed":
        assert event["exceptions"][0]["http_status"] == 403
    elif outcome == "authentication_failed":
        assert event["exceptions"][0]["http_status"] == 401
        assert any(
            "Text provider authentication failed (401)" in notice for notice in notifications
        )
        assert any("Portrait generation did not run" in notice for notice in notifications)
    assert all("PRIVATE" not in notice for notice in notifications)
    assert "PRIVATE" not in content
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_rotation_is_bounded_and_files_are_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(diagnostics, "_MAX_BYTES", 500)
    with diagnostics.tui_diagnostic_logging() as path:
        for _ in range(30):
            diagnostics.log_image_failure(
                ValueError("PRIVATE"),
                provider="openai",
                model="gpt-image-2",
                operation="portrait",
                reference_count=0,
            )
    assert path is not None
    files = list(path.parent.glob("tui.log*"))
    assert len(files) == 4
    assert all(file.stat().st_size <= 500 for file in files)
    assert all(stat.S_IMODE(file.stat().st_mode) == 0o600 for file in files)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_log_write_failure_never_prints_or_replaces_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(logging, "raiseExceptions", True)
    monkeypatch.setattr(diagnostics, "_MAX_BYTES", 1)
    with diagnostics.tui_diagnostic_logging():
        for handler in logging.getLogger("storygen.image_diagnostics").handlers:
            if isinstance(handler, RotatingFileHandler):
                monkeypatch.setattr(
                    handler, "doRollover", MagicMock(side_effect=OSError("PRIVATE DISK ERROR"))
                )
        diagnostics.log_image_failure(
            _provider_error(),
            provider="openai",
            model="gpt-image-2",
            operation="portrait",
            reference_count=0,
        )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_unwritable_log_and_exceptional_exit_restore_existing_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(
        diagnostics, "_QuietRotatingFileHandler", MagicMock(side_effect=OSError("PRIVATE"))
    )
    root = logging.getLogger()
    before = list(root.handlers)
    last_resort = logging.lastResort
    with (
        pytest.raises(RuntimeError, match="test exit"),
        diagnostics.tui_diagnostic_logging() as path,
    ):
        assert path is None
        logging.error("PRIVATE RAW EXCEPTION", exc_info=True)
        raise RuntimeError("test exit")
    assert root.handlers == before
    assert logging.lastResort is last_resort
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_cli_enables_file_logging_for_tui_lifetime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from storygen import main

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    application = MagicMock()
    application.run.side_effect = lambda: diagnostics.log_image_failure(
        _provider_error(),
        provider="openai",
        model="gpt-image-2",
        operation="portrait",
        reference_count=0,
    )
    monkeypatch.setattr(main, "StoryGenApp", MagicMock(return_value=application))
    main.run(resume=False)
    assert "image_generation_failed" in diagnostics.tui_log_path().read_text()
    application.run.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["portrait", "scene"])
async def test_router_logs_configured_model_and_both_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    primary = MagicMock()
    fallback = MagicMock()
    primary.generate_portrait = AsyncMock(side_effect=_provider_error())
    primary.generate_scene = AsyncMock(side_effect=_provider_error())
    fallback.generate_portrait = AsyncMock(side_effect=RuntimeError("PRIVATE"))
    fallback.generate_scene = AsyncMock(side_effect=RuntimeError("PRIVATE"))
    monkeypatch.setattr(
        provider_factory,
        "build_image_provider",
        MagicMock(side_effect=[cast(ImageProvider, primary), cast(ImageProvider, fallback)]),
    )
    router = provider_factory.build_routed_image_provider(
        ImageProviderConfig(provider="openai", model="gpt-image-2"),
        fallback_cfg=ImageProviderConfig(provider="ollama", model="x/z-image-turbo"),
    )
    with diagnostics.tui_diagnostic_logging() as path, pytest.raises(PermissionDeniedError):
        if operation == "portrait":
            await router.generate_portrait("PRIVATE PROMPT", transparent=True)
        else:
            await router.generate_scene("PRIVATE PROMPT", reference_portraits=[])
    assert path is not None
    events = [json.loads(line) for line in path.read_text().splitlines()][1:]
    assert [event["model"] for event in events] == ["gpt-image-2", "x/z-image-turbo"]
    assert [event["provider"] for event in events] == ["openai", "ollama"]
    assert all(event["reference_count"] == 0 for event in events)
    assert "PRIVATE" not in path.read_text()
