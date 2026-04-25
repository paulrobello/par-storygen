"""Z.AI GLM-image cloud image provider.

Z.AI exposes an OpenAI-compatible ``/v1/images/generations`` endpoint at
``https://api.z.ai/api/paas/v4/``, but with two notable deviations from the
OpenAI SDK's assumptions:

1. **Responses carry a URL, not base64.** We follow ``response.data[0].url``
   with :class:`httpx.AsyncClient` to download the actual PNG bytes.
2. **No reference-image support.** ``generate_scene(reference_portraits=...)``
   silently drops the refs (and fires an optional ``on_ref_loss`` callback
   once per provider instance) rather than refusing the call. Phase 4's
   router is responsible for deciding *whether* refs are desired; we just
   flag the degradation when they were supplied.

Pricing: flat ``$0.015`` per image regardless of size/quality (2026-04).
See :mod:`storygen.images.pricing`.

Allowed sizes are 1024-2048 px in multiples of 32. We fix ``1280x1280`` for
both portraits and scenes — large enough for the TUI half-block downscale,
small enough not to waste wall-clock time. Future work can expose size via
config if needed.

Transparency is prompt-only; Z.AI has no API-level flag. Reliability is
best-effort — the same caveat applies as for Gemini.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

import httpx
import openai
from openai import AsyncOpenAI, NotFoundError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from storygen.images._prompts import build_portrait_prompt, build_scene_prompt

DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4/"
DEFAULT_MODEL = "glm-image"

# Fixed output size. Z.AI accepts 1024-2048px in multiples of 32; 1280x1280 is
# a safe middle ground matching the half-block render target in the TUI.
IMAGE_SIZE = "1280x1280"

# Sentinel value passed to AsyncOpenAI when no key is configured. AsyncOpenAI
# requires a non-empty string at construction time. We detect this sentinel at
# call time (see :func:`_require_api_key`) and raise a descriptive error
# instead of letting the user see a misleading 401 referencing "zai-missing".
_MISSING_KEY_SENTINEL = "zai-missing"

# Retries target transient API + network faults. We deliberately do NOT retry
# on ``httpx.HTTPStatusError`` — a 4xx from the image URL fetch is almost
# always permanent (expired URL, 404 on delayed generation). Nor do we retry
# ``openai.NotFoundError`` (subclass of ``APIError``): that means the model id
# is wrong, which will not fix itself on retry.
_RETRYABLE_EXCEPTIONS = (openai.APIError, httpx.TransportError)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if ``exc`` should trigger a tenacity retry.

    Excludes :class:`openai.NotFoundError` — permanent misconfiguration.
    """
    if isinstance(exc, NotFoundError):
        return False
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


