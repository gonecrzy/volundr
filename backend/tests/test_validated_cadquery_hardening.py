from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.gemini_integration.transport import SharedIntegrationRateLimiter
from app.services.validated_cadquery_workflow import (
    canonical_idempotency_hash,
    derive_validated_workflow_state,
    safe_relative_artifact_path,
)
from app.testing.e2e_fixture_server import FixtureProvider, FixtureRunner


ACTOR_HEADERS = {"X-Volundr-Internal-Actor": "volundr-single-user"}


def _app_db(tmp_path: Path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db():
        with sessions() as db:
            yield db

    return engine, sessions, override_db


@pytest.fixture()
def validated_client(tmp_path: Path):
    _engine, _sessions, override_db = _app_db(tmp_path)
    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_ai_provider] = lambda: FixtureProvider()
    app.dependency_overrides[get_cad_runner] = lambda: FixtureRunner(tmp_path)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        settings.validated_cadquery_flow_enabled = previous
        app.dependency_overrides.clear()


def _start(client: TestClient, *, key: str = "start-1", actor: dict[str, str] = ACTOR_HEADERS):
    return client.post(
        "/api/validated-cadquery/designs",
        headers={**actor, "Idempotency-Key": key},
        json={"name": "Hardened design", "intent": "Build a printable mounting plate."},
    )


def test_idempotency_hash_excludes_raw_payload_identity() -> None:
    first = canonical_idempotency_hash("start", "same-key", {"intent": "one"})
    second = canonical_idempotency_hash("start", "same-key", {"intent": "one"})
    different = canonical_idempotency_hash("start", "same-key", {"intent": "two"})

    assert first == second
    assert first != different
    assert "one" not in first


def test_workflow_state_invariants_allow_optional_failure_but_block_required_failure() -> None:
    optional_failure = derive_validated_workflow_state(
        [
            {"output_id": "required", "required": True, "state": "completed"},
            {"output_id": "optional", "required": False, "state": "worker_timeout"},
        ]
    )
    required_failure = derive_validated_workflow_state(
        [
            {"output_id": "required", "required": True, "state": "worker_timeout"},
            {"output_id": "optional", "required": False, "state": "completed"},
        ]
    )

    assert optional_failure == "partially_completed"
    assert required_failure == "partially_completed"


def test_artifact_paths_are_relative_and_confined(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    good = root / "nested" / "part.step"
    good.parent.mkdir()
    good.write_text("step", encoding="utf-8")

    assert safe_relative_artifact_path(root, "nested/part.step") == good.resolve()
    for value in ("../escape.step", "/etc/passwd", "nested\\..\\escape.step", "nested/%2e%2e/escape.step", "nested/%00escape.step"):
        with pytest.raises(ValueError):
            safe_relative_artifact_path(root, value)
    outside = tmp_path / "outside.step"
    outside.write_text("outside", encoding="utf-8")
    (root / "linked.step").symlink_to(outside)
    with pytest.raises(ValueError):
        safe_relative_artifact_path(root, "linked.step")


@pytest.mark.asyncio
async def test_validated_gemini_429_fallback_is_exact_and_redacted() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(
            200,
            json={"modelVersion": "gemini-3.5-flash-lite", "candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    records: list[dict[str, object]] = []
    provider = GeminiApiProvider(
        primary_api_key="primary-secret",
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        primary_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        fallback_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        attempt_recorder=records.append,
    )

    text, _model = await provider._run_prompt("same prompt", stage="requirements")

    assert text == "ok"
    assert [request.url.params["key"] for request in requests] == ["primary-secret", "fallback-secret"]
    assert requests[0].content == requests[1].content
    assert sleeps == [30.0]
    assert records[0]["credential_slot"] == "primary"
    assert records[1]["credential_slot"] == "fallback"
    assert records[0]["logical_operation_id"] == records[1]["logical_operation_id"]
    assert records[0]["attempt_id"] != records[1]["attempt_id"]
    assert records[0]["request_hash"] == records[1]["request_hash"]
    assert all(secret not in json.dumps(record, sort_keys=True) for record in records for secret in ("primary-secret", "fallback-secret"))


@pytest.mark.asyncio
async def test_validated_gemini_transport_retries_transient_failure_on_same_key_only() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = 503 if len(requests) == 1 else 200
        return httpx.Response(status, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]} if status == 200 else {"error": {"message": "busy"}})

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = GeminiApiProvider(
        primary_api_key="primary-secret",
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        primary_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        fallback_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
    )

    text, _model = await provider._run_prompt("same prompt", stage="geometry")

    assert text == "ok"
    assert [request.url.params["key"] for request in requests] == ["primary-secret", "primary-secret"]
    assert sleeps == [10.0]


@pytest.mark.asyncio
async def test_validated_gemini_fallback_429_has_no_third_attempt_and_missing_primary_fails_closed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "quota"}})

    async def sleep(_seconds: float) -> None:
        return None

    provider = GeminiApiProvider(
        primary_api_key="primary-secret",
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        primary_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        fallback_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
    )
    with pytest.raises(RuntimeError, match="permitted fallback"):
        await provider._run_prompt("same prompt", stage="requirements")
    assert len(requests) == 2

    no_primary_requests: list[httpx.Request] = []
    no_primary = GeminiApiProvider(
        primary_api_key=None,
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(lambda request: no_primary_requests.append(request) or httpx.Response(200)),
        sleep=sleep,
    )
    with pytest.raises(RuntimeError, match="primary Gemini credential"):
        await no_primary._run_prompt("same prompt", stage="requirements")
    assert no_primary_requests == []


