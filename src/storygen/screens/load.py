"""LoadGameScreen: pick a saved game to resume."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar, Protocol

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from storygen.images._prompts import build_cover_prompt
from storygen.images.base import ReferencePortrait
from storygen.images.constants import SCENE_QUALITY, SCENE_SIZE
from storygen.images.pricing import image_cost
from storygen.screens._confirm_modal import ConfirmModal
from storygen.storage import app_state, paths
from storygen.storage.save import GameSave, delete_game, load_game, save_game
from storygen.util import copy_text_to_system_clipboard, open_in_system_viewer
from storygen.widgets._image_util import render_image_thumbnail

_logger = logging.getLogger(__name__)


class _CoverImageProvider(Protocol):
    """Minimal image-provider surface used for cover backfill + regen."""

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
    ) -> bytes: ...


class StorySetupDetailsModal(Screen[None]):
    """Modal showing wizard settings and user prompts used to create a save."""

    DEFAULT_CSS = """
    StorySetupDetailsModal {
        align: center middle;
    }
    StorySetupDetailsModal #setup-details-box {
        width: 90;
        height: 80%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    StorySetupDetailsModal #setup-details-scroll {
        height: 1fr;
    }
    StorySetupDetailsModal .setup-details-title {
        text-style: bold;
        margin-bottom: 1;
    }
    StorySetupDetailsModal .setup-details-section-row {
        height: auto;
        margin-top: 1;
    }
    StorySetupDetailsModal .setup-details-section {
        width: 1fr;
        text-style: bold;
        color: $accent;
    }
    StorySetupDetailsModal .setup-details-copy {
        min-width: 8;
        margin-left: 1;
    }
    StorySetupDetailsModal #setup-details-close {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "close", "Close"),
    ]

    def __init__(self, save: GameSave) -> None:
        super().__init__()
        self._save = save
        self._copy_values: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-details-box"):
            yield Static(self._save.theme.title, classes="setup-details-title", markup=False)
            with VerticalScroll(id="setup-details-scroll"):
                for index, (label, value) in enumerate(self._detail_rows()):
                    copy_id = f"copy-detail-{index}"
                    self._copy_values[copy_id] = value
                    with Horizontal(classes="setup-details-section-row"):
                        yield Static(label, classes="setup-details-section", markup=False)
                        yield Button("Copy", id=copy_id, classes="setup-details-copy")
                    yield Static(value or "(blank)", markup=False)
            yield Button("Close", id="setup-details-close", variant="primary")

    def _detail_rows(self) -> list[tuple[str, str]]:
        save = self._save
        prompts = save.creation_prompts
        characters = "\n".join(
            f"- {c.name}: {c.personality or c.backstory or c.physical_description}"
            for c in save.characters
        )
        return [
            ("Theme prompt", prompts.theme_prompt),
            ("Character prompt", prompts.character_prompt),
            ("Theme", f"{save.theme.title}\n{save.theme.setting}\n{save.theme.premise}"),
            ("Tone", f"{save.tone.preset} {save.tone.custom_descriptor or ''}".strip()),
            ("Narration style", save.narration_style),
            ("Art style", save.art_style),
            ("Story length", f"{save.target_major_beats} major beats"),
            ("Reader level", save.reader_level),
            ("Pacing", save.pacing),
            ("Text provider", f"{save.text_config.provider} / {save.text_config.model}"),
            ("Scene image provider", f"{save.image_config.provider} / {save.image_config.model}"),
            (
                "Character image provider",
                f"{save.character_image_config.provider} / {save.character_image_config.model}",
            ),
            ("Characters", characters),
        ]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "setup-details-close":
            self.dismiss(None)
            return
        if button_id.startswith("copy-detail-"):
            text = self._copy_values.get(button_id, "")
            self.app.copy_to_clipboard(text)  # pyright: ignore[reportUnknownMemberType]
            copy_text_to_system_clipboard(text)
            self.notify("Copied section to clipboard.", timeout=2)

    def action_close(self) -> None:
        self.dismiss(None)


