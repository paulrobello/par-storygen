"""Smoke test: WizardScreen renders and starts at THEME step."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static, TextArea

from storygen.llm.models import Character, TextProviderConfig, Theme
from storygen.screens.library_browser import LibraryPick
from storygen.screens.wizard import WizardFlow, WizardScreen, WizardStep
from storygen.storage import app_state
from storygen.storage.library import (
    LibraryCharacter,
    LibrarySource,
    save_library_character,
)

_TEXT_CFG = TextProviderConfig(provider="openai", model="gpt-4o-mini")


class _Harness(App[None]):
    def on_mount(self) -> None:
        self.push_screen(WizardScreen(text_config=_TEXT_CFG))

    def compose(self) -> ComposeResult:
        yield from []


@pytest.mark.asyncio
async def test_wizard_starts_at_theme_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        screen = app.screen
        assert isinstance(screen, WizardScreen)
        assert screen.current_step == WizardStep.THEME
        await pilot.pause()


@pytest.mark.asyncio
async def test_wizard_prefills_from_persisted_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Persisted WizardDefaults pre-fill the wizard widgets on launch."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app_state.write_wizard_defaults(
        app_state.WizardDefaults(
            theme="A misted valley",
            tone_preset="dark",
            tone_descriptor="",
            narration_style="first_person",
            art_style="noir comic",
            target_major_beats=15,
            characters="A wizard and a goblin",
        )
    )

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, WizardScreen)
        art_input = screen.query_one("#wizard-art-style", Input)
        assert art_input.value == "noir comic"
        theme_area = screen.query_one("#wizard-theme", TextArea)
        assert theme_area.text == "A misted valley"
        char_area = screen.query_one("#wizard-char", TextArea)
        assert char_area.text == "A wizard and a goblin"
        tone_select = cast("Select[str]", screen.query_one("#wizard-tone", Select))
        assert tone_select.value == "dark"
        style_select = cast("Select[str]", screen.query_one("#wizard-style", Select))
        assert style_select.value == "first_person"
        length_input = screen.query_one("#wizard-length", Input)
        assert length_input.value == "15"
        # Internal state is also pre-filled from defaults so the CONFIRM
        # summary reflects it before the user even reaches the LENGTH step.
        assert screen._target_major_beats == 15  # pyright: ignore[reportPrivateUsage]


# ---- Library-import integration ---------------------------------------------


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x01\x01\x00\xf5\xfe\x7f\xc0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_lib_char(name: str = "Alyx") -> LibraryCharacter:
    return LibraryCharacter(
        id=uuid4().hex,
        name=name,
        backstory="A wandering scholar.",
        personality="Curious and cautious.",
        physical_description="Tall, brown hair, green cloak.",
        portrait_prompt="A tall figure in a green cloak, neutral pose.",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title="Prev"),
    )


@pytest.mark.asyncio
async def test_library_binding_only_active_on_characters_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`add_from_library` binding is hidden outside CHARACTERS step."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, WizardScreen)
        assert screen.check_action("add_from_library", ()) is False
        # Directly set step; Textual re-runs check_action on refresh_bindings.
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        assert screen.check_action("add_from_library", ()) is True


@pytest.mark.asyncio
async def test_library_pick_appends_to_cast_and_records_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dismissing the library browser with a LibraryCharacter grows the cast."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        # Library picks are only accepted on the CHARACTERS step (matches the
        # production binding gate).
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        # Drive the dismiss callback directly — it's the pure state mutation.
        before_count = len(screen._characters)  # pyright: ignore[reportPrivateUsage]
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()

        assert len(screen._characters) == before_count + 1  # pyright: ignore[reportPrivateUsage]
        appended = screen._characters[-1]  # pyright: ignore[reportPrivateUsage]
        assert appended.name == "Alyx"
        assert appended.backstory == char.backstory
        assert appended.personality == char.personality
        assert appended.physical_description == char.physical_description
        # portrait_prompt is preserved (not overwritten with physical_description).
        assert appended.portrait_prompt == char.portrait_prompt
        # The mapping records the library source id for build_initial_save.
        assert (
            screen._imported_from_library_ids[appended.id]  # pyright: ignore[reportPrivateUsage]
            == char.id
        )
        # portrait_path points at the save-local path that will exist after
        # build_initial_save copies the portrait.
        assert appended.portrait_path == f"images/characters/{appended.id}-v1.png"


@pytest.mark.asyncio
async def test_library_pick_none_leaves_cast_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancelling (None) does not mutate the cast."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        before = list(screen._characters)  # pyright: ignore[reportPrivateUsage]
        screen._on_library_pick(None)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()
        assert screen._characters == before  # pyright: ignore[reportPrivateUsage]
        assert screen._imported_from_library_ids == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_library_pick_adapt_true_routes_through_flow_adapt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pick.mode == "adapt" should trigger WizardFlow.adapt_library_character."""

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    # Spy flow whose adapt returns a modified library character.
    adapt_calls: list[tuple[str, str]] = []

    class _SpyFlow:
        async def adapt_library_character(
            self, lib: LibraryCharacter, theme: Theme
        ) -> LibraryCharacter:
            adapt_calls.append((lib.name, theme.title))
            return lib.model_copy(update={"backstory": "ADAPTED TO NEW THEME"})

    class _SpyWizardScreen(WizardScreen):
        """Stub out the real flow with a spy + pre-seed a theme."""

        def __init__(self) -> None:
            super().__init__(text_config=_TEXT_CFG)
            self._flow = cast(WizardFlow, _SpyFlow())
            self._theme = Theme(
                title="Target Theme",
                setting="setting",
                premise="premise",
                keywords=[],
            )

    class _SpyHarness(App[None]):
        def on_mount(self) -> None:
            self.push_screen(_SpyWizardScreen())

        def compose(self) -> ComposeResult:
            yield from []

    app = _SpyHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="adapt")
        )
        # Wait for the adapt worker + subsequent append to complete.
        for _ in range(20):
            await pilot.pause()
            if screen._characters:  # pyright: ignore[reportPrivateUsage]
                break

        assert adapt_calls == [("Alyx", "Target Theme")]
        assert len(screen._characters) == 1  # pyright: ignore[reportPrivateUsage]
        appended = screen._characters[0]  # pyright: ignore[reportPrivateUsage]
        # The rewritten backstory lands on the save-local Character.
        assert appended.backstory == "ADAPTED TO NEW THEME"
        # Name / personality / physical_description / portrait_prompt all
        # survive from the original library entry (portrait stays valid).
        assert appended.name == char.name
        assert appended.personality == char.personality
        assert appended.physical_description == char.physical_description
        assert appended.portrait_prompt == char.portrait_prompt


