"""Unit tests for agent factories — use pydantic-ai TestModel to avoid network."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.messages import SystemPromptPart
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
@pytest.mark.parametrize("native_output", [False, True])
async def test_theme_agent_returns_theme(native_output: bool) -> None:
    model = (
        TestModel(
            custom_output_text=Theme(
                title="t", setting="s", premise="p", keywords=[]
            ).model_dump_json(),
            profile={"supports_json_schema_output": True},
        )
        if native_output
        else TestModel()
    )
    agent = build_theme_agent(model, native_output=native_output)
    result = await agent.run("propose a theme")
    assert isinstance(result.output, Theme)
    assert (
        isinstance(agent.output_type, NativeOutput) if native_output else agent.output_type is Theme
    )
    system_prompts = [
        part.content
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, SystemPromptPart)
    ]
    assert any(
        "exactly one" in prompt and "structured Theme" in prompt for prompt in system_prompts
    )


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


@pytest.mark.parametrize("native_output", [False, True])
@pytest.mark.parametrize(
    "kind", ["character", "catalog", "beat", "illustration", "summary", "recap", "adapt"]
)
async def test_all_structured_agents_output_modes(kind: str, native_output: bool) -> None:
    """Exercise actual JSON parsing, including pydantic-ai's list wrapper."""
    from storygen.core.models import Recap, Summary
    from storygen.llm.agents import build_catalog_character_agent, build_recap_agent

    theme = Theme(title="t", setting="s", premise="p", keywords=[])
    import json

    char = Character(
        id="c1",
        name="N",
        backstory="b",
        personality="p",
        physical_description="d",
        introduced_at_node_id="root",
    )
    payloads: dict[str, dict[str, Any]] = {
        "character": {"response": [char.model_dump()]},
        "catalog": {"response": [char.model_dump()]},
        "beat": {"narration": "The end.", "choices": [], "is_major": True, "is_ending": True},
        "illustration": {
            "should_illustrate": False,
            "image_prompt": "",
            "featured_character_ids": [],
            "reasoning": "quiet",
        },
        "summary": {"text": "A tale."},
        "recap": {"text": "Previously..."},
        "adapt": {"backstory": "A new past."},
    }
    model = (
        TestModel(
            custom_output_text=json.dumps(payloads[kind]),
            profile={"supports_json_schema_output": True},
        )
        if native_output
        else TestModel()
        if kind in {"character", "catalog"}
        else TestModel(custom_output_args=payloads[kind])
    )
    factories = {
        "character": lambda: build_character_agent(model, theme=theme, native_output=native_output),
        "catalog": lambda: build_catalog_character_agent(model, native_output=native_output),
        "beat": lambda: build_beat_agent(
            model,
            theme=theme,
            tone=Tone(preset="serious"),
            narration_style="third_person",
            native_output=native_output,
        ),
        "illustration": lambda: build_illustration_agent(model, native_output=native_output),
        "summary": lambda: build_summary_agent(model, native_output=native_output),
        "recap": lambda: build_recap_agent(model, native_output=native_output),
        "adapt": lambda: build_adapt_backstory_agent(
            model, theme=theme, native_output=native_output
        ),
    }
    agent = factories[kind]()
    result = await agent.run("Generate the requested output.")
    expected = {
        "character": list,
        "catalog": list,
        "beat": StoryBeat,
        "illustration": IllustrationPlan,
        "summary": Summary,
        "recap": Recap,
        "adapt": AdaptedBackstory,
    }[kind]
    assert isinstance(result.output, expected)
    if isinstance(result.output, list):
        assert result.output and all(isinstance(c, Character) for c in result.output)
    assert isinstance(agent.output_type, NativeOutput) is native_output
    assert model.last_model_request_parameters is not None
    assert model.last_model_request_parameters.output_mode == (
        "native" if native_output else "tool"
    )


async def test_native_beat_validation_failure_emits_no_narration() -> None:
    """Native JSON parsing must not bypass the ending/choices invariant."""
    from unittest.mock import AsyncMock

    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from storygen.runtime.adapters import BeatAgentAdapter

    model = TestModel(
        custom_output_text='{"narration":"Not validated", "choices":[{"id":"c1","text":"Go"}], "is_major":false, "is_ending":true}',
        profile={"supports_json_schema_output": True},
    )
    agent = build_beat_agent(
        model,
        theme=Theme(title="t", setting="s", premise="p", keywords=[]),
        tone=Tone(preset="serious"),
        narration_style="third_person",
        native_output=True,
    )
    delta = AsyncMock()
    with pytest.raises(UnexpectedModelBehavior, match="maximum output retries"):
        await BeatAgentAdapter(agent).run("End the story.", delta)  # pyright: ignore[reportUnknownMemberType]
    delta.assert_not_awaited()
