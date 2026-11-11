"""Send one release notification with Python's standard library.

Reads DISCORD_WEBHOOK and DISCORD_MESSAGE from the environment. Accepts HTTPS
Discord webhook URLs (including legacy discordapp.com and preview hosts),
preserves query parameters, and waits for Discord to confirm the message.
There are no redirects or retries, and errors never include secrets or bodies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import closing
from http.client import HTTPException, HTTPSConnection
from urllib.parse import parse_qsl, urlencode, urlsplit

TIMEOUT_SECONDS = 30
_HOSTS = {
    f"{prefix}{domain}"
    for prefix in ("", "canary.", "ptb.")
    for domain in ("discord.com", "discordapp.com")
}
_WEBHOOK_PATH = re.compile(r"/api(?:/v[0-9]+)?/webhooks/[0-9]+/[A-Za-z0-9._-]+/?")


class NotificationError(RuntimeError):
    """A notification failure whose message is safe to log."""


def webhook_target(webhook: str) -> tuple[str, str]:
    """Validate the destination and enable acknowledged delivery."""
    try:
        url = urlsplit(webhook)
        host = url.hostname
        if (
            url.scheme != "https"
            or not host
            or host not in _HOSTS
            or url.port not in (None, 443)
            or url.username is not None
            or url.password is not None
            or url.fragment
            or not _WEBHOOK_PATH.fullmatch(url.path)
        ):
            raise ValueError
        query = [
            (key, value)
            for key, value in parse_qsl(url.query, keep_blank_values=True)
            if key != "wait"
        ]
        query.append(("wait", "true"))
        return host, f"{url.path}?{urlencode(query)}"
    except ValueError:
        raise NotificationError(
            "DISCORD_WEBHOOK must be a valid HTTPS Discord webhook URL."
        ) from None


def send_notification(webhook: str, message: str) -> None:
    """Post once, without following redirects or exposing response content."""
    host, target = webhook_target(webhook)
    if not message.strip():
        raise NotificationError("DISCORD_MESSAGE must not be empty.")
    payload = json.dumps({"content": message}).encode("utf-8")
    try:
        with closing(HTTPSConnection(host, timeout=TIMEOUT_SECONDS)) as connection:
            connection.request(
                "POST",
                target,
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://github.com/paulrobello/par-storygen, 1.0)",
                },
            )
            response = connection.getresponse()
            status = response.status
            response.close()
    except TimeoutError:
        raise NotificationError("Discord notification timed out.") from None
    except (OSError, HTTPException):
        raise NotificationError("Discord notification failed (network error).") from None
    if not 200 <= status < 300:
        raise NotificationError(f"Discord notification failed (HTTP {status}).")


def main() -> int:
    """Return a nonzero exit code on configuration or delivery failure."""
    try:
        send_notification(
            os.environ.get("DISCORD_WEBHOOK", ""), os.environ.get("DISCORD_MESSAGE", "")
        )
    except NotificationError as error:
        print(error, file=sys.stderr)
        return 1
    print("Discord notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
