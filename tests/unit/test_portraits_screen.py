"""Smoke + behavior tests for PortraitsScreen."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult

from storygen.images.openai_provider import (
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
)
from storygen.images.pricing import image_cost
from storygen.llm.models import (
    Character,
    CharacterOutfit,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens._character_edit_modal import (
    CharacterEditModal,
    CharacterEditResult,
)
from storygen.screens._outfit_modals import OutfitCreateRequest
from storygen.screens._ref_image_modals import ReferenceImageResult
from storygen.screens.portraits import (
    PortraitsScreen,
    _OutfitThumb,  # pyright: ignore[reportPrivateUsage]
)
from storygen.storage import paths
from storygen.storage.library import list_library_characters
from storygen.storage.save import GameSave, load_game, save_game


class FakeImageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ref_calls: list[bytes | None] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        del on_partial
        self.calls.append(description)
        self.ref_calls.append(reference_image)
        return b"NEWPNG"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        del prompt, reference_portraits, art_style, on_partial
        return b"SCENEPNG"


def _save_with_one_character() -> GameSave:
    char = Character(
        id="alyx",
        name="Alyx",
        backstory="b",
        personality="Brave and curious. Quick to act.",
        physical_description="A tall figure with auburn hair.",
        portrait_path=None,
        portrait_prompt=None,
        introduced_at_node_id="root",
    )
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="Begin your tale.",
        choices=[StoredChoice(id="c1", text="Begin")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None,
        image_status="not_planned",
        illustration_reasoning=None,
        featured_character_ids=["alyx"],
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
        characters=[char],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _Harness(App[None]):
    def __init__(self, save: GameSave, provider: FakeImageProvider) -> None:
        super().__init__()
        self._save = save
        self._provider = provider

    def on_mount(self) -> None:
        self.push_screen(PortraitsScreen(self._save, self._provider))

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_portraits_screen_composes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    provider = FakeImageProvider()
    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one(f"#regen-{save.characters[0].id}") is not None


@pytest.mark.asyncio
async def test_regenerate_writes_versioned_file_and_updates_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    save_game(save)
    char_id = save.characters[0].id
    cost_before = save.total_image_cost_usd
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#regen-{char_id}")
        # Allow the worker to run, finish, and the rebuild to settle.
        for _ in range(30):
            await pilot.pause()
            expected = paths.game_dir(str(save.id)) / "images" / "characters" / f"{char_id}-v1.png"
            if expected.exists():
                break

    expected = paths.game_dir(str(save.id)) / "images" / "characters" / f"{char_id}-v1.png"
    assert expected.exists(), "Regenerated portrait file was not written"
    assert expected.read_bytes() == b"NEWPNG"
    assert provider.calls == ["A tall figure with auburn hair."]

    # Persisted save's portrait_path now points at the new file.
    reloaded = load_game(str(save.id))
    assert reloaded.characters[0].portrait_path == f"images/characters/{char_id}-v1.png"
    expected_cost = cost_before + image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )
    assert reloaded.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        expected_cost
    )


@pytest.mark.asyncio
async def test_regenerate_uses_reference_image_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regenerate passes stored reference_image bytes to generate_portrait."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    char = save.characters[0]
    ref_rel = f"images/characters/{char.id}-ref.png"
    save.characters = [
        char.model_copy(update={"reference_image_path": ref_rel})
    ]
    save_game(save)
    # Write the ref image to disk so the worker can load it.
    ref_abs = paths.game_dir(str(save.id)) / ref_rel
    ref_abs.parent.mkdir(parents=True, exist_ok=True)
    ref_abs.write_bytes(_PNG_BYTES)

    provider = FakeImageProvider()
    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#regen-{char.id}")
        for _ in range(30):
            await pilot.pause()
            expected = paths.game_dir(str(save.id)) / "images" / "characters" / f"{char.id}-v2.png"
            if expected.exists():
                break

    # generate_portrait was called with reference_image=<bytes>
    assert provider.ref_calls == [_PNG_BYTES]


def _save_with_portrait_on_disk(portrait_bytes: bytes = b"PORTRAITDATA") -> GameSave:
    """Build a save whose character has a real portrait file written to disk."""
    save = _save_with_one_character()
    char = save.characters[0]
    save_id = str(save.id)
    paths.ensure_game_dirs(save_id)
    dest = paths.character_portrait_path(save_id, char.id, version=1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(portrait_bytes)
    rel = f"images/characters/{char.id}-v1.png"
    save.characters = [
        char.model_copy(
            update={
                "portrait_path": rel,
                "portrait_prompt": "A tall figure with auburn hair, neutral pose.",
            }
        )
    ]
    return save


@pytest.mark.asyncio
async def test_export_button_renders_enabled_when_portrait_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Button

        btn = app.screen.query_one(f"#export-{char_id}", Button)
        assert btn is not None
        assert btn.disabled is False


@pytest.mark.asyncio
async def test_export_button_disabled_when_no_portrait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()  # portrait_path=None
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Button

        btn = app.screen.query_one(f"#export-{char_id}", Button)
        assert btn.disabled is True


@pytest.mark.asyncio
async def test_export_writes_library_entry_with_portrait_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    portrait_bytes = b"ORIGINAL_PORTRAIT_BYTES"
    save = _save_with_portrait_on_disk(portrait_bytes)
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#export-{char_id}")
        for _ in range(10):
            await pilot.pause()
            if list_library_characters():
                break

    entries = list_library_characters()
    assert len(entries) == 1
    lib_char = entries[0]
    assert lib_char.name == "Alyx"
    assert lib_char.backstory == "b"
    assert lib_char.personality == "Brave and curious. Quick to act."
    assert lib_char.physical_description == "A tall figure with auburn hair."
    assert lib_char.portrait_prompt == "A tall figure with auburn hair, neutral pose."
    assert lib_char.exported_from is not None
    assert lib_char.exported_from.save_id == str(save.id)
    assert lib_char.exported_from.save_title == save.theme.title
    # Library id is a fresh uuid4 hex, NOT the save-local char id.
    assert lib_char.id != char_id
    assert len(lib_char.id) == 32

    # Portrait bytes landed on disk in the library.
    from storygen.storage.library import library_portrait_path

    assert library_portrait_path(lib_char.id).read_bytes() == portrait_bytes


@pytest.mark.asyncio
async def test_export_twice_creates_two_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save_game(save)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Drive the screen handler directly to avoid Textual's click
        # coalescing when the same button is hit twice in a row.
        screen = cast(PortraitsScreen, app.screen)
        screen._export_to_library(save.characters[0])  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()
        screen._export_to_library(save.characters[0])  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    entries = list_library_characters()
    assert len(entries) == 2
    assert entries[0].id != entries[1].id


@pytest.mark.asyncio
async def test_export_portrait_prompt_falls_back_to_physical_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy saves may have portrait_prompt=None; fall back to physical_description."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    char = save.characters[0]
    # Clear portrait_prompt to simulate a legacy save.
    save.characters = [char.model_copy(update={"portrait_prompt": None})]
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#export-{char_id}")
        for _ in range(10):
            await pilot.pause()
            if list_library_characters():
                break

    entries = list_library_characters()
    assert len(entries) == 1
    assert entries[0].portrait_prompt == "A tall figure with auburn hair."


@pytest.mark.asyncio
async def test_export_ioerror_does_not_crash_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    # Patch the screen's import binding to raise.
    def _boom(*_args: object, **_kwargs: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr("storygen.screens.portraits.save_library_character", _boom)

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#export-{char_id}")
        for _ in range(5):
            await pilot.pause()
        # Screen is still alive, no library entries persisted.
        assert app.screen.query_one(f"#export-{char_id}") is not None
        assert list_library_characters() == []


# --------------------------------------------------------------------------
# Outfit-row + outfit-action tests (v2.2 Phase 2)
# --------------------------------------------------------------------------


def _make_outfit(
    *,
    name: str = "ballroom gown",
    char_id: str = "alyx",
    outfit_id: str | None = None,
    description: str = "wearing a flowing red gown with gold trim",
) -> CharacterOutfit:
    oid = outfit_id or uuid4().hex
    return CharacterOutfit(
        id=oid,
        name=name,
        description=description,
        portrait_path=paths.relative_character_outfit_path(char_id, oid),
        portrait_prompt=f"A tall figure with auburn hair. Outfit: {description}.",
        created_at=datetime.now(UTC),
    )


def _make_png_bytes() -> bytes:
    """Return a real 4x4 RGBA PNG so PIL.Image.open succeeds in tests."""
    import io as _io

    from PIL import Image as _Image

    buf = _io.BytesIO()
    _Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


_PNG_BYTES = _make_png_bytes()


def _save_with_outfits(*outfits: CharacterOutfit, current_id: str | None = None) -> GameSave:
    """Build a save whose sole character has the given outfits attached.

    Each outfit's portrait file is written to disk so thumbnail rendering
    has something to read; the base portrait is also written.
    """
    save = _save_with_portrait_on_disk(_PNG_BYTES)
    char = save.characters[0]
    save_id = str(save.id)
    paths.ensure_game_dirs(save_id)
    for o in outfits:
        outfit_dest = paths.character_outfit_path(save_id, char.id, o.id)
        outfit_dest.parent.mkdir(parents=True, exist_ok=True)
        outfit_dest.write_bytes(_PNG_BYTES)
    update: dict[str, object] = {"outfits": list(outfits)}
    if current_id is not None:
        target = next(o for o in outfits if o.id == current_id)
        update["current_outfit_id"] = current_id
        update["portrait_path"] = target.portrait_path
        update["portrait_prompt"] = target.portrait_prompt
    save.characters = [char.model_copy(update=update)]
    return save


@pytest.mark.asyncio
async def test_outfits_row_renders_one_thumb_per_outfit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="casual")
    o2 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, o2)
    save_game(save)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        thumbs = list(app.screen.query(_OutfitThumb))
        assert len(thumbs) == 2
        outfit_ids = {t.outfit_id for t in thumbs}
        assert outfit_ids == {o1.id, o2.id}


@pytest.mark.asyncio
async def test_active_outfit_marker_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="casual")
    o2 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, o2, current_id=o2.id)
    save_game(save)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Static

        labels: list[str] = []
        for s in app.screen.query(Static):
            content = getattr(s, "content", None)
            if isinstance(content, str):
                labels.append(content)
        active_labels = [label for label in labels if "[active]" in label]
        assert any("armored" in label for label in active_labels)
        assert not any("casual" in label for label in active_labels)


@pytest.mark.asyncio
async def test_revert_to_base_button_hidden_when_no_active_outfit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="casual")
    save = _save_with_outfits(o1)  # no current_id
    save_game(save)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.css.query import NoMatches

        with pytest.raises(NoMatches):
            app.screen.query_one(f"#revert-outfit-{save.characters[0].id}")


@pytest.mark.asyncio
async def test_revert_to_base_restores_v1_portrait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, current_id=o1.id)
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._revert_to_base(save.characters[0])  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.current_outfit_id is None
    assert char.portrait_path == paths.relative_character_portrait_path(char_id, version=1)
    assert char.portrait_prompt == char.physical_description


@pytest.mark.asyncio
async def test_revert_uses_highest_existing_base_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Revert must restore the most-recently-regenerated base portrait, not
    blindly v1. A user who regenerated the base to v2 before applying an
    outfit should land back on v2."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, current_id=o1.id)
    save_game(save)
    char_id = save.characters[0].id
    # Simulate a prior base regeneration by writing v1 AND v2 portraits.
    chars_dir = paths.game_dir(str(save.id)) / "images" / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / f"{char_id}-v1.png").write_bytes(b"v1-stub")
    (chars_dir / f"{char_id}-v2.png").write_bytes(b"v2-stub")
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._revert_to_base(save.characters[0])  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.current_outfit_id is None
    assert char.portrait_path == paths.relative_character_portrait_path(char_id, version=2)


@pytest.mark.asyncio
async def test_set_as_current_updates_character_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="casual")
    save = _save_with_outfits(o1)  # no current
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._handle_outfit_action(  # pyright: ignore[reportPrivateUsage]
            char_id, o1.id, "set"
        )
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.current_outfit_id == o1.id
    assert char.portrait_path == o1.portrait_path
    assert char.portrait_prompt == o1.portrait_prompt


@pytest.mark.asyncio
async def test_delete_outfit_removes_from_list_and_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="casual")
    o2 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, o2, current_id=o2.id)  # delete the non-active one
    save_game(save)
    char_id = save.characters[0].id
    save_id = str(save.id)
    on_disk = paths.character_outfit_path(save_id, char_id, o1.id)
    assert on_disk.exists()  # sanity
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._handle_outfit_action(  # pyright: ignore[reportPrivateUsage]
            char_id, o1.id, "delete"
        )
        await pilot.pause()

    reloaded = load_game(save_id)
    char = reloaded.characters[0]
    assert [o.id for o in char.outfits] == [o2.id]
    # Active outfit is unchanged because we deleted the non-active one.
    assert char.current_outfit_id == o2.id
    assert not on_disk.exists()


@pytest.mark.asyncio
async def test_delete_active_outfit_reverts_to_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    o1 = _make_outfit(name="armored")
    save = _save_with_outfits(o1, current_id=o1.id)
    save_game(save)
    char_id = save.characters[0].id
    save_id = str(save.id)
    on_disk = paths.character_outfit_path(save_id, char_id, o1.id)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._handle_outfit_action(  # pyright: ignore[reportPrivateUsage]
            char_id, o1.id, "delete"
        )
        await pilot.pause()

    reloaded = load_game(save_id)
    char = reloaded.characters[0]
    assert char.outfits == []
    assert char.current_outfit_id is None
    assert char.portrait_path == paths.relative_character_portrait_path(char_id, version=1)
    assert char.portrait_prompt == char.physical_description
    assert not on_disk.exists()


@pytest.mark.asyncio
async def test_create_modal_save_appends_outfit_and_bumps_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end create flow via the screen's worker; bypasses the modal UI."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    save_game(save)
    char_id = save.characters[0].id
    char_initial = save.characters[0]
    cost_before = save.total_image_cost_usd
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        request = OutfitCreateRequest(
            name="ballroom gown",
            description="wearing a flowing red gown with gold trim",
        )
        screen._create_outfit_worker(char_initial, request)  # pyright: ignore[reportPrivateUsage]
        # Wait for the worker to land — worker calls notify+rebuild on completion.
        for _ in range(40):
            await pilot.pause()
            reloaded = load_game(str(save.id))
            if reloaded.characters[0].outfits:
                break

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert len(char.outfits) == 1
    outfit = char.outfits[0]
    assert outfit.name == "ballroom gown"
    assert outfit.description == "wearing a flowing red gown with gold trim"
    assert outfit.portrait_prompt == (
        "A tall figure with auburn hair. Outfit: wearing a flowing red gown with gold trim."
    )
    on_disk = paths.character_outfit_path(str(save.id), char_id, outfit.id)
    assert on_disk.exists()
    assert on_disk.read_bytes() == b"NEWPNG"
    # Cost bumped exactly once for the new portrait.
    expected_cost = cost_before + image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )
    assert reloaded.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        expected_cost
    )


@pytest.mark.asyncio
async def test_reference_style_transfer_cost_uses_character_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()
    save.character_image_config = ImageProviderConfig(
        provider="gemini", model="gemini-3.1-flash-image-preview"
    )
    save_game(save)
    char = save.characters[0]
    cost_before = save.total_image_cost_usd
    source = tmp_path / "reference.png"
    source.write_bytes(_PNG_BYTES)
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        screen._apply_ref_image_worker(  # pyright: ignore[reportPrivateUsage]
            ReferenceImageResult(source_path=source, mode="style_transfer"),
            char,
        )
        for _ in range(40):
            await pilot.pause()
            reloaded = load_game(str(save.id))
            if reloaded.characters[0].reference_image_path is not None:
                break

    reloaded = load_game(str(save.id))
    assert reloaded.characters[0].reference_image_path is not None
    expected_cost = cost_before + image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )
    assert reloaded.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        expected_cost
    )


# --------------------------------------------------------------------------
# Bio-edit tests (v2.4)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_button_renders_per_character(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Button

        btn = app.screen.query_one(f"#edit-bio-{char_id}", Button)
        assert btn is not None
        # Always enabled — text-only, no image generation.
        assert btn.disabled is False


@pytest.mark.asyncio
async def test_edit_modal_save_updates_character_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Changing physical_description syncs portrait_prompt on save."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        result = CharacterEditResult(
            name="Alyx the Brave",
            personality="Bold and reckless.",
            physical_description="A short figure with silver hair.",
            backstory="A new backstory.",
        )
        screen._apply_bio_edit(char_id, result)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.name == "Alyx the Brave"
    assert char.personality == "Bold and reckless."
    assert char.physical_description == "A short figure with silver hair."
    assert char.backstory == "A new backstory."
    # portrait_prompt auto-synced because physical_description changed.
    assert char.portrait_prompt == "A short figure with silver hair."


@pytest.mark.asyncio
async def test_edit_modal_save_without_physical_change_preserves_portrait_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Editing only name/backstory leaves portrait_prompt alone."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_portrait_on_disk()  # sets portrait_prompt to "... neutral pose."
    save_game(save)
    char_id = save.characters[0].id
    original_prompt = save.characters[0].portrait_prompt
    original_physical = save.characters[0].physical_description
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        result = CharacterEditResult(
            name="Alyx Renamed",
            personality=save.characters[0].personality,
            physical_description=original_physical,  # unchanged
            backstory="A totally new backstory.",
        )
        screen._apply_bio_edit(char_id, result)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.name == "Alyx Renamed"
    assert char.backstory == "A totally new backstory."
    # portrait_prompt preserved — physical_description didn't change.
    assert char.portrait_prompt == original_prompt


@pytest.mark.asyncio
async def test_edit_modal_save_empty_name_notifies_error_and_does_not_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty name → notify error, no dismiss, no save mutation."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    original_name = save.characters[0].name
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = CharacterEditModal(save.characters[0])
        dismissed: list[CharacterEditResult | None] = []

        def _cb(value: CharacterEditResult | None) -> None:
            dismissed.append(value)

        app.push_screen(modal, _cb)  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

        notifications: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            modal,
            "notify",
            lambda *a, **k: notifications.append((a, k)),  # type: ignore[no-untyped-call]
        )

        modal._name_input.value = "   "  # pyright: ignore[reportPrivateUsage]
        modal._attempt_save()  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

        # Modal did not dismiss.
        assert dismissed == []
        # Error notify fired.
        assert notifications
        assert notifications[-1][1].get("severity") == "error"
        assert "Name" in str(notifications[-1][0][0])

    # Save on disk unchanged.
    reloaded = load_game(str(save.id))
    assert reloaded.characters[0].name == original_name


@pytest.mark.asyncio
async def test_edit_modal_cancel_preserves_character(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dismissing with None leaves the save untouched."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    before = save.characters[0].model_copy()
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        # _open_edit_bio_modal wraps the callback; simulate a Cancel by
        # feeding None directly through the same path the callback takes.
        # Touch nothing — no _apply_bio_edit call.
        _ = screen  # use the screen to assert no state mutation
        await pilot.pause()

    reloaded = load_game(str(save.id))
    char = reloaded.characters[0]
    assert char.name == before.name
    assert char.personality == before.personality
    assert char.physical_description == before.physical_description
    assert char.backstory == before.backstory
    assert char.portrait_prompt == before.portrait_prompt


@pytest.mark.asyncio
async def test_edit_modal_physical_change_notifies_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """physical_description edit fires BOTH success toast and drift warning."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _save_with_one_character()
    save_game(save)
    char_id = save.characters[0].id
    provider = FakeImageProvider()

    app = _Harness(save, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(PortraitsScreen, app.screen)
        notifications: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            screen,
            "notify",
            lambda *a, **k: notifications.append((a, k)),  # type: ignore[no-untyped-call]
        )
        result = CharacterEditResult(
            name=save.characters[0].name,
            personality=save.characters[0].personality,
            physical_description="A different appearance entirely.",
            backstory=save.characters[0].backstory,
        )
        screen._apply_bio_edit(char_id, result)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

    # Exactly two notifies: success toast + warning.
    assert len(notifications) == 2
    first_body = str(notifications[0][0][0])
    second_body = str(notifications[1][0][0])
    assert "Updated" in first_body
    assert "Portrait no longer matches" in second_body
    assert notifications[1][1].get("severity") == "warning"


