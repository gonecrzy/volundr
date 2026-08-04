import asyncio
import os
import re
from typing import Any, Callable

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
        max_retries: int | None = None,
        max_retry_sleep_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        model_policy: GeminiModelPolicy | None = None,
        interaction_recorder: Callable[..., Any] | None = None,
        response_processor: Callable[..., tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        resolved_policy = model_policy or GeminiModelPolicy.from_settings(
            settings,
            general_model=model,
        )
        super().__init__(
            model=model,
            timeout_seconds=timeout_seconds,
            model_policy=resolved_policy,
        )
        self.api_key = (
            api_key
            if api_key is not None
            else settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        )
        self.base_url = (base_url or settings.gemini_api_base_url).rstrip("/")
        self.model = model or resolved_policy.general_model
        self.timeout_seconds = timeout_seconds or settings.gemini_timeout_seconds
        self.temperature = (
            temperature
            if temperature is not None
            else resolved_policy.temperature
        )
        self.max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else resolved_policy.max_output_tokens
        )
        self.thinking_level = (
            thinking_level
            if thinking_level is not None
            else resolved_policy.thinking_level
        )
        self.max_retries = (
            max_retries if max_retries is not None else resolved_policy.max_retries
        )
        self.max_retry_sleep_seconds = (
            max_retry_sleep_seconds
            if max_retry_sleep_seconds is not None
            else resolved_policy.max_retry_sleep_seconds
        )
        self._transport = transport
        self._interaction_recorder = interaction_recorder
        self._response_processor = response_processor
        self._last_processing_metadata: dict[str, Any] = {}

    @property
    def provider_id(self) -> str:
        return "gemini_api"

    async def list_available_models(self) -> list[dict[str, Any]]:
        """Return safe metadata for models that support generateContent."""

        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        models: list[dict[str, Any]] = []
        page_token: str | None = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self._transport,
        ) as client:
            while True:
                params: dict[str, str] = {"key": self.api_key}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get("/models", params=params)
                if response.status_code >= 400:
                    raise RuntimeError(self._error_message(response))
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError("Gemini model list response was not valid JSON") from exc
                for item in payload.get("models", []) if isinstance(payload, dict) else []:
                    if not isinstance(item, dict):
                        continue
                    methods = item.get("supportedGenerationMethods")
                    if not isinstance(methods, list) or "generateContent" not in methods:
                        continue
                    raw_name = item.get("name")
                    if not isinstance(raw_name, str):
                        continue
                    name = raw_name.removeprefix("models/")
                    try:
                        GeminiModelPolicy._validate_model(name)
                    except ValueError:
                        continue
                    models.append(
                        {
                            "name": name,
                            "display_name": str(item.get("displayName") or name),
                            "supported_generation_methods": ["generateContent"],
                        }
                    )
                page_token = payload.get("nextPageToken") if isinstance(payload, dict) else None
                if not isinstance(page_token, str) or not page_token:
                    break
        return sorted(models, key=lambda item: item["name"])

    async def _run_prompt(
        self,
        prompt: str,
        *,
        model: str | None = None,
        stage: str = "provider",
        prompt_mode: str = "provider",
        processing_context: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")

        self._last_usage_metadata = None
        self._last_provider_request_id = None
        self._last_provider_call_count = 0
        self._last_provider_retry_count = 0
        self._last_processing_metadata = {}

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
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self._transport,
        ) as client:
            for attempt in range(max(0, self.max_retries) + 1):
                self._last_provider_call_count += 1
                if attempt > 0:
                    self._last_provider_retry_count += 1
                try:
                    response = await asyncio.wait_for(
                        client.post(
                            self._endpoint_path(model),
                            params={"key": self.api_key},
                            json=payload,
                        ),
                        timeout=self.timeout_seconds,
                    )
                except TimeoutError as exc:
                    self._record_interaction(
                        stage=stage,
                        prompt_mode=prompt_mode,
                        requested_model=model or self.model,
                        actual_model=None,
                        prompt=prompt,
                        request_payload=payload,
                        response_payload=None,
                        raw_text=None,
                        status_code=None,
                        provider_metadata={},
                        usage_metadata=None,
                        latency_ms=self.timeout_seconds * 1000,
                        transport_retries=attempt,
                        error_category="provider_timeout",
                    )
                    raise RuntimeError(
                        f"Gemini API request timed out after {self.timeout_seconds} seconds"
                    ) from exc
                except httpx.TimeoutException as exc:
                    self._record_interaction(
                        stage=stage,
                        prompt_mode=prompt_mode,
                        requested_model=model or self.model,
                        actual_model=None,
                        prompt=prompt,
                        request_payload=payload,
                        response_payload=None,
                        raw_text=None,
                        status_code=None,
                        provider_metadata={},
                        usage_metadata=None,
                        latency_ms=self.timeout_seconds * 1000,
                        transport_retries=attempt,
                        error_category="provider_timeout",
                    )
                    raise RuntimeError(
                        f"Gemini API request timed out after {self.timeout_seconds} seconds"
                    ) from exc
                except httpx.HTTPError as exc:
                    self._record_interaction(
                        stage=stage,
                        prompt_mode=prompt_mode,
                        requested_model=model or self.model,
                        actual_model=None,
                        prompt=prompt,
                        request_payload=payload,
                        response_payload=None,
                        raw_text=None,
                        status_code=None,
                        provider_metadata={},
                        usage_metadata=None,
                        latency_ms=0,
                        transport_retries=attempt,
                        error_category="provider_transport_failure",
                    )
                    raise RuntimeError(f"Gemini API request failed: {exc}") from exc

                if response.status_code < 400:
                    response_payload = self._safe_json(response)
                    usage_metadata = response_payload.get("usageMetadata") if isinstance(response_payload, dict) else None
                    raw_output = self._response_text(response_payload) if isinstance(response_payload, dict) else ""
                    actual_model = response_payload.get("modelVersion") if isinstance(response_payload, dict) else None
                    if not isinstance(actual_model, str) or not actual_model:
                        actual_model = model or self.model or ""
                    self._record_interaction(
                        stage=stage,
                        prompt_mode=prompt_mode,
                        requested_model=model or self.model,
                        actual_model=actual_model,
                        prompt=prompt,
                        request_payload=payload,
                        response_payload=response_payload if isinstance(response_payload, dict) else None,
                        raw_text=raw_output,
                        status_code=response.status_code,
                        provider_metadata={"request_id": next((response.headers.get(header) for header in ("x-goog-request-id", "x-request-id", "request-id") if response.headers.get(header)), None)},
                        usage_metadata=usage_metadata if isinstance(usage_metadata, dict) else None,
                        latency_ms=0,
                        transport_retries=attempt,
                        error_category=None if raw_output else "provider_content_failure",
                    )
                    break
                error_payload = self._safe_json(response)
                error_message = self._error_message(response)
                self._record_interaction(
                    stage=stage,
                    prompt_mode=prompt_mode,
                    requested_model=model or self.model,
                    actual_model=None,
                    prompt=prompt,
                    request_payload=payload,
                    response_payload=error_payload,
                    raw_text=None,
                    status_code=response.status_code,
                    provider_metadata={"request_id": next((response.headers.get(header) for header in ("x-goog-request-id", "x-request-id", "request-id") if response.headers.get(header)), None)},
                    usage_metadata=None,
                    latency_ms=0,
                    transport_retries=attempt,
                    error_category=self._provider_error_category(response.status_code, error_message),
                )
                retry_delay = self._retry_delay_seconds(response)
                if retry_delay is None or attempt >= max(0, self.max_retries):
                    raise RuntimeError(self._error_message(response))
                await asyncio.sleep(retry_delay)

        response_payload = self._safe_json(response)
        if not response_payload:
            raise RuntimeError("Gemini API response was not valid JSON")

        raw_output = self._response_text(response_payload)
        if not raw_output:
            raise RuntimeError("Gemini API response missing response text")
        usage_metadata = response_payload.get("usageMetadata")
        if not isinstance(usage_metadata, dict):
            usage_metadata = None
        provider_request_id = next(
            (
                response.headers.get(header)
                for header in ("x-goog-request-id", "x-request-id", "request-id")
                if response.headers.get(header)
            ),
            None,
        )
        actual_model = response_payload.get("modelVersion")
        if not isinstance(actual_model, str) or not actual_model:
            actual_model = model or self.model or ""
        self._last_usage_metadata = usage_metadata
        self._last_provider_request_id = provider_request_id
        if self._response_processor is not None:
            processed_output, metadata = self._response_processor(
                raw_output,
                stage=stage,
                context=processing_context or self._processing_context(prompt_mode),
            )
            if not isinstance(processed_output, str) or not processed_output.strip():
                raise RuntimeError("benchmark response processor returned an empty response")
            raw_output = processed_output
            self._last_processing_metadata = dict(metadata or {})
        return raw_output, actual_model

    @staticmethod
    def _processing_context(prompt_mode: str) -> dict[str, Any]:
        return {"request_kind": prompt_mode}

    @staticmethod
    def _processing_context_for_request(request: Any) -> dict[str, Any]:
        request_name = type(request).__name__
        request_kind = {
            "RequirementExtractionRequest": "requirements",
            "DesignPlanRequest": "design_plan",
            "ModelGenerationRequest": "geometry",
            "RevisionPlanRequest": "revision_planning",
        }.get(request_name, request_name.removesuffix("Request").casefold())
        context = {
            "request_kind": request_kind,
        }
        manifest = getattr(request, "geometry_slot_manifest", None)
        if isinstance(manifest, dict):
            context["slot_function_ids"] = {
                str(slot.get("slot_id")): slot.get("function_id")
                for slot in manifest.get("slots", [])
                if isinstance(slot, dict) and slot.get("slot_id") is not None
            }
        return context

    def _record_interaction(self, **payload: Any) -> None:
        if self._interaction_recorder is None:
            return
        try:
            self._interaction_recorder(**payload)
        except TypeError:
            try:
                self._interaction_recorder(payload)
            except Exception:
                return
        except Exception:
            # Evidence capture must never change ordinary provider behavior.
            return

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _provider_error_category(status_code: int, message: str) -> str:
        lowered = message.casefold()
        if status_code == 429 or "quota" in lowered or "resource_exhausted" in lowered:
            return "provider_quota_exhausted"
        if status_code == 408 or "timeout" in lowered:
            return "provider_timeout"
        if status_code in {502, 503, 504}:
            return "provider_transport_failure"
        return "provider_content_failure"

    def provider_settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "endpoint": self._endpoint_path(),
            "auth_mode": "api_key" if self.api_key else "missing_api_key",
            "thinking_level": self.thinking_level,
            "max_retries": self.max_retries,
            "max_retry_sleep_seconds": self.max_retry_sleep_seconds,
        }

    def _endpoint_path(self, model: str | None = None) -> str:
        return f"/{self._model_path(model)}:generateContent"

    def _model_path(self, model: str | None = None) -> str:
        selected_model = model or self.model or "gemini-3.5-flash-lite"
        if selected_model.startswith("models/"):
            return selected_model
        return f"models/{selected_model}"

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

    def _retry_delay_seconds(self, response: httpx.Response) -> float | None:
        if response.status_code not in {429, 503}:
            return None

        header_delay = self._parse_retry_delay(response.headers.get("retry-after"))
        if header_delay is not None:
            return min(header_delay, self.max_retry_sleep_seconds)

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        retry_info_delay = self._retry_delay_from_details(payload)
        if retry_info_delay is not None:
            return min(retry_info_delay, self.max_retry_sleep_seconds)

        message_delay = self._parse_retry_delay(self._error_message(response))
        if message_delay is not None:
            return min(message_delay, self.max_retry_sleep_seconds)

        return min(2.0, self.max_retry_sleep_seconds)

    def _retry_delay_from_details(self, payload: dict[str, Any]) -> float | None:
        error = payload.get("error")
        if not isinstance(error, dict):
            return None
        details = error.get("details")
        if not isinstance(details, list):
            return None
        for detail in details:
            if not isinstance(detail, dict):
                continue
            retry_delay = detail.get("retryDelay")
            if isinstance(retry_delay, str):
                parsed = self._parse_retry_delay(retry_delay)
                if parsed is not None:
                    return parsed
        return None

    def _parse_retry_delay(self, value: str | None) -> float | None:
        if not value:
            return None
        stripped = value.strip()
        try:
            return max(0.0, float(stripped))
        except ValueError:
            pass

        direct_match = re.fullmatch(r"(?P<seconds>\d+(?:\.\d+)?)s", stripped)
        if direct_match:
            return float(direct_match.group("seconds"))

        direct_ms_match = re.fullmatch(r"(?P<milliseconds>\d+(?:\.\d+)?)ms", stripped)
        if direct_ms_match:
            return float(direct_ms_match.group("milliseconds")) / 1000.0

        message_match = re.search(
            r"retry\s+in\s+(?P<delay>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)",
            stripped,
            flags=re.IGNORECASE,
        )
        if message_match:
            delay = float(message_match.group("delay"))
            if message_match.group("unit").lower() == "ms":
                return delay / 1000.0
            return delay

        return None

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