@pytest.mark.asyncio
async def test_validated_gemini_malformed_and_auth_failures_do_not_rotate() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"candidates": []})

    async def sleep(_seconds: float) -> None:
        raise AssertionError("semantic/content failures must not sleep")

    provider = GeminiApiProvider(
        primary_api_key="primary-secret",
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    with pytest.raises(RuntimeError, match="missing response text"):
        await provider._run_prompt("same prompt", stage="requirements")
    assert len(requests) == 1
    assert requests[0].url.params["key"] == "primary-secret"

    auth_requests: list[httpx.Request] = []
    auth_provider = GeminiApiProvider(
        primary_api_key="primary-secret",
        fallback_api_key="fallback-secret",
        validated_transport=True,
        transport=httpx.MockTransport(lambda request: auth_requests.append(request) or httpx.Response(403, json={"error": {}})),
        sleep=sleep,
    )
    with pytest.raises(RuntimeError, match="authentication"):
        await auth_provider._run_prompt("same prompt", stage="requirements")
    assert len(auth_requests) == 1


def test_validated_api_is_idempotent_and_reads_after_flag_disable(validated_client: TestClient) -> None:
    first = _start(validated_client)
    assert first.status_code == 201, first.text
    first_payload = first.json()

    duplicate = _start(validated_client)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first_payload["id"]

    conflict = validated_client.post(
        "/api/validated-cadquery/designs",
        headers={**ACTOR_HEADERS, "Idempotency-Key": "start-1"},
        json={"name": "Different", "intent": "Different design"},
    )
    assert conflict.status_code == 409

    settings.validated_cadquery_flow_enabled = False
    fetched = validated_client.get(
        f"/api/validated-cadquery/workflows/{first_payload['id']}",
        headers=ACTOR_HEADERS,
    )
    assert fetched.status_code == 200
    assert fetched.json()["provenance"].get("selected_route") is None


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Volundr-Actor-Id": "attacker-selected-actor"},
        {"Authorization": "Bearer arbitrary-client-token"},
        {
            "X-Volundr-Actor-Id": "attacker-selected-actor",
            "Authorization": "Bearer arbitrary-client-token",
        },
    ],
)
def test_validated_api_rejects_missing_or_client_selected_authentication(
    validated_client: TestClient,
    headers: dict[str, str],
) -> None:
    response = _start(validated_client, key=f"auth-rejected-{len(headers)}", actor=headers)

    assert response.status_code == 401


def test_validated_api_internal_boundary_derives_fixed_single_user_actor(
    validated_client: TestClient,
) -> None:
    started = _start(validated_client, key="auth-fixed-actor")
    assert started.status_code == 201, started.text

    spoofed = validated_client.get(
        f"/api/validated-cadquery/workflows/{started.json()['id']}",
        headers={"X-Volundr-Actor-Id": "another-actor"},
    )
    assert spoofed.status_code == 401


