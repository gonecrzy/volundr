import asyncio
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


class OllamaProvider(GeminiCliProvider):
    """Ollama transport using the existing Volundr prompt contracts."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout_seconds = timeout_seconds or settings.ollama_timeout_seconds
        self._transport = transport

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        prompt = self.build_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return ModelGenerationResult(
            raw_output=raw_output,
            provider="ollama",
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
            provider="ollama",
            provider_model=self.model,
        )

    async def create_source_brief(self, request: SourceBriefRequest) -> SourceBriefResult:
        prompt = self.build_source_brief_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return SourceBriefResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self.model,
        )

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        prompt = self.build_design_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return DesignPlanResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self.model,
        )

    async def create_revision_plan(self, request: RevisionPlanRequest) -> RevisionPlanResult:
        prompt = self.build_revision_plan_prompt(request)
        raw_output = await self._run_prompt(prompt)
        return RevisionPlanResult(
            raw_output=raw_output,
            provider="ollama",
            provider_model=self.model,
        )

    async def _run_prompt(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await asyncio.wait_for(
                    client.post("/api/generate", json=payload),
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
            response_payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama response was not valid JSON") from exc

        raw_output = response_payload.get("response")
        if not isinstance(raw_output, str):
            raise RuntimeError("Ollama response missing response text")
        return raw_output

    def provider_settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "endpoint": "/api/generate",
            "stream": False,
            "auth_mode": "local_ollama",
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