@pytest.mark.asyncio
async def test_library_pick_adapt_without_theme_no_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defensive: adapt-before-theme surfaces an error, cast unchanged."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)

    # Default _Harness pushes a WizardScreen with flow=None (no theme set).
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        # _theme is None until the wizard finishes the THEME step.
        assert screen._theme is None  # pyright: ignore[reportPrivateUsage]
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="adapt")
        )
        await pilot.pause()
        assert screen._characters == []  # pyright: ignore[reportPrivateUsage]
        assert screen._imported_from_library_ids == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_library_pick_missing_portrait_surfaces_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If portrait PNG is missing at pick time, no character is appended."""
    from storygen.storage import paths as _paths

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char()
    save_library_character(char, _PNG_BYTES)
    (_paths.library_root() / char.id / "portrait.png").unlink()

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()
        assert screen._characters == []  # pyright: ignore[reportPrivateUsage]
        assert screen._imported_from_library_ids == {}  # pyright: ignore[reportPrivateUsage]


# ---- Regression: re-entry + worker-race guards ------------------------------


class _StubGenerateFlow:
    """Minimal _flow stub exposing just the methods WizardScreen calls at
    CHARACTERS-step advance time (``generate_characters``).
    """

    def __init__(self) -> None:
        self.call_count = 0

    async def generate_characters(
        self,
        theme: object,
        *,
        user_prompt: str = "",
        imported_characters: list[Character] | None = None,
    ) -> list[Character]:
        self.call_count += 1
        # Return a fresh pair of characters each call; IDs are stable so that
        # a re-run would overlap only with the imported library character's
        # save-local id if dedup is broken — but we check dupe by counting
        # names, not ids, below.
        return [
            Character(
                id=f"gen-{self.call_count}-{i}",
                name=f"Gen{i}",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="pending",
            )
            for i in range(2)
        ]


@pytest.mark.asyncio
async def test_characters_step_reentry_does_not_duplicate_library_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Invariant: re-running the CHARACTERS advance preserves library imports
    exactly once.

    The current implementation overwrites ``self._characters`` via
    ``imported + generated``, so the invariant holds naturally; this test
    pins it so a future refactor (e.g. ``extend`` instead of assignment)
    doesn't silently regress the cross-advance preservation.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        # Wire a stub flow + pre-seed a theme so the CHARACTERS advance will
        # actually run.
        stub = _StubGenerateFlow()
        screen._flow = cast(WizardFlow, stub)  # pyright: ignore[reportPrivateUsage]
        screen._theme = Theme(  # pyright: ignore[reportPrivateUsage]
            title="Target",
            setting="s",
            premise="p",
            keywords=[],
        )
        # Drive the CHARACTERS advance twice — simulates Next -> Back -> Next.
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        # Import a library character so the merge logic has something to
        # preserve. The library-pick guard only accepts picks on CHARACTERS.
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()
        # First advance
        screen._advance_worker()  # pyright: ignore[reportPrivateUsage]
        for _ in range(20):
            await pilot.pause()
            if cast(WizardStep, screen.current_step) == WizardStep.CONFIRM:
                break
        assert cast(WizardStep, screen.current_step) == WizardStep.CONFIRM
        # Second advance: go back to CHARACTERS and re-run.
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._advance_worker()  # pyright: ignore[reportPrivateUsage]
        for _ in range(20):
            await pilot.pause()
            if cast(WizardStep, screen.current_step) == WizardStep.CONFIRM:
                break
        assert cast(WizardStep, screen.current_step) == WizardStep.CONFIRM

        # Alyx (the imported library character) must appear exactly once.
        cast_list: list[Character] = screen._characters  # pyright: ignore[reportPrivateUsage]
        assert [c.name for c in cast_list].count("Alyx") == 1
        # And the imported-id mapping stays intact.
        assert len(screen._imported_from_library_ids) == 1  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_late_adapt_worker_after_step_transition_is_discarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the adapt worker resolves after the wizard has left the CHARACTERS
    step, ``_append_library_character`` must discard the late character
    rather than silently mutate the cast.
    """

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        # Simulate the user having already advanced past CHARACTERS while
        # the adapt worker was still running.
        screen.current_step = WizardStep.CONFIRM
        await pilot.pause()
        # The adapt worker's final step is a direct call into
        # _append_library_character; firing that directly is the narrowest
        # reproduction of "worker resolves late".
        screen._append_library_character(char)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()
        assert screen._characters == []  # pyright: ignore[reportPrivateUsage]
        assert screen._imported_from_library_ids == {}  # pyright: ignore[reportPrivateUsage]


