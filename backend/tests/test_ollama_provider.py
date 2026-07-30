import httpx
import pytest
import asyncio

from app.services.ai.ollama import OllamaProvider
from app.services.ai.provider import (
    ModelGenerationRequest,
    RequirementExtractionRequest,
)


def _mock_transport(
    handler,
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_ollama_provider_settings_are_non_secret() -> None:
    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        timeout_seconds=45,
    )

    settings = provider.provider_settings()

    assert settings == {
        "base_url": "http://ollama.local:11434",
        "model": "qwen3.5:9b",
        "timeout_seconds": 45,
        "endpoint": "/api/generate",
        "stream": False,
        "think": None,
        "auth_mode": "local_ollama",
    }


@pytest.mark.asyncio
async def test_ollama_provider_can_disable_thinking_for_thinking_models() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = httpx.Request(
            request.method,
            request.url,
            content=request.content,
        ).read()
        return httpx.Response(200, json={"response": "{\"ok\": true}", "thinking": "hidden"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        think=False,
        transport=_mock_transport(handler),
    )

    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert result.raw_output == "{\"ok\": true}"
    assert provider.provider_settings()["think"] is False
    assert b'"think":false' in captured["payload"]


@pytest.mark.asyncio
async def test_ollama_extract_requirements_posts_prompt_and_returns_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = httpx.Request(
            request.method,
            request.url,
            content=request.content,
        ).read()
        return httpx.Response(200, json={"response": "{\"outcome\":\"generation_ready\"}"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        transport=_mock_transport(handler),
    )

    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert result.provider == "ollama"
    assert result.provider_model == "qwen3.5:9b"
    assert result.raw_output == "{\"outcome\":\"generation_ready\"}"
    assert captured["url"] == "http://ollama.local:11434/api/generate"
    assert b'"model":"qwen3.5:9b"' in captured["payload"]
    assert b'"stream":false' in captured["payload"]
    assert b"Do not use tools, web search, files, or external resources" in captured["payload"]


@pytest.mark.asyncio
async def test_ollama_generate_model_uses_existing_openscad_prompt_contract() -> None:
    captured_prompt = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_prompt
        captured_prompt = request.read().decode("utf-8")
        return httpx.Response(200, json={"response": "```scad\ncube([1,1,1]);\n```"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        transport=_mock_transport(handler),
    )

    result = await provider.generate_model(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="Make a cube.",
            user_instruction="Make a cube.",
        )
    )

    assert result.provider == "ollama"
    assert result.provider_model == "qwen3.5:9b"
    assert result.raw_output == "```scad\ncube([1,1,1]);\n```"
    assert "You generate OpenSCAD for Volundr." in captured_prompt


@pytest.mark.asyncio
async def test_ollama_non_success_response_raises_runtime_error() -> None:
    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        transport=_mock_transport(
            lambda request: httpx.Response(500, json={"error": "model failed"})
        ),
    )

    with pytest.raises(RuntimeError, match="model failed"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_ollama_missing_response_field_raises_runtime_error() -> None:
    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
        transport=_mock_transport(lambda request: httpx.Response(200, json={"done": True})),
    )

    with pytest.raises(RuntimeError, match="missing response"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_ollama_request_timeout_is_bounded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"response": "late"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="qwen3.5:9b",
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
