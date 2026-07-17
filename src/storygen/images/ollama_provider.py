"""Ollama local image-generation provider.

Ollama ≥0.13.3 exposes an OpenAI-compatible ``/v1/images/generations``
endpoint at ``http://localhost:11434/v1/``. Responses are base64-encoded,
not URL-linked (unlike :mod:`storygen.images.zai_provider`).

**macOS-only as of 2026-04.** Linux / Windows Ollama builds have not yet
shipped image-model support. The provider does not try to detect this —
callers get a connection-refused or 404 from the server.

No reference-image support. Same degradation contract as Z.AI: a non-empty
``reference_portraits`` list fires ``on_ref_loss`` once per provider
instance and the scene is generated from the prompt alone.

Cost: local inference, so zero dollars. See
:func:`storygen.images.pricing.ollama_image_cost`.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from storygen.images._retry import is_retryable as _is_retryable
from storygen.images.base import ReferencePortrait
from storygen.images.prompts import build_portrait_prompt, build_scene_prompt

DEFAULT_BASE_URL = "http://localhost:11434/v1/"
DEFAULT_MODEL = "x/z-image-turbo"

# 1024x1024 is the size Ollama image models (Z-Image Turbo, FLUX.2 Klein) are
# tuned for per their model cards. Kept fixed here; exposing this via config
# is cheap to add later if needed.
IMAGE_SIZE = "1024x1024"

# The Ollama server ignores the API key but ``AsyncOpenAI`` requires a
# non-empty string. Using the documented sentinel.
_SENTINEL_API_KEY = "ollama"


class OllamaImageProvider:
    """Implements :class:`storygen.images.base.ImageProvider` against Ollama.

    Requires Ollama ≥0.13.3 running locally on the same machine with an
    image-capable model pulled (e.g. ``ollama pull x/z-image-turbo``).
    """

    # ARC-115: Ollama has no reference-image support. Scenes with refs fire
    # ``on_ref_loss`` and are generated from the prompt alone.
    supports_reference_images: bool = False

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        on_ref_loss: Callable[[], None] | None = None,
    ) -> None:
        """Construct a provider.

        Args:
            model: Ollama image model tag.
            api_key: Ignored — Ollama's OpenAI-compat server doesn't
                authenticate. Accepted for factory-call parity.
            base_url: Override the localhost default; usually unnecessary.
            client: Pre-constructed ``AsyncOpenAI`` client (tests inject).
            on_ref_loss: Fired at least once per provider instance if
                ``generate_scene`` is called with references (may fire more
                than once under rare concurrent-call races).
        """
        # ``api_key`` is ignored; explicit unused reference keeps pyright happy.
        _ = api_key
        self._model = model
        self._on_ref_loss = on_ref_loss
        self._ref_loss_fired = False
        if client is not None:
            self._client = client
        else:
            self._client = AsyncOpenAI(
                api_key=_SENTINEL_API_KEY,
                base_url=base_url or DEFAULT_BASE_URL,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def generate_portrait(
        self,
        description: str,
        *,
        transparent: bool,
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
        reference_image: bytes | None = None,
    ) -> bytes:
        """Generate a character portrait via Ollama.

        Transparency is prompt-only and best-effort. Local image models
        (Z-Image Turbo, FLUX.2 Klein) currently honour transparent-background
        prompts inconsistently.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        del reference_image  # reference_image: not supported by this provider, ignored.
        prompt = build_portrait_prompt(
            description,
            transparent=transparent,
            art_style=art_style,
        )
        resp = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=IMAGE_SIZE,
            response_format="b64_json",
        )
        return _decode_b64(resp)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def generate_scene(
        self,
        prompt: str,
        *,
        reference_portraits: list[ReferencePortrait],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        """Generate a scene via Ollama. References, if any, are dropped.

        See class docstring for ``on_ref_loss`` semantics.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        if reference_portraits and not self._ref_loss_fired:
            self._ref_loss_fired = True
            if self._on_ref_loss is not None:
                self._on_ref_loss()
        styled_prompt = build_scene_prompt(prompt, art_style=art_style)
        resp = await self._client.images.generate(
            model=self._model,
            prompt=styled_prompt,
            size=IMAGE_SIZE,
            response_format="b64_json",
        )
        return _decode_b64(resp)


def _decode_b64(response: object) -> bytes:
    """Decode the base64 payload of an Ollama image response.

    Ollama always returns base64 (there is no remote URL to fall back to, as
    the server is local). Missing payload is treated as a hard error rather
    than silently empty bytes.
    """
    data: list[object] = getattr(response, "data", None) or []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if not data:
        raise RuntimeError("Ollama returned no image data")
    b64 = getattr(data[0], "b64_json", None)
    if not b64:
        raise RuntimeError("Ollama returned no image data")
    return base64.b64decode(b64)
