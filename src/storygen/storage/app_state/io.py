"""Atomic JSON I/O and reader/writer helpers for app state.

All persisted-state accessors live here: the read/write primitives (with a
1-second TTL cache), per-section readers/writers, serializers, and the
:func:`write_all_settings` atomic multi-section writer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

from storygen.core.models import ReaderLevel
from storygen.storage import paths
from storygen.storage.app_state.defaults import (
    ALLOWED_GRAPHICS_MODES,
    ALLOWED_IMAGE_PROVIDERS,
    ALLOWED_PROVIDERS,
    ALLOWED_READER_LEVELS,
    ALLOWED_TTS_PROVIDERS,
    DEFAULT_ART_STYLE,
    DEFAULT_AUTO_RECAP,
    DEFAULT_CHARACTER_IMAGE_MODEL,
    DEFAULT_CHARACTER_IMAGE_PROVIDER,
    DEFAULT_GRAPHICS_MODE,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_NARRATION_STYLE,
    DEFAULT_PACING,
    DEFAULT_READER_LEVEL,
    DEFAULT_RECAP_INTERVAL,
    DEFAULT_RESUME_RECAP,
    DEFAULT_TARGET_MAJOR_BEATS,
    DEFAULT_TEXT_MODEL,
    DEFAULT_TEXT_PROVIDER,
    DEFAULT_TONE_PRESET,
    DEFAULT_TTS_AUTO_READ,
    DEFAULT_TTS_AUTO_READ_RECAP,
    DEFAULT_TTS_PROVIDER,
)
from storygen.storage.app_state.models import (
    CharacterImageProviderPrefs,
    ImageProviderPrefs,
    ProviderPrefs,
    TTSPrefs,
    WizardDefaults,
    clamp_target_beats,
)

STATE_FILENAME = "state.json"

# Simple 1-second TTL cache for read_app_state().  The pipeline calls
# flag accessors (art_enabled, prefetch_enabled, …) on every stage inside
# potentially concurrent prefetch tasks — without caching, each call opens
# and parses the JSON file.  A 1-second window preserves the "live read"
# contract for Settings toggles while collapsing the hot-path reads into
# a single I/O per second.  write_app_state() clears the cache so the
# next read sees the fresh value immediately.
STATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
STATE_CACHE_TTL: float = 1.0


def state_file_path() -> Path:
    return paths.config_root() / STATE_FILENAME


def read_app_state() -> dict[str, Any]:
    """Return the persisted app state, or an empty dict if nothing is stored.

    Results are cached for up to :data:`STATE_CACHE_TTL` seconds so the
    pipeline's per-stage flag accessors (``art_enabled``, ``prefetch_enabled``,
    etc.) don't each open the JSON file.  Writes clear the cache immediately so
    Settings toggles take effect on the very next read.

    The cache key includes the resolved file path so that tests that
    monkeypatch ``XDG_CONFIG_HOME`` get a fresh read rather than a stale
    hit from the real config directory.
    """
    now = time.monotonic()
    path = state_file_path()
    # Include file mtime in cache key so direct writes (e.g. tests) that bypass
    # write_app_state() are detected without waiting for the TTL to expire.
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = f"{path!s}:{mtime}"
    cached = STATE_CACHE.get(cache_key)
    if cached is not None:
        ts, value = cached
        if now - ts < STATE_CACHE_TTL:
            return value

    try:
        with open(path, encoding="utf-8") as f:
            data: object = json.load(f)
    except FileNotFoundError:
        result: dict[str, Any] = {}
        STATE_CACHE[cache_key] = (now, result)
        return result
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable — treat as empty, don't crash startup.
        result = {}
        STATE_CACHE[cache_key] = (now, result)
        return result
    if not isinstance(data, dict):
        result = {}
        STATE_CACHE[cache_key] = (now, result)
        return result
    # Narrow keys to str — top-level JSON keys are always strings.
    result = {str(k): v for k, v in data.items()}  # type: ignore[redundant-cast]
    STATE_CACHE[cache_key] = (now, result)
    return result


def write_app_state(data: dict[str, Any]) -> None:
    """Persist ``data`` atomically under XDG_CONFIG_HOME.

    Clears the read cache so the next :func:`read_app_state` call sees the
    freshly written values without waiting for the TTL to expire.

    SEC-005: the temp file is chmod'd to ``0o600`` before ``os.replace`` so the
    persisted state (which carries provider API keys) is never world-readable,
    matching the file-mode hardening already applied to library files.
    """
    path = paths.config_root() / STATE_FILENAME
    paths.config_root().mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # SEC-005: restrictive mode before the file is renamed into place. The
    # umask might leave group/world bits set; chmod ensures owner-only.
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    # Evict any cache entry for this path (keyed with old mtime).
    path_prefix = str(path) + ":"
    for k in list(STATE_CACHE):
        if k.startswith(path_prefix):
            del STATE_CACHE[k]


def remember_last_story(game_id: str) -> None:
    """Mark ``game_id`` as the most recently opened story."""
    state = read_app_state()
    state["last_story_id"] = game_id
    write_app_state(state)


def last_story_id() -> str | None:
    """Return the most recently opened story id, or None if none recorded."""
    value = read_app_state().get("last_story_id")
    return value if isinstance(value, str) else None


def coerce_reader_level(value: object) -> ReaderLevel:
    """Coerce an arbitrary persisted value to a valid ``ReaderLevel``.

    Falls back to ``DEFAULT_READER_LEVEL`` on any unrecognised value so that
    an old or corrupt ``state.json`` never produces an invalid type.
    """
    if isinstance(value, str) and value in ALLOWED_READER_LEVELS:
        return cast(ReaderLevel, value)
    return DEFAULT_READER_LEVEL


def read_wizard_defaults() -> WizardDefaults:
    """Load persisted wizard defaults from app state, falling back to constants."""
    raw_obj: object = read_app_state().get("wizard_defaults")
    if not isinstance(raw_obj, dict):
        return WizardDefaults()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    target_raw = raw.get("target_major_beats", DEFAULT_TARGET_MAJOR_BEATS)
    return WizardDefaults(
        theme=str(raw.get("theme", "")),
        tone_preset=str(raw.get("tone_preset", DEFAULT_TONE_PRESET)),
        tone_descriptor=str(raw.get("tone_descriptor", "")),
        narration_style=str(raw.get("narration_style", DEFAULT_NARRATION_STYLE)),
        art_style=str(raw.get("art_style", DEFAULT_ART_STYLE)),
        target_major_beats=clamp_target_beats(target_raw),
        reader_level=coerce_reader_level(raw.get("reader_level")),
        pacing=str(raw.get("pacing", DEFAULT_PACING)),
        characters=str(raw.get("characters", "")),
        save_to_catalog=bool(raw.get("save_to_catalog", True)),
    )


def write_wizard_defaults(defaults: WizardDefaults) -> None:
    """Persist ``defaults`` to app state for the next wizard launch."""
    state = read_app_state()
    state["wizard_defaults"] = serialize_wizard_defaults(defaults)
    write_app_state(state)


def art_enabled() -> bool:
    """Whether image generation is allowed app-wide. Defaults to True."""
    raw = read_app_state().get("art_enabled", True)
    return bool(raw)


def set_art_enabled(value: bool) -> None:
    """Toggle global image-generation behavior."""
    state = read_app_state()
    state["art_enabled"] = bool(value)
    write_app_state(state)


def prefetch_enabled() -> bool:
    """Return whether branch prefetch is enabled. Defaults to False (opt-in)."""
    state = read_app_state()
    return bool(state.get("prefetch_enabled", False))


def auto_select_enabled() -> bool:
    """Return whether auto-select story choices is enabled. Defaults to False."""
    state = read_app_state()
    return bool(state.get("auto_select", False))


def set_prefetch_enabled(value: bool) -> None:
    """Persist the prefetch-enabled flag."""
    state = read_app_state()
    state["prefetch_enabled"] = bool(value)
    write_app_state(state)


def read_graphics_mode() -> str:
    """Return the terminal image rendering protocol. Defaults to ``"auto"``."""
    val = read_app_state().get("graphics_mode")
    if not isinstance(val, str) or val not in ALLOWED_GRAPHICS_MODES:
        return DEFAULT_GRAPHICS_MODE
    return val


def prefetch_images_enabled() -> bool:
    """Return whether prefetched beats should also generate scene images.

    Independent of prefetch_enabled — but Settings UI gates the toggle.
    Defaults to False (opt-in) because image gen is expensive.
    """
    state = read_app_state()
    return bool(state.get("prefetch_images", False))


def set_prefetch_images_enabled(value: bool) -> None:
    """Persist the prefetch-images flag."""
    state = read_app_state()
    state["prefetch_images"] = bool(value)
    write_app_state(state)


def image_streaming_enabled() -> bool:
    """Return whether OpenAI streaming partial-image previews are enabled.

    Default False (opt-in, adds ~5% to OpenAI image cost; only OpenAI
    supports it — flag is a no-op for other providers).
    """
    return bool(read_app_state().get("image_streaming", False))


def set_image_streaming_enabled(value: bool) -> None:
    """Persist the image-streaming flag."""
    state = read_app_state()
    state["image_streaming"] = bool(value)
    write_app_state(state)


def llm_cache_enabled() -> bool:
    """Return whether raw LLM exchanges should be dumped to sidecar files.

    Default False. Debug/dev feature — every agent call (beat, illustration,
    summary, blurb) produces a ~4-8KB JSON file keyed by (node_id, agent_name)
    under ``$XDG_DATA_HOME/storygen/games/<save-id>/llm/``. Flag read live at
    each decision point so toggling Settings takes effect immediately.
    """
    return bool(read_app_state().get("llm_cache", False))


def set_llm_cache_enabled(value: bool) -> None:
    """Persist the LLM cache flag."""
    state = read_app_state()
    state["llm_cache"] = bool(value)
    write_app_state(state)


def set_auto_select_enabled(value: bool) -> None:
    """Persist the auto-select flag."""
    state = read_app_state()
    state["auto_select"] = bool(value)
    write_app_state(state)


def auto_open_art_enabled() -> bool:
    """Whether to auto-open full-res images in the system viewer when generated.

    Applies to scene illustrations and character portraits. Default False.
    """
    return bool(read_app_state().get("auto_open_art", False))


def set_auto_open_art_enabled(value: bool) -> None:
    """Persist the auto-open-art flag."""
    state = read_app_state()
    state["auto_open_art"] = bool(value)
    write_app_state(state)


def auto_recap_enabled() -> bool:
    """Return whether auto-recap is enabled (default: False)."""
    return bool(read_app_state().get("auto_recap", DEFAULT_AUTO_RECAP))


def set_auto_recap(enabled: bool) -> None:
    """Set auto-recap enabled flag."""
    state = read_app_state()
    state["auto_recap"] = bool(enabled)
    write_app_state(state)


def resume_recap_enabled() -> bool:
    """Return whether to show a recap when resuming a story with progress."""
    return bool(read_app_state().get("resume_recap", DEFAULT_RESUME_RECAP))


def set_resume_recap(enabled: bool) -> None:
    """Set resume-recap enabled flag."""
    state = read_app_state()
    state["resume_recap"] = bool(enabled)
    write_app_state(state)


def recap_interval() -> int:
    """Return auto-recap interval in major beats (default: 3)."""
    raw = read_app_state().get("recap_interval", DEFAULT_RECAP_INTERVAL)
    try:
        return max(1, int(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_RECAP_INTERVAL


def set_recap_interval(interval: int) -> None:
    """Set auto-recap interval."""
    state = read_app_state()
    state["recap_interval"] = max(1, interval)
    write_app_state(state)


def read_provider_prefs() -> ProviderPrefs:
    """Load persisted text-provider prefs; fall back to defaults on any problem.

    Unknown provider strings, missing keys, and corrupt state all return
    ``ProviderPrefs()`` silently — consistent with ``read_app_state``'s
    tolerance of bad JSON.
    """
    raw_obj: object = read_app_state().get("provider_prefs")
    if not isinstance(raw_obj, dict):
        return ProviderPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_TEXT_PROVIDER))
    if provider not in ALLOWED_PROVIDERS:
        return ProviderPrefs()
    model = str(raw.get("model", DEFAULT_TEXT_MODEL))
    base_url = str(raw.get("base_url", ""))
    return ProviderPrefs(
        provider=provider, model=model, base_url=base_url, api_key=str(raw.get("api_key", ""))
    )


def write_provider_prefs(prefs: ProviderPrefs) -> None:
    """Persist ``prefs`` to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["provider_prefs"] = serialize_text_prefs(prefs)
    write_app_state(state)


