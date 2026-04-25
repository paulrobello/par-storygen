"""Tests for CharacterCatalogScreen — browse + import + delete flow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from storygen.screens._confirm_modal import ConfirmModal
from storygen.screens.library_browser import (
    CharacterCatalogScreen,
    LibraryPick,
    _ImportModeModal,  # pyright: ignore[reportPrivateUsage]
)
from storygen.storage.library import (
    LibraryCharacter,
    LibrarySource,
    list_library_characters,
    save_library_character,
)


def _make_lib_char(
    *,
    library_id: str | None = None,
    name: str = "Alyx",
    source_title: str = "Misted Valley",
) -> LibraryCharacter:
    return LibraryCharacter(
        id=library_id or uuid4().hex,
        name=name,
        backstory="A wandering scholar.",
        personality="Curious and cautious. Quick to act.",
        physical_description="Tall, brown hair, green cloak.",
        portrait_prompt="A tall figure in a green cloak, neutral pose.",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title=source_title),
    )


# A 1x1 PNG (valid but minimal) so PIL can open it for the thumbnail.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x01\x01\x00\xf5\xfe\x7f\xc0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Harness(App[None]):
    """Pushes a CharacterCatalogScreen as the test subject."""

    def __init__(self) -> None:
        super().__init__()
        self.pick_result: object = "<unset>"

    def on_mount(self) -> None:
        def _capture(result: object) -> None:
            self.pick_result = result

        self.push_screen(CharacterCatalogScreen(), _capture)

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_empty_state_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When the library is empty the screen shows the 'no characters' message."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        empty = screen.query_one("#library-empty", Static)
        text = str(empty.render())
        assert "No characters in catalog yet" in text


@pytest.mark.asyncio
async def test_populated_state_renders_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each library entry renders with name, source label, Import + Delete buttons."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char(name="Alyx", source_title="Misted Valley")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        import_btn = screen.query_one(f"#import-{char.id}", Button)
        delete_btn = screen.query_one(f"#delete-{char.id}", Button)
        assert import_btn.label
        assert delete_btn.label
        # Source label surfaced from exported_from.save_title; the label
        # static is mounted alongside the name static.
        statics = screen.query("Static")
        texts = [str(s.render()) for s in statics]
        assert any("Misted Valley" in t for t in texts)
        assert any("Alyx" in t for t in texts)


@pytest.mark.asyncio
async def test_escape_dismisses_with_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.pick_result is None


@pytest.mark.asyncio
async def test_import_keep_as_is_dismisses_with_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clicking Import → Keep as-is dismisses the browser with the LibraryCharacter."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#import-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, _ImportModeModal):
                break
        assert isinstance(app.screen, _ImportModeModal)
        # "Adapt" button is enabled (Phase 4).
        adapt_btn = app.screen.query_one("#mode-adapt", Button)
        assert adapt_btn.disabled is False
        # "Keep as-is" fires dismiss.
        await pilot.click("#mode-keep")
        for _ in range(10):
            await pilot.pause()
            if app.pick_result != "<unset>":
                break

    picked = app.pick_result
    assert isinstance(picked, LibraryPick)
    assert picked.character.id == char.id
    assert picked.character.name == char.name
    assert picked.mode == "keep"


@pytest.mark.asyncio
async def test_import_adapt_dismisses_with_adapt_pick(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clicking Import → Adapt dismisses with LibraryPick(adapt=True)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#import-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, _ImportModeModal):
                break
        assert isinstance(app.screen, _ImportModeModal)
        await pilot.click("#mode-adapt")
        for _ in range(10):
            await pilot.pause()
            if app.pick_result != "<unset>":
                break

    picked = app.pick_result
    assert isinstance(picked, LibraryPick)
    assert picked.character.id == char.id
    assert picked.mode == "adapt"


@pytest.mark.asyncio
async def test_import_mode_cancel_does_not_dismiss_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancelling the mode modal leaves the browser open (no dismiss fires)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#import-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, _ImportModeModal):
                break
        await pilot.click("#mode-cancel")
        for _ in range(5):
            await pilot.pause()
        # Browser is visible again; pick_result still unset.
        assert isinstance(app.screen, CharacterCatalogScreen)
        assert app.pick_result == "<unset>"


@pytest.mark.asyncio
async def test_delete_confirm_removes_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Delete → confirm removes the entry from disk + the list."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)
    assert len(list_library_characters()) == 1

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#delete-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, ConfirmModal):
                break
        await pilot.click("#confirm-yes")
        for _ in range(10):
            await pilot.pause()
            if not list_library_characters():
                break

    assert list_library_characters() == []
    # Filesystem entry was torn down.
    from storygen.storage import paths as _paths

    assert not (_paths.library_root() / char.id).exists()


@pytest.mark.asyncio
async def test_delete_cancel_keeps_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Delete → cancel leaves the entry in place."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(f"#delete-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, ConfirmModal):
                break
        await pilot.click("#confirm-no")
        for _ in range(5):
            await pilot.pause()

    assert len(list_library_characters()) == 1


@pytest.mark.asyncio
async def test_missing_portrait_disables_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the portrait file is gone, the Import button is disabled."""
    from storygen.storage import paths as _paths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)
    # Remove the portrait file but leave character.json.
    (_paths.library_root() / char.id / "portrait.png").unlink()

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        import_btn = screen.query_one(f"#import-{char.id}", Button)
        assert import_btn.disabled is True


