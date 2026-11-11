"""Offline release-notifier tests. No test contacts a webhook."""

from __future__ import annotations

import json
import re
from http.client import HTTPException
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import notify_discord

WEBHOOK = "https://discord.com/api/webhooks/123456789/example-token"


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace all HTTPS transport and isolate potentially configured secrets."""
    monkeypatch.delenv("DISCORD_WEBHOOK", raising=False)
    monkeypatch.delenv("DISCORD_MESSAGE", raising=False)
    factory = MagicMock()
    factory.return_value.getresponse.return_value.status = 200
    monkeypatch.setattr(notify_discord, "HTTPSConnection", factory)
    return factory


def test_payload_identity_and_transport(transport: MagicMock) -> None:
    message = 'A release with "quotes", a newline\n雪 and $(literal text).'
    notify_discord.send_notification(WEBHOOK, message)
    transport.assert_called_once_with("discord.com", timeout=30)
    connection = transport.return_value
    connection.request.assert_called_once()
    args, kwargs = connection.request.call_args
    assert args == ("POST", "/api/webhooks/123456789/example-token?wait=true")
    assert json.loads(kwargs["body"]) == {"content": message}
    assert kwargs["headers"]["Content-Type"] == "application/json"
    connection.close.assert_called_once()
    connection.getresponse.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "host",
    [
        "discord.com",
        "discordapp.com",
        "canary.discord.com",
        "canary.discordapp.com",
        "ptb.discord.com",
        "ptb.discordapp.com",
    ],
)
def test_supported_hosts_and_versioned_webhook(host: str) -> None:
    actual_host, path = notify_discord.webhook_target(
        f"https://{host}:443/api/v10/webhooks/123/token?thread_id=456&wait=false&wait=false"
    )
    assert actual_host == host
    assert urlsplit(path).path == "/api/v10/webhooks/123/token"
    assert parse_qs(urlsplit(path).query) == {"thread_id": ["456"], "wait": ["true"]}


def test_query_preserves_blank_and_repeated_parameters() -> None:
    _, path = notify_discord.webhook_target(
        f"{WEBHOOK}?thread_id=456&extra=&extra=a%2Bb&wait=false"
    )
    assert parse_qs(urlsplit(path).query, keep_blank_values=True) == {
        "thread_id": ["456"],
        "extra": ["", "a+b"],
        "wait": ["true"],
    }


@pytest.mark.parametrize(
    "webhook",
    [
        "",
        "http://discord.com/api/webhooks/123/token",
        "https://discord.com.evil.example/api/webhooks/123/token",
        "https://example.com/api/webhooks/123/token",
        "https://discord.com:8443/api/webhooks/123/token",
        "https://discord.com:invalid/api/webhooks/123/token",
        "https://user:password@discord.com/api/webhooks/123/token",
        "https://discord.com/api/webhooks/123/token#fragment",
        "https://discord.com/channels/123",
        "https://discord.com/api/webhooks/123/",
        "https://[invalid",
    ],
)
def test_invalid_destination_never_connects(webhook: str, transport: MagicMock) -> None:
    with pytest.raises(notify_discord.NotificationError):
        notify_discord.send_notification(webhook, "release")
    transport.assert_not_called()


@pytest.mark.parametrize("message", ["", " \n\t"])
def test_empty_message_never_connects(message: str, transport: MagicMock) -> None:
    with pytest.raises(notify_discord.NotificationError, match="DISCORD_MESSAGE"):
        notify_discord.send_notification(WEBHOOK, message)
    transport.assert_not_called()


@pytest.mark.parametrize("status", [200, 204])
def test_success_exit_code(
    status: int,
    transport: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK", WEBHOOK)
    monkeypatch.setenv("DISCORD_MESSAGE", "release")
    transport.return_value.getresponse.return_value.status = status
    assert notify_discord.main() == 0
    output = capsys.readouterr()
    assert output.out == "Discord notification sent.\n"
    assert output.err == ""


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 404, 429, 500])
def test_http_failure_never_retries_redirects_or_leaks(
    status: int,
    transport: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK", WEBHOOK)
    monkeypatch.setenv("DISCORD_MESSAGE", "private release message")
    response = transport.return_value.getresponse.return_value
    response.status = status
    response.getheader.return_value = "https://example.com/redirect"
    response.read.return_value = b"private response body"
    assert notify_discord.main() == 1
    assert capsys.readouterr().err == f"Discord notification failed (HTTP {status}).\n"
    transport.assert_called_once()
    transport.return_value.request.assert_called_once()
    response.read.assert_not_called()
    response.getheader.assert_not_called()


@pytest.mark.parametrize("error_type", [TimeoutError, OSError, HTTPException])
@pytest.mark.parametrize("operation", ["request", "getresponse"])
def test_transport_failure_is_sanitized_and_not_retried(
    error_type: type[Exception],
    operation: str,
    transport: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK", WEBHOOK)
    monkeypatch.setenv("DISCORD_MESSAGE", "private message")
    getattr(transport.return_value, operation).side_effect = error_type(
        f"private body and URL: {WEBHOOK}"
    )
    assert notify_discord.main() == 1
    expected = "timed out" if error_type is TimeoutError else "failed (network error)"
    assert capsys.readouterr().err == f"Discord notification {expected}.\n"
    transport.assert_called_once()
    transport.return_value.request.assert_called_once()
    transport.return_value.close.assert_called_once()


def test_missing_configuration_is_sanitized(
    transport: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert notify_discord.main() == 1
    assert capsys.readouterr().err == "DISCORD_WEBHOOK must be a valid HTTPS Discord webhook URL.\n"
    transport.assert_not_called()


def test_workflow_preserves_notification_messages_and_failure_handling() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/release.yml").read_text()
    blocks = workflow.split("      - name: Discord notification\n")[1:]
    assert len(blocks) == 3
    expected = [
        (
            "The project ${{ github.repository }} ${{ env.VERSION }} has been published to TestPyPI.",
            True,
        ),
        ("A new release v${{ env.VERSION }} has been created for ${{ github.repository }}.", False),
        (
            "The project ${{ github.repository }} ${{ env.VERSION }} has been published to PyPI.",
            True,
        ),
    ]
    for block, (message, continues) in zip(blocks, expected, strict=True):
        step = re.split(r"(?m)^      - name:|^  [a-z][a-z_-]*:", block, maxsplit=1)[0]
        assert "        if: success()" in step
        assert "          DISCORD_WEBHOOK: ${{ secrets.DISCORD_WEBHOOK }}" in step
        assert f"          DISCORD_MESSAGE: '{message}'" in step
        assert "        run: python scripts/notify_discord.py" in step
        assert ("        continue-on-error: true" in step) is continues
    assert "Ilshidur/action-discord" not in workflow
