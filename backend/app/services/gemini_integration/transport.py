from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from app.services.gemini_integration.profile import (
    SECONDARY_CREDENTIAL_ENV,
    GeminiFlashLiteContractV1,
)


TRANSPORT_STATUSES = {408, 502, 503, 504, 599}


@dataclass(frozen=True)
class SecondaryCredential:
    value: str
    metadata: dict[str, Any]


def load_secondary_credential() -> SecondaryCredential:
    value = os.environ.get(SECONDARY_CREDENTIAL_ENV)
    if not value:
        raise RuntimeError(f"{SECONDARY_CREDENTIAL_ENV} is absent; no provider call was attempted")
    return SecondaryCredential(
        value=value,
        metadata={
            "environment_variable": SECONDARY_CREDENTIAL_ENV,
            "credential_slot": "secondary",
            "credential_present": True,
        },
    )


def retry_delay_seconds(status_code: int | None, attempt_index: int) -> float | None:
    if attempt_index != 0:
        return None
    if status_code == 429:
        return 30.0
    if status_code in TRANSPORT_STATUSES:
        return 10.0
    return None


@dataclass
class SharedIntegrationRateLimiter:
    requests_per_minute: int = 12
    hard_max_requests_per_window: int = 15
    minimum_gap_seconds: float = 5.0
    window_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    starts: list[float] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def acquire(self, *, operation_id: str) -> float:
        async with self._lock:
            while True:
                now = self.clock()
                self.starts = [start for start in self.starts if now - start < self.window_seconds]
                wait = 0.0
                if self.starts:
                    wait = max(wait, self.minimum_gap_seconds - (now - self.starts[-1]))
                if len(self.starts) >= self.hard_max_requests_per_window:
                    wait = max(wait, self.window_seconds - (now - self.starts[0]))
                if wait <= 0:
                    break
                await self.sleep(wait)
            started = self.clock()
            self.starts.append(started)
            self.events.append({"operation_id": operation_id, "started_monotonic": started})
            return started


@dataclass(frozen=True)
class ProviderCallResult:
    operation_id: str
    text: str | None
    complete: bool
    attempts: list[dict[str, Any]]
    request_payload: dict[str, Any]
    actual_model: str | None = None
    usage_metadata: dict[str, Any] | None = None


class SecondaryGeminiClient:
    """Secondary-only Gemini transport for the explicit integration runner."""

    def __init__(
        self,
        profile: GeminiFlashLiteContractV1,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: SharedIntegrationRateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        attempt_recorder: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.profile = profile
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.limiter = limiter or SharedIntegrationRateLimiter()
        self.sleep = sleep
        self.attempt_recorder = attempt_recorder

    async def generate(self, *, stage: str, prompt: str, operation_id: str) -> ProviderCallResult:
        credential = load_secondary_credential()
        configuration = self.profile.request_configuration(stage)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": configuration["generationConfig"],
        }
        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        attempts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt_index in range(2):
                started = await self.limiter.acquire(operation_id=operation_id)
                attempt_id = f"{operation_id}:attempt-{attempt_index + 1}"
                try:
                    response = await client.post(
                        f"/models/{self.profile.model}:generateContent",
                        params={"key": credential.value},
                        json=payload,
                    )
                    status_code = response.status_code
                    response_payload = self._safe_json(response)
                    error_class = None if status_code < 400 else self._failure_class(status_code)
                except httpx.TimeoutException as exc:
                    response = None
                    status_code = 599
                    response_payload = None
                    error_class = "transport_failure"
                    error_message = str(exc)
                except httpx.HTTPError as exc:
                    response = None
                    status_code = 599
                    response_payload = None
                    error_class = "transport_failure"
                    error_message = str(exc)
                else:
                    error_message = None
                attempt = {
                    "operation_id": operation_id,
                    "attempt_id": attempt_id,
                    "attempt_index": attempt_index,
                    "stage": stage,
                    "status_code": status_code,
                    "request_hash": request_hash,
                    "started_monotonic": started,
                    "actual_model": (response_payload or {}).get("modelVersion") if isinstance(response_payload, dict) else None,
                    "usage_metadata": (response_payload or {}).get("usageMetadata") if isinstance(response_payload, dict) else None,
                    "failure_class": error_class,
                    "error_message": error_message,
                    "retry_delay_seconds": None,
                    "request": payload,
                    "response": response_payload,
                    "credential": credential.metadata,
                }
                attempts.append(attempt)
                if self.attempt_recorder is not None:
                    self.attempt_recorder(dict(attempt))
                if status_code is not None and status_code < 400:
                    text = self._response_text(response_payload)
                    if text:
                        return ProviderCallResult(
                            operation_id=operation_id,
                            text=text,
                            complete=True,
                            attempts=attempts,
                            request_payload=payload,
                            actual_model=attempt.get("actual_model"),
                            usage_metadata=attempt.get("usage_metadata"),
                        )
                    attempt["failure_class"] = "provider_content_failure"
                    return ProviderCallResult(operation_id, None, False, attempts, payload)
                delay = retry_delay_seconds(status_code, attempt_index)
                if delay is None:
                    break
                attempt["retry_delay_seconds"] = delay
                await self.sleep(delay)
        return ProviderCallResult(
            operation_id=operation_id,
            text=None,
            complete=False,
            attempts=attempts,
            request_payload=payload,
            actual_model=None,
            usage_metadata=None,
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
        try:
            value = response.json()
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _response_text(payload: dict[str, Any] | None) -> str | None:
        if not isinstance(payload, dict):
            return None
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return None
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            text = "".join(str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("text") is not None)
            if text:
                return text
        return None

    @staticmethod
    def _failure_class(status_code: int) -> str:
        if status_code == 429:
            return "quota_failure"
        if status_code in TRANSPORT_STATUSES:
            return "transport_failure"
        return "provider_failure"


__all__ = [
    "ProviderCallResult",
    "SecondaryCredential",
    "SecondaryGeminiClient",
    "SharedIntegrationRateLimiter",
    "load_secondary_credential",
    "retry_delay_seconds",
]

