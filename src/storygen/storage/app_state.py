"""Per-user application state — small JSON file under XDG_CONFIG_HOME.

Distinct from ``storygen.config`` which loads provider/model settings from env
vars; this module persists *runtime* state across launches (e.g. which story
was opened most recently so ``--resume`` knows where to pick up).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast, get_args

from storygen.core.models import ReaderLevel
from storygen.storage import paths

_ALLOWED_READER_LEVELS: frozenset[str] = frozenset(get_args(ReaderLevel))

_STATE_FILENAME = "state.json"

# Simple 1-second TTL cache for read_app_state().  The pipeline calls
# flag accessors (art_enabled, prefetch_enabled, …) on every stage inside
# potentially concurrent prefetch tasks — without caching, each call opens
# and parses the JSON file.  A 1-second window preserves the "live read"
# contract for Settings toggles while collapsing the hot-path reads into
# a single I/O per second.  write_app_state() clears the cache so the
# next read sees the fresh value immediately.
_STATE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATE_CACHE_TTL: float = 1.0

DEFAULT_ART_STYLE: str = "children's story book"
DEFAULT_TONE_PRESET: str = "serious"
DEFAULT_NARRATION_STYLE: str = "third_person"

DEFAULT_TARGET_MAJOR_BEATS: int = 10
MIN_TARGET_MAJOR_BEATS: int = 2
MAX_TARGET_MAJOR_BEATS: int = 30

DEFAULT_READER_LEVEL: ReaderLevel = "ages_11_15"

DEFAULT_TEXT_PROVIDER: str = "openai"
DEFAULT_TEXT_MODEL: str = "gpt-4o-mini"

# UI-facing (label, provider-id) pairs — consumed by the Settings screen Select widget.
# Immutable tuple-of-tuples so callers can't mutate the module's source of truth.
PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI", "openai"),
    ("OpenRouter", "openrouter"),
    ("Ollama (local)", "ollama"),
)

# Per-provider curated model suggestions for the Settings screen.
# Wrapped in MappingProxyType so the top-level dict is read-only; list values
# are still mutable but callers shouldn't need to touch them.
SUGGESTED_MODELS: MappingProxyType[str, list[str]] = MappingProxyType(
    {
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
        "openrouter": [
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "ollama": ["llama3.3:70b", "qwen2.5:32b-instruct"],
    }
)

_ALLOWED_PROVIDERS: frozenset[str] = frozenset(pid for _, pid in PROVIDER_CHOICES)

DEFAULT_IMAGE_PROVIDER: str = "openai"
DEFAULT_IMAGE_MODEL: str = "gpt-image-2"
DEFAULT_CHARACTER_IMAGE_PROVIDER: str = "openai"
DEFAULT_CHARACTER_IMAGE_MODEL: str = "gpt-image-1.5"

# UI-facing (label, provider-id) pairs — consumed by the Settings screen Select widget.
IMAGE_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI gpt-image", "openai"),
    ("Google Gemini (Nano Banana 2/Pro)", "gemini"),
    ("Z.AI GLM-image", "zai"),
    ("Ollama (local, macOS-only)", "ollama"),
)

# Per-provider curated image-model suggestions for the Settings screen.
SUGGESTED_IMAGE_MODELS: MappingProxyType[str, tuple[str, ...]] = MappingProxyType(
    {
        "openai": ("gpt-image-2", "gpt-image-1.5", "gpt-image-1"),
        "gemini": ("gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"),
        "zai": ("glm-image",),
        "ollama": ("x/z-image-turbo", "x/flux2-klein:4b", "x/flux2-klein:9b"),
    }
)

# Which providers support reference-image inputs (portrait-anchored scene gen).
PROVIDER_SUPPORTS_REFS: frozenset[str] = frozenset({"openai", "gemini"})

# Per-provider environment variable name that supplies the provider's API key.
# None means the provider needs no auth (Ollama local). STORYGEN_IMAGE_API_KEY
# continues to override any of these (existing env pattern on the image side).
IMAGE_API_KEY_ENV: MappingProxyType[str, str | None] = MappingProxyType(
    {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "zai": "ZAI_API_KEY",
        "ollama": None,
    }
)

_ALLOWED_IMAGE_PROVIDERS: frozenset[str] = frozenset(pid for _, pid in IMAGE_PROVIDER_CHOICES)

DEFAULT_TTS_PROVIDER: str = "openai"
DEFAULT_TTS_VOICE: str = ""
DEFAULT_TTS_AUTO_READ: bool = False

TTS_PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("OpenAI", "openai"),
    ("ElevenLabs", "elevenlabs"),
    ("Deepgram", "deepgram"),
    ("Google Gemini", "gemini"),
    ("Kokoro (local)", "kokoro-onnx"),
)

TTS_API_KEY_ENV: MappingProxyType[str, str | None] = MappingProxyType(
    {
        "openai": "OPENAI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "kokoro-onnx": None,
    }
)

_ALLOWED_TTS_PROVIDERS: frozenset[str] = frozenset(pid for _, pid in TTS_PROVIDER_CHOICES)


def _clamp_target_beats(value: object) -> int:
    """Coerce ``value`` to an int and clamp into [MIN, MAX].

    Falls back to ``DEFAULT_TARGET_MAJOR_BEATS`` if the value can't be coerced.
    """
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TARGET_MAJOR_BEATS
    return max(MIN_TARGET_MAJOR_BEATS, min(MAX_TARGET_MAJOR_BEATS, n))


@dataclass(frozen=True)
class ProviderPrefs:
    """Persisted text-provider preferences (Settings screen → state.json)."""

    provider: str = DEFAULT_TEXT_PROVIDER  # one of PROVIDER_CHOICES ids
    model: str = DEFAULT_TEXT_MODEL
    base_url: str = ""  # empty → provider factory picks its default


@dataclass(frozen=True)
class ImageProviderPrefs:
    """Persisted image-provider preferences (Settings screen → state.json).

    ``fallback_provider``/``fallback_model`` configure the router's fallback
    target for transient primary-provider failures (added in Phase 3). Empty
    strings mean "no fallback."
    """

    provider: str = DEFAULT_IMAGE_PROVIDER  # one of IMAGE_PROVIDER_CHOICES ids
    model: str = DEFAULT_IMAGE_MODEL
    base_url: str = ""  # empty → factory picks the provider's default URL
    fallback_provider: str = ""  # "" = no fallback
    fallback_model: str = ""  # "" = use SUGGESTED_IMAGE_MODELS[fallback_provider][0]


@dataclass(frozen=True)
class CharacterImageProviderPrefs:
    """Persisted character-portrait image-provider preferences."""

    provider: str = DEFAULT_CHARACTER_IMAGE_PROVIDER  # one of IMAGE_PROVIDER_CHOICES ids
    model: str = DEFAULT_CHARACTER_IMAGE_MODEL
    base_url: str = ""  # empty → factory picks the provider's default URL


@dataclass(frozen=True)
class WizardDefaults:
    """Persisted defaults that pre-fill the new-story wizard widgets."""

    theme: str = ""
    tone_preset: str = DEFAULT_TONE_PRESET
    tone_descriptor: str = ""  # only used when preset == "custom"
    narration_style: str = DEFAULT_NARRATION_STYLE
    art_style: str = DEFAULT_ART_STYLE
    target_major_beats: int = DEFAULT_TARGET_MAJOR_BEATS
    reader_level: ReaderLevel = DEFAULT_READER_LEVEL
    characters: str = ""
    save_to_catalog: bool = True


@dataclass(frozen=True)
class TTSPrefs:
    """Persisted TTS preferences (Settings screen → state.json)."""

    provider: str = DEFAULT_TTS_PROVIDER  # one of TTS_PROVIDER_CHOICES ids
    api_key: str = ""  # blank → fall back to provider env var
    voice: str = ""  # blank → use provider default
    auto_read: bool = DEFAULT_TTS_AUTO_READ


def _state_file() -> Path:
    return paths.config_root() / _STATE_FILENAME


def read_app_state() -> dict[str, Any]:
    """Return the persisted app state, or an empty dict if nothing is stored.

    Results are cached for up to :data:`_STATE_CACHE_TTL` seconds so the
    pipeline's per-stage flag accessors (``art_enabled``, ``prefetch_enabled``,
    etc.) don't each open the JSON file.  Writes clear the cache immediately so
    Settings toggles take effect on the very next read.

    The cache key includes the resolved file path so that tests that
    monkeypatch ``XDG_CONFIG_HOME`` get a fresh read rather than a stale
    hit from the real config directory.
    """
    now = time.monotonic()
    path = _state_file()
    # Include file mtime in cache key so direct writes (e.g. tests) that bypass
    # write_app_state() are detected without waiting for the TTL to expire.
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = f"{path!s}:{mtime}"
    cached = _STATE_CACHE.get(cache_key)
    if cached is not None:
        ts, value = cached
        if now - ts < _STATE_CACHE_TTL:
            return value

    try:
        with open(path, encoding="utf-8") as f:
            data: object = json.load(f)
    except FileNotFoundError:
        result: dict[str, Any] = {}
        _STATE_CACHE[cache_key] = (now, result)
        return result
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable — treat as empty, don't crash startup.
        result = {}
        _STATE_CACHE[cache_key] = (now, result)
        return result
    if not isinstance(data, dict):
        result = {}
        _STATE_CACHE[cache_key] = (now, result)
        return result
    # Narrow keys to str — top-level JSON keys are always strings.
    result = {str(k): v for k, v in data.items()}  # type: ignore[redundant-cast]
    _STATE_CACHE[cache_key] = (now, result)
    return result


def write_app_state(data: dict[str, Any]) -> None:
    """Persist ``data`` atomically under XDG_CONFIG_HOME.

    Clears the read cache so the next :func:`read_app_state` call sees the
    freshly written values without waiting for the TTL to expire.
    """
    path = paths.config_root() / _STATE_FILENAME
    paths.config_root().mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    # Evict any cache entry for this path (keyed with old mtime).
    path_prefix = str(path) + ":"
    for k in list(_STATE_CACHE):
        if k.startswith(path_prefix):
            del _STATE_CACHE[k]


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
    if isinstance(value, str) and value in _ALLOWED_READER_LEVELS:
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
        target_major_beats=_clamp_target_beats(target_raw),
        reader_level=coerce_reader_level(raw.get("reader_level")),
        characters=str(raw.get("characters", "")),
        save_to_catalog=bool(raw.get("save_to_catalog", True)),
    )


def write_wizard_defaults(defaults: WizardDefaults) -> None:
    """Persist ``defaults`` to app state for the next wizard launch."""
    state = read_app_state()
    state["wizard_defaults"] = _serialize_wizard_defaults(defaults)
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
    if provider not in _ALLOWED_PROVIDERS:
        return ProviderPrefs()
    model = str(raw.get("model", DEFAULT_TEXT_MODEL))
    base_url = str(raw.get("base_url", ""))
    return ProviderPrefs(provider=provider, model=model, base_url=base_url)


def write_provider_prefs(prefs: ProviderPrefs) -> None:
    """Persist ``prefs`` to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["provider_prefs"] = _serialize_text_prefs(prefs)
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
    if provider not in _ALLOWED_IMAGE_PROVIDERS:
        return ImageProviderPrefs()
    model = str(raw.get("model", DEFAULT_IMAGE_MODEL))
    base_url = str(raw.get("base_url", ""))
    fallback_provider = str(raw.get("fallback_provider", ""))
    fallback_model = str(raw.get("fallback_model", ""))
    # Guard against ghost fallback state: unknown fallback resets fallback_model
    # too, and an empty fallback_provider always implies empty fallback_model.
    if fallback_provider and fallback_provider not in _ALLOWED_IMAGE_PROVIDERS:
        fallback_provider = ""
        fallback_model = ""
    if not fallback_provider:
        fallback_model = ""
    return ImageProviderPrefs(
        provider=provider,
        model=model,
        base_url=base_url,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
    )