def test_validated_api_rejects_non_proxy_internal_actor(validated_client: TestClient) -> None:
    response = _start(
        validated_client,
        key="auth-wrong-proxy-actor",
        actor={"X-Volundr-Internal-Actor": "another-actor"},
    )

    assert response.status_code == 401


def test_nginx_overwrites_identity_headers() -> None:
    nginx = Path(__file__).parents[2].joinpath("frontend", "nginx.conf").read_text(encoding="utf-8")

    assert 'proxy_set_header X-Volundr-Actor-Id "";' in nginx
    assert 'proxy_set_header Authorization "";' in nginx
    assert 'proxy_set_header X-Volundr-Internal-Actor "volundr-single-user";' in nginx
    assert 'proxy_set_header X-Volundr-Internal-Actor $http_' not in nginx


def test_auth_boundary_does_not_serialize_a_server_token_or_credentials() -> None:
    source_root = Path(__file__).parents[2]
    frontend_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.joinpath("frontend", "src").rglob("*.ts*")
    )
    compose = source_root.joinpath("docker-compose.yml").read_text(encoding="utf-8")

    assert "GEMINI_API_KEY" not in frontend_source
    assert "VOLUNDR_API_AUTH_TOKEN" not in frontend_source
    worker_block = compose.split("\n  volundr-cad-worker:\n", 1)[1]
    assert "GEMINI_API_KEY" not in worker_block
    assert "X-Volundr-Internal-Actor" not in worker_block


def test_validated_api_rejects_cross_actor_and_wrong_project(validated_client: TestClient) -> None:
    created = _start(validated_client, key="auth-1").json()
    denied = validated_client.get(
        f"/api/validated-cadquery/workflows/{created['id']}",
        headers={"X-Volundr-Actor-Id": "staging-user-2"},
    )
    assert denied.status_code in {401, 403, 404}

    wrong_project = validated_client.get(
        f"/api/projects/not-the-project/designs/{created['id']}",
        headers=ACTOR_HEADERS,
    )
    assert wrong_project.status_code in {403, 404}


def test_restart_reconciliation_records_durable_failure(tmp_path: Path) -> None:
    from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService

    engine, sessions, _override = _app_db(tmp_path)
    with Session(engine) as db:
        from app.models.project import Project

        project = Project(name="Restart", slug="restart", original_intent="restart")
        db.add(project)
        db.flush()
        workflow = ValidatedCadQueryWorkflow(
            project_id=project.id,
            owner_id="actor",
            state="worker_running",
            user_instruction="restart",
        )
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id

    with sessions() as db:
        ValidatedCadQueryWorkflowService.reconcile_after_restart(db=db, data_dir=tmp_path)
        recovered = db.get(ValidatedCadQueryWorkflow, workflow_id)
        assert recovered is not None
        assert recovered.state == "failed"
        assert "restart" in recovered.diagnostics_json.lower()


def test_provider_attempt_metadata_is_durable_and_contains_no_secret(tmp_path: Path) -> None:
    from app.models.project import Project
    from app.models.validated_cadquery_provider_attempt import ValidatedCadQueryProviderAttempt
    from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService

    engine, _sessions, _override = _app_db(tmp_path)
    with Session(engine) as db:
        project = Project(name="Provider", slug="provider", original_intent="provider")
        db.add(project)
        db.flush()
        workflow = ValidatedCadQueryWorkflow(
            project_id=project.id,
            owner_id="actor",
            state="worker_running",
            user_instruction="provider",
        )
        db.add(workflow)
        db.commit()
        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path, owner_id="actor")
        service._active_workflow_id = workflow.id
        service._persist_provider_attempt(
            {
                "logical_operation_id": "logical-1",
                "attempt_id": "attempt-1",
                "credential_slot": "primary",
                "credential_env_var": "GEMINI_API_KEY_2",
                "credential_present": True,
                "request_hash": "a" * 64,
                "status_code": 429,
                "failure_class": "quota_failure",
                "retry_delay_seconds": 30,
            }
        )
        record = db.scalar(select(ValidatedCadQueryProviderAttempt))
        assert record is not None
        assert record.status_code == 429
        assert record.credential_env_var == "GEMINI_API_KEY_2"
        assert all("secret" not in str(getattr(record, field)) for field in record.__table__.columns.keys())
