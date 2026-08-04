import httpx
import pytest
import asyncio

from app.services.ai.ollama import OllamaProvider, classify_ollama_resource_profile
from app.services.ollama_benchmark.calibration import CalibrationProfile
from app.services.ai.provider import (
    ModelGenerationRequest,
    RequirementExtractionRequest,
)
from app.services.ai.model_policy import PromptMode


class _DelayedNdjsonStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[tuple[float, bytes]]) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for delay, chunk in self.chunks:
            await asyncio.sleep(delay)
            yield chunk

    async def aclose(self) -> None:
        return None


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
        "stream": True,
        "connect_timeout_seconds": 15.0,
        "first_token_timeout_seconds": 300.0,
        "generation_idle_timeout_seconds": 300.0,
        "total_generation_timeout_seconds": 45.0,
        "think": None,
        "auth_mode": "local_ollama",
        "context_length": 8192,
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 40,
        "seed": None,
        "max_output_tokens": 8192,
        "keep_alive": "5m",
    }


def test_ollama_resource_profile_requires_context_success_and_vram_limits() -> None:
    assert classify_ollama_resource_profile(
        max_size_vram=12_000_000_000,
        model_size=14_000_000_000,
        context_completed=True,
        warm_throughput_collapse=False,
    ) == "preferred_gpu_resident"
    assert classify_ollama_resource_profile(
        max_size_vram=15_000_000_000,
        model_size=20_000_000_000,
        context_completed=True,
        warm_throughput_collapse=False,
    ) == "allowed_under_16gb"
    assert classify_ollama_resource_profile(
        max_size_vram=4_000_000_000,
        model_size=14_000_000_000,
        context_completed=True,
        warm_throughput_collapse=True,
    ) == "cpu_heavy"
    assert classify_ollama_resource_profile(
        max_size_vram=16_000_000_000,
        model_size=16_000_000_000,
        context_completed=True,
        warm_throughput_collapse=False,
    ) == "rejected"


def test_ollama_provider_initializes_volundr_routing_policy() -> None:
    provider = OllamaProvider(model="qwen2.5-coder:14b")

    decision = provider.routing_for_request(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert decision.provider == "ollama"
    assert decision.prompt_mode is PromptMode.REQUIREMENTS
    assert decision.selected_model == "qwen2.5-coder:14b"
    assert classify_ollama_resource_profile(
        max_size_vram=4_000_000_000,
        model_size=4_000_000_000,
        context_completed=False,
        warm_throughput_collapse=False,
    ) == "rejected"


@pytest.mark.asyncio
async def test_ollama_discovery_captures_exact_identity_and_safe_resource_metadata() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "procad:Q4_K_M", "model": "procad:Q4_K_M", "digest": "sha256:abc", "size": 7_500_000_000}]},
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "details": {"family": "qwen", "parameter_size": "7B", "quantization_level": "Q4_K_M"},
                    "template": "{{ .Prompt }}",
                    "capabilities": ["completion"],
                    "model_info": {"general.context_length": 8192},
                    "parameters": "num_ctx 8192\ntemperature 0.2",
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={"models": [{"name": "procad:Q4_K_M", "size_vram": 7_200_000_000, "size": 7_500_000_000, "context_length": 8192, "expires_at": "2026-08-03T00:00:00Z"}]},
            )
        raise AssertionError(request.url.path)

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="procad:Q4_K_M",
        transport=_mock_transport(handler),
    )

    models = await provider.list_available_models()
    resources = await provider.list_running_models()

    assert calls == ["/api/tags", "/api/show", "/api/ps"]
    assert models == [
        {
            "name": "procad:Q4_K_M",
            "digest": "sha256:abc",
            "size": 7_500_000_000,
            "parameter_size": "7B",
            "quantization": "Q4_K_M",
            "family": "qwen",
            "template": "{{ .Prompt }}",
            "capabilities": ["completion"],
            "context_length": 8192,
            "configured_parameters": {"num_ctx": "8192", "temperature": "0.2"},
        }
    ]
    assert resources[0]["size_vram"] == 7_200_000_000
    assert resources[0]["context_length"] == 8192
    assert "authorization" not in str(models).lower()


@pytest.mark.asyncio
async def test_ollama_benchmark_generation_sends_fixed_options_and_records_usage() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read()
        return httpx.Response(
            200,
            json={
                "model": "procad:Q4_K_M",
                "response": '{"slots": []}',
                "prompt_eval_count": 44,
                "eval_count": 12,
                "load_duration": 100,
                "prompt_eval_duration": 200,
                "eval_duration": 300,
                "total_duration": 600,
            },
        )

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="procad:Q4_K_M",
        context_length=8192,
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        seed=202,
        max_output_tokens=4096,
        keep_alive="10m",
        transport=_mock_transport(handler),
    )

    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    payload = captured["payload"]
    assert isinstance(payload, bytes)
    assert b'"num_ctx":8192' in payload
    assert b'"temperature":0.2' in payload
    assert b'"top_p":0.9' in payload
    assert b'"top_k":40' in payload
    assert b'"seed":202' in payload
    assert b'"num_predict":4096' in payload
    assert b'"keep_alive":"10m"' in payload
    assert result.provider_model == "procad:Q4_K_M"
    assert result.usage_metadata == {
        "prompt_eval_count": 44,
        "eval_count": 12,
        "load_duration": 100,
        "prompt_eval_duration": 200,
        "eval_duration": 300,
        "total_duration": 600,
    }


