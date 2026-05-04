"""Unit tests for WizardFlow — the LLM-facing wizard state machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from storygen.images.base import ReferencePortrait
from storygen.images.constants import PORTRAIT_QUALITY, PORTRAIT_SIZE, SCENE_QUALITY, SCENE_SIZE
from storygen.images.pricing import image_cost
from storygen.llm.models import Character, ImageProviderConfig, TextProviderConfig, Theme
from storygen.screens.wizard import WizardFlow, WizardStep

_TEXT_CONFIG = TextProviderConfig(provider="openai", model="gpt-4o-mini")
_IMAGE_CONFIG = ImageProviderConfig(provider="openai", model="gpt-image-2")
_CHARACTER_IMAGE_CONFIG = ImageProviderConfig(
    provider="gemini", model="gemini-3.1-flash-image-preview"
)


class FakeThemeAgent:
    async def run(self, prompt: str) -> object:
        theme = Theme(
            title="Proposed",
            setting="A misted valley.",
            premise="Something stirs.",
            keywords=["mist", "valley"],
        )
        return _Result(theme)


class FakeCharacterAgent:
    async def run(self, prompt: str) -> object:
        chars = [
            Character(
                id=f"char-{i}",
                name=f"Name{i}",
                backstory="b",
                personality="p",
                physical_description="d",
                portrait_path=None,
                portrait_prompt=None,
                introduced_at_node_id="pending",
            )
            for i in range(2)
        ]
        return _Result(chars)


class FakeImageProvider:
    def __init__(self) -> None:
        self.portrait_calls: list[tuple[str, str]] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        reference_image: bytes | None = None,
    ) -> bytes:
        del reference_image
        self.portrait_calls.append((description, art_style))
        return b"PORTRAIT"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
    ) -> bytes:
        return b"SCENE"


class FakeBlurbAgent:
    async def run(self, prompt: str) -> object:
        return _Result("A gripping tale awaits you in the misted valley.")


def _fake_blurb_factory(
    theme: object, characters: object, narration_style: object
) -> FakeBlurbAgent:
    return FakeBlurbAgent()


class _Result:
    def __init__(self, output: object) -> None:
        self.output = output


@pytest.mark.asyncio
async def test_wizard_flow_proposes_theme(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("any prompt")
    assert theme.title == "Proposed"


@pytest.mark.asyncio
async def test_wizard_flow_generates_characters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("any prompt")
    chars = await flow.generate_characters(theme)
    assert len(chars) == 2


@pytest.mark.asyncio
async def test_wizard_flow_builds_initial_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
    )
    assert save.root_node_id == save.current_node_id
    # Root narration is the back-cover blurb, not empty.
    assert save.nodes[save.root_node_id].narration
    assert "gripping tale" in save.nodes[save.root_node_id].narration
    # Portraits must exist on disk.
    for c in save.characters:
        assert c.portrait_path is not None
        assert c.portrait_path.endswith("-v1.png")


@pytest.mark.asyncio
async def test_wizard_flow_uses_character_config_for_portraits_and_art_config_for_cover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        character_image_config=_CHARACTER_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)

    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
    )

    portrait_cost = image_cost(
        _CHARACTER_IMAGE_CONFIG.provider,
        model=_CHARACTER_IMAGE_CONFIG.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    ) * len(chars)
    cover_cost = image_cost(
        _IMAGE_CONFIG.provider,
        model=_IMAGE_CONFIG.model,
        size=SCENE_SIZE,
        quality=SCENE_QUALITY,
    )
    assert save.character_image_config == _CHARACTER_IMAGE_CONFIG
    assert save.image_config == _IMAGE_CONFIG
    assert save.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        portrait_cost + cover_cost
    )


@pytest.mark.asyncio
async def test_wizard_flow_passes_user_character_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    captured: dict[str, str] = {}

    class CapturingCharacterAgent:
        async def run(self, prompt: str) -> object:
            captured["prompt"] = prompt
            return _Result([])

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: CapturingCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    await flow.generate_characters(theme, user_prompt="2 characters: a wizard and a goblin")

    assert "wizard" in captured["prompt"]
    assert "goblin" in captured["prompt"]


@pytest.mark.asyncio
async def test_wizard_flow_runs_blurb_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_initial_save invokes the blurb agent factory and uses its output."""
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    captured: dict[str, object] = {}

    class CapturingBlurbAgent:
        async def run(self, prompt: str) -> object:
            captured["prompt"] = prompt
            return _Result("BACK COVER BLURB TEXT")

    def capturing_blurb_factory(
        theme: Theme, characters: list[Character], narration_style: object
    ) -> CapturingBlurbAgent:
        captured["theme_title"] = theme.title
        captured["character_count"] = len(characters)
        return CapturingBlurbAgent()

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=capturing_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
    )

    assert captured["prompt"] == "Write the back-cover blurb."
    assert captured["theme_title"] == "Proposed"
    assert captured["character_count"] == 2
    assert save.nodes["root"].narration == "BACK COVER BLURB TEXT"


