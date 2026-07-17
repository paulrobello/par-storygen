"""EndingsScreen: browse every ending reached in the current save.

For each entry in ``save.endings_reached`` (chronological, append-only) we
render a card with:

- A half-block thumbnail of the ending node's image (or "[no image]").
- A short narration excerpt (first 200 chars).
- A breadcrumb describing the choice path from the root to the ending.
- A Jump button that hands the ending's node id back via ``on_jump`` and
  dismisses the screen.

The screen is pushed instance-style by PlayScreen — no ``install_screen``
wiring at the App level, matching the GraphScreen / CharacterCatalogScreen
pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from storygen.core.models import NodeId, StoryNode
from storygen.storage import paths
from storygen.storage.save import GameSave
from storygen.storage.tree import path_from_root
from storygen.widgets.image_util import render_image_thumbnail

# Maximum length of the narration excerpt rendered per card. Endings tend to
# be short, but the cap keeps a verbose ending from blowing the card height
# out of proportion with its peers.
_NARRATION_MAX = 200
# Max width of an individual choice text inside the breadcrumb. Long choice
# strings are ellipsized so the breadcrumb stays scannable.
_CHOICE_MAX = 40


def _excerpt(text: str, *, max_len: int = _NARRATION_MAX) -> str:
    """Collapse whitespace and truncate to ``max_len`` chars with an ellipsis."""
    flat = " ".join(text.split())
    if len(flat) <= max_len:
        return flat
    return flat[: max_len - 1].rstrip() + "…"


def _truncate_choice(text: str, *, max_len: int = _CHOICE_MAX) -> str:
    flat = " ".join(text.split())
    if len(flat) <= max_len:
        return flat
    return flat[: max_len - 1].rstrip() + "…"


def _build_breadcrumb(save: GameSave, node_id: NodeId) -> str:
    """Render a breadcrumb of the form 'Beat 1 → "choice text" → Beat 2 → ...'.

    Walks ``path_from_root`` (root..ending inclusive). For each non-root node
    the incoming edge is the parent's choice whose id matches the child's
    ``chosen_choice_id``; that text is rendered between the surrounding beat
    markers.
    """
    chain = path_from_root(save, node_id)
    if not chain:
        return ""
    parts: list[str] = ["Beat 1"]
    for idx, child in enumerate(chain[1:], start=1):
        parent = chain[idx - 1]
        choice_text = "?"
        if child.chosen_choice_id is not None:
            for c in parent.choices:
                if c.id == child.chosen_choice_id:
                    choice_text = c.text
                    break
        parts.append(f"'{_truncate_choice(choice_text)}'")
        parts.append(f"Beat {idx + 1}")
    return " → ".join(parts)


class EndingsScreen(Screen[None]):
    """Modal screen listing every ending reached, with image + jump-to-node."""

    DEFAULT_CSS = """
    EndingsScreen #endings-body {
        padding: 1 2;
    }
    EndingsScreen #endings-empty {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }
    EndingsScreen .ending-card {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
    }
    /* Scene PNGs are 1024x1024 thumbnailed to (60, 30) -> 30x30 image cells
       wide x ~15 tall in half-block render. The +2 in each dimension is for
       the rounded border. Smaller than PlayScreen's 50x26 so 2-3 cards fit
       on a typical terminal at once. */
    EndingsScreen .ending-thumb {
        width: 32;
        height: 17;
        margin-right: 2;
        border: round $primary 50%;
    }
    EndingsScreen .ending-meta {
        width: 1fr;
        height: auto;
    }
    EndingsScreen .ending-narration {
        margin-bottom: 1;
    }
    EndingsScreen .ending-breadcrumb {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "app.pop_screen", "Back"),
        ("j", "focus_next_row", "▼ Next"),
        ("k", "focus_prev_row", "▲ Prev"),
        ("down", "focus_next_row", "▼ Next"),
        ("up", "focus_prev_row", "▲ Prev"),
    ]

    def __init__(
        self,
        save: GameSave,
        on_jump: Callable[[NodeId], None],
    ) -> None:
        super().__init__()
        self._save = save
        self._on_jump = on_jump
        self._ending_ids: list[str] = [nid for nid in save.endings_reached if nid in save.nodes]
        self._focused_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        if not self._save.endings_reached:
            yield Center(
                Static("No endings reached yet.", id="endings-empty"),
            )
        else:
            with VerticalScroll(id="endings-body"):
                for node_id in self._save.endings_reached:
                    node = self._save.nodes.get(node_id)
                    if node is None:
                        # Defensive: endings_reached is append-only so this
                        # shouldn't happen, but render a stub if it does so a
                        # corrupted save doesn't crash the screen.
                        yield Static(
                            f"(missing ending node: {node_id})",
                            classes="ending-card",
                        )
                        continue
                    yield self._build_card(node)
        yield Footer()

    def on_mount(self) -> None:
        self._apply_header()

    def _apply_header(self) -> None:
        """Mirror PlayScreen's header convention with an endings-specific subtitle."""
        self.title = self._save.theme.title
        n = len(self._save.endings_reached)
        self.sub_title = f"Endings ({n} reached)"

    def action_focus_next_row(self) -> None:
        if not self._ending_ids:
            return
        self._focused_idx = min(self._focused_idx + 1, len(self._ending_ids) - 1)
        self._focus_row(self._focused_idx)

    def action_focus_prev_row(self) -> None:
        if not self._ending_ids:
            return
        self._focused_idx = max(self._focused_idx - 1, 0)
        self._focus_row(self._focused_idx)

    def _focus_row(self, idx: int) -> None:
        if idx >= len(self._ending_ids):
            return
        node_id = self._ending_ids[idx]
        try:
            btn = self.query_one(f"#jump-{node_id}", Button)
            btn.focus()
        except Exception:
            pass

    def _build_card(self, node: StoryNode) -> Horizontal:
        """Construct one card (image + narration + breadcrumb + jump button)."""
        thumb = self._render_thumb(node)
        narration = Static(
            _excerpt(node.narration),
            classes="ending-narration",
        )
        breadcrumb = Static(
            _build_breadcrumb(self._save, node.id),
            classes="ending-breadcrumb",
        )
        jump_btn = Button("Jump", id=f"jump-{node.id}", variant="primary")
        meta = Vertical(narration, breadcrumb, jump_btn, classes="ending-meta")
        return Horizontal(thumb, meta, classes="ending-card")

    def _render_thumb(self, node: StoryNode) -> Static:
        """Render the ending's image as a half-block thumbnail, or a hidden placeholder."""
        if not node.image_path:
            thumb = Static("", classes="ending-thumb")
            thumb.display = False
            return thumb
        return render_image_thumbnail(
            paths.game_dir(str(self._save.id)) / node.image_path,
            size=(60, 30),
            css_class="ending-thumb",
            placeholder="(unavailable)",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("jump-"):
            return
        node_id = button_id[len("jump-") :]
        # Fire callback first; caller persists state and may pop screens.
        self._on_jump(node_id)
        # Defensive: if the caller didn't already pop us (the GraphScreen
        # pattern is for the caller to do it explicitly), dismiss ourselves
        # so the user lands back on PlayScreen either way.
        if self.is_attached:
            self.dismiss()
