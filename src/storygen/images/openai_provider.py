"""OpenAI `gpt-image-2` provider.

Uses `images.generate` for zero-reference renders (portraits and scenes with no
character refs) and `images.edit` when one or more reference portraits are
supplied so the edit endpoint can lock character appearance.  Model-specific
quirks are handled transparently:

- gpt-image-2: no ``background="transparent"`` support (falls back to
  ``"opaque"``), no ``input_fidelity`` param (always high-fidelity).
- gpt-image-1 / 1.5: passes ``background="transparent"`` and
  ``input_fidelity="high"`` as before.
"""

from __future__ import annotations

import base64
import io
import os
from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from storygen.images.base import ReferencePortrait
from storygen.images.constants import (
    OPENAI_PARTIAL_IMAGES,
    PORTRAIT_QUALITY,
    PORTRAIT_SIZE,
    SCENE_QUALITY,
    SCENE_SIZE,
)
from storygen.images.prompts import build_portrait_prompt, build_scene_prompt

# Re-export so existing ``from storygen.images.openai_provider import …``
# call sites continue to work without modification.
__all__ = [
    "OPENAI_PARTIAL_IMAGES",
    "PORTRAIT_QUALITY",
    "PORTRAIT_SIZE",
    "SCENE_QUALITY",
    "SCENE_SIZE",
    "OpenAIImageProvider",
]


class _EditKwargs(TypedDict, total=False):
    input_fidelity: Literal["high"]
    background: Literal["transparent"]


