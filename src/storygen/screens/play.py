"""PlayScreen: the main gameplay loop."""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import ClassVar

from pyfiglet import Figlet
from rich.align import Align
from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header

from storygen.core.models import Recap
from storygen.export.book import export_book
from storygen.llm.models import NodeId, StoryNode
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.screens._art_edit_modal import ArtEditModal, ArtEditMode, ArtEditResult
from storygen.screens._confirm_modal import ConfirmModal
from storygen.screens._recap_modal import RecapModal
from storygen.screens.endings import EndingsScreen
from storygen.screens.graph import GraphScreen
from storygen.screens.portraits import PortraitsScreen
from storygen.screens.relationships import RelationshipsScreen
from storygen.storage import app_state, paths
from storygen.storage.save import GameSave, save_game
from storygen.tts.player import TTSPlayer, TTSState
from storygen.util import open_in_system_viewer
from storygen.widgets._header_util import format_cost_subtitle
from storygen.widgets.choice_list import ChoiceList
from storygen.widgets.image_panel import ImagePanel
from storygen.widgets.story_panel import StoryPanel
from storygen.widgets.throbber import Throbber

_RECAP_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.5)


def _is_transient_recap_error(exc: Exception) -> bool:
    """Return True for provider errors that are likely worth retrying."""
    text = str(exc).lower()
    transient_terms = (
        "network",
        "timeout",
        "timed out",
        "try again later",
        "temporarily",
        "connection",
        "rate limit",
    )
    return any(term in text for term in transient_terms)


