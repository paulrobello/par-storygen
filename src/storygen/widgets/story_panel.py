"""StoryPanel: accumulates streamed narration text and renders it."""

from __future__ import annotations

from rich.console import RenderableType
from textual.widgets import Static


class StoryPanel(Static):
    """Writable text panel that the pipeline streams narration into.

    ``markup=False`` prevents LLM-authored narration from being interpreted as
    Rich markup, which would allow prompt-injected text to render styled content
    or clickable links that look like system messages.
    """

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    def reset(self) -> None:
        self._text = ""
        self.update("")

    def append_delta(self, delta: str) -> None:
        self._text += delta
        self.update(self._text)

    def set_text(self, text: str) -> None:
        self._text = text
        self.update(text)

    def set_renderable(self, content: RenderableType) -> None:
        """Display a pre-built Rich renderable (bypasses markup=False restriction).

        Use this instead of ``set_text`` when the caller needs Rich styling
        (e.g. the ending banner) that cannot be expressed as a plain string.
        Does NOT update ``self._text`` so streaming deltas are unaffected.
        """
        self.update(content)
