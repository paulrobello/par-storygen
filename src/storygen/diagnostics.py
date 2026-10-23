"""Bounded, file-only TUI diagnostics without prompts or provider response bodies."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import traceback
from collections.abc import Generator, Mapping
from datetime import UTC, datetime
from io import BufferedWriter, TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, cast

from xdg_base_dirs import xdg_state_home

_LOGGER = logging.getLogger("storygen.image_diagnostics")
_LOGGER.addHandler(logging.NullHandler())
_LOGGER.propagate = False
_active = False
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 3
_TOKEN = re.compile(r"[A-Za-z0-9_.:/<>-]{1,128}\Z")
_SECRET = re.compile(r"sk[-_]|bearer|authorization|password|secret|data:|base64", re.I)
_REQUEST_ID = re.compile(r"(?:req_[A-Za-z0-9_-]{1,100}|[a-fA-F0-9-]{16,64})\Z")


def tui_log_path() -> Path:
    """Return $XDG_STATE_HOME/storygen/logs/tui.log (default ~/.local/state)."""
    return xdg_state_home() / "storygen" / "logs" / "tui.log"


class _QuietRotatingFileHandler(RotatingFileHandler):
    """Never use logging's stderr fallback, even on write/rotation failures."""

    def _open(self) -> TextIOWrapper[BufferedWriter]:
        fd = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(fd, 0o600)
            return cast("TextIOWrapper[BufferedWriter]", os.fdopen(fd, "a", encoding="utf-8"))
        except Exception:
            os.close(fd)
            raise

    def handleError(self, record: logging.LogRecord) -> None:
        # The standard implementation prints the record and traceback to stderr.
        # Disk failures must neither expose data nor corrupt the running TUI.
        pass

    def close(self) -> None:
        with contextlib.suppress(Exception):
            super().close()


class _SafeExceptionHandler(logging.Handler):
    """Bridge existing exception reports without copying their messages/args."""

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            if record.exc_info is not None and isinstance(record.exc_info[1], BaseException):
                _write(
                    {
                        "event": "tui_exception",
                        "logger": _safe_token(record.name),
                        "file": _safe_token(record.filename),
                        "line": record.lineno,
                        "function": _safe_token(record.funcName),
                        "exceptions": _safe_exception(record.exc_info[1]),
                    }
                )