@pytest.mark.asyncio
async def test_wizard_flow_accumulates_token_usage_into_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Per-call usage from the three LLM agents lands on the freshly built save."""
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    class _Usage:
        def __init__(self, *, in_tok: int, out_tok: int) -> None:
            self.input_tokens = in_tok
            self.output_tokens = out_tok
            self.requests = 1

    class _UsageResult:
        def __init__(self, output: object, *, in_tok: int, out_tok: int) -> None:
            self.output = output
            self._u = _Usage(in_tok=in_tok, out_tok=out_tok)

        def usage(self) -> _Usage:
            return self._u

    class ThemeAgentWithUsage:
        async def run(self, prompt: str) -> object:
            theme = Theme(
                title="Proposed",
                setting="A misted valley.",
                premise="Stir.",
                keywords=[],
            )
            return _UsageResult(theme, in_tok=11, out_tok=22)

    class CharAgentWithUsage:
        async def run(self, prompt: str) -> object:
            chars = [
                Character(
                    id=f"char-{i}",
                    name=f"Name{i}",
                    backstory="b",
                    personality="p",
                    physical_description="d",
                    portrait_path=None,
                    portrait_prompt=None,
                    introduced_at_node_id="pending",
                )
                for i in range(2)
            ]
            return _UsageResult(chars, in_tok=33, out_tok=44)

    class BlurbAgentWithUsage:
        async def run(self, prompt: str) -> object:
            return _UsageResult("Blurb.", in_tok=55, out_tok=66)

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=ThemeAgentWithUsage(),
        character_agent_factory=lambda theme: CharAgentWithUsage(),
        blurb_agent_factory=lambda theme, chars, narration_style: BlurbAgentWithUsage(),
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
    )

    assert save.text_total_input_tokens == 11 + 33 + 55
    assert save.text_total_output_tokens == 22 + 44 + 66
    assert save.text_total_requests == 3
    assert save.text_calls_by_model == {_TEXT_CONFIG.model: 3}


@pytest.mark.asyncio
async def test_wizard_flow_passes_art_style_to_save_and_portraits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
        art_style="watercolor",
    )
    assert save.art_style == "watercolor"
    # Each portrait call received the art_style kwarg.
    assert len(provider.portrait_calls) == len(chars)
    assert all(call[1] == "watercolor" for call in provider.portrait_calls)


@pytest.mark.asyncio
async def test_wizard_flow_skips_portraits_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from storygen.llm.models import Tone
    from storygen.storage import app_state

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_art_enabled(False)

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
    )
    assert provider.portrait_calls == []  # never called
    for c in save.characters:
        assert c.portrait_path is None
    assert save.total_image_cost_usd == 0.0


def test_wizard_step_order() -> None:
    assert list(WizardStep) == [
        WizardStep.THEME,
        WizardStep.TONE,
        WizardStep.STYLE,
        WizardStep.ART_STYLE,
        WizardStep.LENGTH,
        WizardStep.READER_LEVEL,
        WizardStep.CHARACTERS,
        WizardStep.CONFIRM,
    ]


@pytest.mark.asyncio
async def test_build_initial_save_copies_library_portrait_without_generating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Imported-library characters skip the image provider and copy the cached PNG."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.llm.models import Tone
    from storygen.storage import paths as _paths
    from storygen.storage.library import (
        LibraryCharacter,
        LibrarySource,
        library_portrait_path,
        save_library_character,
    )

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    # Seed one library character with known portrait bytes.
    lib_id = uuid4().hex
    lib_char = LibraryCharacter(
        id=lib_id,
        name="ImportedOne",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_prompt="the original prompt",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title="Prev"),
    )
    portrait_bytes = b"LIBRARY_PORTRAIT_BYTES"
    save_library_character(lib_char, portrait_bytes)

    # Two characters: one imported, one freshly generated.
    imported_char = Character(
        id="imported-1",
        name="ImportedOne",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_path="images/characters/imported-1-v1.png",
        portrait_prompt="the original prompt",
        introduced_at_node_id="pending",
    )
    fresh_char = Character(
        id="fresh-1",
        name="FreshOne",
        backstory="b2",
        personality="p2",
        physical_description="d2",
        portrait_path=None,
        portrait_prompt=None,
        introduced_at_node_id="pending",
    )

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[imported_char, fresh_char],
        library_import_ids={"imported-1": lib_id},
    )

    # Image provider was called EXACTLY for the non-imported character.
    assert len(provider.portrait_calls) == 1
    assert provider.portrait_calls[0][0] == "d2"  # fresh_char.physical_description

    # Imported character's portrait was copied from the library.
    by_id = {c.id: c for c in save.characters}
    imported_out = by_id["imported-1"]
    fresh_out = by_id["fresh-1"]
    assert imported_out.portrait_path is not None
    copied = _paths.game_dir(str(save.id)) / imported_out.portrait_path
    assert copied.read_bytes() == portrait_bytes
    # And the library's own file is still intact (copy, not move).
    assert library_portrait_path(lib_id).read_bytes() == portrait_bytes
    # portrait_prompt is PRESERVED from the library; NOT overwritten with
    # physical_description the way fresh generation does.
    assert imported_out.portrait_prompt == "the original prompt"
    assert fresh_out.portrait_prompt == "d2"
    # introduced_at_node_id is rewritten to "root".
    assert imported_out.introduced_at_node_id == "root"
    fresh_portrait_cost = image_cost(
        save.character_image_config.provider,
        model=save.character_image_config.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )
    cover_cost = image_cost(
        _IMAGE_CONFIG.provider,
        model=_IMAGE_CONFIG.model,
        size=SCENE_SIZE,
        quality=SCENE_QUALITY,
    )
    assert save.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        fresh_portrait_cost + cover_cost
    )


@pytest.mark.asyncio
async def test_build_initial_save_library_import_does_not_call_provider_that_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Library import must not invoke the image provider even if it's broken."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.llm.models import Tone
    from storygen.storage import app_state
    from storygen.storage.library import (
        LibraryCharacter,
        LibrarySource,
        save_library_character,
    )

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    app_state.set_art_enabled(False)

    lib_id = uuid4().hex
    lib_char = LibraryCharacter(
        id=lib_id,
        name="ImportedOne",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_prompt="p",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title="Prev"),
    )
    save_library_character(lib_char, b"BYTES")

    class ExplodingImageProvider:
        async def generate_portrait(
            self,
            description: str,
            *,
            transparent: bool,
            art_style: str = "children's story book",
            reference_image: bytes | None = None,
        ) -> bytes:
            del reference_image
            raise RuntimeError("should not be called for library-imported char")

        async def generate_scene(
            self,
            prompt: str,
            *,
            reference_portraits: list[ReferencePortrait],
            art_style: str = "children's story book",
        ) -> bytes:
            raise RuntimeError("should not be called")

    imported_char = Character(
        id="imported-1",
        name="ImportedOne",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_path="images/characters/imported-1-v1.png",
        portrait_prompt="p",
        introduced_at_node_id="pending",
    )

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=ExplodingImageProvider(),
    )
    theme = await flow.propose_theme("")
    # Should not raise.
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[imported_char],
        library_import_ids={"imported-1": lib_id},
    )
    assert len(save.characters) == 1
    assert save.characters[0].portrait_path is not None


@pytest.mark.asyncio
async def test_adapt_library_character_rewrites_only_backstory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """adapt_library_character rewrites backstory but preserves every other field."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.llm.models import AdaptedBackstory
    from storygen.storage.library import LibraryCharacter, LibrarySource

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    class _AdaptUsage:
        input_tokens = 12
        output_tokens = 34
        requests = 1

    class _AdaptResult:
        def __init__(self, output: AdaptedBackstory) -> None:
            self.output = output

        def usage(self) -> _AdaptUsage:
            return _AdaptUsage()

    captured: dict[str, object] = {}

    class FakeAdaptAgent:
        async def run(self, prompt: str) -> object:
            captured["prompt"] = prompt
            return _AdaptResult(AdaptedBackstory(backstory="NEW REWRITTEN BACKSTORY."))

    def adapt_factory(theme: Theme) -> FakeAdaptAgent:
        captured["theme_title"] = theme.title
        return FakeAdaptAgent()

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        adapt_agent_factory=adapt_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")

    lib = LibraryCharacter(
        id=uuid4().hex,
        name="Alyx",
        backstory="OLD BACKSTORY from the prior story.",
        personality="Curious and cautious.",
        physical_description="Tall, brown hair, green cloak.",
        portrait_prompt="A tall figure in a green cloak, neutral pose.",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title="Prev"),
    )
    adapted = await flow.adapt_library_character(lib, theme)

    # Backstory changed; everything else preserved verbatim.
    assert adapted.backstory == "NEW REWRITTEN BACKSTORY."
    assert adapted.name == lib.name
    assert adapted.personality == lib.personality
    assert adapted.physical_description == lib.physical_description
    assert adapted.portrait_prompt == lib.portrait_prompt
    assert adapted.id == lib.id
    assert adapted.exported_at == lib.exported_at
    assert adapted.exported_from == lib.exported_from

    # The theme title landed on the agent factory + the user prompt mentions
    # the old backstory so the LLM can actually transform it.
    assert captured["theme_title"] == theme.title
    assert "OLD BACKSTORY" in str(captured["prompt"])
    assert lib.name in str(captured["prompt"])

    # Usage tracking fired (the adapt call counts).
    assert flow._usage_totals.input_tokens == 12  # pyright: ignore[reportPrivateUsage]
    assert flow._usage_totals.output_tokens == 34  # pyright: ignore[reportPrivateUsage]
    assert flow._usage_totals.requests == 1  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_adapt_library_character_rejects_empty_backstory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty-string adaptation must raise, not silently wipe the backstory."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.llm.models import AdaptedBackstory
    from storygen.storage.library import LibraryCharacter, LibrarySource

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    class _EmptyResult:
        def __init__(self, output: AdaptedBackstory) -> None:
            self.output = output

    class EmptyAdaptAgent:
        async def run(self, prompt: str) -> object:
            # Returns whitespace-only — post-strip this is empty.
            return _EmptyResult(AdaptedBackstory(backstory="   \n\t  "))

    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        adapt_agent_factory=lambda theme: EmptyAdaptAgent(),
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")

    lib = LibraryCharacter(
        id=uuid4().hex,
        name="Alyx",
        backstory="OLD BACKSTORY.",
        personality="Curious.",
        physical_description="Tall.",
        portrait_prompt="Tall figure.",
        exported_at=datetime.now(UTC),
        exported_from=LibrarySource(save_id=uuid4().hex, save_title="Prev"),
    )
    with pytest.raises(ValueError, match="empty backstory"):
        await flow.adapt_library_character(lib, theme)