class LoadGameScreen(Screen[None]):
    """Lists saved games with explicit Load + Delete buttons per row.

    Clicking a row no longer auto-opens the save: use the Load button to
    resume, or Delete (with confirmation) to remove it permanently.
    """

    DEFAULT_CSS = """
    LoadGameScreen #load-body {
        padding: 1 2;
    }
    LoadGameScreen .load-row {
        height: 14;
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
        overflow-y: hidden;
    }
    LoadGameScreen .load-cover {
        width: 24;
        height: 12;
        margin-right: 2;
    }
    LoadGameScreen .load-meta {
        width: 1fr;
        height: auto;
    }
    LoadGameScreen .load-title {
        text-style: bold;
    }
    LoadGameScreen .load-sub {
        color: $text-muted;
    }
    LoadGameScreen .load-buttons {
        height: auto;
        align-horizontal: right;
    }
    LoadGameScreen .load-buttons Button {
        margin-left: 1;
    }
    LoadGameScreen #load-empty {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
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
        on_save_selected: Callable[[GameSave], Awaitable[None]] | None = None,
        image_provider_factory: Callable[[GameSave], _CoverImageProvider] | None = None,
    ) -> None:
        super().__init__()
        self._on_save_selected = on_save_selected
        self._image_provider_factory = image_provider_factory
        self._scroll = VerticalScroll(id="load-list")
        self._empty_label = Static("No saved games yet.", id="load-empty")
        # Set True while a load is in flight so a user who clicks a second
        # Load button while the pipeline is still booting doesn't fire two
        # parallel _start_game handlers.
        self._loading = False
        # Tracks game_ids currently running a cover-gen worker so a second
        # Regenerate click (or a spurious auto-backfill) doesn't spawn a
        # duplicate generation for the same save.
        self._cover_busy: set[str] = set()
        # Ordered list of save IDs currently rendered (for keyboard nav).
        self._saves_order: list[str] = []
        self._focused_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="load-body"):
            yield self._empty_label
            yield self._scroll
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def on_screen_resume(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self._scroll.remove_children()
        saves = _scan_saves()
        if not saves:
            self._scroll.display = False
            self._empty_label.display = True
            return
        self._empty_label.display = False
        self._scroll.display = True
        self._saves_order: list[str] = []
        for save in saves:
            self._mount_row(save)
            self._saves_order.append(str(save.id))
        self._auto_backfill_covers(saves)

    def _auto_backfill_covers(self, saves: list[GameSave]) -> None:
        """Fire a cover-gen worker for each save that is missing one.

        Only runs when ``art_enabled()`` is True AND an image-provider factory
        is configured. The ``_cover_busy`` guard inside ``_start_regen``
        prevents duplicate workers from a second refresh.
        """
        if self._image_provider_factory is None or not app_state.art_enabled():
            return
        for save in saves:
            root = save.nodes.get(save.root_node_id)
            if root is None:
                continue
            if root.image_status == "done" and root.image_path:
                continue
            self._start_regen(str(save.id), force=False, title=save.theme.title)

    def _mount_row(self, save: GameSave) -> None:
        row = Horizontal(classes="load-row")
        self._scroll.mount(row)
        row.mount(self._render_cover(save))
        meta = Vertical(classes="load-meta")
        row.mount(meta)
        meta.mount(Static(save.theme.title, classes="load-title", markup=False))
        meta.mount(
            Static(
                f"updated {save.updated_at.strftime('%Y-%m-%d %H:%M')}  ·  {len(save.nodes)} nodes",
                classes="load-sub",
                markup=False,
            )
        )
        buttons = Horizontal(classes="load-buttons")
        meta.mount(buttons)
        buttons.mount(Button("Load", id=f"load-{save.id}", variant="primary"))
        buttons.mount(Button("Details", id=f"details-{save.id}"))
        regen_btn = Button("Regen Cover", id=f"regen-{save.id}")
        regen_btn.disabled = (
            self._image_provider_factory is None or str(save.id) in self._cover_busy
        )
        buttons.mount(regen_btn)
        buttons.mount(Button("Delete", id=f"delete-{save.id}", variant="error"))

    def _render_cover(self, save: GameSave) -> Static:
        """Half-block thumbnail of the save's cover (root-node image).

        Falls back to a hidden placeholder if the root node has no
        ``image_path`` yet (legacy saves awaiting backfill), the path is
        missing on disk, or decoding fails inside ``render_image_thumbnail``.
        """
        root = save.nodes.get(save.root_node_id)
        if root is None or not root.image_path:
            cover = Static("", classes="load-cover")
            cover.display = False
            return cover
        try:
            abs_path = paths.safe_join(paths.game_dir(str(save.id)), root.image_path)
        except ValueError:
            cover = Static("", classes="load-cover")
            cover.display = False
            return cover
        return render_image_thumbnail(
            abs_path,
            size=(80, 40),
            css_class="load-cover",
            placeholder="(no cover)",
            on_click=open_in_system_viewer,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("load-"):
            self._start_load(button_id[len("load-") :])
            return
        if button_id.startswith("details-"):
            self._show_details(button_id[len("details-") :])
            return
        if button_id.startswith("regen-"):
            game_id = button_id[len("regen-") :]
            title: str | None = None
            with contextlib.suppress(Exception):
                title = load_game(game_id).theme.title
            self._start_regen(game_id, force=True, title=title)
            return
        if button_id.startswith("delete-"):
            self._start_delete(button_id[len("delete-") :])

    def _show_details(self, game_id: str) -> None:
        try:
            save = load_game(game_id)
        except Exception:
            _logger.debug("Could not load game for details", exc_info=True)
            self.notify("Save no longer exists.", severity="error", timeout=5)
            self._refresh()
            return
        self.app.push_screen(StorySetupDetailsModal(save))  # pyright: ignore[reportUnknownMemberType]

    def action_focus_next_row(self) -> None:
        if not self._saves_order:
            return
        self._focused_idx = min(self._focused_idx + 1, len(self._saves_order) - 1)
        self._focus_row(self._focused_idx)

    def action_focus_prev_row(self) -> None:
        if not self._saves_order:
            return
        self._focused_idx = max(self._focused_idx - 1, 0)
        self._focus_row(self._focused_idx)

    def _focus_row(self, idx: int) -> None:
        if idx >= len(self._saves_order):
            return
        game_id = self._saves_order[idx]
        try:
            btn = self._scroll.query_one(f"#load-{game_id}", Button)
            btn.focus()
        except Exception:
            pass

    def _start_load(self, game_id: str) -> None:
        if self._loading or self._on_save_selected is None:
            return
        try:
            save = load_game(game_id)
        except Exception:
            _logger.debug("Could not load game", exc_info=True)
            self.notify("Could not load game.", severity="error", timeout=5)
            return
        self._loading = True
        # Disable every row's buttons so a second click can't spawn a
        # parallel _start_game while the pipeline boots. Relabel the clicked
        # Load button so the list itself shows progress while the app builds
        # the play screen.
        loading_button_id = f"load-{game_id}"
        for btn in self._scroll.query(Button):
            if btn.id == loading_button_id:
                btn.label = "Loading…"
            btn.disabled = True
        self.notify("Loading…", timeout=5)
        self._run_on_save_selected(save)

    @staticmethod
    def _label_for(save: GameSave) -> str:
        """Shared label used in the delete confirmation prompt."""
        return (
            f"{save.theme.title}  —  updated "
            f"{save.updated_at.strftime('%Y-%m-%d %H:%M')}  ·  "
            f"{len(save.nodes)} nodes"
        )

    def _start_regen(
        self,
        game_id: str,
        *,
        force: bool,
        title: str | None = None,
    ) -> None:
        """Kick off a cover-art worker for ``game_id``.

        Args:
            game_id: Save id whose cover to (re)generate.
            force: When True, regenerate even if the save already has a cover
                (Regenerate button). When False (auto-backfill path), the
                worker double-checks and no-ops if the cover landed in between.
            title: Human-readable save title used for the progress toast.
                When None, the toast text falls back to a generic string.

        When ``force`` is True, the Regen-Cover button for this save is
        disabled + relabeled "Working…" and a progress toast is shown so the
        user has immediate feedback that a background job started.
        """
        if self._image_provider_factory is None:
            if force:
                self.notify(
                    "No image provider configured — cannot regenerate.",
                    severity="error",
                    timeout=5,
                )
            return
        if not app_state.art_enabled():
            if force:
                self.notify(
                    "Art generation is disabled in Settings.",
                    severity="warning",
                    timeout=5,
                )
            return
        if game_id in self._cover_busy:
            if force:
                self.notify("Already generating cover art for this save.", timeout=5)
            return
        self._cover_busy.add(game_id)
        if force:
            self._disable_regen_button(game_id)
            display_title = title or "this save"
            self.notify(
                f"Generating cover art for '{display_title}'…",
                timeout=5,
            )
        self._cover_worker(game_id, force=force)

    def _disable_regen_button(self, game_id: str) -> None:
        """Disable the Regen Cover button for ``game_id`` and show a Working… label."""
        try:
            btn = self._scroll.query_one(f"#regen-{game_id}", Button)
        except Exception:
            return
        btn.disabled = True
        btn.label = "Working…"

    @work(exit_on_error=False)
    async def _cover_worker(self, game_id: str, *, force: bool) -> None:
        """Reload the save from disk, generate cover art, persist, and refresh."""
        try:
            save = load_game(game_id)
        except Exception:
            _logger.debug("Could not load save for cover regen", exc_info=True)
            self._cover_busy.discard(game_id)
            return
        root = save.nodes.get(save.root_node_id)
        if root is None:
            self._cover_busy.discard(game_id)
            return
        already_done = root.image_status == "done" and bool(root.image_path)
        if already_done and not force:
            self._cover_busy.discard(game_id)
            return
        if self._image_provider_factory is None:
            self._cover_busy.discard(game_id)
            return
        provider = self._image_provider_factory(save)
        save.nodes[save.root_node_id] = root.model_copy(update={"image_status": "generating"})
        save_game(save)
        cover_prompt = build_cover_prompt(
            theme_title=save.theme.title,
            theme_description=f"{save.theme.setting} {save.theme.premise}",
            art_style=save.art_style,
        )
        try:
            cover_bytes = await provider.generate_scene(
                cover_prompt,
                reference_portraits=[],
                art_style=save.art_style,
            )
        except Exception:
            _logger.debug("Cover generation failed", exc_info=True)
            save.nodes[save.root_node_id] = root.model_copy(update={"image_status": "failed"})
            save_game(save)
            self.notify(
                f"Cover art failed for '{save.theme.title}'.",
                severity="error",
                timeout=5,
            )
            self._cover_busy.discard(game_id)
            self._refresh()
            return
        cover_path = paths.node_image_path(str(save.id), save.root_node_id)
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        cover_path.write_bytes(cover_bytes)
        cover_rel = str(cover_path.relative_to(paths.game_dir(str(save.id))))
        save.nodes[save.root_node_id] = root.model_copy(
            update={
                "image_prompt": cover_prompt,
                "image_path": cover_rel,
                "image_status": "done",
            }
        )
        save.total_image_cost_usd += image_cost(
            save.image_config.provider,
            model=save.image_config.model,
            size=SCENE_SIZE,
            quality=SCENE_QUALITY,
        )
        save_game(save)
        self._cover_busy.discard(game_id)
        self.notify(f"Cover art ready for '{save.theme.title}'.", timeout=5)
        self._refresh()

    def _start_delete(self, game_id: str) -> None:
        try:
            save = load_game(game_id)
        except Exception:
            _logger.debug("Could not load game for delete", exc_info=True)
            self.notify("Save no longer exists.", severity="error", timeout=5)
            self._refresh()
            return
        label = self._label_for(save)

        def _after_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                delete_game(game_id)
            except Exception:
                _logger.debug("Delete failed", exc_info=True)
                self.notify("Delete failed.", severity="error", timeout=5)
                return
            self.notify("Save deleted.", timeout=5)
            self._refresh()

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ConfirmModal(f"Delete this save? This cannot be undone.\n\n{label}"),
            _after_confirm,
        )

    def _run_on_save_selected(self, save: GameSave) -> None:
        """Invoke the async ``on_save_selected`` callback via ``app.run_worker``.

        Kept as a thin wrapper so tests can patch it without monkey-patching
        Textual internals.
        """
        if self._on_save_selected is None:
            return
        callback = self._on_save_selected

        async def _worker() -> None:
            try:
                await callback(save)
            except Exception:
                _logger.debug("Failed to start game", exc_info=True)
                self.notify("Failed to start game.", severity="error", timeout=5)
                self._loading = False
                for btn in self._scroll.query(Button):
                    btn.disabled = False

        self.app.run_worker(_worker(), exclusive=False)  # pyright: ignore[reportUnknownMemberType]


def _scan_saves() -> list[GameSave]:
    """Read every valid save under games_root, newest first."""
    root = paths.games_root()
    if not root.exists():
        return []
    results: list[GameSave] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        if not (d / "game.json").exists():
            continue
        try:
            results.append(load_game(d.name))
        except Exception:
            continue
    return sorted(results, key=lambda s: s.updated_at, reverse=True)
