import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.debug_batch import DebugBatchMembership
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project
from app.models.project_message import ProjectMessage
from app.models.workflow import WorkflowEvent, WorkflowRun
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.reports import DebugBatchReportService
from app.services.debug_batches.service import DebugBatchService
from app.services.workflow.repair_convergence import compare_repair_responses


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "debug_batch"


@pytest.mark.parametrize("fixture_path", sorted(FIXTURE_ROOT.glob("*.json")))
def test_frozen_real_response_fixture_replays_its_expected_contract(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = fixture["expected"]
    assert fixture["fixture_id"]
    assert fixture["source"]["batch_id"] in {
        "e1eb77dd-c6a3-4d62-9a49-72b49aa32c5d",
        "1ec92524-0401-40a2-a0e1-077cb8c52f57",
    }
    assert expected["blocking"] is True
    assert expected["finding"]
    assert expected["final_classification"]

    if "repaired_provider_response" in fixture:
        comparison = compare_repair_responses(
            fixture["raw_provider_response"],
            fixture["repaired_provider_response"],
        )
        assert comparison["unchanged"] is True
        assert expected["normalization"] == "reject_unchanged_repair"
    else:
        assert compare_repair_responses(
            fixture["raw_provider_response"],
            fixture["raw_provider_response"] + " ",
        )["unchanged"] is True


def test_report_separates_provider_calls_repairs_attempts_operations_and_stage_outcome(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=tmp_path / "data")
        batch = service.start(DebugBatchStart(label="metrics", target_project_count=1))
        project = Project(name="Metrics", slug="metrics", original_intent="A test project")
        session.add(project)
        session.flush()
        service.attach_new_project(project)
        user_message = ProjectMessage(project_id=project.id, role="user", content="Make a test object")
        session.add(user_message)
        run = WorkflowRun(
            project_id=project.id,
            workflow_type="initial_generation",
            correlation_id="metrics-correlation",
            status="blocked",
        )
        session.add(run)
        session.flush()
        attempt = GenerationAttempt(
            project_id=project.id,
            attempt_number=1,
            provider_id="gemini_api",
            model_id="fixture-model",
            provider_settings_json="{}",
            routing_metadata_json="{}",
            prompt_version="fixture",
            ruleset_version="fixture",
            request_payload_path="projects/metrics/request.json",
            prompt_path="projects/metrics/prompt.txt",
            raw_output_path="projects/metrics/raw-output.txt",
            status="failed",
            failure_class="design_plan_invalid",
            provider_call_count=3,
            provider_retry_count=1,
            content_repair_count=1,
        )
        session.add(attempt)
        session.flush()
        session.add_all(
            [
                WorkflowEvent(
                    workflow_run_id=run.id,
                    project_id=project.id,
                    correlation_id=run.correlation_id,
                    sequence_number=1,
                    stage="worker",
                    event_type="worker.started",
                    generation_attempt_id=attempt.id,
                    message="worker started",
                ),
                WorkflowEvent(
                    workflow_run_id=run.id,
                    project_id=project.id,
                    correlation_id=run.correlation_id,
                    sequence_number=2,
                    stage="candidate_classification",
                    event_type="candidate.classified",
                    generation_attempt_id=attempt.id,
                    blocking=True,
                    message="candidate blocked",
                ),
            ]
        )
        session.commit()

        report = DebugBatchReportService(db=session, data_dir=tmp_path / "data").generate(batch.id)["report"]

    summary = report["projects"][0]
    assert summary["provider_call_count"] == 3
    assert summary["provider_retry_count"] == 1
    assert summary["content_repair_count"] == 1
    assert summary["generation_attempt_count"] == 1
    assert summary["workflow_stage_attempt_count"] == 2
    assert summary["user_operation_count"] == 1
    assert summary["outcome_category"] == "post_worker_verification_block"
    assert report["provider_behavior"] == {
        "project_count": 1,
        "calls_by_stage": {},
        "provider_calls": 3,
        "provider_retries": 1,
        "content_repairs": 1,
        "generation_attempts": 1,
        "workflow_stage_attempts": 2,
        "user_operations": 1,
    }
