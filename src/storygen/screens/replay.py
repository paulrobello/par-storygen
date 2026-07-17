"""ReplayScreen: walk root -> target_node beat-by-beat (read-only slideshow).

Pushed from GraphScreen with ``r``. Renders the same narration + image the
player saw when the branch was originally generated, but with no LLM/image
work — purely a static walk over `path_from_root(save, target_node_id)`.

Bindings:
- space / right / n: advance one beat
- left / p: step back one beat
- escape: exit replay
- j: jump to live PlayScreen at the currently displayed beat (NOT the
  branch terminus — the user may have stepped backwards)

The screen takes an optional ``on_jump_to_live`` callback so it stays pure;
GraphScreen wires this to the same ``current_node_id``-set-and-pop logic it
already uses for direct node selection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PIL import Image, UnidentifiedImageError
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from storygen.core.models import NodeId, StoryNode
from storygen.storage import paths
from storygen.storage.save import GameSave
from storygen.storage.tree import path_from_root
from storygen.widgets.image_util import pixels_from_image


class _ReplayImage(Static):
    """Half-block image renderer for one replay beat.

    Deliberately simple — replay is a read-only walk, so unlike PlayScreen's
    ImagePanel there's no live-update, generating-spinner, or background-task
    wiring. ``set_for_node`` swaps the rendered content as the cursor moves.
    """

    def set_for_node(self, save: GameSave, node: StoryNode) -> None:
        if not node.image_path:
            self.update("")
            self.display = False
            return
        abs_path = paths.game_dir(str(save.id)) / node.image_path
        if not abs_path.exists():
            self.update("")
            self.display = False
            return
        try:
            with Image.open(abs_path) as im:
                im = im.convert("RGBA")
                im.thumbnail((96, 48))
                self.display = True
                self.update(pixels_from_image(im))
        except (OSError, ValueError, UnidentifiedImageError):
            self.update("")
            self.display = False


class ReplayScreen(Screen[None]):
    """Walk root -> target_node beat-by-beat, narration + image, press-to-advance."""

    DEFAULT_CSS = """
    ReplayScreen #replay-scroll {
        height: 1fr;
    }
    ReplayScreen #replay-layout {
        height: auto;
        min-height: 100%;
    }
    ReplayScreen #replay-main {
        width: 1fr;
        padding: 0 1;
        height: auto;
    }
    ReplayScreen #replay-side {
        width: auto;
        padding: 0 1;
        height: auto;
    }
    ReplayScreen #replay-narration {
        height: auto;
        margin-bottom: 1;
    }
    ReplayScreen #replay-choice {
        height: auto;
        margin-top: 1;
        padding: 1 1 0 1;
        border-top: hkey $primary;
        color: $accent;
    }
    ReplayScreen #replay-end-hint {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }
    /* Match PlayScreen ImagePanel: 48x24 image cells + 1-cell border each side. */
    ReplayScreen _ReplayImage {
        width: 50;
        height: 26;
        border: round $primary;
        padding: 0;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("space", "next", "Next"),
        ("right", "next", "Next"),
        ("n", "next", "Next"),
        ("left", "prev", "Prev"),
        ("p", "prev", "Prev"),
        ("j", "jump_to_live", "Jump"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(
        self,
        save: GameSave,
        target_node_id: NodeId,
        *,
        on_jump_to_live: Callable[[NodeId], None] | None = None,
    ) -> None:
        super().__init__()
        self._save = save
        self._target_node_id = target_node_id
        self._on_jump_to_live = on_jump_to_live
        # Storing nodes (not just ids) avoids re-lookup at render time.
        self._path: list[StoryNode] = path_from_root(save, target_node_id)
        self._cursor: int = 0
        self._image = _ReplayImage(id="replay-image")
        self._narration = Static("", id="replay-narration", markup=False)
        self._choice = Static("", id="replay-choice", markup=False)
        self._end_hint = Static("", id="replay-end-hint", markup=False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="replay-scroll"), Horizontal(id="replay-layout"):
            with Vertical(id="replay-main"):
                yield self._narration
                yield self._choice
                yield self._end_hint
            with Vertical(id="replay-side"):
                yield self._image
        yield Footer()

    def on_mount(self) -> None:
        self._render_step()

    def _apply_header(self) -> None:
        self.title = f"{self._save.theme.title}  ·  Replay"
        n = len(self._path)
        # 1-indexed for the user.
        self.sub_title = f"Beat {self._cursor + 1}/{n}"

    def _render_step(self) -> None:
        if not self._path:
            # Defensive — path_from_root always returns at least the target.
            self._narration.update("(empty path)")
            self._apply_header()
            return
        node = self._path[self._cursor]
        self._narration.update(node.narration)
        self._image.set_for_node(self._save, node)

        if self._cursor == 0:
            self._choice.update("[Beginning]")
        else:
            parent = self._path[self._cursor - 1]
            choice_text = "?"
            if node.chosen_choice_id is not None:
                for c in parent.choices:
                    if c.id == node.chosen_choice_id:
                        choice_text = c.text
                        break
            self._choice.update(f"You chose: {choice_text}")

        if self._cursor == len(self._path) - 1:
            self._end_hint.update("[End of branch]")
        else:
            self._end_hint.update("")

        self._apply_header()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Hide direction bindings at the boundaries so the footer stays accurate.
        if action == "prev" and self._cursor == 0:
            return False
        return not (action == "next" and self._cursor >= len(self._path) - 1)

    def action_next(self) -> None:
        if self._cursor < len(self._path) - 1:
            self._cursor += 1
            self._render_step()

    def action_prev(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._render_step()

    def action_jump_to_live(self) -> None:
        # Jump to the currently displayed node (NOT target_node_id — the user
        # may have stepped backwards through the branch).
        #
        # Order matters: dismiss FIRST, then fire the callback. Otherwise the
        # callback's downstream pop_screen() would pop ReplayScreen instead of
        # GraphScreen, leaving the user on the graph rather than back at play.
        if not self._path:
            self.dismiss()
            return
        node_id = self._path[self._cursor].id
        self.dismiss()
        if self._on_jump_to_live is not None:
            self._on_jump_to_live(node_id)