def test_library_browser_screen_constructs_without_args() -> None:
    """CharacterCatalogScreen takes no args — dismisses via self.dismiss(...)."""
    screen = CharacterCatalogScreen()
    assert screen is not None


@pytest.mark.asyncio
async def test_initial_sort_is_newest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On first mount the browser renders in 'newest' sort mode."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save_library_character(_make_lib_char(name="Alice"), _PNG_BYTES)
    save_library_character(_make_lib_char(name="bob"), _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CharacterCatalogScreen)
        assert screen._sort_mode == "newest"  # pyright: ignore[reportPrivateUsage]
        # Header reflects the default sort + the count.
        title = screen.title or ""
        assert "sorted by newest" in title
        assert "2 characters" in title


@pytest.mark.asyncio
async def test_toggle_sort_to_name_orders_case_insensitive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pressing 's' toggles to 'name' sort and entries order case-insensitive alpha."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Mixed-case names that would sort differently under naive (case-sensitive) sort.
    save_library_character(_make_lib_char(name="charlie"), _PNG_BYTES)
    save_library_character(_make_lib_char(name="Alice"), _PNG_BYTES)
    save_library_character(_make_lib_char(name="bob"), _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CharacterCatalogScreen)
        await pilot.press("s")
        await pilot.pause()
        assert screen._sort_mode == "name"  # pyright: ignore[reportPrivateUsage]
        assert "sorted by name" in (screen.title or "")

        names = [entry.name for entry in screen._entries.values()]  # pyright: ignore[reportPrivateUsage]
        # dict preserves insertion order; _rebuild populates in sorted order.
        assert names == ["Alice", "bob", "charlie"]

        # Second press cycles back to newest.
        await pilot.press("s")
        await pilot.pause()
        assert screen._sort_mode == "newest"  # pyright: ignore[reportPrivateUsage]
        assert "sorted by newest" in (screen.title or "")


@pytest.mark.asyncio
async def test_import_click_uses_cached_entry_no_extra_list_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clicking Import must not trigger another list_library_characters() call.

    Avoids a render/click race (TOCTOU) and halves filesystem I/O per click.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    # Count list_library_characters invocations via monkeypatching the name
    # in the module-under-test's namespace.
    from storygen.screens import library_browser as browser_mod

    real_list = browser_mod.list_library_characters
    call_count = {"n": 0}

    def _counting_list() -> list[LibraryCharacter]:
        call_count["n"] += 1
        return real_list()

    monkeypatch.setattr(browser_mod, "list_library_characters", _counting_list)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # One list call during initial _rebuild.
        baseline = call_count["n"]
        assert baseline >= 1
        # Click Import — must hit the cache, not disk.
        await pilot.click(f"#import-{char.id}")
        for _ in range(5):
            await pilot.pause()
            if isinstance(app.screen, _ImportModeModal):
                break
        assert isinstance(app.screen, _ImportModeModal)
        assert call_count["n"] == baseline, (
            "Clicking Import performed an extra list_library_characters() "
            "call; should reuse the cached _entries dict."
        )


class _BrowseHarness(App[None]):
    """Pushes CharacterCatalogScreen in browse mode (no dismiss callback)."""

    def on_mount(self) -> None:
        self.push_screen(CharacterCatalogScreen(browse=True))

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_browse_mode_title_says_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = _BrowseHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CharacterCatalogScreen)
        title = screen.title or ""
        assert "Character Catalog" in title


@pytest.mark.asyncio
async def test_pick_mode_title_says_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = _Harness()  # default pick mode
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CharacterCatalogScreen)
        title = screen.title or ""
        assert "Character Library" in title