def read_image_provider_prefs() -> ImageProviderPrefs:
    """Load persisted image-provider prefs; fall back to defaults on any problem.

    Unknown primary ``provider`` values reset the whole record to defaults.
    Unknown ``fallback_provider`` values are reset to ``""`` (and
    ``fallback_model`` is force-cleared to avoid ghost state).
    """
    raw_obj: object = read_app_state().get("image_provider_prefs")
    if not isinstance(raw_obj, dict):
        return ImageProviderPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_IMAGE_PROVIDER))
    if provider not in ALLOWED_IMAGE_PROVIDERS:
        return ImageProviderPrefs()
    model = str(raw.get("model", DEFAULT_IMAGE_MODEL))
    base_url = str(raw.get("base_url", ""))
    fallback_provider = str(raw.get("fallback_provider", ""))
    fallback_model = str(raw.get("fallback_model", ""))
    # Guard against ghost fallback state: unknown fallback resets fallback_model
    # too, and an empty fallback_provider always implies empty fallback_model.
    if fallback_provider and fallback_provider not in ALLOWED_IMAGE_PROVIDERS:
        fallback_provider = ""
        fallback_model = ""
    if not fallback_provider:
        fallback_model = ""
    return ImageProviderPrefs(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=str(raw.get("api_key", "")),
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
    )


