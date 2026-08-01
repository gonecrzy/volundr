import asyncio
import json
import time

import httpx
import pytest

from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.provider import ModelGenerationRequest, RequirementExtractionRequest


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _policy() -> GeminiModelPolicy:
    return GeminiModelPolicy(
        general_model="fast-general",
        requirements_model="fast-requirements",
        geometry_model="strong-geometry",
    )


def test_gemini_api_provider_settings_are_non_secret() -> None:
    provider = GeminiApiProvider(
        api_key="secret-key",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        model="gemini-3.5-flash-lite",
        timeout_seconds=45,
    )

    assert provider.provider_settings() == {
        "base_url": "https://generativelanguage.googleapis.test/v1beta",
        "model": "gemini-3.5-flash-lite",
        "timeout_seconds": 45,
        "endpoint": "/models/gemini-3.5-flash-lite:generateContent",
        "auth_mode": "api_key",
        "thinking_level": "minimal",
        "max_retries": 2,
        "max_retry_sleep_seconds": 60.0,
    }


@pytest.mark.asyncio
async def test_missing_gemini_key_fails_when_a_live_request_is_attempted() -> None:
    provider = GeminiApiProvider(api_key="")

    with pytest.raises(RuntimeError, match="API key is not configured"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Create a bracket.",
                user_instruction="Create a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_gemini_api_extract_requirements_posts_prompt_and_returns_text() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{\"outcome\":\"generation_ready\"}"}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 34,
                    "totalTokenCount": 46,
                },
            },
            headers={"x-goog-request-id": "req-123"},
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        base_url="https://generativelanguage.googleapis.test/v1beta",
        model="gemini-3.5-flash-lite",
        transport=_mock_transport(handler),
    )

    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert result.provider == "gemini_api"
    assert result.provider_model == "gemini-3.5-flash-lite"
    assert result.raw_output == "{\"outcome\":\"generation_ready\"}"
    assert result.usage_metadata == {
        "promptTokenCount": 12,
        "candidatesTokenCount": 34,
        "totalTokenCount": 46,
    }
    assert result.provider_request_id == "req-123"
    assert captured["url"] == (
        "https://generativelanguage.googleapis.test/v1beta/"
        "models/gemini-3.5-flash-lite:generateContent?key=secret-key"
    )
    assert captured["payload"]["contents"][0]["role"] == "user"
    assert "Return JSON only" in captured["payload"]["contents"][0]["parts"][0]["text"]
    assert captured["payload"]["generationConfig"]["temperature"] == 0.2
    assert captured["payload"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "MINIMAL"
    }


@pytest.mark.asyncio
async def test_gemini_api_routes_requirements_and_geometry_to_stage_models() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
            },
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="fast-general",
        model_policy=_policy(),
        transport=_mock_transport(handler),
    )

    await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )
    result = await provider.generate_cadquery_model(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
            generation_contract_version="cadquery-scaffold-v1",
        )
    )

    assert "/models/fast-requirements:generateContent" in urls[0]
    assert "/models/strong-geometry:generateContent" in urls[1]
    assert result.provider_model == "strong-geometry"
    assert result.routing_metadata["prompt_mode"] == "cadquery_geometry_bodies"
    assert result.routing_metadata["selected_model"] == "strong-geometry"
    assert result.provider_latency_ms is not None


@pytest.mark.asyncio
async def test_gemini_api_records_operational_model_fallback() -> None:
    urls: list[str] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        urls.append(str(request.url))
        if calls == 1:
            return httpx.Response(503, json={"error": {"message": "service unavailable"}})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="fast-general",
        model_policy=_policy(),
        max_retries=0,
        transport=_mock_transport(handler),
    )

    result = await provider.generate_cadquery_model(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
            generation_contract_version="cadquery-scaffold-v1",
        )
    )

    assert "/models/strong-geometry:generateContent" in urls[0]
    assert "/models/fast-general:generateContent" in urls[1]
    assert result.routing_metadata["routing_reason"] == "operational_fallback"
    assert result.routing_metadata["selected_model"] == "strong-geometry"
    assert result.routing_metadata["actual_model"] == "fast-general"
    assert result.routing_metadata["fallback_chain"] == ["strong-geometry", "fast-general"]


@pytest.mark.asyncio
async def test_gemini_api_generate_cadquery_model_uses_existing_prompt_contract() -> None:
    captured_prompt = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_prompt
        payload = json.loads(request.content.decode("utf-8"))
        captured_prompt = payload["contents"][0]["parts"][0]["text"]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "```python\nimport cadquery as cq\n```"}]}}
                ]
            },
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="models/gemini-3.5-flash-lite",
        transport=_mock_transport(handler),
    )

    result = await provider.generate_cadquery_model(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="Make a plate.",
            user_instruction="Make a plate.",
        )
    )

    assert result.provider == "gemini_api"
    assert result.provider_model == "models/gemini-3.5-flash-lite"
    assert result.raw_output == "```python\nimport cadquery as cq\n```"
    assert "You generate CadQuery Python for Volundr." in captured_prompt
    assert "cadquery-v1 source contract" in captured_prompt


@pytest.mark.asyncio
async def test_gemini_api_can_disable_thinking_config() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{\"outcome\":\"generation_ready\"}"}]}}
                ]
            },
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        thinking_level="off",
        transport=_mock_transport(handler),
    )

    await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert "thinkingConfig" not in captured["payload"]["generationConfig"]


@pytest.mark.asyncio
async def test_gemini_api_rejects_unknown_thinking_level() -> None:
    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        thinking_level="maximum",
        transport=_mock_transport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(RuntimeError, match="thinking level"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_gemini_api_retries_retryable_rate_limit_response() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": (
                            "You exceeded your current quota. "
                            "Please retry in 0.001s."
                        ),
                        "status": "RESOURCE_EXHAUSTED",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{\"outcome\":\"generation_ready\"}"}]}}
                ]
            },
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash",
        transport=_mock_transport(handler),
    )

    started_at = time.monotonic()
    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert attempts == 2
    assert result.raw_output == "{\"outcome\":\"generation_ready\"}"
    assert time.monotonic() - started_at < 0.5


@pytest.mark.asyncio
async def test_gemini_api_retries_millisecond_rate_limit_response() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": (
                            "You exceeded your current quota. "
                            "Please retry in 1.0ms."
                        ),
                        "status": "RESOURCE_EXHAUSTED",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{\"outcome\":\"generation_ready\"}"}]}}
                ]
            },
        )

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash",
        transport=_mock_transport(handler),
    )

    started_at = time.monotonic()
    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert attempts == 2
    assert result.raw_output == "{\"outcome\":\"generation_ready\"}"
    assert time.monotonic() - started_at < 0.5


@pytest.mark.asyncio
async def test_gemini_api_non_success_response_raises_runtime_error() -> None:
    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        transport=_mock_transport(
            lambda request: httpx.Response(
                403,
                json={"error": {"message": "API key not authorized"}},
            )
        ),
    )

    with pytest.raises(RuntimeError, match="API key not authorized"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_gemini_api_missing_text_raises_runtime_error() -> None:
    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        transport=_mock_transport(lambda request: httpx.Response(200, json={"candidates": []})),
    )

    with pytest.raises(RuntimeError, match="missing response text"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_gemini_api_request_timeout_is_bounded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"candidates": []})

    provider = GeminiApiProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        timeout_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )
