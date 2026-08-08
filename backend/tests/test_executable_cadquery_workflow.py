from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
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
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
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

    def __init__(self, *, clarification: bool = False) -> None:
        self.requests: list[ModelGenerationRequest] = []
        self.requirement_requests: list[RequirementExtractionRequest] = []
        self.clarification = clarification

    async def extract_requirements(self, request: RequirementExtractionRequest) -> RequirementExtractionResult:
        self.requirement_requests.append(request)
        if self.clarification:
            payload = {
                "schema_version": "1.0",
                "object_type": "wall_mount",
                "purpose": request.user_instruction,
                "units": "mm",
                "supported_scope": True,
                "critical_dimensions": [],
                "parameters": [],
                "functional_requirements": [],
                "print_requirements": {},
                "assumptions": [],
                "conflicts": [],
                "missing_requirements": [
                    {"id": "mounting_surface", "description": "Mounting surface dimensions"}
                ],
                "clarification_required": True,
                "clarification_questions": [
                    {
                        "id": "mounting_surface",
                        "question": "What mounting surface dimensions should this fit?",
                        "reason": "The fit depends on the mounting surface.",
                        "related_requirement_id": "mounting_surface",
                    }
                ],
                "generation_ready": False,
                "outcome": "clarification_required",
            }
        else:
            payload = {
                "schema_version": "1.0",
                "object_type": "mounting_bracket",
                "purpose": request.user_instruction,
                "units": "mm",
                "supported_scope": True,
                "critical_dimensions": [
                    {
                        "id": "overall_width",
                        "label": "Overall width",
                        "value": 80.0,
                        "unit": "mm",
                        "tolerance": 0.25,
                        "source": "user",
                        "importance": "critical",
                        "protected": True,
                    },
                    {
                        "id": "overall_depth",
                        "label": "Overall depth",
                        "value": 50.0,
                        "unit": "mm",
                        "tolerance": 0.25,
                        "source": "user",
                        "importance": "critical",
                        "protected": True,
                    },
                    {
                        "id": "overall_height",
                        "label": "Overall height",
                        "value": 8.0,
                        "unit": "mm",
                        "tolerance": 0.25,
                        "source": "user",
                        "importance": "critical",
                        "protected": True,
                    }
                ],
                "parameters": [],
                "functional_requirements": [
                    {
                        "id": "secure_attachment",
                        "description": "Keep the attached object secure during ordinary use.",
                        "source": "user",
                        "importance": "critical",
                        "protected": True,
                        "type": "qualitative_behavior",
                        "classification": "review_required",
                    }
                ],
                "print_requirements": {},
                "assumptions": [],
                "conflicts": [],
                "missing_requirements": [],
                "clarification_required": False,
                "clarification_questions": [],
                "generation_ready": True,
                "outcome": "generation_ready",
            }
        return RequirementExtractionResult(
            raw_output=json.dumps(payload),
            provider="fixture",
            provider_model="fixture-model",
        )

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

    with pytest.raises(ValueError, match="authoritative product requirements"):
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


def test_recovery_recheck_preserves_build_failure_as_execution_boundary(tmp_path: Path) -> None:
    (tmp_path / "execution-manifest.json").write_text(
        json.dumps(
            {
                "diagnostics": {
                    "active_phase": "build_function",
                    "message": "AttributeError: Workplane has no attribute arc",
                    "per_output_results": {
                        "curved_cable_guide": {
                            "status": "not_attempted",
                        }
                    },
                },
                "failure_class": "execution_failed",
                "outputs": [],
            }
        ),
        encoding="utf-8",
    )
    revision = SimpleNamespace(
        id="build-failure-recheck",
        status="failed",
        source_path="source.py",
        source_hash=None,
        execution_manifest_path="execution-manifest.json",
        outputs=[
            SimpleNamespace(
                output_id="curved_cable_guide",
                execution_state="failed",
                stl_path=None,
                step_path=None,
                compile_error="AttributeError: Workplane has no attribute arc",
                topology_metadata_json=None,
            )
        ],
    )

    class FakeDb:
        def get(self, _model, revision_id):
            return revision if revision_id == revision.id else None

    service = ExecutableCadQueryWorkflowService(db=FakeDb(), data_dir=tmp_path)
    result = service._reevaluate_revision_evidence(
        revision,
        {
            "outputs": [{"output_id": "curved_cable_guide", "expected_solid_count": 1}],
            "requirements": [],
        },
    )

    assert result["failure_boundary"] == "execution"
    assert result["failure_class"] == "cadquery_api_error"