def write_image_provider_prefs(prefs: ImageProviderPrefs) -> None:
    """Persist ``prefs`` to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["image_provider_prefs"] = serialize_image_prefs(prefs)
    write_app_state(state)


def read_character_image_provider_prefs() -> CharacterImageProviderPrefs:
    """Load persisted character-image prefs; fall back to defaults on any problem."""
    raw_obj: object = read_app_state().get("character_image_provider_prefs")
    if not isinstance(raw_obj, dict):
        return CharacterImageProviderPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_CHARACTER_IMAGE_PROVIDER))
    if provider not in ALLOWED_IMAGE_PROVIDERS:
        return CharacterImageProviderPrefs()
    model = str(raw.get("model", DEFAULT_CHARACTER_IMAGE_MODEL))
    base_url = str(raw.get("base_url", ""))
    return CharacterImageProviderPrefs(
        provider=provider, model=model, base_url=base_url, api_key=str(raw.get("api_key", ""))
    )


def write_character_image_provider_prefs(prefs: CharacterImageProviderPrefs) -> None:
    """Persist character-image prefs to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["character_image_provider_prefs"] = serialize_character_image_prefs(prefs)
    write_app_state(state)


def serialize_character_image_prefs(prefs: CharacterImageProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by character-image prefs writers."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
        "api_key": prefs.api_key,
    }


