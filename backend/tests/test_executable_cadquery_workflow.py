from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_cad_runner, get_data_dir, get_workflow_ai_provider
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.executable_cadquery.fixtures import (
    FROZEN_MOUNTING_BRACKET_CONTRACT,
    valid_mounting_bracket_source,
)
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService
from app.services.executable_cadquery.corpus import REPEATABILITY_CORPUS_SCHEMA_VERSION
from app.services.executable_cadquery.workflow import complete_executable_semantic_coverage


class CompleteSourceFixtureProvider:
    provider_id = "gemini_api"

    def __init__(self) -> None:
        self.requests: list[ModelGenerationRequest] = []

    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.requests.append(request)
        source = valid_mounting_bracket_source()
        if request.executable_repair_envelope and request.executable_repair_envelope.get("repair_level") == "L4":
            source = source.replace("rect(40.0, 20.0)", "rect(46.0, 24.0)")
        return ModelGenerationResult(
            raw_output=source,
            provider="gemini_api",
            provider_model="fixture-gemini",
        )


def test_opt_in_repeatability_manifest_selects_the_exact_prompt_contract(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPEATABILITY_CORPUS_SCHEMA_VERSION,
                "projects": [
                    {
                        "project_id": "project-01",
                        "prompt": "A frozen repeatability prompt.",
                        "contract": FROZEN_MOUNTING_BRACKET_CONTRACT,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "executable_cadquery_corpus_manifest_path", manifest_path)

    service = ExecutableCadQueryWorkflowService(db=None, data_dir=tmp_path)
    contract = service._materialize_contract(
        "database-project",
        "workflow-id",
        ordinal=1,
        prompt="A frozen repeatability prompt.",
    )

    assert contract["outputs"][0]["output_id"] == "mounting_bracket"
    assert contract["project_id"] == "database-project"


def test_executable_flow_rejects_missing_contract_instead_of_using_a_fixture(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "executable_cadquery_corpus_manifest_path", None)

    service = ExecutableCadQueryWorkflowService(db=None, data_dir=tmp_path)

    with pytest.raises(ValueError, match="explicit persisted design contract"):
        service._materialize_contract(
            "database-project",
            "workflow-id",
            ordinal=1,
            prompt="An unregistered executable design request.",
        )


def test_incomplete_semantic_coverage_cannot_be_reported_as_passed() -> None:
    result = complete_executable_semantic_coverage(
        {
            "status": "passed",
            "passed": ["topology"],
            "failed": [],
            "unverifiable": [],
            "findings": [{"requirement_id": "topology", "status": "passed"}],
        },
        {
            "requirements": [{"requirement_id": "coaxial_diameters"}],
        },
    )

    assert result["status"] == "unsupported_verifier"
    assert result["unverifiable"] == ["coaxial_diameters"]
    assert result["unsupported_verifier"] == ["coaxial_diameters"]


def test_recovery_recheck_reuses_persisted_artifacts_without_provider_work() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-05/revision/source.py"
    stl_path = "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-05/revision/stl/mating_insert.stl"
    step_path = "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-05/revision/step/mating_insert.step"
    revision = SimpleNamespace(
        id="recheck-revision",
        status="succeeded",
        source_path=str(source_path.relative_to(repo_root)),
        source_hash=None,
        outputs=[
            SimpleNamespace(
                output_id="mating_insert",
                stl_path=stl_path,
                step_path=step_path,
                topology_metadata_json=json.dumps(
                    {
                        "valid": True,
                        "detected_solid_count": 1,
                        "expected_solid_count": 1,
                    }
                ),
            )
        ],
    )

    class FakeDb:
        def get(self, _model, _revision_id):
            return revision

    service = ExecutableCadQueryWorkflowService(db=FakeDb(), data_dir=repo_root)
    result = service._reevaluate_revision_evidence(
        revision,
        {
            "outputs": [{"output_id": "mating_insert", "expected_solid_count": 1}],
            "requirements": [],
        },
    )

    assert result["status"] == "passed"
    assert result["failure_class"] is None
    assert result["semantic_result"]["status"] == "passed"
    assert result["comparison_facts"]["completed_output_ids"] == ["mating_insert"]


def test_package_failure_persists_retry_before_existing_package_service() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = SimpleNamespace(
        package_path=None,
        revision_id="revision-id",
        diagnostics_json=json.dumps({"kind": "package_generation", "message": "initial failure"}),
        provenance_json="{}",
        state="failed",
        state_version=0,
    )

    class FakeDb:
        def commit(self) -> None:
            return None

        def get(self, _model, _revision_id):
            return SimpleNamespace(id="revision-id")

    service = ExecutableCadQueryWorkflowService(db=FakeDb(), data_dir=repo_root)

    def existing_package_service(_workflow, _revision) -> None:
        workflow.package_path = "backend/pyproject.toml"

    service._create_package = existing_package_service
    service._recover_package_generation(workflow)

    provenance = json.loads(workflow.provenance_json)
    assert provenance["recovery_decisions"][0]["recommended_action"] == "retry_stage"
    assert provenance["recovery_decisions"][0]["observation"]["attempt_ordinal"] == 1
    assert provenance["recovery_executions"] == [
        {
            "action": "retry_stage",
            "diagnostic": None,
            "executed": True,
            "package_available": True,
            "provider_calls": 0,
            "worker_calls": 0,
        }
    ]
    assert workflow.state == "candidate_ready"


@pytest.mark.asyncio
async def test_executable_flow_uses_gemini_complete_source_and_existing_worker(tmp_path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    provider = CompleteSourceFixtureProvider()

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    previous_executable = settings.executable_cadquery_flow_enabled
    previous_validated = settings.validated_cadquery_flow_enabled
    previous_manifest = settings.executable_cadquery_corpus_manifest_path
    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPEATABILITY_CORPUS_SCHEMA_VERSION,
                "projects": [
                    {
                        "project_id": "fixture-project",
                        "prompt": "Create the frozen mounting bracket fixture.",
                        "contract": FROZEN_MOUNTING_BRACKET_CONTRACT,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings.executable_cadquery_flow_enabled = True
    settings.validated_cadquery_flow_enabled = False
    settings.executable_cadquery_corpus_manifest_path = manifest_path
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_workflow_ai_provider] = lambda: provider
    app.dependency_overrides[get_cad_runner] = lambda: CadQueryCliRunner(
        workspace_root=tmp_path / "cad-workspace",
        timeout_seconds=45,
    )
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Volundr-Internal-Actor": "volundr-single-user"})
            response = client.post(
                "/api/validated-cadquery/designs",
                json={
                    "name": "Frozen mounting bracket",
                    "intent": "Create the frozen mounting bracket fixture.",
                },
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["route"] == "validated_cadquery"
            assert payload["provenance"]["source_generation_mode"] == "complete_source"
            assert payload["provenance"]["codex_proxy_used"] is False
            assert payload["state"] == "candidate_ready", next(item for item in payload["provenance"].get("semantic_verification", {}).get("findings", []) if item.get("requirement_id") == "asymmetric_through_hole")
            assert payload["candidate_policy"]["state"] == "candidate_ready_for_review"
            assert payload["verification"]["candidate_policy"] == payload["candidate_policy"]
            assert provider.requests[0].executable_design_contract is not None
            assert provider.requests[0].executable_repair_envelope is None
            assert payload["outputs"]
            assert payload["outputs"][0]["output_id"] == "mounting_bracket"
            assert payload["outputs"][0]["artifact_available"] is True
            response_evidence = next(
                (tmp_path / "data" / "debug-sessions" / "executable-cadquery" / payload["id"]).glob(
                    "attempt-01-provider-response.txt"
                )
            )
            assert response_evidence.read_text(encoding="utf-8") == valid_mounting_bracket_source()
            assert response_evidence.stat().st_mode & 0o777 == 0o600

            accepted = client.post(f"/api/validated-cadquery/workflows/{payload['id']}/accept")
            assert accepted.status_code == 200, accepted.text
            accepted_payload = accepted.json()
            assert accepted_payload["package_available"] is True
            review = client.post(
                f"/api/validated-cadquery/workflows/{payload['id']}/independent-review",
                json={
                    "reviewer": "blind_codex_cad_qa_v1",
                    "review_cycle": 1,
                    "final_verdict": "PASS",
                    "requirements": [],
                    "revision_preservation": [],
                    "discrepancies": [],
                },
            )
            assert review.status_code == 200, review.text
            assert review.json()["candidate_policy"]["state"] == "candidate_fully_verified"

            revision = client.post(
                f"/api/validated-cadquery/workflows/{payload['id']}/revision",
                json={
                    "instruction": "Increase the centered recessed pocket to 46 mm × 24 mm while preserving the body dimensions, all five hole diameters, all hole-center positions, body thickness, and output identity.",
                    "protected_facts": [
                        "body dimensions",
                        "all five hole diameters",
                        "all hole-center positions",
                        "body thickness",
                        "output identity",
                    ],
                },
            )
            assert revision.status_code == 201, revision.text
            revision_payload = revision.json()
            assert revision_payload["state"] == "revision_ready", revision_payload["diagnostics"]
            assert revision_payload["parent_workflow_id"] == payload["id"]
            assert revision_payload["parent_revision_id"] == accepted_payload["revision_id"]
            assert revision_payload["verification"]["output_identity_preserved"] is True
            assert provider.requests[-1].executable_repair_envelope["repair_level"] == "L4"
            assert provider.requests[-1].current_source
    finally:
        settings.executable_cadquery_flow_enabled = previous_executable
        settings.validated_cadquery_flow_enabled = previous_validated
        settings.executable_cadquery_corpus_manifest_path = previous_manifest
        app.dependency_overrides.clear()
