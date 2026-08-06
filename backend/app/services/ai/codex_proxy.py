"""Temporary Responses-compatible geometry transport for the Codex comparison."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult


class CodexProxyError(RuntimeError):
    """A normalized, non-secret Codex proxy failure."""

    def __init__(self, failure_class: str, message: str) -> None:
        self.failure_class = failure_class
        super().__init__(f"{failure_class}: {message}")


class CodexProxyProvider:
    """Generate only the existing CadQuery geometry prompt through Responses."""

    provider_id = "codex_proxy"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        api_mode: str = "responses",
        reasoning_effort: str | None = "xhigh",
        timeout_seconds: float = 120.0,
        max_output_tokens: int = 8192,
        prompt_builder: Any,
        transport: httpx.AsyncBaseTransport | None = None,
        attempt_recorder: Callable[[dict[str, Any]], Any] | None = None,
        request_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        if api_mode != "responses":
            raise ValueError("Codex proxy supports only the Responses API mode")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.prompt_builder = prompt_builder
        self._transport = transport
        self._attempt_recorder = attempt_recorder
        self._request_id_factory = request_id_factory

    def set_validated_attempt_recorder(
        self,
        recorder: Callable[[dict[str, Any]], Any] | None,
    ) -> None:
        self._attempt_recorder = recorder

    def build_cadquery_prompt(self, request: ModelGenerationRequest) -> str:
        builder = getattr(self.prompt_builder, "build_cadquery_prompt", None)
        if not callable(builder):
            raise RuntimeError("Codex proxy geometry prompt builder is unavailable")
        return str(builder(request))

    def provider_settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_mode": self.api_mode,
            "endpoint": "/responses",
            "timeout_seconds": self.timeout_seconds,
            "reasoning_effort": self.reasoning_effort,
            "max_output_tokens": self.max_output_tokens,
            "auth_mode": "bearer",
            "credential_env_var": "VOLUNDR_CODEX_API_KEY",
            "credential_present": bool(self.api_key),
            "tools_enabled": False,
        }

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return await self.generate_cadquery_model(request)

    async def generate_cadquery_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        if not self.api_key:
            raise CodexProxyError("configuration", "Codex proxy API key is not configured")
        if not self.base_url or not self.model:
            raise CodexProxyError("configuration", "Codex proxy endpoint or model is not configured")

        prompt = self.build_cadquery_prompt(request)
        payload: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": self.max_output_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        logical_operation_id = str(uuid.uuid4())
        attempt = {
            "logical_operation_id": logical_operation_id,
            "attempt_id": str(uuid.uuid4()),
            "attempt_index": 0,
            "credential_slot": "codex",
            "credential_env_var": "VOLUNDR_CODEX_API_KEY",
            "credential_present": True,
            "request_hash": request_hash,
            "status_code": None,
            "failure_class": None,
            "retry_delay_seconds": None,
        }
        client_request_id = self._request_id_factory()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-Client-Request-Id": client_request_id,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await asyncio.wait_for(
                    client.post("/responses", headers=headers, json=payload),
                    timeout=self.timeout_seconds,
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            attempt["status_code"] = 599
            attempt["failure_class"] = "timeout"
            self._record_attempt(attempt)
            raise CodexProxyError("timeout", "Codex proxy request timed out") from exc
        except httpx.HTTPError as exc:
            attempt["status_code"] = 599
            attempt["failure_class"] = "transport_failure"
            self._record_attempt(attempt)
            raise CodexProxyError("transport_failure", "Codex proxy request failed") from exc

        attempt["status_code"] = response.status_code
        if response.status_code >= 400:
            failure_class = self._failure_class(response.status_code)
            attempt["failure_class"] = failure_class
            self._record_attempt(attempt)
            raise CodexProxyError(failure_class, self._failure_message(failure_class))

        try:
            response_payload = response.json()
        except ValueError as exc:
            attempt["failure_class"] = "invalid_response"
            self._record_attempt(attempt)
            raise CodexProxyError("invalid_response", "Codex proxy response was not valid JSON") from exc
        if not isinstance(response_payload, dict):
            attempt["failure_class"] = "invalid_response"
            self._record_attempt(attempt)
            raise CodexProxyError("invalid_response", "Codex proxy response was not an object")

        try:
            raw_output = self._extract_response_text(response_payload)
        except CodexProxyError as exc:
            attempt["failure_class"] = exc.failure_class
            self._record_attempt(attempt)
            raise

        self._record_attempt(attempt)
        provider_request_id = self._provider_request_id(response, response_payload)
        actual_model = response_payload.get("model")
        if not isinstance(actual_model, str) or not actual_model:
            actual_model = self.model
        usage = response_payload.get("usage")
        usage_metadata = dict(usage) if isinstance(usage, dict) else None
        return ModelGenerationResult(
            raw_output=raw_output,
            provider=self.provider_id,
            provider_model=actual_model,
            usage_metadata=usage_metadata,
            provider_request_id=provider_request_id,
            routing_metadata={
                "prompt_mode": "cadquery_geometry",
                "selected_model": self.model,
                "actual_model": actual_model,
                "provider_call_count": 1,
                "provider_retry_count": 0,
                "api_mode": self.api_mode,
                "tools_enabled": False,
            },
            provider_latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )

    def _record_attempt(self, attempt: dict[str, Any]) -> None:
        if self._attempt_recorder is not None:
            self._attempt_recorder(dict(attempt))

    @staticmethod
    def _failure_class(status_code: int) -> str:
        if status_code == 429:
            return "rate_limit"
        if status_code in {401, 403}:
            return "authentication_failure"
        if status_code in {408, 502, 503, 504}:
            return "transport_failure"
        return "provider_failure"

    @staticmethod
    def _failure_message(failure_class: str) -> str:
        return {
            "rate_limit": "Codex proxy rate limit reached; no retry was attempted.",
            "authentication_failure": "Codex proxy authentication failed.",
            "transport_failure": "Codex proxy transport failed.",
            "provider_failure": "Codex proxy returned an unsuccessful response.",
        }.get(failure_class, "Codex proxy request failed")

    @classmethod
    def _extract_response_text(cls, payload: dict[str, Any]) -> str:
        status = payload.get("status")
        if status not in (None, "completed"):
            raise CodexProxyError("incomplete", "Codex proxy response was incomplete")

        output = payload.get("output")
        if not isinstance(output, list):
            output = []
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, dict):
                content = [content]
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type in {"refusal", "output_refusal"}:
                    raise CodexProxyError("refusal", "Codex proxy refused the geometry request")
                if part_type == "output_text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])

        top_level_text = payload.get("output_text")
        if isinstance(top_level_text, str):
            text_parts.append(top_level_text)
        text = "".join(text_parts)
        if not text.strip():
            raise CodexProxyError("missing_output", "Codex proxy response contained no geometry text")
        return text

    @staticmethod
    def _provider_request_id(response: httpx.Response, payload: dict[str, Any]) -> str | None:
        for header in ("x-request-id", "request-id"):
            value = response.headers.get(header)
            if value:
                return value
        value = payload.get("id")
        return value if isinstance(value, str) and value else None


class ValidatedGeometryProviderRouter:
    """Keep Gemini upstream while replacing only validated geometry generation."""

    def __init__(self, *, primary_provider: Any, geometry_provider: Any) -> None:
        self.primary_provider = primary_provider
        self.geometry_provider = geometry_provider

    @property
    def provider_id(self) -> str:
        return str(getattr(self.geometry_provider, "provider_id", "codex_proxy"))

    @property
    def model(self) -> str | None:
        model = getattr(self.geometry_provider, "model", None)
        return str(model) if model is not None else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.primary_provider, name)

    def provider_settings(self) -> dict[str, Any]:
        primary_settings = self.primary_provider.provider_settings()
        geometry_settings = self.geometry_provider.provider_settings()
        return {
            "routing": "validated_geometry_only",
            "upstream": primary_settings,
            "geometry": geometry_settings,
        }

    def set_validated_attempt_recorder(self, recorder: Callable[[dict[str, Any]], Any] | None) -> None:
        for provider in (self.primary_provider, self.geometry_provider):
            setter = getattr(provider, "set_validated_attempt_recorder", None)
            if callable(setter):
                setter(recorder)

    async def generate_model(self, request: Any) -> Any:
        return await self.primary_provider.generate_model(request)

    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return await self.geometry_provider.generate_cadquery_model(request)

    async def extract_requirements(self, request: Any) -> Any:
        return await self.primary_provider.extract_requirements(request)

    async def create_source_brief(self, request: Any) -> Any:
        return await self.primary_provider.create_source_brief(request)

    async def create_design_plan(self, request: Any) -> Any:
        return await self.primary_provider.create_design_plan(request)

    async def create_revision_plan(self, request: Any) -> Any:
        return await self.primary_provider.create_revision_plan(request)