def write_image_provider_prefs(prefs: ImageProviderPrefs) -> None:
    """Persist ``prefs`` to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["image_provider_prefs"] = _serialize_image_prefs(prefs)
    write_app_state(state)


def read_character_image_provider_prefs() -> CharacterImageProviderPrefs:
    """Load persisted character-image prefs; fall back to defaults on any problem."""
    raw_obj: object = read_app_state().get("character_image_provider_prefs")
    if not isinstance(raw_obj, dict):
        return CharacterImageProviderPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_CHARACTER_IMAGE_PROVIDER))
    if provider not in _ALLOWED_IMAGE_PROVIDERS:
        return CharacterImageProviderPrefs()
    model = str(raw.get("model", DEFAULT_CHARACTER_IMAGE_MODEL))
    base_url = str(raw.get("base_url", ""))
    return CharacterImageProviderPrefs(provider=provider, model=model, base_url=base_url)


def write_character_image_provider_prefs(prefs: CharacterImageProviderPrefs) -> None:
    """Persist character-image prefs to app state for future ``load_config()`` calls."""
    state = read_app_state()
    state["character_image_provider_prefs"] = _serialize_character_image_prefs(prefs)
    write_app_state(state)


def _serialize_character_image_prefs(prefs: CharacterImageProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by character-image prefs writers."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
    }


def _serialize_image_prefs(prefs: ImageProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by both ``write_image_provider_prefs`` and
    ``write_all_settings`` — must stay byte-identical between them."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
        "fallback_provider": prefs.fallback_provider,
        "fallback_model": prefs.fallback_model,
    }


def _serialize_text_prefs(prefs: ProviderPrefs) -> dict[str, Any]:
    """Serialization shape used by both ``write_provider_prefs`` and
    ``write_all_settings`` — must stay byte-identical between them."""
    return {
        "provider": prefs.provider,
        "model": prefs.model,
        "base_url": prefs.base_url,
    }


def read_tts_prefs() -> TTSPrefs:
    """Load persisted TTS prefs; fall back to defaults on any problem."""
    raw_obj: object = read_app_state().get("tts_prefs")
    if not isinstance(raw_obj, dict):
        return TTSPrefs()
    raw: dict[str, Any] = {str(k): v for k, v in raw_obj.items()}  # type: ignore[redundant-cast]
    provider = str(raw.get("provider", DEFAULT_TTS_PROVIDER))
    if provider not in _ALLOWED_TTS_PROVIDERS:
        return TTSPrefs()
    return TTSPrefs(
        provider=provider,
        api_key=str(raw.get("api_key", "")),
        voice=str(raw.get("voice", "")),
        auto_read=bool(raw.get("auto_read", DEFAULT_TTS_AUTO_READ)),
    )


def _serialize_tts_prefs(prefs: TTSPrefs) -> dict[str, Any]:
    """Serialization shape for TTSPrefs."""
    return {
        "provider": prefs.provider,
        "api_key": prefs.api_key,
        "voice": prefs.voice,
        "auto_read": prefs.auto_read,
    }


def _serialize_wizard_defaults(defaults: WizardDefaults) -> dict[str, Any]:
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
    state["image_provider_prefs"] = _serialize_image_prefs(image_prefs)
    if character_image_prefs is not None:
        state["character_image_provider_prefs"] = _serialize_character_image_prefs(
            character_image_prefs
        )
    state["provider_prefs"] = _serialize_text_prefs(text_prefs)
    state["wizard_defaults"] = _serialize_wizard_defaults(wizard_defaults)
    if tts_prefs is not None:
        state["tts_prefs"] = _serialize_tts_prefs(tts_prefs)
    state["art_enabled"] = bool(art_enabled_value)
    state["prefetch_enabled"] = bool(prefetch_enabled_value)
    state["prefetch_images"] = bool(prefetch_images_enabled_value)
    state["image_streaming"] = bool(image_streaming_enabled_value)
    state["llm_cache"] = bool(llm_cache_enabled_value)
    state["auto_select"] = bool(auto_select_value)
    write_app_state(state)