def test_recovery_recheck_preserves_worker_timeout_as_execution_boundary(tmp_path: Path) -> None:
    (tmp_path / "execution-manifest.json").write_text(
        json.dumps(
            {
                "diagnostics": {
                    "timed_out": True,
                    "timeout_seconds": 60,
                    "active_phase": "build_function",
                    "message": "CAD worker timed out",
                }
            }
        ),
        encoding="utf-8",
    )
    revision = SimpleNamespace(
        id="worker-timeout-recheck",
        status="failed",
        source_path="source.py",
        source_hash=None,
        execution_manifest_path="execution-manifest.json",
        outputs=[
            SimpleNamespace(
                output_id="curved_cable_guide",
                execution_state="failed",
                stl_path=None,
                step_path=None,
                compile_error="CAD worker timed out",
                topology_metadata_json=None,
            )
        ],
    )

    class FakeDb:
        def get(self, _model, revision_id):
            return revision if revision_id == revision.id else None

    service = ExecutableCadQueryWorkflowService(db=FakeDb(), data_dir=tmp_path)
    result = service._reevaluate_revision_evidence(
        revision,
        {
            "outputs": [{"output_id": "curved_cable_guide", "expected_solid_count": 1}],
            "requirements": [],
        },
    )

    assert result["failure_boundary"] == "execution"
    assert result["failure_class"] == "worker_timeout"


def test_persisted_execution_seed_preserves_source_and_worker_diagnostics(tmp_path: Path) -> None:
    diagnostics = {
        "active_phase": "build_function",
        "failure_operation": "chamfer",
        "failure_exception_type": "StdFail_NotDone",
        "failure_message": "BRep_API: command not done",
    }
    revision = SimpleNamespace(
        id="persisted-revision",
        source_hash="source-hash",
    )

    seed, comparison_facts = ExecutableCadQueryWorkflowService._build_persisted_execution_seed(
        revision=revision,
        failure_boundary="execution",
        failure_class="cadquery_api_error",
        diagnostics=diagnostics,
    )

    assert seed["repair_level"] == "initial"
    assert seed["source_hash"] == "source-hash"
    assert seed["worker_result"]["execution_diagnostics"] == diagnostics
    assert seed["topology_result"] == {}
    assert comparison_facts["failure_signature"] == "BRep_API: command not done"
    assert "chamfer" in comparison_facts["diagnostic_signature"]