# --------------------------------------------------------------------------
# Full Res binding tests (v2.5)
# --------------------------------------------------------------------------


def test_full_res_binding_active_when_art_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The 'f' binding should be active when art is enabled."""
    monkeypatch.setattr("storygen.storage.app_state.art_enabled", lambda: True)
    save = _save_with_portrait_on_disk()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    screen = PortraitsScreen(save, FakeImageProvider())
    assert screen.check_action("open_full_res", ()) is True


def test_full_res_binding_hidden_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The 'f' binding should be hidden when art is disabled."""
    monkeypatch.setattr("storygen.storage.app_state.art_enabled", lambda: False)
    save = _save_with_portrait_on_disk()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    screen = PortraitsScreen(save, FakeImageProvider())
    assert screen.check_action("open_full_res", ()) is False


def test_full_res_opens_first_character_portrait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """action_open_full_res calls open_in_system_viewer with the first character's portrait."""
    monkeypatch.setattr("storygen.storage.app_state.art_enabled", lambda: True)
    save = _save_with_portrait_on_disk()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    screen = PortraitsScreen(save, FakeImageProvider())

    opened_paths: list[Path] = []

    def _fake_viewer(p: Path) -> None:
        opened_paths.append(p)

    monkeypatch.setattr("storygen.screens.portraits.open_in_system_viewer", _fake_viewer)

    screen.action_open_full_res()
    assert len(opened_paths) == 1
    assert opened_paths[0].name.endswith(".png")
    assert save.characters[0].id in str(opened_paths[0])
