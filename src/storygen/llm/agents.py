"""pydantic-ai Agent factory functions."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model

from storygen.core.models import (
    AdaptedBackstory,
    Character,
    IllustrationPlan,
    NarrationStyle,
    Pacing,
    ReaderLevel,
    Recap,
    StoryBeat,
    Summary,
    Theme,
    Tone,
)
from storygen.llm import prompts
from storygen.storage.app_state import DEFAULT_TARGET_MAJOR_BEATS


def build_theme_agent(model: Model) -> Agent[None, Theme]:
    """Build an agent that proposes story themes."""
    return Agent(
        model=model,
        output_type=Theme,
        system_prompt=prompts.theme_system_prompt(),
    )


def build_character_agent(model: Model, *, theme: Theme) -> Agent[None, list[Character]]:
    """Build an agent that generates a character cast for the given theme."""
    return Agent(
        model=model,
        output_type=list[Character],
        system_prompt=prompts.character_system_prompt(theme),
    )


def build_beat_agent(
    model: Model,
    *,
    theme: Theme,
    tone: Tone,
    narration_style: NarrationStyle,
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS,
    reader_level: ReaderLevel = "ages_11_15",
    pacing: Pacing = "moderate",
) -> Agent[None, StoryBeat]:
    """Build an agent that writes a single story beat."""
    return Agent(
        model=model,
        output_type=StoryBeat,
        system_prompt=prompts.beat_system_prompt(
            theme=theme,
            tone=tone,
            narration_style=narration_style,
            target_major_beats=target_major_beats,
            reader_level=reader_level,
            pacing=pacing,
        ),
    )


def build_illustration_agent(model: Model) -> Agent[None, IllustrationPlan]:
    """Build an agent that decides whether and how to illustrate a beat."""
    return Agent(
        model=model,
        output_type=IllustrationPlan,
        system_prompt=prompts.illustration_system_prompt(),
    )


def build_blurb_agent(
    model: Model,
    *,
    theme: Theme,
    characters: list[Character],
    narration_style: NarrationStyle = "third_person",
) -> Agent[None, str]:
    """Build an agent that writes a back-cover blurb."""
    return Agent(
        model=model,
        output_type=str,
        system_prompt=prompts.blurb_system_prompt(theme, characters, narration_style),
    )


def build_adapt_backstory_agent(model: Model, *, theme: Theme) -> Agent[None, AdaptedBackstory]:
    """Build an agent that rewrites a character's backstory for a new theme.

    The system prompt forbids changes to ``name``, ``personality``, or
    ``physical_description`` so the imported portrait remains a faithful
    depiction. Output is a single :class:`AdaptedBackstory` with just the
    rewritten backstory text.
    """
    return Agent(
        model=model,
        output_type=AdaptedBackstory,
        system_prompt=prompts.adapt_backstory_system_prompt(theme),
    )


def build_summary_agent(model: Model) -> Agent[None, Summary]:
    """Build an agent that summarises the story so far."""
    return Agent(
        model=model,
        output_type=Summary,
        system_prompt=prompts.summary_system_prompt(),
    )


def build_recap_agent(model: Model) -> Agent[None, Recap]:
    """Build an agent that writes a 'Previously on...' recap."""
    return Agent(
        model=model,
        output_type=Recap,
        system_prompt=prompts.recap_system_prompt(),
    )


def build_catalog_character_agent(model: Model) -> Agent[None, list[Character]]:
    """Build an agent that generates a single character from a concept description."""
    return Agent(
        model=model,
        output_type=list[Character],
        system_prompt=(
            "You are a character designer. Given a concept, create exactly ONE "
            "detailed character with: name, backstory (one paragraph), personality "
            "(one or two sentences), and a physical description vivid enough for "
            "an illustrator to paint from — colors, build, notable features, "
            "signature clothing. Return a list with that single character."
        ),
    )
