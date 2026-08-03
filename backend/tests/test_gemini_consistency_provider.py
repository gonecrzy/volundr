import httpx
import pytest

from app.api.dependencies import build_ai_provider
from app.core.config import Settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.model_policy import GeminiModelPolicy, PromptMode


def test_benchmark_model_policy_applies_one_model_to_every_workflow_stage() -> None:
    configured = Settings(gemini_model="configured-production")

    policy = GeminiModelPolicy.for_benchmark(configured, "gemini-2.5-pro")

    assert policy.general_model == "gemini-2.5-pro"
    for prompt_mode in PromptMode:
        assert policy.resolve(prompt_mode).selected_model == "gemini-2.5-pro"


@pytest.mark.asyncio
async def test_gemini_model_discovery_returns_only_supported_safe_model_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini 2.5 Flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                ]
            },
        )

    provider = GeminiApiProvider(
        api_key="test-key",
        base_url="https://example.test/v1beta",
        model="gemini-2.5-flash",
        transport=httpx.MockTransport(handler),
    )

    models = await provider.list_available_models()

    assert [model["name"] for model in models] == [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    assert all("api_key" not in model and "authorization" not in model for model in models)


def test_build_ai_provider_accepts_developer_benchmark_model_override() -> None:
    configured = Settings(
        ai_provider="gemini_api",
        gemini_model="configured-production",
        gemini_api_key="",
    )

    provider = build_ai_provider(configured, benchmark_model="gemini-2.5-pro")

    assert isinstance(provider, GeminiApiProvider)
    assert provider.model_policy.general_model == "gemini-2.5-pro"
    assert provider.model_policy.resolve(PromptMode.CADQUERY_GEOMETRY_BODIES).selected_model == "gemini-2.5-pro"