# ---- Hint text ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_characters_hint_mentions_library_import_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CHARACTERS step hint should mention the Ctrl+L and Ctrl+I keybindings."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        hint_text = screen._hint.content  # pyright: ignore[reportPrivateUsage]
        assert isinstance(hint_text, str)
        assert "[b]Ctrl+L[/]" in hint_text, (
            "Hint should mention the library-import key 'Ctrl+L' in bold Rich markup"
        )
        assert "[b]Ctrl+I[/]" in hint_text, (
            "Hint should mention the image-import key 'Ctrl+I' in bold Rich markup"
        )


# ---- Cast list widget ----------------------------------------------------------


@pytest.mark.asyncio
async def test_cast_list_hidden_when_no_characters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The cast list is hidden when no characters have been imported."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        cast_list = screen.query_one("#wizard-cast-list", Static)
        assert cast_list.display is False


@pytest.mark.asyncio
async def test_cast_list_shows_imported_character_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After importing a library character, the cast list shows the name."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()
        cast_list = screen.query_one("#wizard-cast-list", Static)
        assert cast_list.display is True
        content = cast_list.content
        assert isinstance(content, str)
        assert "Alyx" in content
        assert "library" in content


# ---- Character removal --------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_character_removes_from_cast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Removing an imported character cleans up all internal state."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()
        assert len(screen._characters) == 1  # pyright: ignore[reportPrivateUsage]
        char_id = screen._characters[0].id  # pyright: ignore[reportPrivateUsage]

        screen._remove_character(char_id)  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()

        assert screen._characters == []  # pyright: ignore[reportPrivateUsage]
        assert screen._imported_from_library_ids == {}  # pyright: ignore[reportPrivateUsage]
        cast_list = screen.query_one("#wizard-cast-list", Static)
        assert cast_list.display is False


