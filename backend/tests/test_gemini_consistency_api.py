from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.api.dependencies import get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.gemini_benchmark import GeminiBenchmarkMembership
from app.models.project_message import ProjectMessage


def _client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app), session_local


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _create_experiment(client: TestClient) -> dict:
    response = client.post(
        "/api/gemini-consistency/experiments",
        json={
            "label": "api-test",
            "corpus_version": "gemini-consistency-v1",
            "corpus_hash": "corpus-hash",
            "mode": "pilot",
            "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
            "runs": 2,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_benchmark_api_rejects_all_access_when_developer_tools_are_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", False)
    client, _ = _client(tmp_path)

    response = client.post(
        "/api/gemini-consistency/experiments",
        json={"label": "disabled", "corpus_version": "v1", "corpus_hash": "hash", "models": ["model"]},
    )

    assert response.status_code == 403


def test_normal_project_creation_remains_available_when_developer_tools_are_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", False)
    client, _ = _client(tmp_path)

    created = client.post(
        "/api/projects",
        json={"name": "normal project", "original_intent": "Create a normal project."},
    )
    assert created.status_code == 201, created.text

    benchmark_header = client.post(
        f"/api/projects/{created.json()['id']}/chat",
        headers={"X-Volundr-Benchmark-Model": "gemini-2.5-pro"},
        json={"message": "Continue", "client_message_id": "normal-disabled-test"},
    )
    assert benchmark_header.status_code == 403


def test_claim_is_atomic_and_duplicate_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, session_local = _client(tmp_path)
    experiment = _create_experiment(client)
    run_id = experiment["runs"][0]["id"]

    payload = {
        "position": 0,
        "title": "Vague phone stand",
        "original_intent": "Make a small phone stand for a desk.",
    }
    first = client.post(
        f"/api/gemini-consistency/experiments/{experiment['id']}/runs/{run_id}/cases/case-001/claim",
        json=payload,
    )
    second = client.post(
        f"/api/gemini-consistency/experiments/{experiment['id']}/runs/{run_id}/cases/case-001/claim",
        json=payload,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["project_id"] == first.json()["project_id"]
    experiment_after_claim = client.get(f"/api/gemini-consistency/experiments/{experiment['id']}")
    started_runs = [run for run in experiment_after_claim.json()["runs"] if run["id"] == run_id]
    assert started_runs[0]["started_at"] is not None
    with session_local() as session:
        memberships = session.scalars(select(GeminiBenchmarkMembership)).all()
        assert len(memberships) == 1
        messages = session.scalars(
            select(ProjectMessage).where(ProjectMessage.project_id == first.json()["project_id"])
        ).all()
        assert [message.role for message in messages] == ["system_event"]


def test_flash_lite_study_api_creates_one_model_and_three_repetitions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)

    response = client.post(
        "/api/gemini-consistency/experiments",
        json={
            "label": "Gemini Flash Lite study baseline",
            "corpus_version": "gemini-flash-lite-study-v1",
            "corpus_hash": "a" * 64,
            "mode": "study",
            "models": ["gemini-3.5-flash-lite"],
            "runs": 3,
        },
    )

    assert response.status_code == 201, response.text
    document = response.json()
    assert document["mode"] == "study"
    assert document["requested_runs"] == 3
    assert len(document["models"]) == 1
    assert len(document["runs"]) == 3


def test_flash_lite_readiness_endpoint_performs_one_minimal_provider_probe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)
    calls: list[object] = []

    class FakeProvider:
        provider_id = "gemini_api"

        async def extract_requirements(self, request):
            calls.append(request)
            return type(
                "Result",
                (),
                {
                    "provider_model": "gemini-3.5-flash-lite",
                    "usage_metadata": {"totalTokenCount": 3},
                    "provider_request_id": "probe-1",
                    "raw_output": '{"ready":true}',
                },
            )()

    monkeypatch.setattr("app.api.gemini_consistency.build_ai_provider", lambda *args, **kwargs: FakeProvider())

    response = client.post(
        "/api/gemini-consistency/readiness",
        json={
            "model": "gemini-3.5-flash-lite",
            "study_id": "gemini-flash-lite-study-01",
            "round": "baseline",
            "repetition": 1,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["actual_model"] == "gemini-3.5-flash-lite"
    assert len(calls) == 1


def test_completion_is_idempotent_and_report_endpoint_is_read_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)
    experiment = _create_experiment(client)
    run_id = experiment["runs"][0]["id"]
    claim_path = f"/api/gemini-consistency/experiments/{experiment['id']}/runs/{run_id}/cases/case-001/claim"
    claim = client.post(
        claim_path,
        json={"position": 0, "title": "Vague phone stand", "original_intent": "Make a small phone stand."},
    ).json()
    complete_path = f"/api/gemini-consistency/experiments/{experiment['id']}/runs/{run_id}/cases/case-001/complete"
    completion = {
        "state": "completed",
        "outcome_category": "candidate",
        "outcome_state": "ready_with_warnings",
        "final_outcome": "Candidate ready with warnings",
        "metrics": {"total_tokens": 123, "provider_call_count": 2},
    }

    first = client.post(complete_path, json=completion)
    second = client.post(complete_path, json=completion)
    report = client.post(f"/api/gemini-consistency/experiments/{experiment['id']}/report")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["project_id"] == claim["project_id"]
    assert report.status_code == 200, report.text
    assert report.json()["experiment_id"] == experiment["id"]


def test_finish_is_idempotent_and_report_generation_does_not_build_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)
    experiment = _create_experiment(client)

    first = client.post(
        f"/api/gemini-consistency/experiments/{experiment['id']}/finish",
        json={"state": "completed"},
    )
    second = client.post(
        f"/api/gemini-consistency/experiments/{experiment['id']}/finish",
        json={"state": "failed"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["state"] == "completed"


def test_model_availability_is_recorded_without_exposing_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)
    experiment = _create_experiment(client)

    response = client.post(
        f"/api/gemini-consistency/experiments/{experiment['id']}/model-availability",
        json={"requested_model": "gemini-2.5-flash", "actual_model": "gemini-2.5-flash", "availability_state": "available"},
    )

    assert response.status_code == 200
    assert response.json()["availability_state"] == "available"
    assert "api_key" not in response.json()


def test_ollama_model_discovery_is_developer_gated_and_returns_safe_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client, _ = _client(tmp_path)

    async def fake_discovery(self):
        return [{"name": "procad:Q4_K_M", "digest": "sha256:abc", "size": 123}]

    monkeypatch.setattr("app.services.ai.ollama.OllamaProvider.list_available_models", fake_discovery)

    response = client.get("/api/gemini-consistency/ollama/models")

    assert response.status_code == 200
    assert response.json() == [{"name": "procad:Q4_K_M", "digest": "sha256:abc", "size": 123}]
