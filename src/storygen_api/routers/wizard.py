from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import TypeAdapter

from storygen.config import AppConfig
from storygen.core.models import Character, Theme, Tone
from storygen.llm import agents as agent_mod
from storygen.llm.provider_factory import build_text_model
from storygen.runtime.wizard_flow import WizardFlow
from storygen_api.deps import build_split_image_provider_for_wizard, get_app_config
from storygen_api.rate_limit import enforce_rate_limit
from storygen_api.schemas import (
    WizardCharactersRequest,
    WizardCharactersResponse,
    WizardConfirmRequest,
    WizardConfirmResponse,
    WizardThemeRequest,
    WizardThemeResponse,
)
from storygen_api.security import verify_token

router = APIRouter(
    prefix="/api/wizard",
    tags=["wizard"],
    # SEC-001: every wizard route triggers cost-incurring LLM/image generation.
    # SEC-007: per-IP rate limit applies because every call burns LLM credit.
    dependencies=[Depends(verify_token), Depends(enforce_rate_limit)],
)

_character_list_adapter = TypeAdapter(list[Character])


def _build_flow(config: AppConfig) -> WizardFlow:
    text_model = build_text_model(config.text_config)
    return WizardFlow(
        text_config=config.text_config,
        image_config=config.image_config,
        character_image_config=config.character_image_config,
        theme_agent=agent_mod.build_theme_agent(text_model),  # pyright: ignore[reportArgumentType]
        character_agent_factory=lambda theme: agent_mod.build_character_agent(  # pyright: ignore[reportArgumentType]
            text_model, theme=theme
        ),
        blurb_agent_factory=lambda theme, characters, narration_style: agent_mod.build_blurb_agent(  # pyright: ignore[reportArgumentType]
            text_model,
            theme=theme,
            characters=characters,
            narration_style=narration_style,
        ),
        adapt_agent_factory=lambda theme: agent_mod.build_adapt_backstory_agent(  # pyright: ignore[reportArgumentType]
            text_model, theme=theme
        ),
        image_provider=None,  # type: ignore[arg-type]  # built on-demand in build_initial_save
    )


@router.post("/theme", response_model=WizardThemeResponse)
async def wizard_theme(
    body: WizardThemeRequest,
    config: AppConfig = Depends(get_app_config),
) -> WizardThemeResponse:
    """Generate a story theme from a prompt."""
    flow = _build_flow(config)
    theme = await flow.propose_theme(body.prompt)
    return WizardThemeResponse(theme=theme.model_dump())


@router.post("/characters", response_model=WizardCharactersResponse)
async def wizard_characters(
    body: WizardCharactersRequest,
    config: AppConfig = Depends(get_app_config),
) -> WizardCharactersResponse:
    """Generate characters for a theme."""
    flow = _build_flow(config)
    theme = Theme.model_validate(body.theme)
    imported: list[Character] = []
    if body.imported_characters:
        imported = _character_list_adapter.validate_python(body.imported_characters)
    characters = await flow.generate_characters(
        theme,
        user_prompt=body.prompt,
        imported_characters=imported or None,
    )
    return WizardCharactersResponse(characters=[c.model_dump() for c in characters])


@router.post("/confirm", response_model=WizardConfirmResponse)
async def wizard_confirm(
    body: WizardConfirmRequest,
    config: AppConfig = Depends(get_app_config),
) -> WizardConfirmResponse:
    """Build the initial save and generate portraits."""
    flow = _build_flow(config)
    theme = Theme.model_validate(body.theme)
    tone = Tone.model_validate(body.tone)
    characters = _character_list_adapter.validate_python(body.characters)

    # The flow needs an image provider for portrait generation
    flow = WizardFlow(
        text_config=config.text_config,
        image_config=config.image_config,
        character_image_config=config.character_image_config,
        theme_agent=agent_mod.build_theme_agent(build_text_model(config.text_config)),  # pyright: ignore[reportArgumentType]
        character_agent_factory=lambda theme: agent_mod.build_character_agent(  # pyright: ignore[reportArgumentType]
            build_text_model(config.text_config), theme=theme
        ),
        blurb_agent_factory=lambda t, c, n: agent_mod.build_blurb_agent(  # pyright: ignore[reportArgumentType]
            build_text_model(config.text_config), theme=t, characters=c, narration_style=n
        ),
        adapt_agent_factory=lambda theme: agent_mod.build_adapt_backstory_agent(  # pyright: ignore[reportArgumentType]
            build_text_model(config.text_config), theme=theme
        ),
        image_provider=build_split_image_provider_for_wizard(config),
    )

    save = await flow.build_initial_save(
        theme=theme,
        tone=tone,
        narration_style=body.narration_style,  # pyright: ignore[reportArgumentType]
        characters=characters,
        art_style=body.art_style,
        target_major_beats=body.target_major_beats,
        reader_level=body.reader_level,  # pyright: ignore[reportArgumentType]
        pacing=body.pacing,  # pyright: ignore[reportArgumentType]
        theme_prompt=body.theme_prompt,
        character_prompt=body.character_prompt,
    )
    return WizardConfirmResponse(
        game_id=str(save.id),
        title=save.theme.title,
    )
