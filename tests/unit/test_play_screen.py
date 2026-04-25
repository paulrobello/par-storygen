"""Smoke test: PlayScreen composes expected widgets."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult

from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens.endings import EndingsScreen
from storygen.screens.play import PlayScreen
from storygen.storage.save import GameSave
from storygen.widgets.choice_list import ChoiceList
from storygen.widgets.image_panel import ImagePanel
from storygen.widgets.story_panel import StoryPanel


def _minimal_save() -> GameSave:
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You open your eyes.",
        choices=[StoredChoice(id="c1", text="sit up")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _Harness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self._save = _minimal_save()

    def on_mount(self) -> None:
        self.push_screen(PlayScreen(self._save, pipeline=None, image_provider=None))  # type: ignore[arg-type]

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_play_screen_composes_three_panels() -> None:
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one(ImagePanel) is not None
        assert app.screen.query_one(StoryPanel) is not None
        assert app.screen.query_one(ChoiceList) is not None
        # Header reflects the story's theme title, cumulative image cost,
        # and cumulative input/output token counters.
        assert app.screen.title == "t"
        assert app.screen.sub_title == "$0.0000  ·  0↑/0↓ tok"


@pytest.mark.asyncio
async def test_check_action_hides_unavailable_choices_and_back() -> None:
    """Root with 1 choice and no parent: only pick_1 visible; back/retry hidden."""
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        # 1 choice → pick(1) enabled, pick(2)..pick(9) hidden
        assert screen.check_action("pick", (1,)) is True
        assert screen.check_action("pick", (2,)) is False
        assert screen.check_action("pick", (9,)) is False
        # No parent → go_back hidden
        assert screen.check_action("go_back", ()) is False
        # No image_prompt yet → retry_image hidden
        assert screen.check_action("retry_image", ()) is False
        # Root has no parent → regenerate hidden (would have nothing to re-roll from)
        assert screen.check_action("regenerate_node", ()) is False


@pytest.mark.asyncio
async def test_graph_action_hidden_when_only_root_exists() -> None:
    """A save with only the root node has no useful graph view."""
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        assert screen.check_action("graph", ()) is False


@pytest.mark.asyncio
async def test_regenerate_check_action_for_leaf_with_parent() -> None:
    """A non-root node whose choices have no children allows regenerate."""
    from datetime import UTC, datetime

    from storygen.llm.models import StoryNode

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        # Synthesize a child node off root with two unvisited choices.
        child = StoryNode(
            id="child",
            parent_id="root",
            chosen_choice_id="c1",
            chosen_at=datetime.now(UTC),
            narration="Beat 1",
            choices=[
                StoredChoice(id="a", text="A"),
                StoredChoice(id="b", text="B"),
            ],
            is_major=False,
            is_ending=False,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        )
        screen._save.nodes["child"] = child  # pyright: ignore[reportPrivateUsage]
        screen._save.current_node_id = "child"  # pyright: ignore[reportPrivateUsage]
        # Leaf with parent → regenerate enabled.
        assert screen.check_action("regenerate_node", ()) is True
        # Two nodes now exist → graph action is enabled.
        assert screen.check_action("graph", ()) is True
        # Now mark one choice as visited → no longer a leaf.
        child.choices[0].child_node_id = "grandchild"
        assert screen.check_action("regenerate_node", ()) is False


# ----- EndingsScreen integration tests below -----


def _root_save_no_endings() -> GameSave:
    """Build a minimal GameSave with only a root node and no endings."""
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="You wake in a dim room.",
        choices=[
            StoredChoice(id="c1", text="open the door"),
            StoredChoice(id="c2", text="check the window"),
        ],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _save_with_endings(n: int) -> GameSave:
    """Build a save with `n` ending nodes hanging off the root via choices."""
    save = _root_save_no_endings()
    extra: list[StoredChoice] = [StoredChoice(id=f"ec{i}", text=f"path {i}") for i in range(n)]
    save.nodes["root"].choices.extend(extra)
    for i in range(n):
        ending_id = f"end{i}"
        save.nodes["root"].choices[2 + i].child_node_id = ending_id
        save.nodes[ending_id] = StoryNode(
            id=ending_id,
            parent_id="root",
            chosen_choice_id=f"ec{i}",
            chosen_at=datetime.now(UTC),
            narration=f"And so it ended in scenario {i}.",
            choices=[],
            is_major=False,
            is_ending=True,
            image_prompt=None,
            image_path=None,
            image_status="not_planned",
            illustration_reasoning=None,
            featured_character_ids=[],
            summary_to_here=None,
            created_at=datetime.now(UTC),
        )
        save.endings_reached.append(ending_id)
    return save


@pytest.mark.asyncio
async def test_play_endings_binding_hidden_with_no_endings() -> None:
    save = _root_save_no_endings()

    class _PlayHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(PlayScreen(save, pipeline=None, image_provider=None))  # type: ignore[arg-type]

        def compose(self) -> ComposeResult:
            yield from []

    app = _PlayHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        assert screen.check_action("endings", ()) is False


@pytest.mark.asyncio
async def test_play_endings_binding_visible_with_endings() -> None:
    save = _save_with_endings(1)

    class _PlayHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(PlayScreen(save, pipeline=None, image_provider=None))  # type: ignore[arg-type]

        def compose(self) -> ComposeResult:
            yield from []

    app = _PlayHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        assert screen.check_action("endings", ()) is True


class _FakePipelineForPrefetch:
    """Minimal stub matching ``BeatPipeline.start_prefetch`` shape."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def start_prefetch(self, save: GameSave, *, from_node_id: str, with_images: bool) -> None:
        self.calls.append((from_node_id, with_images))

    async def cancel_all_prefetches(self) -> None:
        # PlayScreen.on_unmount awaits this; the stub does nothing because
        # it never actually spawns asyncio tasks.
        return None


