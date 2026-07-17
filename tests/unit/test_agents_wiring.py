"""Unit tests for agent factories — use pydantic-ai TestModel to avoid network."""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from storygen.core.models import (
    AdaptedBackstory,
    Character,
    IllustrationPlan,
    StoryBeat,
    TextProviderConfig,
    Theme,
    Tone,
)
from storygen.llm.agents import (
    build_adapt_backstory_agent,
    build_beat_agent,
    build_blurb_agent,
    build_character_agent,
    build_illustration_agent,
    build_summary_agent,
    build_theme_agent,
)
from storygen.llm.provider_factory import build_text_model


@pytest.mark.asyncio
async def test_theme_agent_returns_theme() -> None:
    model = TestModel()
    agent = build_theme_agent(model)
    result = await agent.run("propose a theme")
    assert isinstance(result.output, Theme)


@pytest.mark.asyncio
async def test_character_agent_accepts_theme_in_prompt() -> None:
    model = TestModel()
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    agent = build_character_agent(model, theme=theme)
    result = await agent.run("generate cast")
    assert result.output  # TestModel returns a shape matching the structured type


@pytest.mark.asyncio
async def test_beat_agent_output_type_matches() -> None:
    model = TestModel()
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    agent = build_beat_agent(model, theme=theme, tone=tone, narration_style="third_person")
    # Verify the agent's declared output type is StoryBeat.
    assert agent.output_type is StoryBeat


@pytest.mark.asyncio
async def test_illustration_agent_returns_plan() -> None:
    model = TestModel()
    agent = build_illustration_agent(model)
    result = await agent.run("beat text")
    assert isinstance(result.output, IllustrationPlan)


@pytest.mark.asyncio
async def test_summary_agent_exists() -> None:
    model = TestModel()
    agent = build_summary_agent(model)
    assert agent is not None


@pytest.mark.asyncio
async def test_adapt_backstory_agent_returns_adapted_backstory() -> None:
    model = TestModel()
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    agent = build_adapt_backstory_agent(model, theme=theme)
    result = await agent.run("rewrite this backstory")
    assert isinstance(result.output, AdaptedBackstory)


@pytest.mark.asyncio
async def test_blurb_agent_output_type_is_str() -> None:
    model = TestModel()
    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    char = Character(
        id="c1",
        name="N",
        backstory="b",
        personality="p.",
        physical_description="d",
        introduced_at_node_id="root",
    )
    agent = build_blurb_agent(model, theme=theme, characters=[char])
    assert agent.output_type is str


@pytest.mark.parametrize(
    ("provider", "model_name", "api_key_env"),
    [
        ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
        ("openrouter", "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY"),
        ("ollama", "llama3.3:70b", None),
    ],
)
def test_agent_factories_accept_every_provider_model(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model_name: str,
    api_key_env: str | None,
) -> None:
    """`build_text_model` → agent factory chain must construct without error per provider.

    Construction-only — no network calls are made. We just verify that feeding
    a real provider-backed Model into each agent factory yields a valid Agent.
    """
    if api_key_env is not None:
        monkeypatch.setenv(api_key_env, "sk-test")
    cfg = TextProviderConfig(provider=provider, model=model_name)  # type: ignore[arg-type]
    model = build_text_model(cfg)

    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    tone = Tone(preset="serious", custom_descriptor=None)
    char = Character(
        id="c1",
        name="N",
        backstory="b",
        personality="p.",
        physical_description="d",
        introduced_at_node_id="root",
    )

    assert isinstance(build_theme_agent(model), Agent)
    assert isinstance(build_character_agent(model, theme=theme), Agent)
    assert isinstance(
        build_beat_agent(model, theme=theme, tone=tone, narration_style="third_person"),
        Agent,
    )
    assert isinstance(build_illustration_agent(model), Agent)
    assert isinstance(build_summary_agent(model), Agent)
    assert isinstance(build_blurb_agent(model, theme=theme, characters=[char]), Agent)
    assert isinstance(build_adapt_backstory_agent(model, theme=theme), Agent)
