"""Shared domain types — the neutral bottom layer.

Both ``storygen.storage`` and ``storygen.llm`` import from here.  Neither
``storage`` nor ``llm`` is imported by this module, so there are no cycles.

Moved here from ``storygen.llm.models`` (all prior types) and
``storygen.storage.save`` (``NarrationStyle``, ``ReaderLevel``).  Both
source modules now re-export from this package for backward compatibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Scalar type aliases
# ---------------------------------------------------------------------------

NodeId = str
CharacterId = str

NarrationStyle = Literal["first_person", "third_person", "fourth_wall"]
Pacing = Literal["slow", "moderate", "fast"]
ReaderLevel = Literal["ages_0_5", "ages_6_10", "ages_11_15", "ages_15_plus"]

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


class TextProviderConfig(BaseModel):
    """Configures which text LLM pydantic-ai routes through."""

    provider: Literal["openai", "openrouter", "ollama"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key: str | None = Field(default=None, exclude=True)


class ImageProviderConfig(BaseModel):
    """Configures which image provider renders scenes and portraits."""

    provider: Literal["openai", "gemini", "zai", "ollama"] = "openai"
    model: str = "gpt-image-2"
    base_url: str | None = None
    api_key: str | None = Field(default=None, exclude=True)


# ---------------------------------------------------------------------------
# Story domain models
# ---------------------------------------------------------------------------


class Theme(BaseModel):
    """Story theme configuration."""

    title: str
    setting: str
    premise: str
    keywords: list[str]


class Tone(BaseModel):
    """Story tone, either a preset or a custom descriptor."""

    preset: Literal[
        "silly",
        "serious",
        "dark",
        "whimsical",
        "mysterious",
        "romantic",
        "action",
        "unexpected",
        "custom",
    ]
    custom_descriptor: str | None = None

    @model_validator(mode="after")
    def _custom_requires_descriptor(self) -> Tone:
        if self.preset == "custom" and not self.custom_descriptor:
            raise ValueError("custom_descriptor is required when preset='custom'")
        return self


class CharacterOutfit(BaseModel):
    """A named outfit variant for a character — its own portrait + prompt.

    Outfits are sidecar references stored on ``Character.outfits``. Setting one
    as current copies its ``portrait_path`` / ``portrait_prompt`` into the
    character's main fields, so scene-generation code (which reads
    ``Character.portrait_path``) picks the active outfit up automatically.

    Attributes:
        id: Stable identifier (uuid4 hex, 32 lowercase chars).
        name: Human-readable label (e.g. ``"casual"``, ``"ballroom gown"``).
        description: Prompt addition describing the outfit (e.g. ``"wearing a
            red gown with gold trim"``).
        portrait_path: Outfit portrait path, relative to the save directory
            (mirrors ``Character.portrait_path`` storage convention).
        portrait_prompt: Full prompt used to generate the portrait, retained so
            the outfit can be regenerated later with identical wording.
        created_at: When the outfit was added. Required — caller passes
            ``datetime.now(UTC)`` at creation time.
    """

    id: str
    name: str
    description: str
    portrait_path: str
    portrait_prompt: str
    created_at: datetime


class Character(BaseModel):
    """A character who appears in the story."""

    id: CharacterId
    name: str
    backstory: str
    personality: str
    physical_description: str
    portrait_path: str | None = None
    portrait_prompt: str | None = None
    introduced_at_node_id: NodeId
    outfits: list[CharacterOutfit] = Field(default_factory=list[CharacterOutfit])
    current_outfit_id: str | None = None
    reference_image_path: str | None = None


class Choice(BaseModel):
    """A branching choice as the LLM produces it — id + display text only.

    The cache link to a child node lives on ``StoredChoice``; it is internal
    bookkeeping that the LLM should never see (or invent values for).
    """

    id: str
    text: str


class StoredChoice(Choice):
    """A choice persisted on a StoryNode, with the cache link to its child."""

    child_node_id: NodeId | None = None


class StoryBeat(BaseModel):
    """Output of `beat_agent` — the narrative content of one beat."""

    narration: str
    choices: list[Choice]
    is_major: bool
    is_ending: bool
    new_characters: list[Character] = Field(default_factory=list[Character])

    @model_validator(mode="after")
    def _ending_has_no_choices(self) -> StoryBeat:
        if self.is_ending and self.choices:
            raise ValueError("is_ending=True forbids choices")
        return self


class IllustrationPlan(BaseModel):
    """Output of `illustration_agent` — decides whether and how to illustrate a beat."""

    should_illustrate: bool
    image_prompt: str
    featured_character_ids: list[CharacterId]
    reasoning: str


class Summary(BaseModel):
    """Output of `summary_agent`."""

    text: str


class Recap(BaseModel):
    """Output of `recap_agent`."""

    text: str


class AdaptedBackstory(BaseModel):
    """Output of ``adapt_backstory_agent`` — ONLY the rewritten backstory.

    The agent MUST NOT emit a name, personality, or physical description.
    Those fields are load-bearing for the existing portrait (the library
    character's portrait was painted from ``physical_description`` and keyed
    to the visible name/personality) so the portrait stays consistent across
    theme adaptations.
    """

    backstory: str


ImageStatus = Literal["not_planned", "generating", "done", "failed"]


class StoryNode(BaseModel):
    """A single node in the story graph, persisted to storage."""

    id: NodeId
    parent_id: NodeId | None
    chosen_choice_id: str | None
    chosen_at: datetime | None
    narration: str
    choices: list[StoredChoice]
    is_major: bool
    is_ending: bool
    image_prompt: str | None
    image_path: str | None
    image_status: ImageStatus
    illustration_reasoning: str | None
    featured_character_ids: list[CharacterId]
    summary_to_here: str | None
    recap_text: str | None = None
    tts_audio_path: str | None = None
    created_at: datetime


__all__ = [
    "AdaptedBackstory",
    "Character",
    "CharacterId",
    "CharacterOutfit",
    "Choice",
    "IllustrationPlan",
    "ImageProviderConfig",
    "ImageStatus",
    "NarrationStyle",
    "NodeId",
    "Pacing",
    "ReaderLevel",
    "Recap",
    "StoredChoice",
    "StoryBeat",
    "StoryNode",
    "Summary",
    "TextProviderConfig",
    "Theme",
    "Tone",
]
