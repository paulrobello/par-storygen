"""No-reference portraits exercise real SDK serialization without network access."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI

from storygen.images.openai_provider import OpenAIImageProvider


@pytest.mark.asyncio
async def test_no_reference_portrait_sdk_request_and_response() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"created": 0, "data": [{"b64_json": base64.b64encode(b"PNG").decode()}]},
        )

    async with AsyncOpenAI(
        api_key="unused-local-test-value",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        assert await provider.generate_portrait("A scholar", transparent=True) == b"PNG"

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/images/generations"
    body = json.loads(request.content)
    assert body == {
        "model": "gpt-image-2",
        "prompt": body["prompt"],
        "size": "1024x1536",
        "quality": "low",
        "background": "opaque",
        "output_format": "png",
    }
    assert "A scholar" in body["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "model_not_found"), (403, "permission_denied"), (429, "insufficient_quota")],
)
async def test_no_reference_sdk_error_survives_provider_retries(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"x-request-id": "local-test-request"},
            json={
                "error": {
                    "message": "Mock rejection",
                    "type": "invalid_request_error",
                    "code": code,
                }
            },
        )

    async with AsyncOpenAI(
        api_key="unused-local-test-value",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        with pytest.raises(APIStatusError) as raised:
            await provider.generate_portrait("A scholar", transparent=True)
    assert len(requests) == 3
    assert raised.value.status_code == status
    assert raised.value.code == code
    assert raised.value.request_id == "local-test-request"


@pytest.mark.asyncio
async def test_no_reference_response_without_base64_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    async with AsyncOpenAI(
        api_key="unused-local-test-value",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"created": 0, "data": [{}]})
            )
        ),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        with pytest.raises(RuntimeError, match="missing b64_json"):
            await provider.generate_portrait("A scholar", transparent=True)