def _env_or_none(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


class OpenAIImageProvider:
    """Implements the `ImageProvider` protocol against OpenAI `gpt-image-2`."""

    # ARC-115: OpenAI supports reference images via ``images.edit`` (both
    # portraits and scenes). This is a static capability flag; consult it
    # instead of hard-coding provider names at call sites.
    supports_reference_images: bool = True

    def __init__(
        self,
        model: str = "gpt-image-2",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._is_v2 = model.startswith("gpt-image-2")
        if client is not None:
            self._client = client
        else:
            resolved_key = (
                api_key
                if api_key
                else _env_or_none("STORYGEN_IMAGE_API_KEY") or _env_or_none("OPENAI_API_KEY") or ""
            )
            if base_url:
                self._client = AsyncOpenAI(api_key=resolved_key, base_url=base_url)
            else:
                self._client = AsyncOpenAI(api_key=resolved_key)

    def _edit_kwargs(self) -> _EditKwargs:
        """Build model-specific kwargs for ``images.edit`` calls.

        gpt-image-2 always processes references at high fidelity — the
        ``input_fidelity`` parameter is not supported and causes an error
        if passed.  Older models (gpt-image-1 / gpt-image-1.5) require it.
        """
        if self._is_v2:
            return {}
        return {"input_fidelity": "high"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
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
        """Generate a character portrait image.

        Args:
            description: Text description of the character's appearance.
            transparent: Whether to render with a transparent background.
            art_style: Visual style guidance (default: children's story book).
            on_partial: Ignored — portraits are too fast for streaming.
            reference_image: Optional user-provided image bytes. When provided,
                uses ``images.edit`` to stylize the reference image in the
                story's art style.

        Returns:
            PNG image bytes.
        """
        del on_partial
        prompt = build_portrait_prompt(
            description,
            transparent=transparent,
            art_style=art_style,
            model=self._model,
        )

        if reference_image is not None:
            image_file = ("image", ("reference.png", io.BytesIO(reference_image), "image/png"))
            edit_kwargs = self._edit_kwargs()
            if transparent and not self._is_v2:
                edit_kwargs["background"] = "transparent"
            resp = await self._client.images.edit(
                model=self._model,
                prompt=prompt,
                image=[image_file[1]],
                size=PORTRAIT_SIZE,
                quality=PORTRAIT_QUALITY,
                output_format="png",
                **edit_kwargs,
            )
            return _decode_b64(resp)

        # gpt-image-2 does not support background="transparent" — only
        # "opaque" and "auto" are accepted.  The prompt already asks for a
        # plain neutral / no-background look so the visual result is similar.
        bg = "opaque"
        if transparent and not self._is_v2:
            bg = "transparent"

        resp = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=PORTRAIT_SIZE,
            quality=PORTRAIT_QUALITY,
            background=bg,
            output_format="png",
        )
        return _decode_b64(resp)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
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
        """Generate a scene image, optionally anchored to character reference portraits.

        Args:
            prompt: Narrative description of the scene to render.
            reference_portraits: Named character reference images to preserve
                appearance via the edit endpoint's ``input_fidelity="high"`` mode.
                Pass an empty list to use the standard generate endpoint.
            art_style: Visual style guidance (default: children's story book).
                Appended to the prompt so the rendered image matches portraits.
            on_partial: Optional async callback invoked with each intermediate
                low->high resolution preview PNG when streaming is active.
                Passing a non-None value enables ``stream=True`` and requests
                ``partial_images=OPENAI_PARTIAL_IMAGES`` from the OpenAI API
                (gpt-image-2 / gpt-image-1.5 / gpt-image-1 only). The callback is awaited
                serially per partial event before the next is processed.

        Returns:
            PNG image bytes.
        """
        styled_prompt = build_scene_prompt(
            prompt, art_style=art_style, model=self._model, reference_portraits=reference_portraits
        )
        image_files = [
            ("image", (f"ref-{ref.name}.png", io.BytesIO(ref.data), "image/png"))
            for ref in reference_portraits
        ]

        if on_partial is not None:
            return await self._generate_scene_streaming(
                styled_prompt=styled_prompt,
                image_files=image_files,
                on_partial=on_partial,
            )

        if not reference_portraits:
            resp = await self._client.images.generate(
                model=self._model,
                prompt=styled_prompt,
                size=SCENE_SIZE,
                quality=SCENE_QUALITY,
                output_format="png",
            )
            return _decode_b64(resp)

        resp = await self._client.images.edit(
            model=self._model,
            prompt=styled_prompt,
            image=[tup[1] for tup in image_files],
            size=SCENE_SIZE,
            quality=SCENE_QUALITY,
            output_format="png",
            **self._edit_kwargs(),
        )
        return _decode_b64(resp)

    async def _generate_scene_streaming(
        self,
        *,
        styled_prompt: str,
        image_files: list[tuple[str, tuple[str, io.BytesIO, str]]],
        on_partial: Callable[[bytes], Awaitable[None]],
    ) -> bytes:
        """Run a streaming images.generate / images.edit call, firing ``on_partial``
        for each intermediate event and returning the final image bytes.

        OpenAI emits one event per partial (``image_generation.partial_image``
        for ``generate``; ``image_edit.partial_image`` for ``edit``) followed
        by exactly one terminal event (``*.completed``) carrying the final
        b64-encoded PNG. We dispatch on event type via string comparison so
        the loop tolerates SDK shape drift; the contract is "anything matching
        ``*.partial_image`` fires the callback; ``*.completed`` is the final."

        Raises:
            RuntimeError: if the stream ends without a terminal completed event.
        """
        if not image_files:
            stream = await self._client.images.generate(
                model=self._model,
                prompt=styled_prompt,
                size=SCENE_SIZE,
                quality=SCENE_QUALITY,
                output_format="png",
                stream=True,
                partial_images=OPENAI_PARTIAL_IMAGES,
            )
        else:
            stream = await self._client.images.edit(
                model=self._model,
                prompt=styled_prompt,
                image=[tup[1] for tup in image_files],
                size=SCENE_SIZE,
                quality=SCENE_QUALITY,
                output_format="png",
                stream=True,
                partial_images=OPENAI_PARTIAL_IMAGES,
                **self._edit_kwargs(),
            )

        final_bytes: bytes | None = None
        async for event in stream:  # pyright: ignore[reportUnknownVariableType]
            event_type = getattr(event, "type", "")  # pyright: ignore[reportUnknownArgumentType]
            b64 = getattr(event, "b64_json", None)  # pyright: ignore[reportUnknownArgumentType]
            if not b64:
                continue
            payload = base64.b64decode(b64)
            if isinstance(event_type, str) and event_type.endswith(".completed"):
                final_bytes = payload
            else:
                # Treat anything else (partial_image events, or unknown
                # intermediate types) as a preview frame.
                await on_partial(payload)
        if final_bytes is None:
            raise RuntimeError("OpenAI image stream ended without a final image")
        return final_bytes


def _decode_b64(response: object) -> bytes:
    """Decode the base64-encoded image from an OpenAI image response.

    Args:
        response: An OpenAI image generation/edit response object.

    Returns:
        Raw PNG bytes.

    Raises:
        RuntimeError: If the response contains no data or missing b64_json.
    """
    data = getattr(response, "data", None)
    if not data:
        raise RuntimeError("OpenAI image response had no data")
    b64 = getattr(data[0], "b64_json", None)
    if not b64:
        raise RuntimeError("OpenAI image response missing b64_json")
    return base64.b64decode(b64)