def serialize_image_prefs(prefs: ImageProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by both ``write_image_provider_prefs`` and
    ``write_all_settings`` — must stay byte-identical between them."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
        "api_key": prefs.api_key,
        "fallback_provider": prefs.fallback_provider,
        "fallback_model": prefs.fallback_model,
    }


def serialize_text_prefs(prefs: ProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by both ``write_provider_prefs`` and
    ``write_all_settings`` — must stay byte-identical between them."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
        "api_key": prefs.api_key,
    }


def read_tts_prefs() -> TTSPrefs:
    """Load persisted TTS prefs; fall back to defaults on any problem."""
    raw_obj: object = read_app_state().get("tts_prefs")
    if not isinstance(raw_obj, dict):
        return TTSPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_TTS_PROVIDER))
    if provider not in ALLOWED_TTS_PROVIDERS:
        return TTSPrefs()
    return TTSPrefs(
        provider=provider,
        api_key=str(raw.get("api_key", "")),
        voice=str(raw.get("voice", "")),
        auto_read=bool(raw.get("auto_read", DEFAULT_TTS_AUTO_READ)),
        auto_read_recap=bool(raw.get("auto_read_recap", DEFAULT_TTS_AUTO_READ_RECAP)),
    )


def serialize_tts_prefs(prefs: TTSPrefs) -> dict[str, Any]:
    """Serialization shape for TTSPrefs."""
    return {
        "provider": prefs.provider,
        "api_key": prefs.api_key,
        "voice": prefs.voice,
        "auto_read": prefs.auto_read,
        "auto_read_recap": prefs.auto_read_recap,
    }


