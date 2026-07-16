"""Tests for cover art generation during save construction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from storygen.images.prompts import build_cover_prompt
from storygen.llm.models import (
    Character,
    ImageProviderConfig,
    ImageStatus,
    StoredChoice,
    StoryNode,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.runtime.wizard_flow import WizardFlow
from storygen.storage import app_state, paths
from storygen.storage.save import GameSave, save_game


class FakeImageProvider:
    def __init__(self) -> None:
        self.scenes: list[str] = []

    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        reference_image: bytes | None = None,
    ) -> bytes:
        return b"FAKEPORTRAIT"

    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
    ) -> bytes:
        self.scenes.append(prompt)
        return b"FAKESCENE"


_TEXT_CONFIG = TextProviderConfig(provider="openai", model="gpt-4o-mini")
_IMAGE_CONFIG = ImageProviderConfig(provider="openai", model="gpt-image-2")


class _Result:
    def __init__(self, output: object) -> None:
        self.output = output


class _FakeBlurbAgent:
    async def run(self, prompt: str) -> object:
        return _Result("A gripping cover art blurb.")


def _fake_blurb_factory(
    theme: object, characters: object, narration_style: object
) -> _FakeBlurbAgent:
    return _FakeBlurbAgent()


_TEST_THEME = Theme(
    title="Test Theme",
    setting="A test setting.",
    premise="A test premise.",
    keywords=["test"],
)


@pytest.mark.asyncio
async def test_build_initial_save_generates_cover_art(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When art_enabled is True, build_initial_save sets root node image fields."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(app_state, "art_enabled", lambda: True)

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=_FakeThemeAgent(),
        character_agent_factory=lambda theme: _FakeCharAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    save = await flow.build_initial_save(
        theme=_TEST_THEME,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[
            Character(
                id="c1",
                name="Hero",
                backstory="b",
                personality="Brave.",
                physical_description="Tall.",
                introduced_at_node_id="root",
            ),
        ],
    )
    root = save.nodes["root"]
    assert root.image_status == "done"
    assert root.image_path is not None
    assert root.image_prompt is not None
    assert "Test Theme" in root.image_prompt
    assert save.total_image_cost_usd > 0


@pytest.mark.asyncio
async def test_build_initial_save_skips_cover_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When art_enabled is False, root node stays not_planned."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(app_state, "art_enabled", lambda: False)

    provider = FakeImageProvider()
    flow = WizardFlow(
        text_config=_TEXT_CONFIG,
        image_config=_IMAGE_CONFIG,
        theme_agent=_FakeThemeAgent(),
        character_agent_factory=lambda theme: _FakeCharAgent(),
        blurb_agent_factory=_fake_blurb_factory,
        image_provider=provider,
    )
    save = await flow.build_initial_save(
        theme=_TEST_THEME,
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        characters=[
            Character(
                id="c1",
                name="Hero",
                backstory="b",
                personality="Brave.",
                physical_description="Tall.",
                introduced_at_node_id="root",
            ),
        ],
    )
    root = save.nodes["root"]
    assert root.image_status == "not_planned"
    assert root.image_path is None
    assert root.image_prompt is None


# -- Shared fakes (avoid repeating the same agents across tests above) ------


class _FakeThemeAgent:
    async def run(self, prompt: str) -> object:
        return _Result(
            Theme(
                title="Test Theme",
                setting="A test setting.",
                premise="A test premise.",
                keywords=["test"],
            )
        )


class _FakeCharAgent:
    async def run(self, prompt: str) -> object:
        return _Result(
            [
                Character(
                    id="c1",
                    name="Hero",
                    backstory="b",
                    personality="Brave.",
                    physical_description="Tall.",
                    introduced_at_node_id="pending",
                ),
            ]
        )


# -- Cover art backfill tests ------------------------------------------------


async def _run_backfill_cover(
    save: GameSave,
    image_provider: FakeImageProvider,
) -> None:
    """Standalone version of _backfill_cover_if_missing for testing.

    Mirrors the logic in app.py without requiring a StoryGenApp instance.
    Expects the root node to already be set to image_status="generating"
    (matching the _mark_cover_generating_if_missing → create_task pattern).
    """
    root = save.nodes.get(save.root_node_id)
    if root is None or root.image_status == "done":
        return
    cover_prompt = build_cover_prompt(
        theme_title=save.theme.title,
        theme_description=f"{save.theme.setting} {save.theme.premise}",
        art_style=save.art_style,
    )
    try:
        cover_bytes = await image_provider.generate_scene(
            cover_prompt,
            reference_portraits=[],
            art_style=save.art_style,
        )
    except Exception:
        save.nodes[save.root_node_id] = root.model_copy(update={"image_status": "failed"})
        save_game(save)
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
    save_game(save)


def _make_minimal_save(
    tmp_path: Path,
    *,
    root_image_status: ImageStatus = "not_planned",
) -> GameSave:
    """Create a minimal save with a root node for backfill testing."""
    game_id = uuid4()
    paths.ensure_game_dirs(str(game_id))
    root = StoryNode(
        id="root",
        parent_id=None,
        chosen_choice_id=None,
        chosen_at=None,
        narration="A blurb for the story.",
        choices=[StoredChoice(id="start", text="Begin")],
        is_major=True,
        is_ending=False,
        image_prompt=None,
        image_path=None if root_image_status != "done" else "images/nodes/root.png",
        image_status=root_image_status,
        illustration_reasoning=None,
        featured_character_ids=[],
        summary_to_here=None,
        created_at=datetime.now(UTC),
    )
    return GameSave(
        version=1,
        id=game_id,
        theme=Theme(
            title="Test Theme",
            setting="A dark forest",
            premise="An ancient evil awakens",
            keywords=["fantasy"],
        ),
        tone=Tone(preset="serious", custom_descriptor=None),
        narration_style="third_person",
        art_style="children's story book",
        target_major_beats=10,
        text_config=TextProviderConfig(provider="openai", model="gpt-4o-mini"),
        image_config=ImageProviderConfig(provider="openai", model="gpt-image-2"),
        characters=[],
        nodes={"root": root},
        root_node_id="root",
        current_node_id="root",
        endings_reached=[],
        total_image_cost_usd=0.0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_mark_cover_generating_sets_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_mark_cover_generating_if_needed sets root to 'generating' when backfill needed."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(app_state, "art_enabled", lambda: True)

    save = _make_minimal_save(tmp_path, root_image_status="not_planned")
    from storygen.app import StoryGenApp

    app = StoryGenApp()
    result = app._mark_cover_generating_if_needed(save)  # pyright: ignore[reportPrivateUsage]
    assert result is True
    assert save.nodes["root"].image_status == "generating"


def test_mark_cover_skips_when_art_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_mark_cover_generating_if_needed returns False when art is disabled."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(app_state, "art_enabled", lambda: False)

    save = _make_minimal_save(tmp_path, root_image_status="not_planned")
    from storygen.app import StoryGenApp

    app = StoryGenApp()
    result = app._mark_cover_generating_if_needed(save)  # pyright: ignore[reportPrivateUsage]
    assert result is False
    assert save.nodes["root"].image_status == "not_planned"


def test_mark_cover_skips_when_already_done(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_mark_cover_generating_if_needed returns False when cover already exists."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(app_state, "art_enabled", lambda: True)

    save = _make_minimal_save(tmp_path, root_image_status="done")
    from storygen.app import StoryGenApp

    app = StoryGenApp()
    result = app._mark_cover_generating_if_needed(save)  # pyright: ignore[reportPrivateUsage]
    assert result is False


def test_backfill_cover_generates_for_generating_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy saves with image_status='generating' get a cover backfilled."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(app_state, "art_enabled", lambda: True)

    save = _make_minimal_save(tmp_path, root_image_status="generating")
    save_game(save)

    provider = FakeImageProvider()
    asyncio.run(_run_backfill_cover(save, provider))

    root = save.nodes["root"]
    assert root.image_status == "done"
    assert root.image_path is not None
    assert len(provider.scenes) == 1
    assert "Test Theme" in provider.scenes[0]


def test_backfill_cover_skips_when_already_done(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Saves that already have a cover image are not re-generated."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(app_state, "art_enabled", lambda: True)

    save = _make_minimal_save(tmp_path, root_image_status="done")
    save_game(save)

    provider = FakeImageProvider()
    asyncio.run(_run_backfill_cover(save, provider))

    assert len(provider.scenes) == 0