@pytest.mark.asyncio
async def test_ollama_auth_header_is_used_but_never_returned_in_settings() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"response": "ok"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="procad:Q4_K_M",
        api_key="ollama-secret",
        transport=_mock_transport(handler),
    )

    await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert captured["authorization"] == "Bearer ollama-secret"
    assert "ollama-secret" not in str(provider.provider_settings())


@pytest.mark.asyncio
async def test_ollama_preflight_polls_ps_and_records_cold_warm_tokens_and_throughput() -> None:
    calls = {"generate": 0, "ps": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            calls["generate"] += 1
            return httpx.Response(
                200,
                json={
                    "model": "procad:Q4_K_M",
                    "response": "{}",
                    "prompt_eval_count": 80,
                    "eval_count": 20,
                    "load_duration": 900_000_000 if calls["generate"] == 1 else 10_000_000,
                    "prompt_eval_duration": 400_000_000,
                    "eval_duration": 200_000_000,
                    "total_duration": 1_500_000_000 if calls["generate"] == 1 else 700_000_000,
                },
            )
        if request.url.path == "/api/ps":
            calls["ps"] += 1
            return httpx.Response(
                200,
                json={"models": [{"name": "procad:Q4_K_M", "size_vram": 7_000_000_000, "context_length": 8192}]},
            )
        raise AssertionError(request.url.path)

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="procad:Q4_K_M",
        transport=_mock_transport(handler),
    )

    result = await provider.preflight("largest frozen prompt", poll_interval_seconds=0)

    assert calls["generate"] == 2
    assert calls["ps"] >= 1
    assert result["context_completed"] is True
    assert result["max_size_vram"] == 7_000_000_000
    assert result["cold_load_duration"] == 900
    assert result["warm_execution_duration"] == 700
    assert result["prompt_tokens_per_second"] == 200.0
    assert result["output_tokens_per_second"] == 100.0


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
    assert b'"stream":true' in captured["payload"]
    assert b"Do not use tools, web search, files, or external resources" in captured["payload"]


@pytest.mark.asyncio
async def test_ollama_generate_model_uses_cadquery_prompt_contract() -> None:
    captured_prompt = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_prompt
        captured_prompt = request.read().decode("utf-8")
        return httpx.Response(200, json={"response": "```python\nimport cadquery as cq\n```"})

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
    assert result.raw_output == "```python\nimport cadquery as cq\n```"
    assert "You generate CadQuery Python for Volundr." in captured_prompt
    assert "Follow the cadquery-v1 source contract" in captured_prompt


@pytest.mark.asyncio
async def test_ollama_geometry_slot_generation_uses_json_schema_format() -> None:
    captured: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.read()
        return httpx.Response(200, json={"response": '{"slots": []}'})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="procad:Q4_K_M",
        transport=_mock_transport(handler),
    )

    await provider.generate_model(
        ModelGenerationRequest(
            project_name="Draft",
            original_intent="Make a cube.",
            user_instruction="Make a cube.",
            geometry_slot_manifest={"slots": []},
        )
    )

    assert b'"format":{"type":"object"' in captured["payload"]


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


@pytest.mark.asyncio
async def test_ollama_streaming_parses_chunks_and_allows_long_active_generation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=_DelayedNdjsonStream(
                [
                    (0.0, b'{"model":"specialist","response":"first ","done":false}\n'),
                    (0.03, b'{"response":"second","done":false}\n'),
                    (0.03, b'{"response":"","done":true,"eval_count":2}\n'),
                ]
            ),
        )

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="specialist",
        timeout_seconds=0.1,
        first_token_timeout_seconds=0.05,
        generation_idle_timeout_seconds=0.05,
        total_generation_timeout_seconds=0.2,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.extract_requirements(
        RequirementExtractionRequest(
            project_name="Draft",
            original_intent="Make a bracket.",
            user_instruction="Make a bracket.",
        )
    )

    assert result.raw_output == "first second"
    assert result.provider_model == "specialist"


@pytest.mark.asyncio
async def test_ollama_streaming_distinguishes_first_token_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=_DelayedNdjsonStream([(0.05, b'{"response":"late","done":true}\n')]),
        )

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="specialist",
        timeout_seconds=0.2,
        first_token_timeout_seconds=0.01,
        generation_idle_timeout_seconds=0.2,
        total_generation_timeout_seconds=0.2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="ollama_first_token_timeout"):
        await provider.extract_requirements(
            RequirementExtractionRequest(
                project_name="Draft",
                original_intent="Make a bracket.",
                user_instruction="Make a bracket.",
            )
        )


@pytest.mark.asyncio
async def test_profile_aware_calibration_request_uses_profile_generation_settings() -> None:
    captured: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.content
        return httpx.Response(200, json={"model": "specialist", "response": "result = 1"})

    provider = OllamaProvider(
        base_url="http://ollama.local:11434",
        model="specialist",
        stream=False,
        transport=_mock_transport(handler),
    )
    profile = CalibrationProfile(
        profile_version="v1",
        model_name="specialist",
        model_digest="abc",
        system_prompt="You are a helpful assistant.",
        stop_sequences=("STOP",),
        context_length=8192,
        max_output_tokens=111,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        keep_alive="30m",
    )

    result = await provider.generate_calibration_response("calibration prompt", profile=profile)

    assert result == "result = 1"
    assert b'"system":"You are a helpful assistant."' in captured["payload"]
    assert b'"stop":["STOP"]' in captured["payload"]
    assert b'"num_predict":111' in captured["payload"]
