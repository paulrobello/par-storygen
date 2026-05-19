from __future__ import annotations

from fastapi import APIRouter

from storygen.storage import app_state
from storygen.storage.app_state import TTSPrefs
from storygen_api.schemas import SettingsResponse, SettingsUpdateRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Return the full application state."""
    text_prefs = app_state.read_provider_prefs()
    image_prefs = app_state.read_image_provider_prefs()
    char_image_prefs = app_state.read_character_image_provider_prefs()
    wizard_defaults = app_state.read_wizard_defaults()
    tts = app_state.read_tts_prefs()
    return SettingsResponse(
        art_enabled=app_state.art_enabled(),
        prefetch_enabled=app_state.prefetch_enabled(),
        prefetch_images_enabled=app_state.prefetch_images_enabled(),
        image_streaming_enabled=app_state.image_streaming_enabled(),
        llm_cache_enabled=app_state.llm_cache_enabled(),
        auto_select_enabled=app_state.auto_select_enabled(),
        auto_open_art_enabled=app_state.auto_open_art_enabled(),
        auto_recap_enabled=app_state.auto_recap_enabled(),
        resume_recap_enabled=app_state.resume_recap_enabled(),
        recap_interval=app_state.recap_interval(),
        graphics_mode=app_state.read_graphics_mode(),
        text_provider={
            "provider": text_prefs.provider,
            "model": text_prefs.model,
            "base_url": text_prefs.base_url,
        },
        image_provider={
            "provider": image_prefs.provider,
            "model": image_prefs.model,
            "base_url": image_prefs.base_url,
            "fallback_provider": image_prefs.fallback_provider,
            "fallback_model": image_prefs.fallback_model,
        },
        character_image_provider={
            "provider": char_image_prefs.provider,
            "model": char_image_prefs.model,
            "base_url": char_image_prefs.base_url,
        },
        wizard_defaults={
            "theme": wizard_defaults.theme,
            "tone_preset": wizard_defaults.tone_preset,
            "tone_descriptor": wizard_defaults.tone_descriptor,
            "narration_style": wizard_defaults.narration_style,
            "art_style": wizard_defaults.art_style,
            "target_major_beats": wizard_defaults.target_major_beats,
            "reader_level": wizard_defaults.reader_level,
            "pacing": wizard_defaults.pacing,
            "characters": wizard_defaults.characters,
            "save_to_catalog": wizard_defaults.save_to_catalog,
        },
        tts_prefs={
            "provider": tts.provider,
            "voice": tts.voice,
            "auto_read": tts.auto_read,
            "auto_read_recap": tts.auto_read_recap,
        },
    )


def _str_or_default(d: dict[str, object], key: str, default: str) -> str:
    """Get a string from a dict, falling back to default."""
    val = d.get(key)
    return str(val) if isinstance(val, str) else default


@router.put("", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    """Write settings and return the updated state."""
    text_prefs = app_state.read_provider_prefs()
    image_prefs = app_state.read_image_provider_prefs()
    char_image_prefs = app_state.read_character_image_provider_prefs()
    wizard_defaults = app_state.read_wizard_defaults()

    if body.text_provider is not None:
        tp = body.text_provider
        text_prefs = app_state.ProviderPrefs(
            provider=_str_or_default(tp, "provider", text_prefs.provider),
            model=_str_or_default(tp, "model", text_prefs.model),
            base_url=_str_or_default(tp, "base_url", text_prefs.base_url),
            api_key=_str_or_default(tp, "api_key", text_prefs.api_key),
        )

    if body.image_provider is not None:
        ip = body.image_provider
        image_prefs = app_state.ImageProviderPrefs(
            provider=_str_or_default(ip, "provider", image_prefs.provider),
            model=_str_or_default(ip, "model", image_prefs.model),
            base_url=_str_or_default(ip, "base_url", image_prefs.base_url),
            api_key=_str_or_default(ip, "api_key", image_prefs.api_key),
            fallback_provider=_str_or_default(
                ip, "fallback_provider", image_prefs.fallback_provider
            ),
            fallback_model=_str_or_default(ip, "fallback_model", image_prefs.fallback_model),
        )

    if body.character_image_provider is not None:
        cp = body.character_image_provider
        char_image_prefs = app_state.CharacterImageProviderPrefs(
            provider=_str_or_default(cp, "provider", char_image_prefs.provider),
            model=_str_or_default(cp, "model", char_image_prefs.model),
            base_url=_str_or_default(cp, "base_url", char_image_prefs.base_url),
            api_key=_str_or_default(cp, "api_key", char_image_prefs.api_key),
        )

    if body.wizard_defaults is not None:
        wd = body.wizard_defaults
        target_raw = wd.get("target_major_beats", wizard_defaults.target_major_beats)
        try:
            target_beats = int(target_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            target_beats = wizard_defaults.target_major_beats
        reader_level = wd.get("reader_level", wizard_defaults.reader_level)
        wizard_defaults = app_state.WizardDefaults(
            theme=_str_or_default(wd, "theme", wizard_defaults.theme),
            tone_preset=_str_or_default(wd, "tone_preset", wizard_defaults.tone_preset),
            tone_descriptor=_str_or_default(wd, "tone_descriptor", wizard_defaults.tone_descriptor),
            narration_style=_str_or_default(wd, "narration_style", wizard_defaults.narration_style),
            art_style=_str_or_default(wd, "art_style", wizard_defaults.art_style),
            target_major_beats=target_beats,
            reader_level=str(reader_level)
            if isinstance(reader_level, str)
            else wizard_defaults.reader_level,  # pyright: ignore[reportArgumentType]
            pacing=_str_or_default(wd, "pacing", wizard_defaults.pacing),
            characters=_str_or_default(wd, "characters", wizard_defaults.characters),
            save_to_catalog=bool(wd.get("save_to_catalog", wizard_defaults.save_to_catalog)),
        )

    tts = app_state.read_tts_prefs()
    if body.tts_prefs is not None:
        tp = body.tts_prefs
        tts = TTSPrefs(
            provider=_str_or_default(tp, "provider", tts.provider),
            api_key=_str_or_default(tp, "api_key", tts.api_key),
            voice=_str_or_default(tp, "voice", tts.voice),
            auto_read=bool(tp.get("auto_read", tts.auto_read)),
            auto_read_recap=bool(tp.get("auto_read_recap", tts.auto_read_recap)),
        )

    app_state.write_all_settings(
        image_prefs=image_prefs,
        text_prefs=text_prefs,
        wizard_defaults=wizard_defaults,
        character_image_prefs=char_image_prefs,
        tts_prefs=tts,
        art_enabled_value=body.art_enabled
        if body.art_enabled is not None
        else app_state.art_enabled(),
        prefetch_enabled_value=body.prefetch_enabled
        if body.prefetch_enabled is not None
        else app_state.prefetch_enabled(),
        prefetch_images_enabled_value=body.prefetch_images_enabled
        if body.prefetch_images_enabled is not None
        else app_state.prefetch_images_enabled(),
        image_streaming_enabled_value=body.image_streaming_enabled
        if body.image_streaming_enabled is not None
        else app_state.image_streaming_enabled(),
        llm_cache_enabled_value=body.llm_cache_enabled
        if body.llm_cache_enabled is not None
        else app_state.llm_cache_enabled(),
        auto_select_value=body.auto_select_enabled
        if body.auto_select_enabled is not None
        else app_state.auto_select_enabled(),
        auto_open_art_value=body.auto_open_art_enabled
        if body.auto_open_art_enabled is not None
        else app_state.auto_open_art_enabled(),
        auto_recap_value=body.auto_recap_enabled
        if body.auto_recap_enabled is not None
        else app_state.auto_recap_enabled(),
        resume_recap_value=body.resume_recap_enabled
        if body.resume_recap_enabled is not None
        else app_state.resume_recap_enabled(),
        recap_interval_value=body.recap_interval
        if body.recap_interval is not None
        else app_state.recap_interval(),
        graphics_mode_value=body.graphics_mode
        if body.graphics_mode is not None
        else app_state.read_graphics_mode(),
    )

    return await get_settings()
