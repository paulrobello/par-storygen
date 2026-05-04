"""Google Gemini image provider via the ``google-genai`` SDK.

Targets the Nano Banana image-generation models
(``gemini-3.1-flash-image-preview`` default, ``gemini-3-pro-image-preview``
opt-in). Uses ``client.aio.models.generate_content`` for async calls and
passes reference portraits as inline ``types.Part.from_bytes`` entries inside
the ``contents`` list.

Notes:
- Gemini does **not** accept a ``size=`` kwarg the way OpenAI does; the model
  infers aspect ratio from the prompt. We keep the module-level
  :data:`PORTRAIT_SIZE` / :data:`SCENE_SIZE` constants in sync with the OpenAI
  provider so cost-estimation call sites can reuse the same lookup contract.
- Transparency is prompt-only — not an API flag — and not guaranteed. We
  ask for a "Transparent PNG background" in the portrait prompt when
  ``transparent=True`` and otherwise leave it to the model.
- Response part ordering is non-deterministic. We iterate
  ``candidates[0].content.parts`` and return the bytes of the first part
  whose ``inline_data`` is non-None.
- ``config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])``
  is required — without it the SDK can return text-only responses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from storygen.images._prompts import build_portrait_prompt, build_scene_prompt
from storygen.images.base import ReferencePortrait

PORTRAIT_MODEL_DEFAULT = "gemini-3.1-flash-image-preview"
SCENE_MODEL_DEFAULT = "gemini-3.1-flash-image-preview"

# Kept in sync with OpenAI provider constants so pricing/cost-estimation call
# sites treat Gemini the same way — Gemini itself infers aspect ratio from the
# prompt, so these strings never become a ``size=`` kwarg.
PORTRAIT_SIZE = "1024x1024"
SCENE_SIZE = "1024x1024"

# Gemini caps reference images at 14 per request. Silently truncate beyond
# that rather than surfacing a cryptic 400 from the API.
_MAX_REFERENCE_IMAGES = 14


class GeminiImageProvider:
    """Implements :class:`storygen.images.base.ImageProvider` against Gemini."""

    def __init__(
        self,
        *,
        model: str = PORTRAIT_MODEL_DEFAULT,
        api_key: str | None = None,
        base_url: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        """Construct a provider.

        Args:
            model: Gemini model id.
            api_key: Optional explicit API key. If omitted, the SDK picks up
                ``GEMINI_API_KEY`` from the environment.
            base_url: Unused — the Google SDK does not accept OpenAI-style base
                URLs. Accepted for factory-call parity.
            client: Pre-constructed client (tests inject a stub here).
        """
        # ``base_url`` is ignored — accepted for factory-call parity with the
        # OpenAI adapter. Explicit unused reference keeps pyright strict quiet.
        _ = base_url
        self._model = model
        if client is not None:
            self._client = client
        elif api_key:
            self._client = genai.Client(api_key=api_key)
        else:
            self._client = genai.Client()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(genai_errors.APIError),
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
        """Generate a character portrait.

        Wraps ``description`` with full-body framing guidance matching the
        OpenAI provider's portrait shape so downstream scene calls can reuse
        the image as a consistent reference anchor.

        Transparency is prompt-only; the Gemini API has no
        ``background="transparent"`` flag. Reliability is best-effort.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        del reference_image  # reference_image: not supported by this provider, ignored.
        prompt = build_portrait_prompt(
            description,
            transparent=transparent,
            art_style=art_style,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        return _extract_image_bytes(response)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(genai_errors.APIError),
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
        """Generate a scene, optionally anchored by character reference portraits.

        Reference portraits are silently truncated at 14 — the Gemini per-call
        limit.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        refs = reference_portraits[:_MAX_REFERENCE_IMAGES]
        styled_prompt = (
            build_scene_prompt(prompt, art_style=art_style)
            if not refs
            else (
                f"{art_style} style. {prompt}. "
                f"Keep the appearance of the following reference characters exactly as shown: "
                f"{', '.join(ref.name for ref in refs)}."
            )
        )
        # ``contents`` is a heterogenous list of strings and Parts. The SDK's
        # ``ContentListUnion`` is ``list[str | PIL_Image | File | Part]``;
        # because Python ``list`` is invariant, we widen via an explicit
        # annotation that matches the SDK union element type.
        contents: list[str | genai_types.PIL_Image | genai_types.File | genai_types.Part] = [
            styled_prompt
        ]
        contents.extend(
            genai_types.Part.from_bytes(data=ref.data, mime_type="image/png") for ref in refs
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=genai_types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        return _extract_image_bytes(response)


def _extract_image_bytes(response: object) -> bytes:
    """Pull the first inline PNG from a ``generate_content`` response.

    Raises :class:`RuntimeError` if the response has no candidates / parts, or
    if no part carries ``inline_data``.

    The SDK's response model is fully typed, but in practice we also accept
    arbitrary duck-typed stubs here (tests pass ``MagicMock`` instances), so
    we introspect through ``getattr`` and lean on pyright-ignore for the
    partial-unknown noise that introduces.
    """
    candidates: list[object] = getattr(response, "candidates", None) or []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    content = getattr(candidates[0], "content", None)
    parts: list[object] = getattr(content, "parts", None) or []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        data = getattr(inline, "data", None)
        if data:
            return cast(bytes, data)
    raise RuntimeError("Gemini returned no image part")