class ZaiImageProvider:
    """Implements :class:`storygen.images.base.ImageProvider` against Z.AI GLM-image.

    Does NOT support reference portraits. Callers that pass a non-empty
    ``reference_portraits`` list trigger the ``on_ref_loss`` callback (at
    least once per provider instance; may fire more than once under rare
    concurrent-call races) and the scene is generated without them.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        http_client: httpx.AsyncClient | None = None,
        on_ref_loss: Callable[[], None] | None = None,
    ) -> None:
        """Construct a provider.

        Args:
            model: Z.AI image model id.
            api_key: Explicit key; falls back to ``ZAI_API_KEY`` env var.
                If still empty, a sentinel is passed to ``AsyncOpenAI``
                (which requires non-empty) so construction never raises.
                Each call method pre-checks and raises a descriptive
                :class:`RuntimeError` before making the HTTP request.
            base_url: Z.AI paas v4 base URL. Trailing slash is significant.
            client: Pre-constructed AsyncOpenAI client (tests inject a stub).
            http_client: Reusable ``httpx.AsyncClient`` for URL fetches. When
                omitted, a short-lived client is created per call.
            on_ref_loss: Fired at least once per provider instance if
                ``generate_scene`` is called with references (may fire more
                than once under rare concurrent-call races). Phase 4 wraps
                this to surface a user-visible warning.
        """
        self._model = model
        self._http_client = http_client
        self._on_ref_loss = on_ref_loss
        self._ref_loss_fired = False
        # Track whether we have a real API key so call-time pre-checks can
        # raise a descriptive error instead of letting the sentinel leak into
        # the 401 message from Z.AI.
        resolved_key = api_key or os.environ.get("ZAI_API_KEY", "")
        self._has_api_key = bool(resolved_key) or client is not None
        if client is not None:
            self._client = client
        else:
            # AsyncOpenAI requires a non-empty string. Passing a sentinel keeps
            # construction failure-free; we pre-check ``_has_api_key`` at call
            # time and raise a descriptive error there.
            effective_key = resolved_key or _MISSING_KEY_SENTINEL
            self._client = AsyncOpenAI(
                api_key=effective_key,
                base_url=base_url or DEFAULT_BASE_URL,
            )

    def _require_api_key(self) -> None:
        """Raise if no ``ZAI_API_KEY`` is configured.

        Called at the top of each public generate method so the user sees a
        clear error instead of a 401 referencing the internal sentinel.
        """
        if not self._has_api_key:
            raise RuntimeError("Z.AI requires ZAI_API_KEY environment variable to be set")

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
        """Generate a character portrait via Z.AI GLM-image.

        Transparency is requested in the prompt; reliability is best-effort.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        del reference_image  # reference_image: not supported by this provider, ignored.
        self._require_api_key()
        prompt = build_portrait_prompt(
            description,
            transparent=transparent,
            art_style=art_style,
        )
        # Z.AI accepts 1024-2048 in multiples of 32; OpenAI SDK's ``size`` param
        # is typed as an OpenAI-only Literal, so we bypass the static check.
        resp = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=IMAGE_SIZE,  # pyright: ignore[reportArgumentType]
        )
        return await self._download_first(resp)

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
        reference_portraits: list[bytes],
        art_style: str = "children's story book",
        on_partial: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> bytes:
        """Generate a scene via Z.AI GLM-image.

        Z.AI does not accept reference images. If any are supplied, the
        ``on_ref_loss`` callback fires (at least once per provider instance;
        may fire more than once under rare concurrent-call races) and the
        scene is generated from the prompt alone. This mirrors the behaviour
        of :class:`storygen.images.ollama_provider.OllamaImageProvider`.
        """
        del on_partial  # on_partial: not supported by this provider, ignored.
        self._require_api_key()
        if reference_portraits and not self._ref_loss_fired:
            self._ref_loss_fired = True
            if self._on_ref_loss is not None:
                self._on_ref_loss()
        styled_prompt = build_scene_prompt(prompt, art_style=art_style)
        resp = await self._client.images.generate(
            model=self._model,
            prompt=styled_prompt,
            size=IMAGE_SIZE,  # pyright: ignore[reportArgumentType]
        )
        return await self._download_first(resp)

    async def _download_first(self, response: object) -> bytes:
        """Follow ``response.data[0].url`` and return the raw bytes.

        Raises :class:`RuntimeError` on empty data or non-2xx HTTP status.
        """
        data: list[object] = getattr(response, "data", None) or []  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if not data:
            raise RuntimeError("Z.AI image response had no data")
        url = getattr(data[0], "url", None)
        if not url:
            raise RuntimeError("Z.AI image response missing url")

        if self._http_client is not None:
            return await _fetch_url_bytes(self._http_client, url)
        # Short-lived client. Image generation is rare enough that pooling
        # connections isn't worth the lifecycle risk here.
        async with httpx.AsyncClient(timeout=30.0) as http:
            return await _fetch_url_bytes(http, url)


async def _fetch_url_bytes(http: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url`` and return body bytes; raise on non-2xx."""
    resp = await http.get(url)
    status = getattr(resp, "status_code", 0)
    if not (200 <= status < 300):
        raise RuntimeError(f"Z.AI image URL fetch returned {status}")
    return bytes(resp.content)
