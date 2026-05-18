"""Smoke tests for LoadGameScreen — empty state and listing of saves."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from storygen.images.base import ReferencePortrait
from storygen.llm.models import (
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens._confirm_modal import ConfirmModal
from storygen.screens.load import LoadGameScreen, StorySetupDetailsModal
from storygen.storage import paths
from storygen.storage.save import GameSave, save_game


def _seed_save(title: str) -> GameSave:
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="",
        choices=[StoredChoice(id="start", text="Begin")],
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
    save = GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title=title, setting="s", premise="p", keywords=[]),
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
    save_game(save)
    return save


class _Harness(App[None]):
    def on_mount(self) -> None:
        self.push_screen(LoadGameScreen())

    def compose(self) -> ComposeResult:
        yield from []


class _LoadCallbackHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.loaded: list[GameSave] = []

    def on_mount(self) -> None:
        self.push_screen(LoadGameScreen(on_save_selected=self._on_save_selected))

    def compose(self) -> ComposeResult:
        yield from []

    async def _on_save_selected(self, save: GameSave) -> None:
        self.loaded.append(save)
        self.started.set()
        await self.release.wait()


@pytest.mark.asyncio
async def test_load_screen_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        assert "No saved games" in str(screen._empty_label.content)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_load_screen_lists_saves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _seed_save("Mystic Mountain")
    _seed_save("Cyber Heist")

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        rows = screen._scroll.query(".load-row")  # pyright: ignore[reportPrivateUsage]
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_load_button_shows_loading_while_save_opens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("Slow Load")

    app = _LoadCallbackHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        load_btn = screen.query_one(f"#load-{save.id}", Button)

        await pilot.click(f"#load-{save.id}")
        for _ in range(10):
            await pilot.pause()
            if app.started.is_set():
                break

        assert app.started.is_set()
        assert str(load_btn.label) == "Loading…"
        assert load_btn.disabled is True
        app.release.set()


@pytest.mark.asyncio
async def test_load_screen_skips_orphan_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _seed_save("Real Save")
    # Orphan dir from a failed wizard run — has subdirs but no game.json
    orphan = tmp_path / "storygen" / "games" / "orphan-uuid"
    (orphan / "images" / "characters").mkdir(parents=True)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        rows = screen._scroll.query(".load-row")  # pyright: ignore[reportPrivateUsage]
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_delete_confirm_removes_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Click Delete → confirm modal → save directory is removed."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("To Delete")
    save_dir = paths.game_dir(str(save.id))
    assert save_dir.exists()

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        delete_btn = screen.query_one(f"#delete-{save.id}", Button)
        assert delete_btn.label
        await pilot.click(f"#delete-{save.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, ConfirmModal):
                break
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm-yes")
        for _ in range(10):
            await pilot.pause()
            if not save_dir.exists():
                break
    assert not save_dir.exists()


@pytest.mark.asyncio
async def test_delete_cancel_keeps_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cancel in the confirm modal leaves the save on disk."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("Keep Me")
    save_dir = paths.game_dir(str(save.id))

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        await pilot.click(f"#delete-{save.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, ConfirmModal):
                break
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm-no")
        for _ in range(5):
            await pilot.pause()
    assert save_dir.exists()


@pytest.mark.asyncio
async def test_details_button_opens_story_setup_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("With Details")
    save.creation_prompts.theme_prompt = "Make a mall adventure"
    save.creation_prompts.character_prompt = "Use Rosie and Galera"
    save.art_style = "watercolor"
    save.target_major_beats = 7
    save_game(save)
    system_clipboard_calls: list[str] = []

    def fake_system_clipboard(text: str) -> bool:
        system_clipboard_calls.append(text)
        return True

    monkeypatch.setattr(
        "storygen.screens.load.copy_text_to_system_clipboard",
        fake_system_clipboard,
    )

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        assert screen.query_one(f"#details-{save.id}", Button).label == "Details"
        await pilot.click(f"#details-{save.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, StorySetupDetailsModal):
                break
        assert isinstance(app.screen, StorySetupDetailsModal)
        text = "\n".join(str(static.content) for static in app.screen.query(Static))
        assert "Make a mall adventure" in text
        assert "Use Rosie and Galera" in text
        assert "watercolor" in text
        assert "7" in text
        copy_buttons = [btn for btn in app.screen.query(Button) if str(btn.label) == "Copy"]
        assert len(copy_buttons) == len(app.screen._detail_rows())  # pyright: ignore[reportPrivateUsage]
        await pilot.click("#copy-detail-0")
        await pilot.pause()
        assert app.clipboard == "Make a mall adventure"
        assert system_clipboard_calls == ["Make a mall adventure"]


def _valid_png_bytes() -> bytes:
    """Build a tiny valid PNG via PIL so ``Pixels.from_image`` can decode it."""
    import io

    from PIL import Image

    im = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_cover_art_renders_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save whose root node has a valid image_path renders the cover thumbnail."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("With Cover")
    # Place a PNG at the root node's image location and update the save to
    # point at it — mirrors what the cover-backfill worker does.
    cover_path = paths.node_image_path(str(save.id), save.root_node_id)
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(_valid_png_bytes())
    rel = str(cover_path.relative_to(paths.game_dir(str(save.id))))
    root = save.nodes[save.root_node_id]
    save.nodes[save.root_node_id] = root.model_copy(update={"image_path": rel})
    from storygen.storage.save import save_game as _save_game

    _save_game(save)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        covers = screen._scroll.query(".load-cover")  # pyright: ignore[reportPrivateUsage]
        assert len(covers) == 1
        # When the PNG loads, the widget is a Static rendering Pixels;
        # the placeholder path would instead render the "(no cover)" text.
        rendered = str(covers[0].render())
        assert "(no cover)" not in rendered


@pytest.mark.asyncio
async def test_cover_placeholder_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A save without a root-node image_path hides the cover thumbnail."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _seed_save("No Cover")

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LoadGameScreen)
        covers = screen._scroll.query(".load-cover")  # pyright: ignore[reportPrivateUsage]
        assert len(covers) == 1
        assert not covers[0].display


class _FakeProvider:
    """Stubbed image provider that records calls and returns a valid PNG."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
    ) -> bytes:
        self.calls.append(prompt)
        return _valid_png_bytes()