@pytest.mark.asyncio
async def test_adapt_library_character_without_factory_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Calling adapt without a factory is a clear error, not a silent no-op."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from storygen.storage.library import LibraryCharacter

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
        # adapt_agent_factory intentionally omitted
    )
    theme = await flow.propose_theme("")
    lib = LibraryCharacter(
        id=uuid4().hex,
        name="X",
        backstory="b",
        personality="p",
        physical_description="d",
        portrait_prompt="pp",
        exported_at=datetime.now(UTC),
    )
    with pytest.raises(RuntimeError, match="adapt_agent_factory"):
        await flow.adapt_library_character(lib, theme)


@pytest.mark.asyncio
async def test_wizard_flow_persists_target_major_beats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_initial_save records the target_major_beats kwarg on the save."""
    from storygen.llm.models import Tone

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=FakeImageProvider(),
    )
    theme = await flow.propose_theme("")
    chars = await flow.generate_characters(theme)
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=chars,
        target_major_beats=15,
    )
    assert save.target_major_beats == 15


def test_wizard_defaults_save_to_catalog_roundtrip() -> None:
    """WizardDefaults.save_to_catalog persists and reads back."""
    from storygen.storage.app_state import WizardDefaults

    defaults = WizardDefaults(save_to_catalog=False)
    assert defaults.save_to_catalog is False
    defaults2 = WizardDefaults()
    assert defaults2.save_to_catalog is True


@pytest.mark.asyncio
async def test_build_initial_save_pending_ref_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pending_ref_writes path: ref and portrait bytes are written to disk correctly."""
    from storygen.llm.models import Tone
    from storygen.storage import paths as _paths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    # A character added via "style-transfer" reference image (portrait PNG generated).
    ref_char_id = "ref-char-1"
    ref_png_bytes = b"REFERENCE_PNG_BYTES"
    portrait_png_bytes = b"PORTRAIT_PNG_BYTES"

    ref_char = Character(
        id=ref_char_id,
        name="Ref Hero",
        backstory="",
        personality="",
        physical_description="As shown in reference image",
        portrait_path=_paths.relative_character_portrait_path(ref_char_id, version=1),
        portrait_prompt="(from reference image)",
        introduced_at_node_id="pending",
        reference_image_path=_paths.relative_character_reference_path(ref_char_id),
    )

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[ref_char],
        pending_ref_writes={ref_char_id: (ref_png_bytes, portrait_png_bytes)},
    )

    # Image provider was NOT called (ref path bypasses generation).
    assert provider.portrait_calls == []

    # The character should be in the save with the correct paths.
    by_id = {c.id: c for c in save.characters}
    out = by_id[ref_char_id]

    # portrait_path is set and the file contains portrait bytes
    assert out.portrait_path is not None
    portrait_on_disk = _paths.game_dir(str(save.id)) / out.portrait_path
    assert portrait_on_disk.exists()
    assert portrait_on_disk.read_bytes() == portrait_png_bytes

    # reference_image_path is set and the file contains reference bytes
    assert out.reference_image_path is not None
    ref_on_disk = _paths.game_dir(str(save.id)) / out.reference_image_path
    assert ref_on_disk.exists()
    assert ref_on_disk.read_bytes() == ref_png_bytes

    # introduced_at_node_id is rewritten to "root"
    assert out.introduced_at_node_id == "root"


@pytest.mark.asyncio
async def test_build_initial_save_pending_ref_writes_counts_generated_portrait_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Generated ref-image portraits are billed using the character image config."""
    from storygen.llm.models import Tone
    from storygen.storage import paths as _paths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    ref_char_id = "ref-char-cost"
    ref_png_bytes = b"REFERENCE_PNG_BYTES"
    portrait_png_bytes = b"GENERATED_STYLE_TRANSFER_PORTRAIT"
    ref_char = Character(
        id=ref_char_id,
        name="Costed Ref Hero",
        backstory="",
        personality="",
        physical_description="As shown in reference image",
        portrait_path=_paths.relative_character_portrait_path(ref_char_id, version=1),
        portrait_prompt="(from reference image)",
        introduced_at_node_id="pending",
        reference_image_path=_paths.relative_character_reference_path(ref_char_id),
    )

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        character_image_config=_CHARACTER_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[ref_char],
        pending_ref_writes={ref_char_id: (ref_png_bytes, portrait_png_bytes)},
    )

    assert provider.portrait_calls == []
    portrait_cost = image_cost(
        _CHARACTER_IMAGE_CONFIG.provider,
        model=_CHARACTER_IMAGE_CONFIG.model,
        size=PORTRAIT_SIZE,
        quality=PORTRAIT_QUALITY,
    )
    cover_cost = image_cost(
        _IMAGE_CONFIG.provider,
        model=_IMAGE_CONFIG.model,
        size=SCENE_SIZE,
        quality=SCENE_QUALITY,
    )
    assert save.total_image_cost_usd == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
        portrait_cost + cover_cost
    )


@pytest.mark.asyncio
async def test_build_initial_save_pending_ref_writes_use_as_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pending_ref_writes with portrait_png=None: reference bytes are used as portrait."""
    from storygen.llm.models import Tone
    from storygen.storage import paths as _paths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    ref_char_id = "ref-char-2"
    ref_png_bytes = b"USE_AS_IS_REFERENCE_BYTES"

    ref_char = Character(
        id=ref_char_id,
        name="Portrait Hero",
        backstory="",
        personality="",
        physical_description="As shown in reference image",
        portrait_path=_paths.relative_character_portrait_path(ref_char_id, version=1),
        portrait_prompt="(from reference image)",
        introduced_at_node_id="pending",
        reference_image_path=_paths.relative_character_reference_path(ref_char_id),
    )

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=FakeThemeAgent(),
        character_agent_factory=lambda theme: FakeCharacterAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    theme = await flow.propose_theme("")
    save = await flow.build_initial_save(
        theme=theme,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[ref_char],
        # portrait_png is None -> use_as_is: both portrait and reference get ref bytes
        pending_ref_writes={ref_char_id: (ref_png_bytes, None)},
    )

    by_id = {c.id: c for c in save.characters}
    out = by_id[ref_char_id]

    assert out.portrait_path is not None
    portrait_on_disk = _paths.game_dir(str(save.id)) / out.portrait_path
    assert portrait_on_disk.read_bytes() == ref_png_bytes  # same bytes as ref

    assert out.reference_image_path is not None
    ref_on_disk = _paths.game_dir(str(save.id)) / out.reference_image_path
    assert ref_on_disk.read_bytes() == ref_png_bytes

    cover_cost = image_cost(
        _IMAGE_CONFIG.provider,
        model=_IMAGE_CONFIG.model,
        size=SCENE_SIZE,
        quality=SCENE_QUALITY,
    )
    assert save.total_image_cost_usd == pytest.approx(cover_cost)  # pyright: ignore[reportUnknownMemberType]