@pytest.mark.asyncio
async def test_persisted_execution_recovery_commits_router_decision_before_ladder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "execution-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "diagnostics": {
                    "active_phase": "build_function",
                    "failure_operation": "chamfer",
                    "failure_exception_type": "StdFail_NotDone",
                    "failure_message": "BRep_API: command not done",
                }
            }
        ),
        encoding="utf-8",
    )
    revision = SimpleNamespace(
        id="persisted-recovery-revision",
        source_hash="persisted-source-hash",
        execution_manifest_path="execution-manifest.json",
    )
    contract = dict(FROZEN_MOUNTING_BRACKET_CONTRACT)
    workflow = SimpleNamespace(
        id="persisted-recovery-workflow",
        project_id="persisted-recovery-project",
        revision_id=revision.id,
        provenance_json=json.dumps({"executable_design_contract": contract}),
        diagnostics_json="{}",
        failure_boundary=None,
        state="failed",
        state_version=1,
    )

    class FakeDb:
        def __init__(self) -> None:
            self.commit_count = 0

        def get(self, _model, _identifier):
            return revision

        def commit(self) -> None:
            self.commit_count += 1

    db = FakeDb()
    service = ExecutableCadQueryWorkflowService(db=db, data_dir=tmp_path)
    operation = SimpleNamespace(
        id="persisted-recovery-operation",
        status="started",
        workflow_id=workflow.id,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(settings, "executable_cadquery_flow_enabled", True)
    service._get = lambda _workflow_id: workflow
    service.read = lambda _workflow_id: workflow
    service._begin_operation = lambda *args, **kwargs: operation

    async def fake_ladder(workflow_arg, contract_arg, **kwargs):
        persisted = json.loads(workflow_arg.provenance_json)
        captured["decision"] = persisted["recovery_decisions"][-1]
        captured["execution"] = persisted["recovery_executions"][-1]
        captured["contract"] = contract_arg
        captured["kwargs"] = kwargs
        return workflow_arg

    service._generate_with_repair_ladder = fake_ladder

    result = await service.recover_persisted_execution_failure(workflow.id)

    assert result is workflow
    assert db.commit_count >= 2
    assert captured["decision"]["recommended_action"] == "gemini_execution_repair"
    assert captured["decision"]["observation"]["evidence"]["recovery_operation_id"] == operation.id
    assert captured["execution"]["status"] == "dispatching"
    assert captured["kwargs"]["parent_revision_id"] == revision.id
    assert captured["kwargs"]["starting_level"] == "L1"
    assert captured["kwargs"]["provider_operation_limit"] == 1
    assert captured["kwargs"]["initial_history"][0]["source_hash"] == revision.source_hash
    assert captured["kwargs"]["initial_history"][0]["worker_result"]["execution_diagnostics"]["failure_operation"] == "chamfer"
    assert captured["contract"]["outputs"] == contract["outputs"]
    assert operation.status == "completed"


@pytest.mark.asyncio
async def test_persisted_execution_recovery_executes_worker_retry_and_rechecks_router(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "execution-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "diagnostics": {
                    "active_phase": "build_function",
                    "timed_out": True,
                    "message": "CAD worker did not complete job within 90 seconds",
                    "source_hash": "persisted-source-hash",
                }
            }
        ),
        encoding="utf-8",
    )
    output = SimpleNamespace(
        id="persisted-output-id",
        output_id="mounting_bracket",
        required=True,
        execution_state="failed",
        stl_path=None,
        step_path=None,
        compile_error="CAD worker did not complete job within 90 seconds",
        topology_metadata_json=None,
        validation_summary_json=json.dumps({}),
        worker_status="failed",
        state="not_generated",
        topology_status=None,
        artifact_available=False,
    )
    revision = SimpleNamespace(
        id="persisted-timeout-revision",
        status="failed",
        source_hash="persisted-source-hash",
        source_path="source.py",
        execution_manifest_path="execution-manifest.json",
        outputs=[output],
    )
    contract = dict(FROZEN_MOUNTING_BRACKET_CONTRACT)
    workflow = SimpleNamespace(
        id="persisted-timeout-workflow",
        project_id="persisted-timeout-project",
        revision_id=revision.id,
        provenance_json=json.dumps(
            {
                "executable_design_contract": contract,
                "recovery_decisions": [
                    {
                        "observation": {
                            "attempt_ordinal": 2,
                            "failure_class": "worker_timeout",
                            "evidence": {"source_hash": "older-source-hash"},
                        },
                        "recommended_action": "require_review",
                        "terminal": True,
                        "terminal_reason": "repair_ceiling_exhausted",
                    }
                ],
            }
        ),
        diagnostics_json="{}",
        failure_boundary=None,
        state="failed",
        state_version=1,
    )

    class FakeDb:
        def __init__(self) -> None:
            self.commit_count = 0

        def get(self, _model, _identifier):
            return revision

        def commit(self) -> None:
            self.commit_count += 1

    class FakeExecution:
        action = "retry_stage"
        executed = True
        provider_calls = 0
        worker_calls = 1
        diagnostic = None

        def to_record(self) -> dict[str, object]:
            return {
                "action": self.action,
                "executed": self.executed,
                "provider_calls": self.provider_calls,
                "worker_calls": self.worker_calls,
                "diagnostic": self.diagnostic,
            }

    db = FakeDb()
    service = ExecutableCadQueryWorkflowService(db=db, data_dir=tmp_path)
    operation = SimpleNamespace(
        id="persisted-timeout-operation",
        status="started",
        workflow_id=workflow.id,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(settings, "executable_cadquery_flow_enabled", True)
    service._get = lambda _workflow_id: workflow
    service.read = lambda _workflow_id: workflow
    service._begin_operation = lambda *args, **kwargs: operation
    service._project_service = lambda: "existing-project-service"

    async def fake_execute(decision, **kwargs):
        captured["decision"] = decision
        captured["kwargs"] = kwargs
        return FakeExecution()

    service._recovery_executor.execute = fake_execute
    service._reevaluate_revision_evidence = lambda *_args, **_kwargs: {
        "status": "failed",
        "failure_boundary": "execution",
        "failure_class": "worker_timeout",
        "source_hash": revision.source_hash,
        "result_hash": "same-timeout-result",
        "worker_result": {
            "phase": "failed",
            "output_ids": [],
            "revision_id": revision.id,
            "execution_diagnostics": {
                "timed_out": True,
                "message": "CAD worker did not complete job within 90 seconds",
            },
        },
        "topology_result": {},
        "semantic_result": {},
        "diagnostic": {
            "timed_out": True,
            "message": "CAD worker did not complete job within 90 seconds",
        },
        "normalized_error": "CAD worker did not complete job within 90 seconds",
        "comparison_facts": {
            "contract_valid": True,
            "extracted_source_hash": revision.source_hash,
            "diagnostic_signature": "same-timeout",
            "failure_signature": "CAD worker did not complete job within 90 seconds",
            "phase_index": 0,
            "completed_output_ids": [],
            "valid": None,
            "detected_solid_count": None,
            "expected_solid_count": 1,
            "failed_requirement_ids": [],
            "unverifiable_requirement_ids": [],
            "passed_requirement_ids": [],
        },
        "record": {
            "status": "failed",
            "source_hash": revision.source_hash,
            "result_hash": "same-timeout-result",
            "failure_boundary": "execution",
            "failure_class": "worker_timeout",
        },
    }

    result = await service.recover_persisted_execution_failure(workflow.id)

    assert result is workflow
    assert captured["decision"].recommended_action == "retry_stage"
    assert captured["kwargs"]["project_service"] == "existing-project-service"
    provenance = json.loads(workflow.provenance_json)
    assert provenance["recovery_decisions"][0]["recommended_action"] == "require_review"
    assert provenance["recovery_decisions"][1]["recommended_action"] == "retry_stage"
    assert provenance["recovery_executions"][-1]["action"] == "retry_stage"
    assert provenance["recovery_executions"][-1]["worker_calls"] == 1
    assert provenance["recovery_decisions"][-1]["terminal"] is True
    assert provenance["recovery_decisions"][-1]["terminal_reason"] == "same_source_hash_repeated"
    assert operation.status == "completed"


def test_recovery_recheck_preserves_topology_failure_from_worker_phase(tmp_path: Path) -> None:
    (tmp_path / "execution-manifest.json").write_text(
        json.dumps(
            {
                "diagnostics": {
                    "active_phase": "topology_analysis",
                    "message": "output shape is invalid",
                    "per_output_results": {
                        "enclosure_lid": {
                            "status": "invalid_shape",
                            "compile_error": "output shape is invalid",
                        }
                    },
                },
                "failure_class": "execution_failed",
                "outputs": [],
            }
        ),
        encoding="utf-8",
    )
    revision = SimpleNamespace(
        id="topology-failure-recheck",
        status="failed",
        source_path="source.py",
        source_hash=None,
        execution_manifest_path="execution-manifest.json",
        outputs=[
            SimpleNamespace(
                output_id="enclosure_lid",
                execution_state="failed",
                stl_path=None,
                step_path=None,
                compile_error="output shape is invalid",
                topology_metadata_json=None,
            )
        ],
    )

    class FakeDb:
        def get(self, _model, revision_id):
            return revision if revision_id == revision.id else None

    service = ExecutableCadQueryWorkflowService(db=FakeDb(), data_dir=tmp_path)
    result = service._reevaluate_revision_evidence(
        revision,
        {
            "outputs": [{"output_id": "enclosure_lid", "expected_solid_count": 1}],
            "requirements": [],
        },
    )

    assert result["failure_boundary"] == "topology"
    assert result["failure_class"] == "invalid_shape"


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
    workflow_contract = deepcopy(FROZEN_MOUNTING_BRACKET_CONTRACT)
    workflow_contract["requirements"] = [
        requirement
        for requirement in workflow_contract["requirements"]
        if requirement["requirement_id"] not in {
            "mounting_hole_pattern",
            "mounting_hole_edge_offsets",
            "asymmetric_through_hole",
        }
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPEATABILITY_CORPUS_SCHEMA_VERSION,
                "projects": [
                    {
                        "project_id": "fixture-project",
                        "prompt": "Create the frozen mounting bracket fixture.",
                        "contract": workflow_contract,
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
            assert payload["state"] == "candidate_ready"
            assert payload["concept_state"] == "concept_available"
            assert payload["candidate_policy"]["state"] == "candidate_ready_for_review"
            assert payload["verification"]["candidate_policy"] == payload["candidate_policy"]
            assert payload["verification"]["concept_state"]["state"] == "concept_available"
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
            assert review.json()["concept_state"] == "concept_available"

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

            review_fail = client.post(
                f"/api/validated-cadquery/workflows/{payload['id']}/independent-review",
                json={
                    "reviewer": "blind_codex_cad_qa_v1",
                    "review_cycle": 2,
                    "final_verdict": "FAIL",
                    "requirements": [
                        {
                            "requirement_id": "body_dimensions",
                            "verdict": "violated",
                            "evidence_type": "measured",
                        }
                    ],
                    "revision_preservation": [],
                    "discrepancies": ["measured body dimensions differ"],
                },
            )
            assert review_fail.status_code == 200, review_fail.text
            review_fail_payload = review_fail.json()
            assert review_fail_payload["candidate_policy"]["state"] == "candidate_blocked"
            assert review_fail_payload["concept_state"] == "concept_available"
            recovery_decision = review_fail_payload["provenance"]["recovery_decisions"][-1]
            assert recovery_decision["observation"]["failure_class"] == "semantic_requirement_failed"
            assert recovery_decision["recommended_action"] == "gemini_semantic_repair"
            assert recovery_decision["restart_stage"] == "source_contract"
    finally:
        settings.executable_cadquery_flow_enabled = previous_executable
        settings.validated_cadquery_flow_enabled = previous_validated
        settings.executable_cadquery_corpus_manifest_path = previous_manifest
        app.dependency_overrides.clear()


def test_executable_flow_derives_contract_from_product_requirements_without_manifest(tmp_path: Path) -> None:
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
    settings.executable_cadquery_flow_enabled = True
    settings.validated_cadquery_flow_enabled = False
    settings.executable_cadquery_corpus_manifest_path = None
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
                    "name": "Product path holder",
                    "intent": "Design a useful mounting bracket with secure attachment.",
                },
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            # The fixture deliberately supplies scalar dimensions without a
            # deterministic verifier policy.  The product path must preserve
            # them and fail closed, rather than dropping them or inventing a
            # PASS.
            assert payload["state"] == "verification_failed"
            contract = payload["provenance"]["executable_design_contract"]
            assert len(provider.requirement_requests) == 1
            assert len(provider.requests) == 1
            assert contract["contract_source"] == "production_requirement_ledger"
            assert contract["requirements"]
            assert {item["requirement_id"] for item in contract["requirements"]} == {
                "overall_width",
                "overall_depth",
                "overall_height",
                "secure_attachment",
            }
            assert next(
                item for item in contract["requirements"] if item["requirement_id"] == "secure_attachment"
            )["classification"] == "review_required"
            assert payload["outputs"][0]["output_id"] == "mounting_bracket"
    finally:
        settings.executable_cadquery_flow_enabled = previous_executable
        settings.validated_cadquery_flow_enabled = previous_validated
        settings.executable_cadquery_corpus_manifest_path = previous_manifest
        app.dependency_overrides.clear()


def test_executable_flow_preserves_product_clarification_before_generation(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    provider = CompleteSourceFixtureProvider(clarification=True)

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    previous_executable = settings.executable_cadquery_flow_enabled
    previous_validated = settings.validated_cadquery_flow_enabled
    previous_manifest = settings.executable_cadquery_corpus_manifest_path
    settings.executable_cadquery_flow_enabled = True
    settings.validated_cadquery_flow_enabled = False
    settings.executable_cadquery_corpus_manifest_path = None
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
                    "name": "Needs a fit detail",
                    "intent": "Design a wall-mounted tool holder.",
                },
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["state"] == "awaiting_clarification"
            assert payload["requirements"]["clarification_required"] is True
            assert payload["requirements"]["clarification_questions"]
            assert len(provider.requirement_requests) == 1
            assert provider.requests == []
    finally:
        settings.executable_cadquery_flow_enabled = previous_executable
        settings.validated_cadquery_flow_enabled = previous_validated
        settings.executable_cadquery_corpus_manifest_path = previous_manifest
        app.dependency_overrides.clear()