class PlayScreen(Screen[None]):
    """Main gameplay screen: streams story beats and presents choices."""

    DEFAULT_CSS = """
    PlayScreen #play-scroll {
        height: 1fr;
    }
    PlayScreen #play-layout {
        height: auto;
        min-height: 100%;
    }
    PlayScreen #main-col {
        /* Side col is fixed-width (image + border + col padding); we take
           everything else. */
        width: 1fr;
        padding: 0 1;
        height: auto;
    }
    PlayScreen #side-col {
        /* Hugs the image's fixed dimensions instead of stretching as a
           flexible column. Using 'auto' lets the side bar collapse to
           exactly the image-panel width + the column's own padding. */
        width: auto;
        padding: 0 1;
        height: auto;
    }
    PlayScreen StoryPanel {
        height: auto;
        margin-top: 1;
        margin-bottom: 1;
    }
    /* Scene PNGs are 1024x1024 thumbnailed to (96, 48) -> 48x48 pixels ->
       48 cells wide x 24 cells tall in half-block render. The +2 in each
       dimension accounts for the rounded border (1 cell each side).
       Sizing the container to the image (rather than letting it stretch)
       keeps the frame snug and avoids dead space inside the border. */
    PlayScreen ImagePanel {
        width: 50;
        height: 26;
        border: round $primary;
        padding: 0;
    }
    /* Hover affordance — only meaningful once an image is loaded; before
       then the click handler no-ops, but the brighter border on hover is a
       harmless cue. */
    PlayScreen ImagePanel:hover {
        border: round $accent;
    }
    PlayScreen ChoiceList {
        height: auto;
        margin-top: 1;
        padding: 1 1 0 1;
        border-top: hkey $primary;
        color: $accent;
    }
    PlayScreen Throbber {
        margin-top: 0;
        margin-bottom: 0;
    }
    """

    # Footer space is tight: keep labels short and verb-first. Choice slots
    # show only when the current node actually has that many choices (see
    # check_action below); the LLM is asked for 2-4 so 5..9 are usually
    # hidden, but the bindings exist for the rare case the model returns more.
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("b", "go_back", "Back 1 node"),
        ("r", "regen_picker", "Regen"),
        ("i", "info_picker", "Info"),
        ("R", "recap", "Previously on..."),
        ("a", "auto_select", "Auto play"),
        ("t", "tts_toggle", "Read aloud"),
        ("T", "tts_restart", "Restart TTS"),
        ("s", "tts_stop", "Stop TTS"),
        ("m", "menu", "Main menu"),
        ("escape", "menu", "Main menu"),
        ("1", "pick(1)", "Pick 1"),
        ("2", "pick(2)", "Pick 2"),
        ("3", "pick(3)", "Pick 3"),
        ("4", "pick(4)", "Pick 4"),
        ("5", "pick(5)", "Pick 5"),
        ("6", "pick(6)", "Pick 6"),
        ("7", "pick(7)", "Pick 7"),
        ("8", "pick(8)", "Pick 8"),
        ("9", "pick(9)", "Pick 9"),
        ("j", "highlight_next", "▼ Choice"),
        ("k", "highlight_prev", "▲ Choice"),
        ("down", "highlight_next", "▼ Choice"),
        ("up", "highlight_prev", "▲ Choice"),
        ("enter", "pick_highlighted", "Pick ▸"),
        ("x", "export_book", "Export book"),
    ]

    def __init__(
        self,
        save: GameSave,
        *,
        pipeline: BeatPipeline | None,
        image_provider: object | None = None,
        tts_player: TTSPlayer | None = None,
    ) -> None:
        super().__init__()
        self._save = save
        self._pipeline = pipeline
        self._image_provider = image_provider
        self._tts_player = tts_player
        self._image = ImagePanel()
        self._image.set_protocol(app_state.read_graphics_mode())
        self._story = StoryPanel()
        self._choices = ChoiceList()
        self._throbber = Throbber()
        # True while a beat is being generated — disables all bindings so the
        # previous beat's choices/back/regen don't fire on the wrong state.
        self._loading: bool = False
        self._auto_selecting: bool = False
        self._image_displayed_at: float | None = None
        # True while an edit-regen worker is in flight — prevents
        # on_screen_resume from clobbering show_generating().
        self._edit_regen_active: bool = False
        # True while a retry-image worker is in flight — same guard.
        self._image_regen_active: bool = False
        # Last node id we kicked off prefetch FROM. _maybe_start_prefetch
        # short-circuits when current_node_id matches this — the comparison
        # IS the reset, so picks/jumps that change current_node_id naturally
        # re-arm the next call. Limitation: if all pending choices become
        # cached via some other path while this is still pinned, a redundant
        # call would be a no-op (start_prefetch skips cached choices).
        self._last_prefetched_from: NodeId | None = None
        self._major_beats_since_recap: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="play-scroll"), Horizontal(id="play-layout"):
            with Vertical(id="main-col"):
                yield self._story
                yield self._throbber
                yield self._choices
            with Vertical(id="side-col"):
                yield self._image
        yield Footer()

    def on_mount(self) -> None:
        self._render_current()
        self._apply_header()
        self._maybe_auto_start_select()

    def _maybe_auto_start_select(self) -> None:
        """Start auto-select if the persisted setting is enabled and not already running."""
        if self._auto_selecting or self._loading or self._pipeline is None:
            return
        if not app_state.auto_select_enabled():
            return
        node = self._save.nodes.get(self._save.current_node_id)
        if node is None or node.is_ending or not node.choices:
            return

        def _after_confirm(confirmed: bool | None) -> None:
            if confirmed and self.is_attached:
                self._start_auto_select()

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ConfirmModal(
                "Auto-select is enabled. Start auto-playing this story now?",
                confirm_label="Start auto-play",
                cancel_label="Not now",
            ),
            _after_confirm,
        )

    def _start_auto_select(self) -> None:
        """Start auto-select immediately without another confirmation prompt."""
        if self._auto_selecting or self._loading or self._pipeline is None:
            return
        node = self._save.nodes.get(self._save.current_node_id)
        if node is None or node.is_ending or not node.choices:
            return
        self._auto_selecting = True
        self.run_worker(self._auto_select_next(), exclusive=True, name="auto-select")

    async def on_unmount(self) -> None:
        """Cancel any in-flight prefetch tasks and TTS before the screen tears down.

        Avoids asyncio cancelling a prefetch mid-``save_game`` (or mid-portrait
        write) at app shutdown. ``cancel_all_prefetches`` is a no-op when
        nothing is in flight.
        """
        self._auto_selecting = False
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        if self._tts_player is not None:
            await self._tts_player.stop()

    async def _stop_tts(self) -> None:
        """Stop any playing TTS audio."""
        if self._tts_player is not None:
            await self._tts_player.stop()

    def _apply_header(self) -> None:
        """Set the screen title to the story theme + cumulative image cost + tokens."""
        self.title = self._save.theme.title
        subtitle = format_cost_subtitle(self._save)
        node = self._save.nodes[self._save.current_node_id]
        if node.tts_audio_path:
            subtitle += "  ♪"
        self.sub_title = subtitle

    def _render_current(self) -> None:
        node = self._save.nodes[self._save.current_node_id]
        if node.is_ending:
            fig = Figlet(font="blocky")
            from storygen.screens.intro import gradient_text

            banner = gradient_text(fig.renderText("The End"))
            self._story.set_renderable(Group(Text(node.narration), Text(), Align.center(banner)))
        else:
            self._story.set_text(node.narration)
        self._choices.set_choices(node.choices)
        # Don't clobber the image panel's generating throbber with a
        # "not_planned" status from a node whose illustration hasn't started.
        # Once the image pipeline sets a real status (generating/done/failed),
        # the committed/failed callbacks drive the panel directly.
        if node.image_status not in ("not_planned",):
            self._render_image_for(node.image_status, node.image_path)
        # Choice count, parent, and image state may have changed — refresh footer.
        self.refresh_bindings()
        self._apply_header()
        # Branch prefetch: any time the player is settled on a beat (not
        # mid-generation) and there are pending choices to consider, kick off
        # background generation for them. Idempotent + Settings-gated.
        if not self._loading:
            self._maybe_start_prefetch()

    def _maybe_start_prefetch(self) -> None:
        """Kick off branch prefetch if Settings has it enabled.

        Reads ``app_state.prefetch_enabled()`` live so toggling Settings
        takes effect on the next render. ``BeatPipeline.start_prefetch`` is
        itself idempotent (skips already-cached choices, skips choices with
        an in-flight task, skips terminal nodes) so this can fire freely.

        Screen-level dedupe: short-circuits when the current node hasn't
        changed since the last prefetch wave. ``_render_current`` is invoked
        from many entry points (mount, beat-committed, screen-resume, image
        callbacks); without this guard each one would re-iterate every
        choice and do redundant dict lookups even though the pipeline's
        ``_prefetch_tasks`` already prevents duplicate task spawns.
        """
        if self._pipeline is None:
            return
        if not app_state.prefetch_enabled():
            return
        current = self._save.current_node_id
        if current == self._last_prefetched_from:
            return  # already kicked off prefetch for this node
        self._last_prefetched_from = current
        self._pipeline.start_prefetch(
            self._save,
            from_node_id=current,
            with_images=app_state.prefetch_images_enabled(),
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # While a beat is generating, keep navigation disabled so actions don't
        # apply to stale choices; TTS controls are safe and must remain available
        # when auto-play is waiting on image generation while audio is playing.
        if self._loading and action not in (
            "menu",
            "recap",
            "auto_select",
            "tts_stop",
            "tts_restart",
            "highlight_next",
            "highlight_prev",
        ):
            return False
        # During auto-select, only menu, auto_select, and TTS controls are available.
        if self._auto_selecting and action not in (
            "menu",
            "auto_select",
            "tts_toggle",
            "tts_stop",
            "tts_restart",
        ):
            return False
        node = self._save.nodes.get(self._save.current_node_id)
        if node is None:
            return True
        if action == "pick":
            # parameters is (n,) for parameterized action pick(N)
            if parameters:
                try:
                    n = int(str(parameters[0]))
                    return n <= len(node.choices)
                except (ValueError, TypeError):
                    return None
            return None
        if action == "pick_highlighted":
            return bool(node.choices) and self._choices.highlighted is not None
        if action in ("highlight_next", "highlight_prev"):
            return bool(node.choices)
        if action == "go_back":
            return node.parent_id is not None
        if action == "regen_picker":
            return True
        if action == "info_picker":
            return True
        if action == "tts_toggle":
            return self._tts_player is not None and self._tts_player.is_configured
        if action == "tts_restart":
            if self._tts_player is None:
                return False
            return self._tts_player.state in (TTSState.PLAYING, TTSState.PAUSED)
        if action == "tts_stop":
            if self._tts_player is None:
                return False
            return self._tts_player.state in (
                TTSState.PLAYING,
                TTSState.PAUSED,
                TTSState.GENERATING,
            )
        if action == "auto_select":
            return self._pipeline is not None
        if action == "export_book":
            node = self._save.nodes.get(self._save.current_node_id)
            if node is None or not node.is_ending:
                return False
            if self._loading or self._edit_regen_active or self._image_regen_active:
                return False
            return not (
                self._tts_player is not None and self._tts_player.state == TTSState.GENERATING
            )
        if action == "recap":
            return True
        if action == "menu":
            return True
        return None

    def _render_image_for(self, status: str, image_path: str | None) -> None:
        # If a partial or final image is on disk, show it regardless of
        # status. Streaming previews land at status="generating" once a
        # partial bytes write completes; the final lands at status="done".
        # Showing whatever's on disk gives the user the best frame
        # available without changing the existing state-machine semantics.
        if image_path:
            try:
                abs_path = paths.safe_join(paths.game_dir(str(self._save.id)), image_path)
            except ValueError:
                abs_path = None
            if abs_path is not None and abs_path.exists():
                self._image.show_image(abs_path)
                return
        if status == "generating":
            self._image.show_generating()
            return
        if status == "failed":
            self._image.show_failed()
            return
        self._image.clear()

    async def _pick(self, n: int, *, auto_read_inline: bool = False) -> None:
        await self._stop_tts()
        node = self._save.nodes[self._save.current_node_id]
        if n - 1 >= len(node.choices):
            return
        choice = node.choices[n - 1]
        if self._pipeline is None:
            return
        self._story.reset()
        self._story.set_renderable(
            Text(f"You chose: {choice.text}\nGenerating next beat…", style="dim")
        )
        # Hide the previous beat's choices and image while the new beat streams
        # in; _render_current() at the end repopulates them from the new node.
        # Show the spinner placeholder up front so the user gets immediate
        # feedback instead of staring at the previous beat's illustration for
        # however long stages 1+2 take before stage 3 even starts.
        self._choices.clear()
        if app_state.art_enabled():
            self._image.show_generating()
        self._loading = True
        self._throbber.start()
        self.refresh_bindings()
        # Clear when the first delta arrives (the streamed text replaces this).
        self._awaiting_first_delta = True
        auto_read_task: asyncio.Task[None] | None = None

        async def on_beat_committed(committed: object) -> None:
            nonlocal auto_read_task
            await self._on_beat_committed(committed)
            if isinstance(committed, StoryNode) and committed.narration:
                if auto_read_inline:
                    auto_read_task = asyncio.create_task(self._maybe_auto_read(committed.narration))
                else:
                    self.run_worker(
                        self._maybe_auto_read(committed.narration),
                        exclusive=False,
                        name="auto-read",
                    )
                # Auto-recap after major beats.
                if committed.is_major:
                    self._major_beats_since_recap += 1
                    if (
                        app_state.auto_recap_enabled()
                        and self._major_beats_since_recap >= app_state.recap_interval()
                    ):
                        self._major_beats_since_recap = 0
                        self.run_worker(self.action_recap(), name="auto-recap")

        cb = PipelineCallbacks(
            on_narration_delta=self._on_narration_delta,
            on_beat_committed=on_beat_committed,
            on_image_committed=self._on_image_committed,
            on_image_failed=self._on_image_failed,
            on_new_characters=self._on_new_characters,
        )
        try:
            await self._pipeline.advance(
                self._save,
                from_node_id=node.id,
                choice_id=choice.id,
                callbacks=cb,
            )
        finally:
            self._loading = False
            self._throbber.stop()
            self._render_current()
            if auto_read_inline and auto_read_task is not None:
                await auto_read_task

    async def _on_narration_delta(self, delta: str) -> None:
        if getattr(self, "_awaiting_first_delta", False):
            self._story.reset()
            self._awaiting_first_delta = False
            self._throbber.stop()
        self._story.append_delta(delta)

    async def _on_beat_committed(self, node: object) -> None:
        # Text generation is done — clear loading so bindings (including
        # read aloud) become available. Image generation may still be in
        # flight; _render_current handles that via the image_status field.
        self._loading = False
        self.refresh_bindings()
        self._render_current()

    async def _on_image_committed(self, node: object) -> None:
        from storygen.llm.models import StoryNode

        if isinstance(node, StoryNode) and node.id == self._save.current_node_id:
            self._image_regen_active = False
            self._image_displayed_at = time.monotonic()
            self._render_image_for(node.image_status, node.image_path)
            if app_state.auto_open_art_enabled() and node.image_path:
                try:
                    abs_path = paths.safe_join(paths.game_dir(str(self._save.id)), node.image_path)
                except ValueError:
                    abs_path = None
                if abs_path is not None and abs_path.exists():
                    open_in_system_viewer(abs_path)
        # Cost may have changed even if the image isn't for the current node.
        self._apply_header()

    async def _on_image_failed(self, node: object) -> None:
        from storygen.llm.models import StoryNode

        if isinstance(node, StoryNode) and node.id == self._save.current_node_id:
            self._image_regen_active = False
            self._image.show_failed()

    async def _on_new_characters(self, characters: object) -> None:
        """Toast new characters as they're introduced mid-story."""
        if not isinstance(characters, list) or not characters:
            return
        names = ", ".join(
            str(getattr(c, "name", "?"))  # pyright: ignore[reportUnknownArgumentType]
            for c in characters  # pyright: ignore[reportUnknownVariableType]
        )
        self.notify(f"New character(s) joined: {names}", timeout=5)

    async def action_go_back(self) -> None:
        await self._stop_tts()
        node = self._save.nodes[self._save.current_node_id]
        if node.parent_id is None:
            return
        # Cancel any in-flight prefetches before mutating + persisting `save`.
        # Concurrent `save_game` calls on the same dict can serialize a
        # half-stitched state to disk (see _pick + advance for the gated path).
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        self._save.current_node_id = node.parent_id
        save_game(self._save)
        self._render_current()

    def action_regen_picker(self) -> None:
        from storygen.screens._regen_picker import RegenPickerModal

        node = self._save.nodes.get(self._save.current_node_id)
        if node is None:
            return
        can_retry = node.image_prompt is not None and node.image_status in (
            "failed",
            "done",
            "not_planned",
        )
        can_edit = can_retry
        can_beat = node.parent_id is not None and not any(c.child_node_id for c in node.choices)
        can_audio = self._tts_player is not None and self._tts_player.is_configured

        def _on_pick(action: str | None) -> None:
            if action == "retry_image":
                self._image_regen_active = True
                node = self._save.nodes.get(self._save.current_node_id)
                if node and node.image_prompt:
                    self._save.nodes[node.id] = node.model_copy(
                        update={"image_status": "generating", "image_path": None}
                    )
                    save_game(self._save)
                self._image.show_generating()
                self.notify("Regenerating scene image…", timeout=60)  # pyright: ignore[reportUnknownMemberType]
                self.run_worker(self.action_retry_image(), name="regen-retry")
            elif action == "edit_regen_image":
                self.run_worker(self.action_edit_regen_image(), name="regen-edit")
            elif action == "regenerate_node":
                self.run_worker(self.action_regenerate_node(), name="regen-beat")
            elif action == "regen_audio":
                self.run_worker(self.action_regen_audio(), name="regen-audio")

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            RegenPickerModal(
                can_retry_image=can_retry,
                can_edit_regen=can_edit,
                can_regen_beat=can_beat,
                can_regen_audio=can_audio,
            ),
            _on_pick,
        )

    def action_info_picker(self) -> None:
        from storygen.screens._info_picker import InfoPickerModal

        def _on_pick(action: str | None) -> None:
            if action == "portraits":
                self.run_worker(self.action_portraits(), name="info-portraits")
            elif action == "graph":
                self.action_graph()
            elif action == "endings":
                self.action_endings()
            elif action == "relationships":
                self.action_relationships()

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            InfoPickerModal(
                can_portraits=bool(self._save.characters) and self._image_provider is not None,
                can_graph=len(self._save.nodes) > 1,
                can_endings=len(self._save.endings_reached) > 0,
                can_relationships=bool(self._save.relationships),
            ),
            _on_pick,
        )

    async def action_retry_image(self) -> None:
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]
        if not node.image_prompt:
            return
        cb = PipelineCallbacks(
            on_image_committed=self._on_image_committed,
            on_image_failed=self._on_image_failed,
        )
        await self._pipeline.retry_scene(self._save, node_id=node.id, callbacks=cb)
        self._render_current()

    async def action_edit_regen_image(self) -> None:
        """Open the edit-regen modal for the current scene image."""
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]
        if not node.image_prompt:
            return
        save_id = str(self._save.id)
        image_bytes: bytes | None = None
        if node.image_path:
            try:
                abs_path = paths.safe_join(paths.game_dir(save_id), node.image_path)
                if abs_path.exists():
                    image_bytes = abs_path.read_bytes()
            except ValueError:
                pass

        def _on_result(result: ArtEditResult | None) -> None:
            if result is None:
                return
            self._edit_regen_active = True
            self._image.show_generating()
            self._choices.clear()
            self.notify("Generating edited image…", timeout=120)
            self.run_worker(
                self._do_edit_regen(node, result),
                exclusive=True,
                name="play-edit-regen",
            )

        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            ArtEditModal(
                original_prompt=node.image_prompt,
                image_bytes=image_bytes,
            ),
            _on_result,
        )

    async def _do_edit_regen(self, node: StoryNode, result: ArtEditResult) -> None:
        """Execute the edit-regen after the modal returns a result."""
        if self._pipeline is None:
            return
        if result.mode == ArtEditMode.EDIT:
            new_prompt = f"{node.image_prompt}\n\nEdit instructions: {result.text}"
        else:
            new_prompt = result.text
        cb = PipelineCallbacks(
            on_image_committed=self._on_image_committed,
            on_image_failed=self._on_image_failed,
        )
        try:
            await self._pipeline.edit_scene(
                self._save,
                node_id=node.id,
                new_prompt=new_prompt,
                current_image_as_ref=result.use_current_as_ref,
                callbacks=cb,
            )
        except Exception:
            self.notify("Edit regen failed.", severity="error", timeout=10)
        finally:
            self._edit_regen_active = False
        self._render_current()

    def action_menu(self) -> None:
        self.app.switch_screen("menu")  # pyright: ignore[reportUnknownMemberType]

    def _make_recap_modal(self, recap_text: str) -> RecapModal:
        """Build a RecapModal with TTS player and cache path wired in."""
        tts_prefs = app_state.read_tts_prefs()
        node = self._save.nodes.get(self._save.current_node_id)
        cache_str = ""
        if node and self._tts_player is not None:
            cache_str = str(self._tts_cache_path(f"{node.id}-recap", tts_prefs))
        return RecapModal(
            recap_text,
            tts_player=self._tts_player,
            tts_cache_path=cache_str,
        )

    async def action_recap(self) -> None:
        """Show a 'Previously on...' recap for the current story."""
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]

        if node.recap_text:
            self.app.push_screen(self._make_recap_modal(node.recap_text))  # pyright: ignore[reportUnknownMemberType]
            await self._maybe_speak_recap(node.recap_text)
            return

        self.notify("Generating recap…", timeout=30)
        try:
            recap = await self._generate_recap()
        except Exception as exc:
            self.notify(f"Recap failed: {exc}", severity="error", timeout=10)
            return

        node.recap_text = recap.text
        save_game(self._save)
        self.app.push_screen(self._make_recap_modal(recap.text))  # pyright: ignore[reportUnknownMemberType]
        await self._maybe_speak_recap(recap.text)

    async def _generate_recap(self) -> Recap:
        from storygen.llm.agents import build_recap_agent
        from storygen.llm.provider_factory import build_text_model
        from storygen.storage.tree import path_from_root

        text_model = build_text_model(self._save.text_config)
        agent = build_recap_agent(text_model)

        chain = path_from_root(self._save, self._save.current_node_id)
        parts: list[str] = [f"Story title: {self._save.theme.title}"]

        for node in chain:
            if node.narration:
                label = "[Opening blurb]" if node.id == "root" else "[Beat]"
                parts.append(f"---\n{label}\n{node.narration}")
            if node.choices:
                chosen = next(
                    (c for c in node.choices if c.child_node_id is not None),
                    None,
                )
                if chosen:
                    parts.append(f"Player chose: {chosen.text}")

        prompt = "\n\n".join(parts)
        for attempt, delay in enumerate((*_RECAP_RETRY_DELAYS, 0.0), start=1):
            try:
                result = await agent.run(prompt)
                return result.output
            except Exception as exc:
                if delay <= 0 or not _is_transient_recap_error(exc):
                    raise
                if self.is_attached:
                    self.notify(
                        f"Recap hit a transient network error; retrying ({attempt + 1}/3)…",
                        severity="warning",
                        timeout=5,
                    )
                await asyncio.sleep(delay)
        raise RuntimeError("recap retry loop exhausted")

    async def action_regenerate_node(self) -> None:
        """Discard the current beat and re-roll it from the parent's choice."""
        await self._stop_tts()
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]
        if node.parent_id is None or node.chosen_choice_id is None:
            return
        if any(c.child_node_id for c in node.choices):
            self.notify(
                "Cannot regenerate — this beat already has descendant nodes.",
                severity="warning",
            )
            return
        parent = self._save.nodes.get(node.parent_id)
        if parent is None:
            return
        chosen_id = node.chosen_choice_id
        # Find the parent choice index so we can re-pick after invalidating.
        n = next(
            (i + 1 for i, c in enumerate(parent.choices) if c.id == chosen_id),
            None,
        )
        if n is None:
            return
        # Cancel any in-flight prefetches before mutating + persisting `save`.
        # Without this, a prefetch task could race with our save_game below
        # and serialize a half-stitched state to disk.
        await self._pipeline.cancel_all_prefetches()
        # Cache-bust: clear the parent's link to this child + drop the node.
        for c in parent.choices:
            if c.id == chosen_id:
                c.child_node_id = None
                break
        del self._save.nodes[node.id]
        self._save.current_node_id = parent.id
        save_game(self._save)
        self._render_current()
        await self._pick(n)

    def action_graph(self) -> None:
        """Push the GraphScreen; on selection, jump current node + re-render."""
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            GraphScreen(self._save, on_node_selected=self._graph_jump)
        )

    def _graph_jump(self, node_id: str) -> None:
        """GraphScreen jump callback: cancel prefetches + persist the jump."""
        # Schedule the async cancel + mutate as a background task so this sync
        # callback (invoked from GraphScreen) can stay sync. The pop_screen +
        # _render_current happen inside _do_graph_jump after the cancel awaits.
        self.run_worker(self._do_graph_jump(node_id), exclusive=False, name="play-graph-jump")

    async def _do_graph_jump(self, node_id: str) -> None:
        await self._stop_tts()
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        self._save.current_node_id = node_id
        save_game(self._save)
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]
        self._render_current()

    async def action_regen_audio(self) -> None:
        """Regenerate TTS audio for every node from root to the current node."""
        if self._tts_player is None or not self._tts_player.is_configured:
            return
        await self._stop_tts()
        from storygen.storage.tree import path_from_root

        chain = path_from_root(self._save, self._save.current_node_id)
        tts_prefs = app_state.read_tts_prefs()
        self._tts_player.configure(
            tts_prefs.provider, api_key=tts_prefs.api_key, voice=tts_prefs.voice
        )
        total = len(chain)
        for idx, node in enumerate(chain, 1):
            if not node.narration:
                continue
            cache = self._tts_cache_path(node.id, tts_prefs)
            cache.unlink(missing_ok=True)
            self.notify(f"Generating audio {idx}/{total}…", timeout=30)
            ok = await self._tts_player.generate(node.narration, cache_path=cache)
            if ok:
                relative_cache = self._relative_tts_cache_path(node.id, tts_prefs)
                if node.tts_audio_path != relative_cache:
                    node.tts_audio_path = relative_cache
                    save_game(self._save)
        self.notify(f"Audio regenerated for {total} node(s).")

    def action_endings(self) -> None:
        """Push the EndingsScreen; on jump, set current node + re-render.

        EndingsScreen calls ``self.dismiss()`` after the callback fires, so
        the pop happens inside the screen and we don't pop again here.
        """
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            EndingsScreen(self._save, on_jump=self._endings_jump)
        )

    def _endings_jump(self, node_id: str) -> None:
        """EndingsScreen jump callback: cancel prefetches + persist the jump."""
        self.run_worker(self._do_endings_jump(node_id), exclusive=False, name="play-endings-jump")

    async def _do_endings_jump(self, node_id: str) -> None:
        await self._stop_tts()
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        self._save.current_node_id = node_id
        save_game(self._save)
        self._render_current()

    def action_relationships(self) -> None:
        """Push the RelationshipsScreen modal."""
        if self._loading:
            return
        save = self._save
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            RelationshipsScreen(
                characters=save.characters,
                relationships=save.relationships,
            )
        )

    async def action_portraits(self) -> None:
        if not self._save.characters or self._image_provider is None:
            return
        # Cast: PortraitsScreen expects ImageProviderLike; the provider passed
        # by the app implements the protocol structurally.
        self.app.push_screen(  # pyright: ignore[reportUnknownMemberType]
            PortraitsScreen(self._save, self._image_provider)  # type: ignore[arg-type]
        )

    def on_screen_resume(self) -> None:
        """Re-render after returning from a child screen (e.g. PortraitsScreen).

        Portrait regeneration mutates ``self._save.characters``, so the cast
        sidebar needs to reflect the new portrait paths.

        Skipped while edit-regen is active to avoid overwriting the
        generating throbber with the old on-disk image.
        """
        if self._edit_regen_active or self._image_regen_active:
            return
        self._render_current()
        self._maybe_auto_start_select()

    async def action_pick(self, n: int) -> None:
        """Pick choice number n (1-indexed). Bound to number keys 1-9."""
        await self._pick(n)

    def action_highlight_next(self) -> None:
        self._choices.highlight_next()

    def action_highlight_prev(self) -> None:
        self._choices.highlight_prev()

    async def action_pick_highlighted(self) -> None:
        n = self._choices.highlighted
        if n is not None:
            await self._pick(n)

    def action_tts_toggle(self) -> None:
        """Read aloud / pause / resume based on current TTS state."""
        if self._tts_player is None:
            return
        if self._tts_player.state == TTSState.GENERATING:
            self.notify("TTS is generating, please wait…", severity="warning", timeout=5)
            return
        if self._tts_player.state == TTSState.PLAYING:
            self.run_worker(self._tts_player.pause(), name="tts-pause")
        elif self._tts_player.state == TTSState.PAUSED:
            self.run_worker(self._tts_player.resume(), name="tts-resume")
        else:
            node = self._save.nodes.get(self._save.current_node_id)
            if node and node.narration:
                tts_prefs = app_state.read_tts_prefs()
                cache = self._tts_cache_path(node.id, tts_prefs)
                if not cache.exists():
                    self._tts_player.set_state(TTSState.GENERATING)
                    self.notify("Generating speech…", timeout=15)
            self.run_worker(self._speak_current_node(), exclusive=True, name="tts-speak")
        self.refresh_bindings()

    async def action_tts_restart(self) -> None:
        """Restart TTS playback from the beginning."""
        if self._tts_player is None:
            return
        await self._tts_player.stop()
        node = self._save.nodes.get(self._save.current_node_id)
        if node and node.narration:
            tts_prefs = app_state.read_tts_prefs()
            cache = self._tts_cache_path(node.id, tts_prefs)
            if not cache.exists():
                self.notify("Generating speech…", timeout=15)
        self.run_worker(self._speak_current_node(), exclusive=True, name="tts-speak")
        self.refresh_bindings()

    async def action_tts_stop(self) -> None:
        """Stop TTS playback."""
        if self._tts_player is not None:
            await self._tts_player.stop()
            self.refresh_bindings()

    def _tts_cache_path(self, node_id: str, prefs: app_state.TTSPrefs) -> Path:
        """Return the current provider/voice-aware TTS cache path for a node."""
        ext = self._tts_player.preferred_extension if self._tts_player is not None else "mp3"
        return paths.tts_audio_path(
            str(self._save.id),
            node_id,
            provider=prefs.provider,
            voice=prefs.voice,
            ext=ext,
        )

    def _relative_tts_cache_path(self, node_id: str, prefs: app_state.TTSPrefs) -> str:
        """Return the relative current provider/voice-aware TTS cache path for a node."""
        ext = self._tts_player.preferred_extension if self._tts_player is not None else "mp3"
        return paths.relative_tts_audio_path(
            node_id,
            provider=prefs.provider,
            voice=prefs.voice,
            ext=ext,
        )

    async def _speak_current_node(self) -> None:
        """Generate/play TTS for the current node, with caching."""
        if self._tts_player is None:
            return
        tts_prefs = app_state.read_tts_prefs()
        node = self._save.nodes.get(self._save.current_node_id)
        if not node or not node.narration:
            return
        self._tts_player.configure(
            tts_prefs.provider,
            api_key=tts_prefs.api_key,
            voice=tts_prefs.voice,
        )
        cache = self._tts_cache_path(node.id, tts_prefs)
        relative_cache = self._relative_tts_cache_path(node.id, tts_prefs)
        ok = await self._tts_player.speak(node.narration, cache_path=cache)
        if ok and node.tts_audio_path != relative_cache:
            node.tts_audio_path = relative_cache
            save_game(self._save)
            self._apply_header()
        self.refresh_bindings()

    async def _maybe_auto_read(self, text: str) -> None:
        """If auto-read is enabled, speak the narration text."""
        if self._tts_player is None:
            return
        tts_prefs = app_state.read_tts_prefs()
        if not tts_prefs.auto_read:
            return
        node = self._save.nodes.get(self._save.current_node_id)
        if node and node.narration:
            cache = self._tts_cache_path(node.id, tts_prefs)
            if not cache.exists():
                self.notify("Generating speech…", timeout=15)
        await self._speak_current_node()

    async def _maybe_speak_recap(self, recap_text: str) -> None:
        """If auto-read-recap is enabled, speak the recap text aloud."""
        if self._tts_player is None:
            return
        tts_prefs = app_state.read_tts_prefs()
        if not tts_prefs.auto_read_recap:
            return
        node = self._save.nodes.get(self._save.current_node_id)
        if not node or not recap_text:
            return
        self._tts_player.configure(
            tts_prefs.provider,
            api_key=tts_prefs.api_key,
            voice=tts_prefs.voice,
        )
        cache = self._tts_cache_path(f"{node.id}-recap", tts_prefs)
        if not cache.exists():
            self.notify("Generating recap speech…", timeout=15)
        await self._tts_player.speak(recap_text, cache_path=cache)
        self.refresh_bindings()

    def action_auto_select(self) -> None:
        """Toggle auto-select on/off."""
        self._auto_selecting = not self._auto_selecting
        if self._auto_selecting:
            self.notify("Auto-play started", timeout=3)
            self.run_worker(self._auto_select_next(), exclusive=True, name="auto-select")
        else:
            self.notify("Auto-play stopped", timeout=3)
        self.refresh_bindings()

    def _current_node_image_terminal(self, node_id: NodeId) -> bool:
        """Return whether *node_id* no longer has an in-flight image generation."""
        if not app_state.art_enabled():
            return True
        node = self._save.nodes.get(node_id)
        if node is None:
            return True
        return node.image_status != "generating"

    async def _wait_for_current_image_ready(self, node_id: NodeId) -> bool:
        """Wait until the current node image is terminal, or autoplay should abort."""
        while self._auto_selecting and self._save.current_node_id == node_id:
            if self._current_node_image_terminal(node_id):
                return True
            await asyncio.sleep(0.5)
        return False

    async def _auto_select_next(self) -> None:
        """One cycle: wait for image+TTS, pick a random choice, schedule next."""
        if not self._auto_selecting:
            return
        node = self._save.nodes.get(self._save.current_node_id)
        if not node or node.is_ending or not node.choices:
            self._auto_selecting = False
            if node and node.is_ending:
                self.notify("Auto-play: story ended", timeout=5)
            self.refresh_bindings()
            return

        if not await self._wait_for_current_image_ready(node.id):
            return

        # Wait for image viewing delay (5s after image was displayed).
        if app_state.art_enabled() and self._image_displayed_at:
            elapsed = time.monotonic() - self._image_displayed_at
            if elapsed < 5.0:
                await asyncio.sleep(5.0 - elapsed)

        # Wait for TTS playback to finish if auto-read is active.
        if self._tts_player and app_state.read_tts_prefs().auto_read:
            while self._tts_player.state in (
                TTSState.GENERATING,
                TTSState.PLAYING,
                TTSState.PAUSED,
            ):
                await asyncio.sleep(0.5)

        # Abort if toggled off while waiting or the visible node changed.
        if not self._auto_selecting or self._save.current_node_id != node.id:
            return

        # Pick a random choice.
        n = random.randint(1, len(node.choices))
        await self._pick(n, auto_read_inline=True)

        # Schedule next cycle if still active.
        if self._auto_selecting:
            self.run_worker(self._auto_select_next(), exclusive=True, name="auto-select")

    @work(exit_on_error=False)
    async def action_export_book(self) -> None:
        """Export the current ending path as an HTML book and open in browser."""
        node = self._save.nodes.get(self._save.current_node_id)
        if node is None or not node.is_ending:
            return
        try:
            out = await asyncio.to_thread(export_book, self._save, node.id)
            self.notify(f"Book exported to {out}", title="Export Complete", timeout=10)
        except Exception as exc:
            self.notify(
                f"Export failed: {exc}",
                title="Export Error",
                severity="error",
                timeout=15,
            )
