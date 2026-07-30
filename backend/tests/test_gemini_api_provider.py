import asyncio
import json

import httpx
import pytest

from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.provider import ModelGenerationRequest, RequirementExtractionRequest


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


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
    }


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
                ]
            },
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