def _make_prefetch_harness(save: GameSave, pipeline: object | None) -> type[App[None]]:
    class _PrefetchHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(PlayScreen(save, pipeline=pipeline, image_provider=None))  # type: ignore[arg-type]

        def compose(self) -> ComposeResult:
            yield from []

    return _PrefetchHarness


@pytest.mark.asyncio
async def test_prefetch_called_after_render_when_enabled(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When prefetch_enabled=True, _render_current triggers start_prefetch."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(False)

    save = _root_save_no_endings()
    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        # _render_current ran on_mount; prefetch should be called.
        assert len(fake.calls) >= 1
        assert fake.calls[0] == (save.current_node_id, False)


@pytest.mark.asyncio
async def test_prefetch_not_called_when_disabled(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When prefetch_enabled=False, start_prefetch is NOT called."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(False)

    save = _root_save_no_endings()
    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert fake.calls == []


@pytest.mark.asyncio
async def test_prefetch_with_images_passes_through(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prefetch_images_enabled=True should reach start_prefetch as with_images."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(True)

    save = _root_save_no_endings()
    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(fake.calls) >= 1
        assert fake.calls[0] == (save.current_node_id, True)


@pytest.mark.asyncio
async def test_prefetch_skipped_at_ending_node(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At a terminal node, PlayScreen still calls start_prefetch but the
    pipeline's own guard (in start_prefetch) refuses to spawn anything.
    PlayScreen must not error in either case."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(True)

    # Build a save whose current node is an ending.
    save = _save_with_endings(1)
    save.current_node_id = "end0"

    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        # The screen should still call start_prefetch; the pipeline contract
        # is that it ignores ending nodes. The fake records the call.
        # The important assertion is that mount didn't crash.
        assert isinstance(app.screen, PlayScreen)


class _FakePipelineWithCancelTracking:
    """Stub that records ``cancel_all_prefetches`` invocations."""

    def __init__(self) -> None:
        self.cancel_calls: int = 0
        self.start_prefetch_calls: list[tuple[str, bool]] = []

    def start_prefetch(self, save: GameSave, *, from_node_id: str, with_images: bool) -> None:
        self.start_prefetch_calls.append((from_node_id, with_images))

    async def cancel_all_prefetches(self) -> None:
        self.cancel_calls += 1


def _two_node_save() -> GameSave:
    """Save with root + one child node so go_back / regenerate are valid."""
    save = _root_save_no_endings()
    child = StoryNode(
        id="child",
        parent_id="root",
        chosen_choice_id="c1",
        chosen_at=datetime.now(UTC),
        narration="Beat 1",
        choices=[StoredChoice(id="a", text="A")],
        is_major=False,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    save.nodes["child"] = child
    save.nodes["root"].choices[0].child_node_id = "child"
    save.current_node_id = "child"
    return save


@pytest.mark.asyncio
async def test_action_go_back_cancels_prefetches(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Going back must cancel in-flight prefetches to avoid mid-write race."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    save = _two_node_save()
    fake = _FakePipelineWithCancelTracking()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        before = fake.cancel_calls
        await screen.action_go_back()
        assert fake.cancel_calls == before + 1
        # Verify the actual back action also took effect.
        assert save.current_node_id == "root"


@pytest.mark.asyncio
async def test_action_regenerate_cancels_prefetches(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerating a beat must cancel in-flight prefetches first."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    save = _two_node_save()
    fake = _FakePipelineWithCancelTracking()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        before = fake.cancel_calls

        # Pipeline lacks `advance` (etc.) so _pick will bail at `_pipeline is None`?
        # No — _pipeline is the fake. We need to short-circuit before _pick runs.
        # Easiest: raise from _pick by patching it to a no-op, OR just drive the
        # pre-_pick portion by patching _pick on the screen.
        async def _noop_pick(n: int) -> None:
            return None

        screen._pick = _noop_pick  # pyright: ignore[reportPrivateUsage]
        await screen.action_regenerate_node()
        assert fake.cancel_calls == before + 1
        # The regenerate path nukes the child + reroots to parent before _pick.
        assert save.current_node_id == "root"
        assert "child" not in save.nodes


@pytest.mark.asyncio
async def test_graph_jump_cancels_prefetches(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GraphScreen jump callback must cancel prefetches before persisting."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    save = _two_node_save()
    fake = _FakePipelineWithCancelTracking()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        before = fake.cancel_calls
        # Drive the jump handler directly (bypasses GraphScreen).
        await screen._do_graph_jump("root")  # pyright: ignore[reportPrivateUsage]
        assert fake.cancel_calls == before + 1
        assert save.current_node_id == "root"


@pytest.mark.asyncio
async def test_endings_jump_cancels_prefetches(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EndingsScreen jump callback must cancel prefetches before persisting."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    save = _save_with_endings(1)
    fake = _FakePipelineWithCancelTracking()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        before = fake.cancel_calls
        # Drive the jump handler directly (bypasses EndingsScreen).
        await screen._do_endings_jump("end0")  # pyright: ignore[reportPrivateUsage]
        assert fake.cancel_calls == before + 1
        assert save.current_node_id == "end0"


@pytest.mark.asyncio
async def test_play_action_endings_pushes_screen(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Push EndingsScreen needs save_game to work (jump callback persists).
    # action_endings itself only pushes; saves happen on jump.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    save = _save_with_endings(1)

    class _PlayHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(PlayScreen(save, pipeline=None, image_provider=None))  # type: ignore[arg-type]

        def compose(self) -> ComposeResult:
            yield from []

    app = _PlayHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        screen.action_endings()
        await pilot.pause()
        assert isinstance(app.screen, EndingsScreen)


@pytest.mark.asyncio
async def test_prefetch_not_refired_for_same_node(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_maybe_start_prefetch`` is idempotent per current node — repeated
    ``_render_current`` calls without a node change must NOT spawn another
    prefetch wave on the pipeline."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(False)

    save = _root_save_no_endings()
    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        # Mount fired _render_current → exactly one prefetch call.
        assert len(fake.calls) == 1
        # A second render with no node change must NOT re-fire prefetch.
        screen._render_current()  # pyright: ignore[reportPrivateUsage]
        screen._render_current()  # pyright: ignore[reportPrivateUsage]
        assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_prefetch_refires_after_current_node_changes(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once ``current_node_id`` moves to a different node, the next render
    triggers a fresh prefetch wave."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")

    from storygen.storage import app_state

    app_state.set_prefetch_enabled(True)
    app_state.set_prefetch_images_enabled(False)

    # Two-node save: root + child. Switch the cursor between renders.
    save = _two_node_save()
    # _two_node_save points current at "child"; flip back so we can move it
    # forward to a distinct second value within the test.
    save.current_node_id = "root"
    fake = _FakePipelineForPrefetch()
    harness_cls = _make_prefetch_harness(save, fake)
    app = harness_cls()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        # Mount fired _render_current with current="root".
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "root"
        # Move cursor and re-render — should refire.
        save.current_node_id = "child"
        screen._render_current()  # pyright: ignore[reportPrivateUsage]
        assert len(fake.calls) == 2
        assert fake.calls[1][0] == "child"
        # And another no-op render at "child" must not refire.
        screen._render_current()  # pyright: ignore[reportPrivateUsage]
        assert len(fake.calls) == 2


def _real_png_bytes() -> bytes:
    """Return a minimal valid PNG so PIL can open it without exploding."""
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_render_image_for_streaming_partial_shows_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When status='generating' but image_path points at an existing file
    (a streaming partial), ImagePanel should display the image — not the
    spinner. This is the streaming-preview UX win."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")
    from storygen.storage import paths
    from storygen.widgets.image_panel import ImagePanel, ImagePanelState

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        save = screen._save  # pyright: ignore[reportPrivateUsage]
        # Drop a real PNG at the expected partial location.
        node_id = save.root_node_id
        dest = paths.node_image_path(str(save.id), node_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_real_png_bytes())
        rel = str(dest.relative_to(paths.game_dir(str(save.id))))

        # Status STILL "generating" — partial bytes have just landed.
        screen._render_image_for("generating", rel)  # pyright: ignore[reportPrivateUsage]
        panel = screen.query_one(ImagePanel)
        assert panel.panel_state == ImagePanelState.DONE


@pytest.mark.asyncio
async def test_render_image_for_generating_no_file_shows_spinner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When status='generating' and no partial has landed yet, the panel
    falls back to the existing spinner. This preserves the pre-streaming
    behavior for non-streaming providers / pre-first-partial moments."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")
    from storygen.widgets.image_panel import ImagePanel, ImagePanelState

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        # image_path set but file does NOT exist on disk.
        screen._render_image_for("generating", "images/nodes/missing.png")  # pyright: ignore[reportPrivateUsage]
        panel = screen.query_one(ImagePanel)
        assert panel.panel_state == ImagePanelState.GENERATING

        # No image_path at all — also spinner.
        screen._render_image_for("generating", None)  # pyright: ignore[reportPrivateUsage]
        assert panel.panel_state == ImagePanelState.GENERATING


@pytest.mark.asyncio
async def test_render_image_for_failed_state_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """status='failed' must show the failed glyph regardless of image_path."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path) + "/cfg")
    from storygen.widgets.image_panel import ImagePanel, ImagePanelState

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PlayScreen)
        screen._render_image_for("failed", None)  # pyright: ignore[reportPrivateUsage]
        panel = screen.query_one(ImagePanel)
        assert panel.panel_state == ImagePanelState.FAILED
