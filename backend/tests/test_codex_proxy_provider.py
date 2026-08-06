import json
from dataclasses import dataclass

import httpx
import pytest

from app.services.ai.codex_proxy import (
    CodexProxyError,
    CodexProxyProvider,
    ValidatedGeometryProviderRouter,
)
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult


def _request() -> ModelGenerationRequest:
    return ModelGenerationRequest(
        project_name="Frozen Project 01",
        original_intent="Create the frozen bracket.",
        user_instruction="Create the frozen bracket.",
        design_specification={"requirements": "frozen"},
        design_plan={"plan": "frozen"},
        generation_contract_version="cadquery-scaffold-v1",
    )


@dataclass
class PromptBuilder:
    prompts: list[ModelGenerationRequest]

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        self.prompts.append(request)
        return "EXACT EXISTING GEOMETRY PROMPT"


def _provider(
    handler,
    *,
    prompt_builder: PromptBuilder | None = None,
    attempt_recorder=None,
) -> CodexProxyProvider:
    return CodexProxyProvider(
        api_key="codex-secret",
        base_url="https://codex.test/backend-api/codex",
        model="gpt-5.6-luna",
        api_mode="responses",
        reasoning_effort="xhigh",
        timeout_seconds=7,
        prompt_builder=prompt_builder or PromptBuilder([]),
        transport=httpx.MockTransport(handler),
        attempt_recorder=attempt_recorder,
    )


@pytest.mark.asyncio
async def test_codex_responses_request_uses_settings_and_extracts_text_usage_and_request_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"x-request-id": "resp-123"},
            json={
                "id": "resp-body-id",
                "status": "completed",
                "model": "gpt-5.6-luna-20260806",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "cadquery output"}],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46},
            },
        )

    result = await _provider(handler).generate_cadquery_model(_request())

    assert captured["url"] == "https://codex.test/backend-api/codex/responses"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer codex-secret"
    assert headers["x-client-request-id"]
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload == {
        "model": "gpt-5.6-luna",
        "input": "EXACT EXISTING GEOMETRY PROMPT",
        "max_output_tokens": 8192,
        "reasoning": {"effort": "xhigh"},
    }
    assert result.provider == "codex_proxy"
    assert result.provider_model == "gpt-5.6-luna-20260806"
    assert result.raw_output == "cadquery output"
    assert result.provider_request_id == "resp-123"
    assert result.usage_metadata == {
        "input_tokens": 12,
        "output_tokens": 34,
        "total_tokens": 46,
    }
    assert result.routing_metadata["provider_call_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "failure_class"),
    [
        (
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            },
            "refusal",
        ),
        (
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            },
            "incomplete",
        ),
    ],
)
async def test_codex_refusal_and_incomplete_responses_fail_closed(payload, failure_class: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(CodexProxyError) as error:
        await _provider(handler).generate_cadquery_model(_request())

    assert error.value.failure_class == failure_class
    assert "no" not in str(error.value)
    assert "max_output_tokens" not in str(error.value)


@pytest.mark.asyncio
async def test_codex_response_does_not_duplicate_top_level_output_text() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": "cadquery output",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "cadquery output"}],
                    }
                ],
            },
        )

    result = await _provider(handler).generate_cadquery_model(_request())

    assert result.raw_output == "cadquery output"


@pytest.mark.asyncio
async def test_codex_timeout_is_classified_and_does_not_retry() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private timeout detail")

    with pytest.raises(CodexProxyError) as error:
        await _provider(handler).generate_cadquery_model(_request())

    assert calls == 1
    assert error.value.failure_class == "timeout"
    assert "private timeout detail" not in str(error.value)


@pytest.mark.asyncio
async def test_codex_429_is_bounded_and_persisted_without_secret_diagnostics() -> None:
    records: list[dict] = []
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": {"message": "secret upstream detail"}})

    provider = _provider(handler, attempt_recorder=records.append)
    with pytest.raises(CodexProxyError) as error:
        await provider.generate_cadquery_model(_request())

    assert calls == 1
    assert error.value.failure_class == "rate_limit"
    assert "secret upstream detail" not in str(error.value)
    assert len(records) == 1
    assert records[0]["failure_class"] == "rate_limit"
    assert records[0]["credential_env_var"] == "VOLUNDR_CODEX_API_KEY"
    assert "codex-secret" not in json.dumps(records)
    assert "authorization" not in records[0]


def test_codex_provider_settings_are_redacted() -> None:
    provider = _provider(lambda _request: httpx.Response(200, json={}))

    settings = provider.provider_settings()

    assert settings == {
        "base_url": "https://codex.test/backend-api/codex",
        "model": "gpt-5.6-luna",
        "api_mode": "responses",
        "endpoint": "/responses",
        "timeout_seconds": 7,
        "reasoning_effort": "xhigh",
        "max_output_tokens": 8192,
        "auth_mode": "bearer",
        "credential_env_var": "VOLUNDR_CODEX_API_KEY",
        "credential_present": True,
        "tools_enabled": False,
    }
    assert "codex-secret" not in json.dumps(settings)


@pytest.mark.asyncio
async def test_geometry_router_delegates_upstream_stages_and_codex_geometry_only() -> None:
    class Primary:
        provider_id = "gemini_api"
        model = "gemini-3.5-flash-lite"

        def __init__(self) -> None:
            self.requirements_calls = 0
            self.plan_calls = 0
            self.revision_plan_calls = 0
            self.recorder = None

        def build_cadquery_prompt(self, _request: ModelGenerationRequest) -> str:
            return "EXACT PRIMARY PROMPT"

        def set_validated_attempt_recorder(self, recorder) -> None:
            self.recorder = recorder

        async def generate_model(self, _request):
            self.requirements_calls += 1
            return "upstream-model"

        async def extract_requirements(self, _request):
            self.requirements_calls += 1
            return "upstream-requirements"

        async def create_design_plan(self, _request):
            self.plan_calls += 1
            return "upstream-plan"

        async def create_revision_plan(self, _request):
            self.revision_plan_calls += 1
            return "upstream-revision-plan"

        async def generate_cadquery_model(self, _request):
            raise AssertionError("primary geometry provider must not be called")

    class Geometry:
        provider_id = "codex_proxy"
        model = "gpt-5.6-luna"

        def __init__(self) -> None:
            self.geometry_calls = 0
            self.recorder = None

        def build_cadquery_prompt(self, _request):
            return "EXACT PRIMARY PROMPT"

        def set_validated_attempt_recorder(self, recorder) -> None:
            self.recorder = recorder

        async def generate_cadquery_model(self, _request):
            self.geometry_calls += 1
            return ModelGenerationResult(raw_output="geometry", provider="codex_proxy")

    primary = Primary()
    geometry = Geometry()
    router = ValidatedGeometryProviderRouter(primary_provider=primary, geometry_provider=geometry)

    assert await router.extract_requirements(object()) == "upstream-requirements"
    assert await router.create_design_plan(object()) == "upstream-plan"
    assert await router.create_revision_plan(object()) == "upstream-revision-plan"
    result = await router.generate_cadquery_model(_request())

    assert result.provider == "codex_proxy"
    assert geometry.geometry_calls == 1
    assert primary.requirements_calls == 1
    assert primary.plan_calls == 1
    assert primary.revision_plan_calls == 1

    recorder = lambda _record: None
    router.set_validated_attempt_recorder(recorder)
    assert primary.recorder is recorder
    assert geometry.recorder is recorder