@pytest.mark.asyncio
async def test_regen_button_generates_cover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clicking Regen Cover forces a new cover even when one already exists."""
    from storygen.storage.save import save_game as _save_game

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("Has Cover")
    # Pre-populate a cover so auto-backfill does NOT fire — we only want to
    # observe the forced regen that the button click triggers.
    cover_path = paths.node_image_path(str(save.id), save.root_node_id)
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(_valid_png_bytes())
    rel = str(cover_path.relative_to(paths.game_dir(str(save.id))))
    root = save.nodes[save.root_node_id]
    save.nodes[save.root_node_id] = root.model_copy(
        update={"image_path": rel, "image_status": "done"}
    )
    _save_game(save)
    fake = _FakeProvider()

    class _HarnessWithFactory(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                LoadGameScreen(image_provider_factory=lambda _s: fake),
            )

        def compose(self) -> ComposeResult:
            yield from []

    app = _HarnessWithFactory()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert fake.calls == []  # auto-backfill skipped (cover already done)
        await pilot.click(f"#regen-{save.id}")
        for _ in range(40):
            await pilot.pause()
            if fake.calls:
                break
    assert len(fake.calls) == 1
    assert cover_path.exists()


@pytest.mark.asyncio
async def test_auto_backfill_when_cover_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Screen mount triggers cover gen for saves missing image_path when art is on."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("Auto Backfill")
    fake = _FakeProvider()

    class _HarnessWithFactory(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                LoadGameScreen(image_provider_factory=lambda _s: fake),
            )

        def compose(self) -> ComposeResult:
            yield from []

    app = _HarnessWithFactory()
    async with app.run_test() as pilot:
        for _ in range(40):
            await pilot.pause()
            if fake.calls:
                break

    assert fake.calls, "Auto-backfill should have invoked generate_scene"
    cover_path = paths.node_image_path(str(save.id), save.root_node_id)
    assert cover_path.exists()


@pytest.mark.asyncio
async def test_clicking_row_does_not_auto_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Row-level click must not invoke the on_save_selected callback — only Load does."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _seed_save("Do Not Auto Load")

    invocations: list[GameSave] = []

    async def _on_save_selected(s: GameSave) -> None:
        invocations.append(s)

    class _HarnessWithCallback(App[None]):
        def on_mount(self) -> None:
            self.push_screen(LoadGameScreen(on_save_selected=_on_save_selected))

        def compose(self) -> ComposeResult:
            yield from []

    app = _HarnessWithCallback()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Click the row itself (not the Load/Delete button) — equivalent to
        # the stale OptionList auto-load behaviour we just removed.
        await pilot.click(".load-row")
        for _ in range(3):
            await pilot.pause()
    assert invocations == []
    assert save is not None  # keep the save seeded in scope for clarity
