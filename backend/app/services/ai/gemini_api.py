import asyncio
import os
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.gemini_cli import GeminiCliProvider
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


class GeminiApiProvider(GeminiCliProvider):
    """Gemini Generative Language API transport using Volundr prompt contracts."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.base_url = (base_url or settings.gemini_api_base_url).rstrip("/")
        self.model = model or settings.gemini_model
        self.timeout_seconds = timeout_seconds or settings.gemini_timeout_seconds
        self.temperature = (
            temperature
            if temperature is not None
            else settings.gemini_api_temperature
        )
        self.max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else settings.gemini_api_max_output_tokens
        )
        self.thinking_level = (
            thinking_level
            if thinking_level is not None
            else settings.gemini_api_thinking_level
        )
        self._transport = transport

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        prompt = self.build_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return ModelGenerationResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def generate_cadquery_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        prompt = self.build_cadquery_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return ModelGenerationResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        prompt = self.build_requirement_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return RequirementExtractionResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def create_source_brief(self, request: SourceBriefRequest) -> SourceBriefResult:
        prompt = self.build_source_brief_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return SourceBriefResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        prompt = self.build_design_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return DesignPlanResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def create_revision_plan(self, request: RevisionPlanRequest) -> RevisionPlanResult:
        prompt = self.build_revision_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return RevisionPlanResult(
            raw_output=raw_output,
            provider="gemini_api",
            provider_model=self.model,
        )

    async def _run_prompt(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")

        generation_config: dict[str, Any] = {
            "temperature": self.temperature,
            "topP": 0.95,
            "maxOutputTokens": self.max_output_tokens,
        }
        thinking_level = self._normalized_thinking_level()
        if thinking_level:
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": generation_config,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await asyncio.wait_for(
                    client.post(
                        self._endpoint_path(),
                        params={"key": self.api_key},
                        json=payload,
                    ),
                    timeout=self.timeout_seconds,
                )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Gemini API request timed out after {self.timeout_seconds} seconds"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Gemini API request timed out after {self.timeout_seconds} seconds"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        if response.status_code >= 400:
            raise RuntimeError(self._error_message(response))

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Gemini API response was not valid JSON") from exc

        raw_output = self._response_text(response_payload)
        if not raw_output:
            raise RuntimeError("Gemini API response missing response text")
        return raw_output

    def provider_settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "endpoint": self._endpoint_path(),
            "auth_mode": "api_key" if self.api_key else "missing_api_key",
            "thinking_level": self.thinking_level,
        }

    def _endpoint_path(self) -> str:
        return f"/{self._model_path()}:generateContent"

    def _model_path(self) -> str:
        model = self.model or "gemini-3.5-flash-lite"
        if model.startswith("models/"):
            return model
        return f"models/{model}"

    def _response_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        first = candidates[0]
        if not isinstance(first, dict):
            return ""
        content = first.get("content")
        if not isinstance(content, dict):
            return ""
        parts = content.get("parts")
        if not isinstance(parts, list):
            return ""
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )

    def _normalized_thinking_level(self) -> str | None:
        if self.thinking_level is None:
            return None
        value = self.thinking_level.strip().lower()
        if value in {"", "none", "off", "false", "0"}:
            return None
        allowed = {"minimal", "low", "medium", "high"}
        if value not in allowed:
            raise RuntimeError(
                "Gemini API thinking level must be one of: minimal, low, medium, high, "
                "or empty/off"
            )
        return value.upper()

    def _error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or f"Gemini API request failed with HTTP {response.status_code}"
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        return f"Gemini API request failed with HTTP {response.status_code}"
