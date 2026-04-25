"""Tests for StoryImportModal."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox

from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.screens._story_import_modal import StoryImportModal, StoryImportResult
from storygen.storage import paths
from storygen.storage.save import GameSave, save_game


def _make_save(*, title: str = "Test Story", char_names: list[str] | None = None) -> GameSave:
    names = char_names or ["Alice"]
    characters = [
        Character(
            id=f"char-{i}",
            name=name,
            backstory="A test character.",
            personality="Brave and curious.",
            physical_description="Tall with dark hair.",
            introduced_at_node_id="root",
        )
        for i, name in enumerate(names)
    ]
    return GameSave(
        version=1,
        id=uuid4(),
        theme=Theme(title=title, setting="Test", premise="Test", keywords=[]),
        tone=Tone(preset="serious"),
        narration_style="third_person",
        text_config=TextProviderConfig(),
        image_config=ImageProviderConfig(),
        characters=characters,
        nodes={
            "root": StoryNode(
                id="root",
                parent_id=None,
                chosen_choice_id=None,
                chosen_at=None,
                narration="Test",
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
        },
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _ModalHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.result: object = "<unset>"

    def on_mount(self) -> None:
        def _cap(r: object) -> None:
            self.result = r

        self.push_screen(StoryImportModal(), _cap)

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_modal_lists_saves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save(title="My Story")
    paths.ensure_game_dirs(str(save.id))
    save_game(save)

    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        statics = app.screen.query("Static")
        texts = [str(s.render()) for s in statics]
        assert any("My Story" in t for t in texts)


@pytest.mark.asyncio
async def test_escape_dismisses_with_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


def test_story_import_result_model() -> None:
    result = StoryImportResult(save_id="abc", character_ids=["char-0"])
    assert result.save_id == "abc"
    assert result.character_ids == ["char-0"]


@pytest.mark.asyncio
async def test_select_all_toggles_per_character_checkboxes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Checking 'Select All' sets all per-character checkboxes to checked."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save(title="Multi Char", char_names=["Alice", "Bob"])
    paths.ensure_game_dirs(str(save.id))
    save_game(save)

    save_id = str(save.id)
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Toggle select-all via widget value
        sel_all = app.screen.query_one(f"#selall-{save_id}", Checkbox)
        sel_all.value = True
        await pilot.pause()
        # Both character checkboxes should be checked
        cb0 = app.screen.query_one(f"#charcb-{save_id}__char-0", Checkbox)
        cb1 = app.screen.query_one(f"#charcb-{save_id}__char-1", Checkbox)
        assert cb0.value is True
        assert cb1.value is True
        assert sel_all.value is True


@pytest.mark.asyncio
async def test_per_character_check_updates_select_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Checking all per-character boxes sets Select All; unchecking one clears it."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save(title="Two Char", char_names=["Alice", "Bob"])
    paths.ensure_game_dirs(str(save.id))
    save_game(save)

    save_id = str(save.id)
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Check both per-character boxes
        cb0 = app.screen.query_one(f"#charcb-{save_id}__char-0", Checkbox)
        cb1 = app.screen.query_one(f"#charcb-{save_id}__char-1", Checkbox)
        cb0.value = True
        await pilot.pause()
        cb1.value = True
        await pilot.pause()
        # Select All should now be True
        sel_all = app.screen.query_one(f"#selall-{save_id}", Checkbox)
        assert sel_all.value is True
        # Uncheck one character
        cb0.value = False
        await pilot.pause()
        # Select All should go back to False
        assert sel_all.value is False


@pytest.mark.asyncio
async def test_do_import_with_one_character_dismisses_with_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Selecting one character and clicking Import dismisses with list[StoryImportResult]."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save(title="One Char", char_names=["Alice"])
    paths.ensure_game_dirs(str(save.id))
    save_game(save)

    save_id = str(save.id)
    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Check the one character via widget
        cb = app.screen.query_one(f"#charcb-{save_id}__char-0", Checkbox)
        cb.value = True
        await pilot.pause()
        # Click Import button
        app.screen.query_one("#btn-do-import", Button).press()
        await pilot.pause()

    assert isinstance(app.result, list)
    result_list: list[object] = list(app.result)  # type: ignore[arg-type]
    results: list[StoryImportResult] = [r for r in result_list if isinstance(r, StoryImportResult)]
    assert len(results) == 1
    assert results[0].save_id == save_id
    assert "char-0" in results[0].character_ids


@pytest.mark.asyncio
async def test_do_import_with_nothing_checked_shows_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clicking Import with nothing checked shows a warning and does not dismiss."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save = _make_save(title="Empty Select")
    paths.ensure_game_dirs(str(save.id))
    save_game(save)

    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Do NOT check anything
        app.screen.query_one("#btn-do-import", Button).press()
        await pilot.pause()
    # Should not have dismissed
    assert app.result == "<unset>"


@pytest.mark.asyncio
async def test_do_import_collects_all_saves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Characters from multiple saves are all collected in the import result."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save_a = _make_save(title="Save A", char_names=["Alice"])
    save_b = _make_save(title="Save B", char_names=["Bob"])
    paths.ensure_game_dirs(str(save_a.id))
    paths.ensure_game_dirs(str(save_b.id))
    save_game(save_a)
    save_game(save_b)

    id_a = str(save_a.id)
    id_b = str(save_b.id)

    app = _ModalHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Check one character from each save via widget
        cb_a = app.screen.query_one(f"#charcb-{id_a}__char-0", Checkbox)
        cb_b = app.screen.query_one(f"#charcb-{id_b}__char-0", Checkbox)
        cb_a.value = True
        await pilot.pause()
        cb_b.value = True
        await pilot.pause()
        app.screen.query_one("#btn-do-import", Button).press()
        await pilot.pause()

    assert isinstance(app.result, list)
    # Both saves should appear in results
    result_list2: list[object] = list(app.result)  # type: ignore[arg-type]
    import_results: list[StoryImportResult] = [
        r for r in result_list2 if isinstance(r, StoryImportResult)
    ]
    save_ids = {r.save_id for r in import_results}
    assert id_a in save_ids
    assert id_b in save_ids
