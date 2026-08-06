import json
import hashlib
import zipfile
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.project import Project
from app.models.generation_attempt import GenerationAttempt
from app.models.revision import Revision
from app.models.validation_finding import ValidationFinding
from app.models.workflow import (
    FrontendWorkflowEvent,
    WorkflowArtifact,
    WorkflowDiagnosis,
    WorkflowEvent,
    WorkflowRun,
)
from app.services.workflow.debug_bundle import WorkflowDebugBundleService
from app.services.workflow.diagnosis import WorkflowDiagnosisService
from app.services.workflow.observability import WorkflowRecorder
from app.services.workflow.redaction import RedactionService
from app.services.workflow.comparison import WorkflowRunComparisonService
from app.services.workflow.stage_trace import WorkflowStageTraceService
from app.services.projects.service import ProjectService
from app.services.generation.failure_taxonomy import FailureClass
from tests.test_design_plans import (
    FakeCadRunner,
    PlanningAiProvider,
    READY_PLAN,
    build_client as build_plan_client,
)
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.api.dependencies import get_cad_runner


def _session(tmp_path: Path) -> tuple[Session, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    return session, SessionLocal


def _project(session: Session) -> Project:
    project = Project(
        name="Observable bracket",
        slug="observable-bracket",
        original_intent="Create a mounting bracket.",
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_workflow_events_have_deterministic_sequence_and_dedupe(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(
        project_id=project.id,
        workflow_type="initial_generation",
        logging_mode="diagnostic",
        provider="fake",
        model="fake-model",
        prompt_versions={"requirements": "requirements-v1"},
        application_commit="abc123",
        worker_version="cad-worker-v1",
    )

    first = recorder.record_event(
        run,
        stage="source_generation",
        event_type="source_generation.started",
        severity="summary",
        message="source generation started",
        deduplication_key="source-start-1",
    )
    duplicate = recorder.record_event(
        run,
        stage="source_generation",
        event_type="source_generation.started",
        severity="summary",
        message="duplicate source generation started",
        deduplication_key="source-start-1",
    )
    second = recorder.record_event(
        run,
        stage="source_contract_validation",
        event_type="source_contract.passed",
        severity="summary",
        message="source contract passed",
        deduplication_key="contract-passed-1",
    )

    assert duplicate.id == first.id
    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert first.occurred_at is not None
    assert first.recorded_at is not None
    assert (
        session.scalar(
            select(func.count()).select_from(WorkflowEvent).where(WorkflowEvent.workflow_run_id == run.id)
        )
        == 2
    )


def test_child_runs_share_root_and_link_to_parent(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    root = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    repair = recorder.start_run(
        project_id=project.id,
        workflow_type="contract_repair",
        parent_workflow_run_id=root.id,
    )

    assert root.root_workflow_run_id == root.id
    assert repair.parent_workflow_run_id == root.id
    assert repair.root_workflow_run_id == root.id
    assert repair.correlation_id == root.correlation_id


def test_failed_repair_artifact_remains_visible_after_successful_repair(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")

    failed_path = tmp_path / "data" / "failed-source.py"
    failed_path.parent.mkdir(parents=True)
    failed_path.write_text("bad source", encoding="utf-8")
    failed = recorder.record_artifact(
        run,
        stage="contract_repair",
        artifact_type="cadquery_source",
        role="failed_repair_source",
        path=failed_path,
        redacted=False,
    )
    repaired_path = tmp_path / "data" / "repaired-source.py"
    repaired_path.write_text("good source", encoding="utf-8")
    repaired = recorder.record_artifact(
        run,
        stage="contract_repair",
        artifact_type="cadquery_source",
        role="successful_repair_source",
        path=repaired_path,
        supersedes_artifact_id=failed.id,
        redacted=False,
    )

    artifacts = list(session.scalars(select(WorkflowArtifact).order_by(WorkflowArtifact.created_at)))
    assert [artifact.id for artifact in artifacts] == [failed.id, repaired.id]
    assert artifacts[1].supersedes_artifact_id == failed.id


def test_conservative_diagnosis_marks_candidate_block_as_symptom(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    source_failure = recorder.record_event(
        run,
        stage="source_contract_validation",
        event_type="source_contract.failed",
        severity="error",
        blocking=True,
        rule_id="cadquery.required_parameter_missing",
        message="Protected parameter was omitted.",
        deduplication_key="source-failure",
    )
    candidate_block = recorder.record_event(
        run,
        stage="candidate_classification",
        event_type="candidate.blocked",
        severity="error",
        blocking=True,
        rule_id="candidate.blocked",
        message="Candidate blocked.",
        caused_by_event_id=source_failure.id,
        deduplication_key="candidate-blocked",
    )

    diagnosis = WorkflowDiagnosisService(db=session).diagnose(run.id)

    assert diagnosis.workflow_run_id == run.id
    assert diagnosis.root_cause["event_id"] == source_failure.id
    assert diagnosis.root_cause["confidence"] == "confirmed"
    assert any(effect["event_id"] == candidate_block.id for effect in diagnosis.downstream_effects)
    stored = session.get(WorkflowDiagnosis, diagnosis.id)
    assert stored is not None


def test_diagnosis_uses_plan_finding_when_legacy_block_event_is_nonblocking(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    attempt = GenerationAttempt(
        project_id=project.id,
        attempt_number=1,
        provider_id="fake",
        model_id="fake-model",
        prompt_version="compact-cad-plan-v1",
        ruleset_version="test-rules",
        request_payload_path="request.json",
        prompt_path="prompt.txt",
        status="succeeded",
        failure_class="design_plan_invalid",
    )
    session.add(attempt)
    session.flush()
    finding = ValidationFinding(
        generation_attempt_id=attempt.id,
        rule_id="plan.pattern_owner_missing",
        category="plan_pattern",
        severity="critical",
        is_blocking=True,
        title="Pattern owner missing",
        explanation="The pattern does not identify its owning feature.",
        suggested_correction="Reference an existing feature.",
        metadata_json=json.dumps({"workflow_run_id": run.id}),
    )
    session.add(finding)
    session.commit()
    recorder.record_event(
        run,
        stage="blocked_attempt",
        event_type="blocked_attempt.preserved",
        severity="error",
        blocking=False,
        message="Blocked attempt preserved; Current working version unchanged.",
        generation_attempt_id=attempt.id,
        deduplication_key="legacy-blocked-attempt",
    )

    diagnosis = WorkflowDiagnosisService(db=session).diagnose(run.id)

    assert diagnosis.root_cause["stage"] == "plan_validation"
    assert diagnosis.root_cause["rule_id"] == "plan.pattern_owner_missing"
    assert diagnosis.root_cause["confidence"] == "confirmed"


def test_diagnosis_uses_blocked_attempt_failure_metadata_and_revision_finding(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    revision = Revision(
        project_id=project.id,
        revision_number=1,
        source_type="ai_generated",
        user_instruction="Create a tackle tray holder.",
        source_path="projects/observable-bracket/revisions/1/source.py",
        status="failed",
        review_state="blocked",
        is_accepted=False,
    )
    session.add(revision)
    session.flush()
    attempt = GenerationAttempt(
        project_id=project.id,
        resulting_revision_id=revision.id,
        attempt_number=1,
        provider_id="fake",
        model_id="fake-model",
        prompt_version="cadquery-geometry-body-v8",
        ruleset_version="test-rules",
        request_payload_path="request.json",
        prompt_path="prompt.txt",
        raw_output_path="raw-output.json",
        status="failed",
        failure_class="design_artifact_inconsistent",
    )
    session.add(attempt)
    session.flush()
    finding = ValidationFinding(
        revision_id=revision.id,
        generation_attempt_id=attempt.id,
        rule_id="design_artifact.requirement_trace_failed",
        category="design_artifact_consistency",
        severity="critical",
        is_blocking=True,
        title="Requirement trace failed",
        explanation="The approved Design Plan no longer preserves explicit user requirements.",
        suggested_correction="Regenerate from the approved Design Plan.",
    )
    session.add(finding)
    session.commit()
    recorder.record_event(
        run,
        stage="chat_workflow",
        event_type="blocked_attempt.preserved",
        severity="summary",
        blocking=False,
        message="Blocked attempt preserved; Current working version unchanged.",
        generation_attempt_id=attempt.id,
        revision_id=revision.id,
        deduplication_key="blocked-artifact-consistency",
        metadata={
            "attempt_id": attempt.id,
            "revision_id": revision.id,
            "failure_class": "design_artifact_inconsistent",
            "failure_stage": "artifact_consistency",
            "provider_response_received": True,
            "geometry_generation_attempted": True,
            "worker_reached": False,
            "current_working_version_unchanged": True,
        },
    )

    diagnosis = WorkflowDiagnosisService(db=session).diagnose(run.id)

    assert diagnosis.root_cause["stage"] == "artifact_consistency"
    assert diagnosis.root_cause["rule_id"] == "design_artifact.requirement_trace_failed"
    assert diagnosis.root_cause["findings"][0]["rule_id"] == "design_artifact.requirement_trace_failed"
    assert diagnosis.root_cause["basis"]["worker_reached"] is False


def test_diagnosis_summary_preserves_typed_requirement_trace_fields() -> None:
    finding = ValidationFinding(
        rule_id="design_artifact.feature_function_trace_missing",
        category="design_artifact_consistency",
        severity="critical",
        is_blocking=True,
        title="Feature function trace missing",
        explanation="A required feature has no implementation or verification path.",
        suggested_correction="Restore the feature trace.",
        metadata_json=json.dumps(
            {
                "requirement_id": "required_handle",
                "feature_id": "handle",
                "component_id": "base",
                "function_id": None,
                "output_id": "base_output",
                "trace_classification": "source_or_geometry_trace",
                "normalization_decision": None,
            }
        ),
    )

    summary = WorkflowDiagnosisService._finding_summary(finding)

    assert summary["requirement_id"] == "required_handle"
    assert summary["feature_id"] == "handle"
    assert summary["component_id"] == "base"
    assert summary["output_id"] == "base_output"
    assert summary["trace_classification"] == "source_or_geometry_trace"


def test_plan_validation_block_persists_provider_and_normalized_evidence(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="design_plan_creation")
    attempt = GenerationAttempt(
        project_id=project.id,
        attempt_number=1,
        provider_id="fake",
        model_id="fake-model",
        prompt_version="compact-cad-plan-v2",
        ruleset_version="test-rules",
        request_payload_path="request.json",
        prompt_path="prompt.txt",
        status="succeeded",
        failure_class=FailureClass.NONE.value,
    )
    session.add(attempt)
    session.flush()
    service = ProjectService(db=session, data_dir=tmp_path / "data")
    service._generation_attempt_dir(project.id, attempt.id).mkdir(parents=True, exist_ok=True)
    event_id = service._persist_plan_normalization_evidence(
        workflow_run=run,
        attempt=attempt,
        specification=None,
        raw_output=json.dumps({"patterns": [{"pattern_id": "tray_slots"}]}),
        normalized_payload={"patterns": []},
        findings=[
            {
                "rule_id": "plan.pattern_type_missing",
                "category": "plan_pattern",
                "severity": "critical",
                "blocking": True,
                "title": "Pattern type missing",
                "explanation": "The pattern type cannot be inferred safely.",
                "suggested_correction": "Provide an explicit layout type.",
                "pattern_index": 0,
                "pattern_id": "tray_slots",
            }
        ],
        validation_outcome="blocked",
    )
    service._finish_generation_attempt(
        attempt,
        status="succeeded",
        failure_class=FailureClass.DESIGN_PLAN_INVALID,
    )
    session.commit()

    session.refresh(attempt)
    routing = json.loads(attempt.routing_metadata_json)
    finding = session.scalar(
        select(ValidationFinding).where(ValidationFinding.generation_attempt_id == attempt.id)
    )
    artifacts = list(
        session.scalars(
            select(WorkflowArtifact).where(WorkflowArtifact.workflow_run_id == run.id)
        )
    )
    event = session.get(WorkflowEvent, event_id)

    assert attempt.status == "succeeded"
    assert attempt.failure_class == FailureClass.DESIGN_PLAN_INVALID.value
    assert routing["provider_response_received"] is True
    assert routing["plan_validation_outcome"] == "blocked"
    assert routing["geometry_generation_attempted"] is False
    assert routing["worker_reached"] is False
    assert finding is not None
    assert finding.rule_id == "plan.pattern_type_missing"
    assert finding.is_blocking is True
    assert {artifact.artifact_type for artifact in artifacts} == {
        "provider_plan_original",
        "provider_plan_normalized",
    }
    assert event is not None
    assert event.stage == "plan_validation"
    assert event.blocking is True
    assert event.rule_id == "plan.pattern_type_missing"


def test_resolved_historical_failure_is_not_later_root_cause(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    root = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    source_failure = recorder.record_event(
        root,
        stage="source_contract_validation",
        event_type="source_contract.failed",
        severity="error",
        blocking=True,
        rule_id="cadquery.required_parameter_unused",
        message="A required parameter was not used.",
        deduplication_key="historical-source-failure",
    )
    repair = recorder.start_run(
        project_id=project.id,
        workflow_type="contract_repair",
        parent_workflow_run_id=root.id,
    )
    recorder.record_event(
        repair,
        stage="contract_repair",
        event_type="contract_repair.succeeded",
        severity="summary",
        message="Contract repair resolved the source failure.",
        caused_by_event_id=source_failure.id,
        deduplication_key="historical-source-repair-succeeded",
    )
    recorder.complete_run(repair, status="completed")
    recorder.complete_run(root, status="completed")

    diagnosis = WorkflowDiagnosisService(db=session).diagnose(repair.id)

    assert diagnosis.root_cause["event_id"] is None
    assert diagnosis.root_cause["confidence"] == "unknown"
    assert diagnosis.final_outcome == "completed"


def test_staged_generation_closes_source_and_repair_child_runs(tmp_path: Path) -> None:
    provider = RepairThenValidProvider(READY_PLAN)
    client, SessionLocal = build_plan_client(tmp_path, provider)
    app.dependency_overrides[get_cad_runner] = lambda: ManifestCadRunner()
    project = client.post(
        "/api/projects",
        json={"name": "Terminal workflow project", "original_intent": "Create a bracket."},
    ).json()

    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a bracket with mount_hole_spacing=60 mm."},
    ).json()
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    assert client.post(f"/api/design-plans/{plan['id']}/approve").status_code == 200
    revision_response = client.post(f"/api/design-plans/{plan['id']}/generate")
    assert revision_response.status_code == 201, revision_response.json()
    revision = revision_response.json()
    assert client.post(f"/api/candidates/{revision['id']}/accept").status_code == 200

    with SessionLocal() as session:
        runs = list(session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project["id"])))
        statuses = {run.workflow_type: run.status for run in runs}
        assert statuses["source_generation"] == "completed"
        assert statuses["contract_repair"] == "completed"
        assert statuses["design_plan_creation"] == "completed"
        assert statuses["initial_generation"] == "completed"


def test_stale_running_workflow_can_be_diagnosed(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")

    stale = recorder.classify_stale_runs(max_running_seconds=0)

    assert stale == 1
    session.refresh(run)
    assert run.status == "abandoned"


def test_allowlist_redactor_removes_secret_query_headers_and_patterns() -> None:
    service = RedactionService()
    redacted = service.redact_mapping(
        {
            "url": "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=fake-api-key",
            "method": "POST",
            "headers": {
                "authorization": "Bearer fake-token",
                "content-type": "application/json",
                "x-random": "should-not-survive",
            },
            "api_key": "AIza1234567890",
        },
        artifact_type="provider_request_metadata",
    )

    assert redacted["url"] == "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent"
    assert redacted["headers"] == {"content-type": "application/json"}
    assert redacted["api_key"] == "[REDACTED]"
    assert json.dumps(redacted).find("fake-token") == -1


def test_debug_bundle_redacts_fake_api_key_before_release(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    secret_path = tmp_path / "data" / "raw-provider-response.txt"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("leakedAIza1234567890", encoding="utf-8")
    recorder.record_artifact(
        run,
        stage="provider_response",
        artifact_type="raw_provider_response",
        role="raw_response",
        path=secret_path,
        redacted=False,
    )

    bundle = WorkflowDebugBundleService(db=session, data_dir=tmp_path / "data").build_bundle(run.id)

    with zipfile.ZipFile(bundle) as archive:
        payload = "\n".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.endswith(".txt") or name.endswith(".json") or name.endswith(".ndjson")
        )
    assert "AIza1234567890" not in payload
    assert "[REDACTED]" in payload


def test_debug_bundle_contains_trace_config_and_redaction_report(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(
        project_id=project.id,
        workflow_type="initial_generation",
        logging_mode="diagnostic",
        provider="fake",
        model="fake-model",
        prompt_versions={"cadquery": "cadquery-generation-v4"},
        application_commit="abc123",
        worker_version="cad-worker-v1",
    )
    recorder.record_event(
        run,
        stage="acceptance",
        event_type="candidate.accepted",
        severity="summary",
        message="Accepted",
    )
    bundle = WorkflowDebugBundleService(db=session, data_dir=tmp_path / "data").build_bundle(run.id)

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert any(name.endswith("run-summary.json") for name in names)
        assert any(name.endswith("event-log.ndjson") for name in names)
        assert any(name.endswith("redaction-report.json") for name in names)
        summary_name = next(name for name in names if name.endswith("run-summary.json"))
        summary = json.loads(archive.read(summary_name))
        assert summary["application_commit"] == "abc123"
        assert summary["prompt_versions"] == {"cadquery": "cadquery-generation-v4"}


def test_stage_trace_identifies_first_drift(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")

    recorder.record_event(
        run,
        stage="design_plan_validation",
        event_type="design_plan.parameter_confirmed",
        severity="standard",
        message="Wall thickness preserved.",
        entity_type="parameter",
        entity_id="wall_thickness",
        detected=3.0,
        metadata={"value_source": "product_default"},
    )
    recorder.record_event(
        run,
        stage="source_contract_validation",
        event_type="source_contract.parameter_drift",
        severity="error",
        blocking=True,
        rule_id="cadquery.parameter_drift",
        message="Wall thickness drifted in source.",
        entity_type="parameter",
        entity_id="wall_thickness",
        expected=3.0,
        detected=2.5,
        metadata={"value_source": "parameter_default"},
    )

    trace = WorkflowStageTraceService(db=session).build_trace(run.id)

    item = next(entry for entry in trace["traces"] if entry["entity_id"] == "wall_thickness")
    assert item["status"] == "drift_detected"
    assert item["first_drift"]["stage"] == "source_contract_validation"


def test_run_comparison_detects_parameter_regression_and_reduced_repair_count(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    recorder = WorkflowRecorder(db=session, data_dir=tmp_path / "data")
    baseline = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    candidate = recorder.start_run(project_id=project.id, workflow_type="initial_generation")

    recorder.record_event(
        baseline,
        stage="design_plan_validation",
        event_type="design_plan.parameter_confirmed",
        severity="standard",
        message="Parameter recorded.",
        entity_type="parameter",
        entity_id="wall_thickness",
        detected=3.0,
        metadata={"value_source": "explicit_user_value"},
    )
    recorder.record_event(
        baseline,
        stage="contract_repair",
        event_type="contract_repair.failed",
        severity="error",
        message="Repair failed.",
    )
    recorder.record_event(
        baseline,
        stage="contract_repair",
        event_type="contract_repair.succeeded",
        severity="standard",
        message="Repair succeeded.",
    )
    recorder.record_event(
        candidate,
        stage="design_plan_validation",
        event_type="design_plan.parameter_confirmed",
        severity="standard",
        message="Parameter recorded.",
        entity_type="parameter",
        entity_id="wall_thickness",
        detected=2.5,
        metadata={"value_source": "explicit_user_value"},
    )
    recorder.record_event(
        candidate,
        stage="contract_repair",
        event_type="contract_repair.succeeded",
        severity="standard",
        message="Repair succeeded.",
    )

    comparison = WorkflowRunComparisonService(db=session).compare(baseline.id, candidate.id)

    assert any(item["metric"] == "parameter_value" for item in comparison["regressions"])
    assert any(item["metric"] == "repair_count" for item in comparison["improvements"])


def test_project_deletion_removes_trace_records_and_generated_bundles(tmp_path: Path) -> None:
    session, _SessionLocal = _session(tmp_path)
    project = _project(session)
    data_dir = tmp_path / "data"
    recorder = WorkflowRecorder(db=session, data_dir=data_dir)
    run = recorder.start_run(project_id=project.id, workflow_type="initial_generation")
    recorder.record_event(
        run,
        stage="acceptance",
        event_type="candidate.accepted",
        severity="summary",
        message="Accepted.",
    )
    bundle = WorkflowDebugBundleService(db=session, data_dir=data_dir).build_bundle(run.id)
    assert bundle.exists()

    deleted = ProjectService(db=session, data_dir=data_dir).delete_project(project.id)

    assert deleted is True
    assert not bundle.exists()
    assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 0
    assert session.scalar(select(func.count()).select_from(WorkflowEvent)) == 0


def _build_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app), SessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_frontend_event_ingestion_rejects_unknown_event_names(tmp_path: Path) -> None:
    client, SessionLocal = _build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={"name": "Observable project", "original_intent": "Make a box."},
    ).json()
    with SessionLocal() as session:
        run = WorkflowRecorder(db=session, data_dir=tmp_path / "data").start_run(
            project_id=project["id"],
            workflow_type="initial_generation",
        )
        run_id = run.id

    response = client.post(
        "/api/workflow/frontend-events",
        json={
            "frontend_session_id": "session-1",
            "workflow_run_id": run_id,
            "correlation_id": "correlation-1",
            "project_id": project["id"],
            "events": [
                {
                    "action_name": "unknown_event",
                    "route": "/",
                    "user_visible_state": "idle",
                    "timestamp": "2026-07-31T00:00:00Z",
                    "metadata": {},
                }
            ],
        },
    )

    assert response.status_code == 422


def test_frontend_event_ingestion_accepts_registered_event_and_links_workflow(tmp_path: Path) -> None:
    client, SessionLocal = _build_client(tmp_path)
    project = client.post(
        "/api/projects",
        json={"name": "Observable project", "original_intent": "Make a box."},
    ).json()
    with SessionLocal() as session:
        run = WorkflowRecorder(db=session, data_dir=tmp_path / "data").start_run(
            project_id=project["id"],
            workflow_type="initial_generation",
        )
        run_id = run.id
        correlation_id = run.correlation_id

    response = client.post(
        "/api/workflow/frontend-events",
        json={
            "frontend_session_id": "session-1",
            "workflow_run_id": run_id,
            "correlation_id": correlation_id,
            "project_id": project["id"],
            "events": [
                {
                    "action_name": "candidate_accepted",
                    "route": "/",
                    "user_visible_state": "candidate_review",
                    "timestamp": "2026-07-31T00:00:00Z",
                    "metadata": {"revision_id": "revision-1"},
                }
            ],
        },
    )

    assert response.status_code == 201
    with SessionLocal() as session:
        stored = session.scalar(select(FrontendWorkflowEvent))
        assert stored is not None
        assert stored.workflow_run_id == run_id
        assert stored.action_name == "candidate_accepted"


class RepairThenValidProvider(PlanningAiProvider):
    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.cadquery_requests.append(request)
        if len(self.cadquery_requests) == 1:
            return ModelGenerationResult(
                raw_output="""
```python
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [
    ParameterSpec(id="mount_hole_spacing", label="Mount hole spacing", type="float", default=60.0, unit="mm", protected=True, source_requirement_id="mount_hole_spacing"),
    ParameterSpec(id="plate_thickness", label="Plate thickness", type="float", default=6.0, unit="mm"),
]

def build(params):
    body = cq.Workplane("XY").box(80, 80, 6)
    return Product(parameters=PARAMETERS, outputs=[
        PrintableOutput(output_id="bracket_body_output", component_id="wrong", label="Body", model=body, expected_solid_count=1, allow_disconnected_solids=False)
    ])
```
""",
                provider="fake",
                provider_model="fake-planning-model",
            )
        return await super().generate_cadquery_model(request)


class AlwaysInvalidSourceProvider(PlanningAiProvider):
    async def generate_cadquery_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return await RepairThenValidProvider(READY_PLAN).generate_cadquery_model(request)


class InvalidFunctionalPlanProvider(PlanningAiProvider):
    def __init__(self) -> None:
        invalid_plan = {
                **READY_PLAN,
                "schema_version": "1.1",
                "functional_contract": {
                    "retention_interfaces": [
                        {
                            "id": "retention",
                            "required": True,
                            "strategy": "reviewed_proposal",
                        }
                    ]
                },
            }
        super().__init__(invalid_plan, invalid_plan)


def test_functional_plan_failure_records_root_diagnosis(tmp_path: Path) -> None:
    provider = InvalidFunctionalPlanProvider()
    client, SessionLocal = build_plan_client(tmp_path, provider)
    project = client.post(
        "/api/projects",
        json={"name": "Invalid functional plan project", "original_intent": "Create a holder."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a holder with a retention feature."},
    ).json()

    response = client.post(f"/api/design-specifications/{specification['id']}/design-plan")

    assert response.status_code == 502
    with SessionLocal() as session:
        root = session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project["id"])
            .where(WorkflowRun.workflow_type == "initial_generation")
        )
        assert root is not None
        diagnosis = WorkflowDiagnosisService(db=session).diagnose(root.id)
        assert diagnosis.root_cause["stage"] == "design_plan_validation"
        assert diagnosis.root_cause["rule_id"] == "functional.retention_strategy_placeholder"
        assert diagnosis.root_cause["confidence"] == "confirmed"


def test_failed_generation_closes_root_and_completed_plan_child(tmp_path: Path) -> None:
    provider = AlwaysInvalidSourceProvider(READY_PLAN)
    client, SessionLocal = build_plan_client(tmp_path, provider)
    project = client.post(
        "/api/projects",
        json={"name": "Failed terminal workflow project", "original_intent": "Create a bracket."},
    ).json()
    specification = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a bracket with mount_hole_spacing=60 mm."},
    ).json()
    plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
    assert client.post(f"/api/design-plans/{plan['id']}/approve").status_code == 200

    response = client.post(f"/api/design-plans/{plan['id']}/generate")

    assert response.status_code == 409
    with SessionLocal() as session:
        runs = list(session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project["id"])))
        statuses = {run.workflow_type: run.status for run in runs}
        assert statuses["design_plan_creation"] == "completed"
        assert statuses["source_generation"] == "failed"
        assert statuses["contract_repair"] == "failed"
        assert statuses["initial_generation"] == "failed"


class ManifestCadRunner(FakeCadRunner):
    async def compile(self, *args, **kwargs):
        result = await super().compile(*args, **kwargs)
        source = args[0] if args else ""
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        job_id = result.job_id
        manifest_path = Path("/tmp") / "volundr-fake-plan-jobs" / job_id / "execution-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "success": result.success,
                    "source_hash": source_hash,
                    "parameters": kwargs.get("parameter_values") or {},
                    "output_ids": [output.output_id for output in result.outputs if output.success],
                    "outputs": [
                        {
                            "output_id": output.output_id,
                            "success": output.success,
                            "topology_metadata": output.topology_metadata,
                            "stl_hash": output.stl_hash,
                            "step_hash": output.step_hash,
                            "brep_hash": output.brep_hash,
                        }
                        for output in result.outputs
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        object.__setattr__(result, "execution_manifest_path", manifest_path)
        return result


def test_staged_generation_records_repair_worker_classification_and_acceptance(tmp_path: Path) -> None:
    provider = RepairThenValidProvider(READY_PLAN)
    client, SessionLocal = build_plan_client(tmp_path, provider)
    app.dependency_overrides[get_cad_runner] = lambda: ManifestCadRunner()
    project = client.post(
        "/api/projects",
        json={"name": "Observable planned bracket", "original_intent": "Create a bracket."},
    ).json()

    specification_response = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create a bracket with mount_hole_spacing=60 mm."},
    )
    assert specification_response.status_code == 201, specification_response.json()
    specification = specification_response.json()
    plan_response = client.post(f"/api/design-specifications/{specification['id']}/design-plan")
    assert plan_response.status_code == 201, plan_response.json()
    plan = plan_response.json()
    approve_response = client.post(f"/api/design-plans/{plan['id']}/approve")
    assert approve_response.status_code == 200, approve_response.json()
    revision_response = client.post(f"/api/design-plans/{plan['id']}/generate")
    assert revision_response.status_code == 201, revision_response.json()
    revision = revision_response.json()
    acceptance_response = client.post(f"/api/candidates/{revision['id']}/accept")
    assert acceptance_response.status_code == 200, acceptance_response.json()
    accepted = acceptance_response.json()

    assert accepted["review_state"] == "accepted"
    with SessionLocal() as session:
        root = session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project["id"])
            .where(WorkflowRun.workflow_type == "initial_generation")
        )
        assert root is not None
        runs = list(session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project["id"])))
        assert {run.workflow_type for run in runs} >= {
            "initial_generation",
            "design_plan_creation",
            "source_generation",
            "contract_repair",
            "candidate_acceptance",
        }
        events = list(
            session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.root_workflow_run_id == root.id)
                .order_by(WorkflowEvent.sequence_number.asc())
            )
        )
        event_types = {event.event_type for event in events}
        assert "source_contract.failed" in event_types
        assert "contract_repair.succeeded" in event_types
        assert "worker.submitted" in event_types
        assert "candidate.classified" in event_types
        assert "candidate.accepted" in event_types
        source_artifacts = list(
            session.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.root_workflow_run_id == root.id)
                .where(WorkflowArtifact.artifact_type == "cadquery_source")
            )
        )
        assert {artifact.role for artifact in source_artifacts} >= {
            "initial_generated_source",
            "contract_repaired_source",
        }