def serialize_wizard_defaults(defaults: WizardDefaults) -> dict[str, Any]:
    """Serialization shape used by both ``write_wizard_defaults`` and
    ``write_all_settings`` — must stay byte-identical between them."""
    return {
        "theme": defaults.theme,
        "tone_preset": defaults.tone_preset,
        "tone_descriptor": defaults.tone_descriptor,
        "narration_style": defaults.narration_style,
        "art_style": defaults.art_style,
        "target_major_beats": defaults.target_major_beats,
        "reader_level": defaults.reader_level,
        "pacing": defaults.pacing,
        "characters": defaults.characters,
        "save_to_catalog": defaults.save_to_catalog,
    }


def write_all_settings(
    *,
    image_prefs: ImageProviderPrefs,
    text_prefs: ProviderPrefs,
    wizard_defaults: WizardDefaults,
    character_image_prefs: CharacterImageProviderPrefs | None = None,
    tts_prefs: TTSPrefs | None = None,
    art_enabled_value: bool,
    prefetch_enabled_value: bool,
    prefetch_images_enabled_value: bool,
    image_streaming_enabled_value: bool,
    llm_cache_enabled_value: bool = False,
    auto_select_value: bool = False,
    auto_open_art_value: bool = False,
    auto_recap_value: bool = False,
    resume_recap_value: bool = DEFAULT_RESUME_RECAP,
    recap_interval_value: int = 3,
    graphics_mode_value: str = DEFAULT_GRAPHICS_MODE,
) -> None:
    """Atomic write of all Settings-screen-owned state in a single JSON rewrite.

    The individual writers each do a read-modify-write cycle; calling several of
    them in sequence leaves a window where a crash between calls produces
    partial persistence. This helper reads state once, updates every Settings
    section in memory, and writes once via ``write_app_state``'s atomic
    ``.tmp + os.replace`` mechanism. Unrelated top-level keys (e.g.
    ``last_story_id``) are preserved.
    """
    state = read_app_state()
    state["image_provider_prefs"] = serialize_image_prefs(image_prefs)
    if character_image_prefs is not None:
        state["character_image_provider_prefs"] = serialize_character_image_prefs(
            character_image_prefs
        )
    state["provider_prefs"] = serialize_text_prefs(text_prefs)
    state["wizard_defaults"] = serialize_wizard_defaults(wizard_defaults)
    if tts_prefs is not None:
        state["tts_prefs"] = serialize_tts_prefs(tts_prefs)
    state["art_enabled"] = bool(art_enabled_value)
    state["prefetch_enabled"] = bool(prefetch_enabled_value)
    state["prefetch_images"] = bool(prefetch_images_enabled_value)
    state["image_streaming"] = bool(image_streaming_enabled_value)
    state["llm_cache"] = bool(llm_cache_enabled_value)
    state["auto_select"] = bool(auto_select_value)
    state["auto_open_art"] = bool(auto_open_art_value)
    state["auto_recap"] = bool(auto_recap_value)
    state["resume_recap"] = bool(resume_recap_value)
    state["recap_interval"] = max(1, int(recap_interval_value))
    mode = str(graphics_mode_value)
    state["graphics_mode"] = mode if mode in ALLOWED_GRAPHICS_MODES else DEFAULT_GRAPHICS_MODE
    write_app_state(state)
