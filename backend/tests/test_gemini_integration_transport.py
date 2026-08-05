import asyncio
from pathlib import Path

import httpx
import pytest

from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.transport import (
    SharedIntegrationRateLimiter,
    SecondaryGeminiClient,
    load_secondary_credential,
    retry_delay_seconds,
)


def _profile():
    from pathlib import Path

    return GeminiFlashLiteContractV1.from_repository(Path(__file__).resolve().parents[2])


def test_only_secondary_credential_is_allowed(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "primary-secret")

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY_2"):
        load_secondary_credential(dotenv_path=Path("/tmp/gemini-integration-no-credential.env"))

    monkeypatch.setenv("GEMINI_API_KEY_2", "secondary-secret")
    credential = load_secondary_credential()
    assert credential.value == "secondary-secret"
    assert credential.metadata == {
        "environment_variable": "GEMINI_API_KEY_2",
        "credential_slot": "secondary",
        "credential_present": True,
    }


def test_secondary_credential_can_be_read_from_explicit_dotenv_without_loading_primary(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "primary-secret")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "GEMINI_API_KEY=primary-secret\nexport GEMINI_API_KEY_2='secondary-from-dotenv'\n",
        encoding="utf-8",
    )

    credential = load_secondary_credential(dotenv_path=dotenv)

    assert credential.value == "secondary-from-dotenv"


def test_retry_delays_are_frozen_and_no_third_attempt_is_permitted() -> None:
    assert retry_delay_seconds(429, 0) == 30.0
    assert retry_delay_seconds(429, 1) is None
    assert retry_delay_seconds(502, 0) == 10.0
    assert retry_delay_seconds(503, 1) is None
    assert retry_delay_seconds(400, 0) is None


@pytest.mark.asyncio
async def test_client_retries_first_429_identically_once(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY_2", "secondary-secret")
    responses = [
        httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}),
        httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "late"}]}}]}),
    ]
    requests: list[httpx.Request] = []
    waits: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = SecondaryGeminiClient(
        _profile(),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0),
    )
    result = await client.generate(stage="requirements", prompt="frozen", operation_id="op-1")

    assert result.complete is False
    assert len(result.attempts) == 2
    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    assert waits == [30.0]


@pytest.mark.asyncio
async def test_transport_failure_receives_one_retry_and_counts_both_attempts(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY_2", "secondary-secret")
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    client = SecondaryGeminiClient(
        _profile(),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0),
    )
    result = await client.generate(stage="geometry", prompt="frozen", operation_id="op-2")

    assert result.complete is True
    assert result.text == "ok"
    assert len(result.attempts) == 2
    assert waits == [10.0]
