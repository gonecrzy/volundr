import asyncio
import json
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.provider import (
    DesignPlanRequest,
    DesignPlanResult,
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
    RevisionPlanRequest,
    RevisionPlanResult,
    SourceBriefRequest,
    SourceBriefResult,
)


class OllamaProviderError(RuntimeError):
    """A local-provider failure with a stable evidence classification."""

    def __init__(self, failure_class: str, message: str) -> None:
        self.failure_class = failure_class
        super().__init__(f"{failure_class}: {message}")


def classify_ollama_resource_profile(
    *,
    max_size_vram: int | None,
    model_size: int | None,
    context_completed: bool,
    warm_throughput_collapse: bool,
) -> str:
    """Classify a preflight from reported evidence without inferring hardware state."""

    if not context_completed or (max_size_vram is not None and max_size_vram >= 16_000_000_000):
        return "rejected"
    if warm_throughput_collapse or (
        max_size_vram is not None
        and model_size is not None
        and max_size_vram < model_size * 0.5
    ):
        return "cpu_heavy"
    if max_size_vram is not None and max_size_vram <= 12_000_000_000:
        return "preferred_gpu_resident"
    return "allowed_under_16gb"


class OllamaProvider(GeminiCliProvider):
    """Ollama transport using the existing Volundr prompt contracts."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        connect_timeout_seconds: float | None = None,
        first_token_timeout_seconds: float | None = None,
        generation_idle_timeout_seconds: float | None = None,
        total_generation_timeout_seconds: float | None = None,
        stream: bool | None = None,
        think: bool | str | None = None,
        api_key: str | None = None,
        context_length: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        seed: int | None = None,
        max_output_tokens: int | None = None,
        keep_alive: str | int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_model = model or settings.ollama_model
        resolved_timeout = timeout_seconds or int(settings.ollama_total_generation_timeout_seconds)
        super().__init__(
            model=resolved_model,
            timeout_seconds=resolved_timeout,
            model_policy=GeminiModelPolicy.for_benchmark(settings, resolved_model),
        )
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = resolved_model
        self.timeout_seconds = resolved_timeout
        self.connect_timeout_seconds = (
            connect_timeout_seconds
            if connect_timeout_seconds is not None
            else settings.ollama_connect_timeout_seconds
        )
        self.first_token_timeout_seconds = (
            first_token_timeout_seconds
            if first_token_timeout_seconds is not None
            else settings.ollama_first_token_timeout_seconds
        )
        self.generation_idle_timeout_seconds = (
            generation_idle_timeout_seconds
            if generation_idle_timeout_seconds is not None
            else settings.ollama_generation_idle_timeout_seconds
        )
        self.total_generation_timeout_seconds = (
            total_generation_timeout_seconds
            if total_generation_timeout_seconds is not None
            else float(resolved_timeout)
        )
        self.stream = settings.ollama_stream if stream is None else stream
        self.think = self._normalize_think(settings.ollama_think if think is None else think)
        self.api_key = api_key if api_key is not None else settings.ollama_api_key
        self.context_length = context_length if context_length is not None else settings.ollama_context_length
        self.temperature = temperature if temperature is not None else settings.ollama_temperature
        self.top_p = top_p if top_p is not None else settings.ollama_top_p
        self.top_k = top_k if top_k is not None else settings.ollama_top_k
        self.seed = seed if seed is not None else settings.ollama_seed
        self.max_output_tokens = max_output_tokens if max_output_tokens is not None else settings.ollama_max_output_tokens
        self.keep_alive = keep_alive if keep_alive is not None else settings.ollama_keep_alive
        self._transport = transport
        self._last_usage_metadata: dict[str, Any] | None = None
        self._last_provider_latency_ms: int | None = None
        self._last_actual_model: str = self.model

    @property
    def provider_id(self) -> str:
        return "ollama"

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return await self.generate_cadquery_model(request)

    async def generate_cadquery_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        prompt = self.build_cadquery_prompt(request)
        raw_output = await self._run_prompt(
            prompt,
            structured=bool(request.geometry_slot_manifest or request.geometry_slot_brief),
        )
        return ModelGenerationResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self._last_actual_model,
            usage_metadata=self._last_usage_metadata,
            provider_latency_ms=self._last_provider_latency_ms,
        )

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        prompt = self.build_requirement_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return RequirementExtractionResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self._last_actual_model,
            usage_metadata=self._last_usage_metadata,
            provider_latency_ms=self._last_provider_latency_ms,
        )

    async def create_source_brief(self, request: SourceBriefRequest) -> SourceBriefResult:
        prompt = self.build_source_brief_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return SourceBriefResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self._last_actual_model,
            usage_metadata=self._last_usage_metadata,
            provider_latency_ms=self._last_provider_latency_ms,
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        prompt = self.build_design_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return DesignPlanResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self._last_actual_model,
            usage_metadata=self._last_usage_metadata,
            provider_latency_ms=self._last_provider_latency_ms,
        )

    async def create_revision_plan(self, request: RevisionPlanRequest) -> RevisionPlanResult:
        prompt = self.build_revision_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return RevisionPlanResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self._last_actual_model,
            usage_metadata=self._last_usage_metadata,
            provider_latency_ms=self._last_provider_latency_ms,
        )

    async def list_available_models(self) -> list[dict[str, Any]]:
        tags = await self._request_json("GET", "/api/tags")
        raw_models = tags.get("models", []) if isinstance(tags, dict) else []
        result: list[dict[str, Any]] = []
        for item in raw_models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            name = str(item["name"])
            show = await self._request_json("POST", "/api/show", payload={"name": name})
            details = show.get("details") if isinstance(show, dict) else {}
            details = details if isinstance(details, dict) else {}
            model_info = show.get("model_info") if isinstance(show, dict) else {}
            model_info = model_info if isinstance(model_info, dict) else {}
            result.append(
                {
                    "name": name,
                    "digest": item.get("digest"),
                    "size": item.get("size"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization": details.get("quantization_level"),
                    "family": details.get("family"),
                    "template": show.get("template"),
                    "capabilities": list(show.get("capabilities", [])) if isinstance(show.get("capabilities"), list) else [],
                    "context_length": self._context_length(model_info),
                    "configured_parameters": self._parse_parameters(show.get("parameters")),
                }
            )
        return result

    async def list_running_models(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/api/ps")
        models = payload.get("models", []) if isinstance(payload, dict) else []
        safe_fields = {"name", "model", "digest", "size", "size_vram", "context_length", "expires_at", "details"}
        return [
            {key: value for key, value in item.items() if key in safe_fields}
            for item in models
            if isinstance(item, dict)
        ]

    async def preflight(self, prompt: str, *, poll_interval_seconds: float = 0.5) -> dict[str, Any]:
        """Run one cold and one warm request while sampling `/api/ps`."""

        observations: list[dict[str, Any]] = []
        started = time.perf_counter()
        cold_task = asyncio.create_task(self._run_prompt(prompt))
        while not cold_task.done():
            try:
                observations.extend(await self.list_running_models())
            except RuntimeError as exc:
                observations.append({"integrity_finding": "resource_poll_failed", "error_type": type(exc).__name__})
            if not cold_task.done():
                await asyncio.sleep(max(0.0, poll_interval_seconds))
        await cold_task
        if not observations:
            observations.extend(await self.list_running_models())
        cold_usage = dict(self._last_usage_metadata or {})
        cold_latency = self._last_provider_latency_ms or max(0, round((time.perf_counter() - started) * 1000))
        await self._run_prompt(prompt)
        warm_usage = dict(self._last_usage_metadata or {})
        warm_latency = self._last_provider_latency_ms or 0
        max_vram = max(
            (int(item["size_vram"]) for item in observations if isinstance(item.get("size_vram"), (int, float))),
            default=None,
        )
        context_length = max(
            (int(item["context_length"]) for item in observations if isinstance(item.get("context_length"), (int, float))),
            default=None,
        )
        cold_tps = self._tokens_per_second(cold_usage.get("prompt_eval_count"), cold_usage.get("prompt_eval_duration"))
        warm_tps = self._tokens_per_second(warm_usage.get("prompt_eval_count"), warm_usage.get("prompt_eval_duration"))
        return {
            "requested_model": self.model,
            "actual_model": self._last_actual_model,
            "context_target": self.context_length,
            "active_context_length": context_length,
            "context_completed": True,
            "max_size_vram": max_vram,
            "cold_load_duration": self._duration_ms(cold_usage.get("load_duration")),
            "cold_latency_ms": cold_latency,
            "warm_execution_duration": self._duration_ms(warm_usage.get("total_duration")),
            "warm_latency_ms": warm_latency,
            "prompt_tokens_per_second": cold_tps,
            "output_tokens_per_second": self._tokens_per_second(warm_usage.get("eval_count"), warm_usage.get("eval_duration")),
            "warm_throughput_collapse": bool(cold_tps and warm_tps and warm_tps < cold_tps * 0.5),
            "observations": observations,
        }

    async def _run_prompt(self, prompt: str, *, structured: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": self.stream,
            "keep_alive": self.keep_alive,
            "options": {
                "num_ctx": self.context_length,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "num_predict": self.max_output_tokens,
            },
        }
        if self.seed is not None:
            payload["options"]["seed"] = self.seed
        if self.think is not None:
            payload["think"] = self.think
        if structured:
            payload["format"] = self._structured_output_schema()
        started = time.perf_counter()
        if self.stream:
            return await self._run_streaming_prompt(payload, started)
        return await self._run_non_streaming_prompt(payload, started)

    async def _run_non_streaming_prompt(self, payload: dict[str, Any], started: float) -> str:
        try:
            timeout = httpx.Timeout(
                self.total_generation_timeout_seconds,
                connect=self.connect_timeout_seconds,
            )
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                transport=self._transport,
            ) as client:
                response = await asyncio.wait_for(
                    client.post("/api/generate", json=payload, headers=self._headers()),
                    timeout=self.total_generation_timeout_seconds,
                )
        except TimeoutError as exc:
            raise OllamaProviderError(
                "ollama_total_timeout",
                f"request timed out after {self.total_generation_timeout_seconds} seconds",
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaProviderError(
                "ollama_connect_timeout" if isinstance(exc, httpx.ConnectTimeout) else "ollama_total_timeout",
                f"request timed out after {self.total_generation_timeout_seconds} seconds",
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaProviderError("ollama_server_unreachable", f"request failed: {exc}") from exc

        if response.status_code >= 400:
            raise OllamaProviderError("ollama_explicit_error", self._error_message(response))

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise OllamaProviderError("ollama_stream_parse_error", "response was not valid JSON") from exc

        raw_output = response_payload.get("response")
        if not isinstance(raw_output, str):
            raise OllamaProviderError("ollama_stream_parse_error", "response missing response text")
        self._last_actual_model = str(response_payload.get("model") or self.model)
        self._last_provider_latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        self._last_usage_metadata = self._usage_metadata(response_payload)
        return raw_output

    async def _run_streaming_prompt(self, payload: dict[str, Any], started: float) -> str:
        timeout = httpx.Timeout(None, connect=self.connect_timeout_seconds)
        output: list[str] = []
        usage: dict[str, Any] = {}
        saw_output = False
        iterator = None
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST", "/api/generate", json=payload, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise OllamaProviderError("ollama_explicit_error", self._error_message(response))
                    iterator = response.aiter_lines().__aiter__()
                    while True:
                        elapsed = time.perf_counter() - started
                        remaining_total = self.total_generation_timeout_seconds - elapsed
                        if remaining_total <= 0:
                            raise OllamaProviderError("ollama_total_timeout", "generation timed out after exceeding total timeout")
                        wait_budget = min(
                            remaining_total,
                            self.generation_idle_timeout_seconds if saw_output else self.first_token_timeout_seconds,
                        )
                        try:
                            line = await asyncio.wait_for(anext(iterator), timeout=wait_budget)
                        except StopAsyncIteration:
                            break
                        except TimeoutError as exc:
                            failure_class = "ollama_idle_timeout" if saw_output else "ollama_first_token_timeout"
                            raise OllamaProviderError(failure_class, f"stream made no progress for {wait_budget} seconds") from exc
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaProviderError("ollama_stream_parse_error", "stream chunk was not JSON") from exc
                        if not isinstance(chunk, dict):
                            raise OllamaProviderError("ollama_stream_parse_error", "stream chunk was not an object")
                        if isinstance(chunk.get("error"), str) and chunk["error"].strip():
                            raise OllamaProviderError("ollama_explicit_error", chunk["error"].strip())
                        if isinstance(chunk.get("model"), str):
                            self._last_actual_model = chunk["model"]
                        text = chunk.get("response")
                        if isinstance(text, str):
                            output.append(text)
                            if text:
                                saw_output = True
                        usage.update(self._usage_metadata(chunk) or {})
                        if chunk.get("done") is True:
                            break
        except OllamaProviderError:
            raise
        except httpx.ConnectTimeout as exc:
            raise OllamaProviderError("ollama_connect_timeout", "connection timed out") from exc
        except httpx.ReadTimeout as exc:
            failure_class = "ollama_idle_timeout" if saw_output else "ollama_first_token_timeout"
            raise OllamaProviderError(failure_class, "stream read timed out") from exc
        except httpx.HTTPError as exc:
            raise OllamaProviderError("ollama_proxy_disconnect", f"stream failed: {exc}") from exc
        if not saw_output:
            raise OllamaProviderError("ollama_stream_parse_error", "stream missing response text")
        self._last_provider_latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        self._last_usage_metadata = usage or None
        return "".join(output)

    def provider_settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "endpoint": "/api/generate",
            "stream": self.stream,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "first_token_timeout_seconds": self.first_token_timeout_seconds,
            "generation_idle_timeout_seconds": self.generation_idle_timeout_seconds,
            "total_generation_timeout_seconds": self.total_generation_timeout_seconds,
            "think": self.think,
            "auth_mode": "bearer" if self.api_key else "local_ollama",
            "context_length": self.context_length,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "seed": self.seed,
            "max_output_tokens": self.max_output_tokens,
            "keep_alive": self.keep_alive,
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def _request_json(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await asyncio.wait_for(
                    client.request(method, path, json=payload, headers=self._headers()),
                    timeout=self.timeout_seconds,
                )
        except TimeoutError as exc:
            raise RuntimeError(f"Ollama request timed out after {self.timeout_seconds} seconds") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Ollama request timed out after {self.timeout_seconds} seconds") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(self._error_message(response))
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama response was not valid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Ollama response must be a JSON object")
        return result

    @staticmethod
    def _parse_parameters(value: Any) -> dict[str, str]:
        if not isinstance(value, str):
            return {}
        result: dict[str, str] = {}
        for line in value.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] in {"num_ctx", "temperature", "top_p", "top_k", "num_predict", "seed"}:
                result[parts[0]] = parts[1]
        return result

    @staticmethod
    def _context_length(model_info: dict[str, Any]) -> int | None:
        for key, value in model_info.items():
            if str(key).casefold().endswith("context_length") and isinstance(value, (int, float)):
                return int(value)
        return None

    @staticmethod
    def _usage_metadata(payload: dict[str, Any]) -> dict[str, Any] | None:
        fields = (
            "prompt_eval_count",
            "eval_count",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
            "total_duration",
        )
        result = {field: payload[field] for field in fields if field in payload and isinstance(payload[field], (int, float))}
        return result or None

    @staticmethod
    def _duration_ms(value: Any) -> int | None:
        return round(value / 1_000_000) if isinstance(value, (int, float)) else None

    @staticmethod
    def _tokens_per_second(count: Any, duration: Any) -> float | None:
        if not isinstance(count, (int, float)) or not isinstance(duration, (int, float)) or duration <= 0:
            return None
        return round(float(count) / (float(duration) / 1_000_000_000), 3)

    @staticmethod
    def _structured_output_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "schema_version": {"type": "string"},
                "slots": {"type": "array"},
            },
            "required": ["slots"],
        }

    def _error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or f"Ollama request failed with HTTP {response.status_code}"
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        return f"Ollama request failed with HTTP {response.status_code}"

    def _normalize_think(self, value: bool | str | None) -> bool | str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        normalized = value.strip().lower()
        if normalized in {"", "unset", "none", "null"}:
            return None
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"low", "medium", "high", "max"}:
            return normalized
        return value
