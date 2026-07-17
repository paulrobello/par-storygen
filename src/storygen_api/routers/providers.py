"""Provider registry route (ENH-005).

Exposes the declarative provider registry in :mod:`storygen.core.providers` so
the web UI (and any other API client) can render provider dropdowns, model
suggestions, and base-URL placeholders from a single source of truth. After
ENH-005, adding a provider is a one-(registry)-file change end to end.

The route is gated by the shared bearer-token dependency (``verify_token``)
like every other content-bearing router; provider ids, env-var names, and
default models are not sensitive on their own (they already live in
``.env.example`` and the public source tree), but reads from this surface
should still require auth so an off-box peer without a configured token cannot
enumerate the configured surface (fail-closed, consistent with SEC-001).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from storygen.core.providers import IMAGE_PROVIDERS, TEXT_PROVIDERS, ProviderInfo
from storygen_api.schemas import ProviderInfoOut, ProvidersResponse
from storygen_api.security import verify_token

router = APIRouter(
    prefix="/api/providers",
    tags=["providers"],
    # SEC-001: enumerate the configured surface behind the same gate as the
    # other content routes (settings, presets, library).
    dependencies=[Depends(verify_token)],
)


def _to_out(info: ProviderInfo) -> ProviderInfoOut:
    """Project a frozen ``ProviderInfo`` dataclass into the JSON-friendly DTO.

    ``kind`` (frozenset) becomes a sorted list so the wire shape is stable.
    """
    return ProviderInfoOut(
        id=info.id,
        label=info.label,
        kind=sorted(info.kind),
        key_env_var=info.key_env_var,
        default_model=info.default_model,
        default_base_url=info.default_base_url,
        allows_loopback_base_url=info.allows_loopback_base_url,
        supports_reference_images=info.supports_reference_images,
        suggested_models=list(info.suggested_models),
    )


@router.get("", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    """Return the full provider registry (text + image)."""
    return ProvidersResponse(
        text_providers=[_to_out(info) for info in TEXT_PROVIDERS.values()],
        image_providers=[_to_out(info) for info in IMAGE_PROVIDERS.values()],
    )
