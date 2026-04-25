"""Workarounds for upstream Textual bugs we hit in storygen.

Imported for side effects from ``storygen.app`` so the patches are applied
exactly once before any Header is mounted.
"""

from __future__ import annotations

import contextlib

from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.events import Mount
from textual.widgets import Header
from textual.widgets._header import HeaderTitle


def _patch_header_set_title() -> None:
    """Make Header._on_mount tolerant of NoMatches on its initial fire.

    Textual 8.2.3's ``Header._on_mount`` registers a ``set_title`` watcher
    that synchronously calls ``self.query_one(HeaderTitle)``. The watcher
    fires once at registration time to seed the value, but during the very
    first mount the HeaderTitle child hasn't been mounted yet, so the
    lookup raises NoMatches. Upstream catches NoScreen but not NoMatches,
    so the exception escapes as a noisy "coroutine never awaited"
    traceback at startup. The patch widens the suppression to NoMatches;
    once HeaderTitle exists, the next title-change re-fires the watcher
    and the header renders correctly.
    """

    def patched_on_mount(self: Header, _event: Mount) -> None:
        async def set_title() -> None:
            with contextlib.suppress(NoScreen, NoMatches):
                self.query_one(HeaderTitle).update(self.format_title())

        self.watch(self.app, "title", set_title)  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
        self.watch(self.app, "sub_title", set_title)  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
        self.watch(self.screen, "title", set_title)
        self.watch(self.screen, "sub_title", set_title)

    Header._on_mount = patched_on_mount  # type: ignore[method-assign]


_patch_header_set_title()