@pytest.mark.asyncio
async def test_remove_character_idempotent_for_unknown_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Removing a non-existent character id is a no-op."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._remove_character("nonexistent")  # pyright: ignore[reportPrivateUsage]
        await pilot.pause()
        assert screen._characters == []  # pyright: ignore[reportPrivateUsage]


# ---- Prompt augmentation ------------------------------------------------------


class _CaptureGenerateFlow:
    """Stub flow that records arguments passed to generate_characters."""

    def __init__(self) -> None:
        self.captured_prompt: str = ""
        self.captured_imported: list[Character] | None = None

    async def generate_characters(
        self,
        theme: object,
        *,
        user_prompt: str = "",
        imported_characters: list[Character] | None = None,
    ) -> list[Character]:
        self.captured_prompt = user_prompt
        self.captured_imported = imported_characters
        return []


@pytest.mark.asyncio
async def test_advance_with_imports_passes_them_to_generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When imported characters exist, they are passed to generate_characters."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    char = _make_lib_char(name="Alyx")
    save_library_character(char, _PNG_BYTES)

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        stub = _CaptureGenerateFlow()
        screen._flow = cast(WizardFlow, stub)  # pyright: ignore[reportPrivateUsage]
        screen._theme = Theme(  # pyright: ignore[reportPrivateUsage]
            title="Test Theme", setting="s", premise="p", keywords=[]
        )
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._on_library_pick(  # pyright: ignore[reportPrivateUsage]
            LibraryPick(character=char, mode="keep")
        )
        await pilot.pause()
        screen._advance_worker()  # pyright: ignore[reportPrivateUsage]
        for _ in range(20):
            await pilot.pause()
            if cast(WizardStep, screen.current_step) == WizardStep.CONFIRM:
                break
        assert cast(WizardStep, screen.current_step) == WizardStep.CONFIRM
        assert stub.captured_imported is not None
        assert len(stub.captured_imported) == 1
        assert stub.captured_imported[0].name == "Alyx"


@pytest.mark.asyncio
async def test_advance_without_imports_passes_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no characters are imported, imported_characters is empty list."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = cast(WizardScreen, app.screen)
        stub = _CaptureGenerateFlow()
        screen._flow = cast(WizardFlow, stub)  # pyright: ignore[reportPrivateUsage]
        screen._theme = Theme(  # pyright: ignore[reportPrivateUsage]
            title="Test Theme", setting="s", premise="p", keywords=[]
        )
        screen.current_step = WizardStep.CHARACTERS
        await pilot.pause()
        screen._advance_worker()  # pyright: ignore[reportPrivateUsage]
        for _ in range(20):
            await pilot.pause()
            if cast(WizardStep, screen.current_step) == WizardStep.CONFIRM:
                break
        assert cast(WizardStep, screen.current_step) == WizardStep.CONFIRM
        assert stub.captured_imported == []