@contextlib.contextmanager
def tui_diagnostic_logging() -> Generator[Path | None]:
    """Isolate existing logging sinks for a TUI session, restoring them on exit.

    Raw SDK/application logs can contain prompts and response bodies. Discard
    their messages and args; translate exception reports to safe stack metadata.
    Only structured diagnostics write to disk. No root handlers are closed.
    """
    global _active
    application_logger = logging.getLogger("storygen")
    old_application_level = application_logger.level
    loggers = [logging.getLogger()] + [
        item
        for item in logging.Logger.manager.loggerDict.copy().values()
        if isinstance(item, logging.Logger)
    ]
    snapshots = [(item, list(item.handlers), item.propagate) for item in loggers]
    old_level, old_disabled = _LOGGER.level, _LOGGER.disabled
    old_filters = list(_LOGGER.filters)
    old_active, old_last_resort = _active, logging.lastResort
    old_disable = logging.Logger.manager.disable
    handler: _QuietRotatingFileHandler | None = None
    path: Path | None = None
    try:
        for item, handlers, _ in snapshots:
            for existing in handlers:
                item.removeHandler(existing)
            item.propagate = True
        logging.getLogger().addHandler(logging.NullHandler())
        logging.getLogger().addHandler(_SafeExceptionHandler())
        logging.lastResort = logging.NullHandler()
        logging.disable(logging.NOTSET)
        application_logger.setLevel(logging.DEBUG)
        _LOGGER.propagate = False
        _LOGGER.disabled = False
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.filters = []
        _LOGGER.addHandler(logging.NullHandler())
        try:
            target = tui_log_path()
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.parent.chmod(0o700)
            handler = _QuietRotatingFileHandler(
                target, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            _LOGGER.addHandler(handler)
            path = target
            _active = True
            _write({"event": "tui_started", "diagnostic_version": 2})
        except Exception:
            # An unwritable state directory must not trigger a console warning.
            _active = False
        yield path
    finally:
        _active = old_active
        if handler is not None:
            handler.close()
        for item, handlers, propagate in snapshots:
            for current in list(item.handlers):
                item.removeHandler(current)
            for existing in handlers:
                item.addHandler(existing)
            item.propagate = propagate
        _LOGGER.setLevel(old_level)
        _LOGGER.disabled = old_disabled
        _LOGGER.filters = old_filters
        logging.lastResort = old_last_resort
        logging.disable(old_disable)
        application_logger.setLevel(old_application_level)


def _safe_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not _TOKEN.fullmatch(value) or _SECRET.search(value):
        return "[redacted]"
    return value


def _attribute(value: object, name: str) -> object:
    return getattr(value, name, None)


def _safe_exception(error: BaseException) -> list[dict[str, object]]:
    """Keep stack locations and machine metadata; omit messages, code and locals."""
    chain: list[dict[str, object]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        detail: dict[str, object] = {"type": _safe_token(type(current).__name__)}
        response = _attribute(current, "response")
        status = _attribute(current, "status_code")
        if status is None:
            status = _attribute(response, "status_code") or _attribute(current, "code")
        if type(status) is int and 100 <= status <= 599:
            detail["http_status"] = status
        code = _safe_token(_attribute(current, "code"))
        if code is not None:
            detail["error_code"] = code
        param = _safe_token(_attribute(current, "param"))
        if param is not None:
            detail["error_param"] = param
        provider_status = _safe_token(_attribute(current, "status"))
        if provider_status is not None:
            detail["provider_status"] = provider_status
        request_id = _attribute(current, "request_id")
        headers = _attribute(response, "headers")
        if request_id is None and isinstance(headers, Mapping):
            request_id = cast(Mapping[str, object], headers).get("x-request-id")
        if isinstance(request_id, str):
            detail["request_id"] = (
                request_id
                if _REQUEST_ID.fullmatch(request_id) and not _SECRET.search(request_id)
                else "[redacted]"
            )
        frames: list[dict[str, object]] = []
        for frame, line in traceback.walk_tb(current.__traceback__):
            frames.append(
                {
                    "file": _safe_token(Path(frame.f_code.co_filename).name),
                    "line": line,
                    "function": _safe_token(frame.f_code.co_name),
                }
            )
            if len(frames) == 48:
                break
        detail["traceback"] = frames
        chain.append(detail)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain


def _write(payload: dict[str, object]) -> None:
    if _active:
        payload["timestamp"] = datetime.now(UTC).isoformat(timespec="milliseconds")
        # Never attach exc_info: standard traceback formatting includes messages
        # and source lines, either of which can contain private prompt data.
        _LOGGER.info("%s", json.dumps(payload, ensure_ascii=True))


def log_image_failure(
    error: BaseException,
    *,
    provider: str,
    model: str,
    operation: Literal["portrait", "scene"],
    reference_count: int,
) -> None:
    """Log only safe image-failure fields, without changing generation behavior."""
    if not _active:
        return
    # Unusual exception objects or logging failures must not replace the
    # provider exception or fall back to printing it to the terminal.
    with contextlib.suppress(Exception):
        _write(
            {
                "event": "image_generation_failed",
                "provider": _safe_token(provider),
                "model": _safe_token(model),
                "operation": operation,
                "reference_count": reference_count,
                "exceptions": _safe_exception(error),
            }
        )


def log_tts_failure(
    error: BaseException,
    *,
    provider: str,
    operation: Literal["preview", "narration", "prefetch"],
) -> None:
    """Record a TTS generation failure without changing generation behavior.

    TTS exceptions are swallowed into logger warnings (messages can contain
    prompt text), so without this the file log never sees why preview or
    narration actually failed.
    """
    if not _active:
        return
    with contextlib.suppress(Exception):
        _write(
            {
                "event": "tts_generation_failed",
                "provider": _safe_token(provider),
                "operation": operation,
                "exceptions": _safe_exception(error),
            }
        )


def log_character_creation(
    *,
    stage: Literal["dispatch", "text_generation", "portrait_generation", "save", "refresh"],
    outcome: Literal[
        "started",
        "succeeded",
        "failed",
        "skipped",
        "no_agent",
        "empty_output",
        "invalid_output",
        "placeholder_saved",
    ],
    provider: str,
    model: str,
    reference_count: int,
    error: BaseException | None = None,
) -> None:
    """Record catalog creation progress without character input or output data."""
    if not _active:
        return
    with contextlib.suppress(Exception):
        event: dict[str, object] = {
            "event": "character_creation",
            "stage": stage,
            "outcome": outcome,
            "provider": _safe_token(provider),
            "model": _safe_token(model),
            "reference_count": reference_count,
        }
        if error is not None:
            event["exceptions"] = _safe_exception(error)
        _write(event)
