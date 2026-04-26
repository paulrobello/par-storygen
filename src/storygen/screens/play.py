"""PlayScreen: the main gameplay loop."""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import ClassVar

from pyfiglet import Figlet
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header

from storygen.llm.models import NodeId
from storygen.pipeline import BeatPipeline, PipelineCallbacks
from storygen.screens.endings import EndingsScreen
from storygen.screens.graph import GraphScreen
from storygen.screens.portraits import PortraitsScreen
from storygen.storage import app_state, paths
from storygen.storage.save import GameSave, save_game
from storygen.tts.player import TTSPlayer, TTSState
from storygen.widgets._header_util import format_cost_subtitle
from storygen.widgets.choice_list import ChoiceList
from storygen.widgets.image_panel import ImagePanel
from storygen.widgets.story_panel import StoryPanel
from storygen.widgets.throbber import Throbber


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
        ("i", "retry_image", "Regen image"),
        ("r", "regenerate_node", "Regen beat"),
        ("p", "portraits", "Portraits"),
        ("g", "graph", "Graph"),
        ("e", "endings", "Endings"),
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
        self._story = StoryPanel()
        self._choices = ChoiceList()
        self._throbber = Throbber()
        # True while a beat is being generated — disables all bindings so the
        # previous beat's choices/back/regen don't fire on the wrong state.
        self._loading: bool = False
        self._auto_selecting: bool = False
        self._image_displayed_at: float | None = None
        # Last node id we kicked off prefetch FROM. _maybe_start_prefetch
        # short-circuits when current_node_id matches this — the comparison
        # IS the reset, so picks/jumps that change current_node_id naturally
        # re-arm the next call. Limitation: if all pending choices become
        # cached via some other path while this is still pinned, a redundant
        # call would be a no-op (start_prefetch skips cached choices).
        self._last_prefetched_from: NodeId | None = None

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

    def _apply_header(self) -> None:
        """Set the screen title to the story theme + cumulative image cost + tokens."""
        self.title = self._save.theme.title
        self.sub_title = format_cost_subtitle(self._save)

    def _render_current(self) -> None:
        node = self._save.nodes[self._save.current_node_id]
        if node.is_ending:
            fig = Figlet(font="big")
            banner = fig.renderText("The End")
            # Use set_renderable so the bold banner is styled by Rich rather
            # than treating the markup tag as literal text (StoryPanel is
            # markup=False to prevent LLM injection).
            from rich.console import Group

            self._story.set_renderable(Group(Text(banner, style="bold"), Text(node.narration)))
        else:
            self._story.set_text(node.narration)
        self._choices.set_choices(node.choices)
        # While a beat is being generated we're showing a "generating" spinner
        # in the image panel (set in _pick); don't clobber it with the
        # newly-committed node's image_status (which is "not_planned" until
        # stage 2 finishes the illustration plan). The finally-block in _pick
        # re-runs _render_current with _loading=False, so the real image
        # status is picked up then.
        if not self._loading:
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
        # While a beat is generating, only "menu" (escape) stays available so
        # the user can bail out; everything else would act on stale state.
        if self._loading and action not in ("menu", "auto_select"):
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
        if action == "go_back":
            return node.parent_id is not None
        if action == "retry_image":
            return node.image_prompt is not None and node.image_status in (
                "failed",
                "done",
                "not_planned",
            )
        if action == "portraits":
            return bool(self._save.characters)
        if action == "graph":
            # Only meaningful once at least one beat beyond the root exists;
            # otherwise the graph would just show the root and its unexplored
            # choices, which the user already sees on the play screen.
            return len(self._save.nodes) > 1
        if action == "endings":
            # The endings gallery has no useful content until at least one
            # ending has been reached.
            return len(self._save.endings_reached) > 0
        if action == "regenerate_node":
            # Regenerate is allowed only on a non-root leaf — that is, a node
            # that has a parent and whose own choices have not yet been picked
            # (so no descendant nodes will be orphaned by the rewrite).
            if node.parent_id is None:
                return False
            return not any(c.child_node_id for c in node.choices)
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

    async def _pick(self, n: int) -> None:
        node = self._save.nodes[self._save.current_node_id]
        if n - 1 >= len(node.choices):
            return
        choice = node.choices[n - 1]
        if self._pipeline is None:
            return
        self._story.reset()
        self._story.set_renderable(Text("Generating next beat…", style="dim"))
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
        cb = PipelineCallbacks(
            on_narration_delta=self._on_narration_delta,
            on_beat_committed=self._on_beat_committed,
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
            # Auto-read the newly generated narration if TTS is configured.
            current_node = self._save.nodes.get(self._save.current_node_id)
            if current_node and current_node.narration:
                self.run_worker(
                    self._maybe_auto_read(current_node.narration),
                    exclusive=False,
                    name="auto-read",
                )

    async def _on_narration_delta(self, delta: str) -> None:
        if getattr(self, "_awaiting_first_delta", False):
            self._story.reset()
            self._awaiting_first_delta = False
            self._throbber.stop()
        self._story.append_delta(delta)

    async def _on_beat_committed(self, node: object) -> None:
        self._render_current()

    async def _on_image_committed(self, node: object) -> None:
        from storygen.llm.models import StoryNode

        if isinstance(node, StoryNode) and node.id == self._save.current_node_id:
            self._image_displayed_at = time.monotonic()
            self._render_image_for(node.image_status, node.image_path)
        # Cost may have changed even if the image isn't for the current node.
        self._apply_header()

    async def _on_image_failed(self, node: object) -> None:
        from storygen.llm.models import StoryNode

        if isinstance(node, StoryNode) and node.id == self._save.current_node_id:
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

    async def action_retry_image(self) -> None:
        if self._pipeline is None:
            return
        node = self._save.nodes[self._save.current_node_id]
        if not node.image_prompt:
            return
        self._image.show_generating()
        cb = PipelineCallbacks(
            on_image_committed=self._on_image_committed,
            on_image_failed=self._on_image_failed,
        )
        await self._pipeline.retry_scene(self._save, node_id=node.id, callbacks=cb)
        self._render_current()

    def action_menu(self) -> None:
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]

    async def action_regenerate_node(self) -> None:
        """Discard the current beat and re-roll it from the parent's choice."""
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
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        self._save.current_node_id = node_id
        save_game(self._save)
        self.app.pop_screen()  # pyright: ignore[reportUnknownMemberType]
        self._render_current()

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
        if self._pipeline is not None:
            await self._pipeline.cancel_all_prefetches()
        self._save.current_node_id = node_id
        save_game(self._save)
        self._render_current()

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
        """
        self._render_current()

    async def action_pick(self, n: int) -> None:
        """Pick choice number n (1-indexed). Bound to number keys 1-9."""
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

    def action_auto_select(self) -> None:
        """Toggle auto-select on/off."""
        self._auto_selecting = not self._auto_selecting
        if self._auto_selecting:
            self.notify("Auto-play started", timeout=3)
            self.run_worker(self._auto_select_next(), exclusive=True, name="auto-select")
        else:
            self.notify("Auto-play stopped", timeout=3)
        self.refresh_bindings()

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

        # Abort if toggled off while waiting.
        if not self._auto_selecting:
            return

        # Pick a random choice.
        n = random.randint(1, len(node.choices))
        await self._pick(n)

        # Schedule next cycle if still active.
        if self._auto_selecting:
            self.run_worker(self._auto_select_next(), exclusive=True, name="auto-select")
