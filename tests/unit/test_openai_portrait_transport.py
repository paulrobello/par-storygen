"""No-reference portraits exercise real SDK serialization without network access."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import APIStatusError, AsyncOpenAI

from storygen.images.openai_provider import OpenAIImageProvider


@pytest.mark.asyncio
async def test_no_reference_portrait_sdk_request_and_response() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={"created": 0, "data": [{"b64_json": base64.b64encode(b"PNG").decode()}]},
        )

    async with AsyncOpenAI(
        api_key="unused-local-test-value",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        assert await provider.generate_portrait("A scholar", transparent=True) == b"PNG"

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/images/generations"
    body = json.loads(request.content)
    assert body == {
        "model": "gpt-image-2.6-flare",
        "prompt": body["prompt"],
        "size": "1024x1536",
        "quality": "low",
        "background": "transparent",
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
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
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
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
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
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(200, json={"created": 0, "data": [{}]})
            )
        ),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        with pytest.raises(RuntimeError, match="missing b64_json"):
            await provider.generate_portrait("A scholar", transparent=True)


@pytest.mark.asyncio
async def test_reference_portrait_v26_sdk_multipart_request() -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200, json={"created": 0, "data": [{"b64_json": base64.b64encode(b"PNG").decode()}]}
        )

    async with AsyncOpenAI(
        api_key="unused-local-test-value",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond), trust_env=False),
    ) as client:
        provider = OpenAIImageProvider(client=client)
        assert (
            await provider.generate_portrait(
                "A scholar", transparent=True, reference_image=b"REFERENCE"
            )
            == b"PNG"
        )

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/images/edits"
    assert "multipart/form-data" in request.headers["content-type"]
    assert b"gpt-image-2.6-flare" in request.content
    assert b"REFERENCE" in request.content
    assert b"transparent" in request.content
    assert b"input_fidelity" not in request.content
