import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.api.dependencies import build_executable_ai_provider
from app.core.config import Settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.validated_transport import ValidatedGeminiTransport


def _response(status_code: int, text: str = "ok") -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


def _configured() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider="gemini_api",
        gemini_primary_api_key=SecretStr("primary-secret"),
        gemini_fallback_api_key=SecretStr("fallback-secret"),
    )


def test_api_credentials_are_canonical_secret_settings_and_never_serialize(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VOLUNDR_GEMINI_PRIMARY_API_KEY=primary-secret\n"
        "VOLUNDR_GEMINI_FALLBACK_API_KEY=fallback-secret\n",
        encoding="utf-8",
    )

    configured = Settings(_env_file=env_file)

    assert isinstance(configured.gemini_primary_api_key, SecretStr)
    assert isinstance(configured.gemini_fallback_api_key, SecretStr)
    assert configured.gemini_primary_api_key.get_secret_value() == "primary-secret"
    assert configured.gemini_fallback_api_key.get_secret_value() == "fallback-secret"
    serialized = json.dumps(configured.model_dump(mode="json"))
    assert "primary-secret" not in serialized
    assert "fallback-secret" not in serialized


def test_executable_provider_uses_direct_primary_and_fallback_settings() -> None:
    provider = build_executable_ai_provider(_configured())

    assert isinstance(provider, GeminiApiProvider)
    assert provider.primary_api_key == "primary-secret"
    assert provider.fallback_api_key == "fallback-secret"
    metadata = provider.provider_settings()
    assert metadata["primary_credential"] == {"slot": "primary", "credential_present": True}
    assert metadata["fallback_credential"] == {"slot": "fallback", "credential_present": True}
    assert "environment_variable" not in json.dumps(metadata)
    assert "primary-secret" not in json.dumps(metadata)
    assert "fallback-secret" not in json.dumps(metadata)


@pytest.mark.asyncio
async def test_primary_is_used_normally_and_fallback_is_unused() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(200)

    result = await ValidatedGeminiTransport(
        primary_credential="primary-secret",
        fallback_credential="fallback-secret",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    ).generate(endpoint_path="/generate", payload={"prompt": "same"}, operation_id="logical-1")

    assert len(requests) == 1
    assert requests[0].headers["x-goog-api-key"] == "primary-secret"
    assert len(result.attempts) == 1
    assert result.attempts[0]["credential_slot"] == "primary"
    assert "credential_env_var" not in result.attempts[0]
    assert "primary-secret" not in json.dumps(result.attempts)
    assert "fallback-secret" not in json.dumps(result.attempts)


@pytest.mark.asyncio
async def test_first_429_waits_then_replays_exact_request_once_with_fallback() -> None:
    requests: list[httpx.Request] = []
    waits: list[float] = []
    responses = [_response(429), _response(200)]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    result = await ValidatedGeminiTransport(
        primary_credential="primary-secret",
        fallback_credential="fallback-secret",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    ).generate(endpoint_path="/generate", payload={"prompt": "same"}, operation_id="logical-2")

    assert len(requests) == 2
    assert [request.headers["x-goog-api-key"] for request in requests] == [
        "primary-secret",
        "fallback-secret",
    ]
    assert requests[0].content == requests[1].content
    assert requests[0].url == requests[1].url
    assert waits == [30.0]
    assert [attempt["logical_operation_id"] for attempt in result.attempts] == ["logical-2", "logical-2"]
    assert result.attempts[0]["attempt_id"] != result.attempts[1]["attempt_id"]
    assert [attempt["credential_slot"] for attempt in result.attempts] == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_fallback_429_stops_without_a_third_attempt() -> None:
    requests: list[httpx.Request] = []
    waits: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(429)

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    result = await ValidatedGeminiTransport(
        primary_credential="primary-secret",
        fallback_credential="fallback-secret",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    ).generate(endpoint_path="/generate", payload={"prompt": "same"}, operation_id="logical-3")

    assert len(requests) == 2
    assert len(result.attempts) == 2
    assert waits == [30.0]
    assert result.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 502, 503, 504])
async def test_transport_retry_stays_on_primary_for_retryable_transport_status(status_code: int) -> None:
    requests: list[httpx.Request] = []
    waits: list[float] = []
    responses = [_response(status_code), _response(200)]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    result = await ValidatedGeminiTransport(
        primary_credential="primary-secret",
        fallback_credential="fallback-secret",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    ).generate(endpoint_path="/generate", payload={"prompt": "same"}, operation_id="logical-4")

    assert len(requests) == 2
    assert [request.headers["x-goog-api-key"] for request in requests] == [
        "primary-secret",
        "primary-secret",
    ]
    assert waits == [10.0]
    assert [attempt["credential_slot"] for attempt in result.attempts] == ["primary", "primary"]


@pytest.mark.asyncio
async def test_401_does_not_rotate_to_fallback() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(401)

    result = await ValidatedGeminiTransport(
        primary_credential="primary-secret",
        fallback_credential="fallback-secret",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    ).generate(endpoint_path="/generate", payload={"prompt": "same"}, operation_id="logical-5")

    assert len(requests) == 1
    assert requests[0].headers["x-goog-api-key"] == "primary-secret"
    assert len(result.attempts) == 1
