"""Opt-in Gemini transport policy for the validated staging application path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.services.gemini_integration.transport import SharedIntegrationRateLimiter
from app.services.validated_cadquery_security import redact_sensitive_payload


@dataclass(frozen=True)
class ValidatedTransportResult:
    operation_id: str
    status_code: int | None
    response_payload: dict[str, Any]
    attempts: list[dict[str, Any]]
    request_payload: dict[str, Any]
    provider_request_id: str | None = None


class ValidatedGeminiTransport:
    """Exactly-once-in-process retry policy with durable-safe attempt metadata."""

    def __init__(
        self,
        *,
        primary_credential: str | None,
        fallback_credential: str | None,
        primary_credential_env: str = "GEMINI_API_KEY_2",
        fallback_credential_env: str | None = "GEMINI_API_KEY",
        primary_limiter: SharedIntegrationRateLimiter | None = None,
        fallback_limiter: SharedIntegrationRateLimiter | None = None,
        global_semaphore: asyncio.Semaphore | None = None,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        attempt_recorder: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.primary_credential = self._validate_credential(primary_credential, "primary")
        self.fallback_credential = self._validate_credential(fallback_credential, "fallback")
        self.primary_credential_env = primary_credential_env
        self.fallback_credential_env = fallback_credential_env
        self.primary_limiter = primary_limiter or SharedIntegrationRateLimiter()
        self.fallback_limiter = fallback_limiter or SharedIntegrationRateLimiter()
        self.global_semaphore = global_semaphore or asyncio.Semaphore(1)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.sleep = sleep
        self.attempt_recorder = attempt_recorder

    async def generate(
        self,
        *,
        endpoint_path: str,
        payload: dict[str, Any],
        operation_id: str | None = None,
    ) -> ValidatedTransportResult:
        if not self.primary_credential:
            raise RuntimeError("primary Gemini credential is not configured")
        operation_id = operation_id or str(uuid.uuid4())
        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        attempts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            first = await self._request(
                client=client,
                endpoint_path=endpoint_path,
                payload=payload,
                operation_id=operation_id,
                attempt_index=0,
                request_hash=request_hash,
                credential_slot="primary",
                credential_env_var=self.primary_credential_env,
                credential=self.primary_credential,
                limiter=self.primary_limiter,
                attempts=attempts,
            )
            if first["status_code"] == 429:
                first["retry_delay_seconds"] = 30.0
                self._record_attempt(first)
                await self.sleep(30.0)
                if not self.fallback_credential:
                    return self._result(operation_id, payload, attempts, first)
                fallback = await self._request(
                    client=client,
                    endpoint_path=endpoint_path,
                    payload=payload,
                    operation_id=operation_id,
                    attempt_index=1,
                    request_hash=request_hash,
                    credential_slot="fallback",
                    credential_env_var=self.fallback_credential_env,
                    credential=self.fallback_credential,
                    limiter=self.fallback_limiter,
                    attempts=attempts,
                )
                self._record_attempt(fallback)
                return self._result(operation_id, payload, attempts, fallback)
            if self._is_transient(first["status_code"]):
                first["retry_delay_seconds"] = 10.0
                self._record_attempt(first)
                await self.sleep(10.0)
                retry = await self._request(
                    client=client,
                    endpoint_path=endpoint_path,
                    payload=payload,
                    operation_id=operation_id,
                    attempt_index=1,
                    request_hash=request_hash,
                    credential_slot="primary",
                    credential_env_var=self.primary_credential_env,
                    credential=self.primary_credential,
                    limiter=self.primary_limiter,
                    attempts=attempts,
                )
                self._record_attempt(retry)
                return self._result(operation_id, payload, attempts, retry)
            self._record_attempt(first)
            return self._result(operation_id, payload, attempts, first)

    async def _request(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint_path: str,
        payload: dict[str, Any],
        operation_id: str,
        attempt_index: int,
        request_hash: str,
        credential_slot: str,
        credential_env_var: str | None,
        credential: str,
        limiter: SharedIntegrationRateLimiter,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started = await limiter.acquire(operation_id=operation_id)
        attempt = {
            "logical_operation_id": operation_id,
            "attempt_id": str(uuid.uuid4()),
            "attempt_index": attempt_index,
            "credential_slot": credential_slot,
            "credential_env_var": credential_env_var,
            "credential_present": True,
            "request_hash": request_hash,
            "status_code": None,
            "failure_class": None,
            "retry_delay_seconds": None,
            "started_monotonic": started,
            "response": {},
        }
        try:
            async with self.global_semaphore:
                response = await asyncio.wait_for(
                    client.post(
                        endpoint_path,
                        headers={"x-goog-api-key": credential},
                        json=payload,
                    ),
                    timeout=self.timeout_seconds,
                )
            status_code = response.status_code
            response_payload = redact_sensitive_payload(
                self._safe_json(response),
                tuple(secret for secret in (self.primary_credential, self.fallback_credential) if secret),
            )
            if not isinstance(response_payload, dict):
                response_payload = {}
            attempt["status_code"] = status_code
            attempt["response"] = response_payload
            attempt["failure_class"] = self._failure_class(status_code)
            attempt["provider_request_id"] = next(
                (
                    response.headers.get(header)
                    for header in ("x-goog-request-id", "x-request-id", "request-id")
                    if response.headers.get(header)
                ),
                None,
            )
        except (TimeoutError, httpx.TimeoutException):
            status_code = 599
            response_payload = {}
            attempt["status_code"] = status_code
            attempt["failure_class"] = "timeout"
        except httpx.HTTPError:
            status_code = 599
            response_payload = {}
            attempt["status_code"] = status_code
            attempt["failure_class"] = "transport_failure"
        attempts.append(attempt)
        return attempt

    def _record_attempt(self, attempt: dict[str, Any]) -> None:
        if self.attempt_recorder is not None:
            self.attempt_recorder(dict(attempt))

    @staticmethod
    def _validate_credential(value: str | None, slot: str) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError(f"{slot} Gemini credential must be text")
        if value != value.strip() or any(character in value for character in "\r\n"):
            raise ValueError(f"{slot} Gemini credential contains surrounding whitespace")
        if value[0] in {"'", '"'} or value[-1] in {"'", '"'}:
            raise ValueError(f"{slot} Gemini credential contains shell quoting")
        return value

    @staticmethod
    def _result(
        operation_id: str,
        payload: dict[str, Any],
        attempts: list[dict[str, Any]],
        final_attempt: dict[str, Any],
    ) -> ValidatedTransportResult:
        return ValidatedTransportResult(
            operation_id=operation_id,
            status_code=final_attempt.get("status_code"),
            response_payload=final_attempt.get("response") or {},
            attempts=attempts,
            request_payload=payload,
            provider_request_id=final_attempt.get("provider_request_id"),
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_transient(status_code: int | None) -> bool:
        return status_code in {408, 502, 503, 504, 599}

    @classmethod
    def _failure_class(cls, status_code: int) -> str | None:
        if status_code < 400:
            return None
        if status_code == 429:
            return "quota_failure"
        if cls._is_transient(status_code):
            return "transport_failure"
        if status_code in {401, 403}:
            return "authentication_failure"
        return "provider_failure"
