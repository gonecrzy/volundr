from app.core.config import Settings
from app.models.validated_cadquery_workflow import (
    VALIDATED_OUTPUT_STATES,
    VALIDATED_WORKFLOW_STATES,
)
from app.services.validated_cadquery_workflow import (
    classify_validated_output,
    derive_validated_workflow_state,
)


def test_sync_persists_successful_sibling_when_one_output_fails(tmp_path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.project import Project
    from app.models.revision import Revision
    from app.models.revision_output import RevisionOutput
    from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
    from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Fixture", slug="fixture", original_intent="Build a fixture")
        db.add(project)
        db.flush()
        revision = Revision(
            project_id=project.id,
            revision_number=1,
            source_type="fixture",
            user_instruction="Build a fixture",
            source_path="projects/fixture/source.py",
            status="failed",
        )
        db.add(revision)
        db.flush()
        db.add_all(
            [
                RevisionOutput(
                    revision_id=revision.id,
                    output_id="body",
                    label="Body",
                    filename="body.stl",
                    entrypoint="body",
                    execution_state="ready",
                    required=True,
                    stl_path="projects/fixture/body.stl",
                    step_path="projects/fixture/body.step",
                    detected_solid_count=1,
                    topology_metadata_json='{"valid": true, "detected_solid_count": 1}',
                    validation_summary_json='{"blocking_count": 0}',
                ),
                RevisionOutput(
                    revision_id=revision.id,
                    output_id="lid",
                    label="Lid",
                    filename="lid.stl",
                    entrypoint="lid",
                    execution_state="failed",
                    required=True,
                    compile_error="worker timeout while building lid",
                ),
            ]
        )
        db.flush()
        workflow = ValidatedCadQueryWorkflow(
            project_id=project.id,
            user_instruction=project.original_intent,
            state="worker_running",
        )
        db.add(workflow)
        db.commit()

        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path)
        service.sync_outputs(workflow, revision)

        assert workflow.state == "partially_completed"
        outputs = {output.output_id: output for output in workflow.outputs}
        assert outputs["body"].state == "completed"
        assert outputs["body"].artifact_available is True
        assert outputs["lid"].state == "worker_timeout"
        assert outputs["lid"].failure_owner == "worker"


def test_sync_maps_blocked_valid_geometry_to_semantic_verification_failure(tmp_path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.project import Project
    from app.models.revision import Revision
    from app.models.revision_output import RevisionOutput
    from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
    from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Fixture", slug="semantic-fixture", original_intent="Build a fixture")
        db.add(project)
        db.flush()
        revision = Revision(
            project_id=project.id,
            revision_number=1,
            source_type="fixture",
            user_instruction="Build a fixture",
            source_path="projects/fixture/source.py",
            status="succeeded",
        )
        db.add(revision)
        db.flush()
        db.add(
            RevisionOutput(
                revision_id=revision.id,
                output_id="body",
                label="Body",
                filename="body.stl",
                entrypoint="body",
                execution_state="blocked",
                required=True,
                stl_path="projects/fixture/body.stl",
                step_path="projects/fixture/body.step",
                brep_path="projects/fixture/body.brep",
                stl_hash="stl-hash",
                step_hash="step-hash",
                brep_hash="brep-hash",
                detected_solid_count=1,
                topology_metadata_json='{"valid": true, "detected_solid_count": 1}',
                validation_summary_json='{"blocking_count": 1}',
            )
        )
        db.flush()
        workflow = ValidatedCadQueryWorkflow(
            project_id=project.id,
            user_instruction=project.original_intent,
            state="worker_running",
        )
        db.add(workflow)
        db.commit()

        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path)
        service.sync_outputs(workflow, revision)

        output = workflow.outputs[0]
        assert output.state == "semantic_verification_failed"
        assert output.generation_status == "completed"
        assert output.worker_status == "completed"
        assert output.semantic_verification == "failed"
        assert output.artifact_available is True
        assert workflow.state == "verification_failed"


def test_sync_preserves_canonical_output_identity_through_verification(tmp_path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.project import Project
    from app.models.revision import Revision
    from app.models.revision_output import RevisionOutput
    from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
    from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Fixture", slug="identity-fixture", original_intent="Build a fixture")
        db.add(project)
        db.flush()
        revision = Revision(
            project_id=project.id,
            revision_number=1,
            source_type="fixture",
            user_instruction="Build a fixture",
            source_path="projects/fixture/source.py",
            status="succeeded",
        )
        db.add(revision)
        db.flush()
        db.add(
            RevisionOutput(
                revision_id=revision.id,
                output_id="canonical_mounting_plate",
                label="Mounting plate",
                filename="mounting_plate.stl",
                entrypoint="canonical_mounting_plate",
                execution_state="ready",
                required=True,
                stl_path="projects/fixture/mounting_plate.stl",
                step_path="projects/fixture/mounting_plate.step",
                brep_path="projects/fixture/mounting_plate.brep",
                stl_hash="stl-hash",
                step_hash="step-hash",
                brep_hash="brep-hash",
                detected_solid_count=1,
                topology_metadata_json='{"valid": true, "detected_solid_count": 1}',
                validation_summary_json='{"blocking_count": 0}',
            )
        )
        db.flush()
        workflow = ValidatedCadQueryWorkflow(
            project_id=project.id,
            user_instruction=project.original_intent,
            state="worker_running",
        )
        db.add(workflow)
        db.commit()

        service = ValidatedCadQueryWorkflowService(db=db, data_dir=tmp_path)
        service.sync_outputs(workflow, revision)

        assert workflow.outputs[0].output_id == "canonical_mounting_plate"
        assert workflow.verification_json is not None
        assert '"canonical_mounting_plate": "completed"' in workflow.verification_json


def test_output_classification_fails_closed_for_missing_or_invalid_geometry() -> None:
    missing = classify_validated_output(
        {"success": False, "compile_error": "no output"},
        required=True,
    )
    invalid = classify_validated_output(
        {
            "success": True,
            "topology_metadata": {"valid": False, "detected_solid_count": 2},
            "stl_path": "body.stl",
            "step_path": "body.step",
        },
        required=True,
    )

    assert missing.state == "not_generated"
    assert invalid.state == "invalid_shape"


def test_output_classification_preserves_semantic_mismatch_after_valid_geometry() -> None:
    result = classify_validated_output(
        {
            "success": True,
            "topology_metadata": {"valid": True, "detected_solid_count": 1},
            "semantic_verification": {"status": "failed"},
            "stl_path": "body.stl",
            "step_path": "body.step",
        },
        required=True,
    )

    assert result.state == "semantic_verification_failed"
    assert result.failure_owner == "verification"


def test_workflow_aggregation_distinguishes_candidate_partial_verification_and_not_generated() -> None:
    assert derive_validated_workflow_state(
        [{"required": True, "state": "completed"}]
    ) == "candidate_ready"
    assert derive_validated_workflow_state(
        [
            {"required": True, "state": "completed"},
            {"required": False, "state": "worker_timeout"},
        ]
    ) == "partially_completed"
    assert derive_validated_workflow_state(
        [{"required": True, "state": "semantic_verification_failed"}]
    ) == "verification_failed"
    assert derive_validated_workflow_state(
        [{"required": True, "state": "not_generated"}]
    ) == "failed"


def test_enabled_start_design_uses_the_product_application_path(tmp_path) -> None:
    from collections.abc import Generator

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
    from app.core.config import settings
    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app
    from app.testing.e2e_fixture_server import FixtureProvider, FixtureRunner

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_ai_provider] = lambda: FixtureProvider()
    app.dependency_overrides[get_cad_runner] = lambda: FixtureRunner(tmp_path)
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Volundr-Internal-Actor": "volundr-single-user"})
            response = client.post(
                "/api/validated-cadquery/designs",
                json={
                    "name": "Mounting plate",
                    "intent": "Build a simple mounting plate.",
                },
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["route"] == "validated_cadquery"
            assert payload["state"] == "candidate_ready", payload["diagnostics"]
            assert {output["output_id"] for output in payload["outputs"]} == {"primary_printable_output"}

            for suffix in ("", "/requirements", "/plan", "/outputs", "/verification", "/diagnostics"):
                fetched = client.get(f"/api/validated-cadquery/workflows/{payload['id']}{suffix}")
                assert fetched.status_code == 200, (suffix, fetched.text)

            accepted = client.post(f"/api/validated-cadquery/workflows/{payload['id']}/accept")
            assert accepted.status_code == 200, accepted.text
            accepted_payload = accepted.json()
            assert accepted_payload["package_available"] is True
            assert accepted_payload["package_manifest"]["schema_version"] == "validated-cadquery-design-package-v1"

            artifacts = client.get(f"/api/validated-cadquery/workflows/{payload['id']}/artifacts")
            assert artifacts.status_code == 200
            package = next(item for item in artifacts.json() if item["kind"] == "design_package")
            download = client.get(f"/api/validated-cadquery/workflows/{payload['id']}/artifacts/{package['artifact_id']}/download")
            assert download.status_code == 200
            assert download.headers["content-type"].startswith("application/zip")
        assert payload["project_id"]
        assert payload["id"]
    finally:
        settings.validated_cadquery_flow_enabled = previous
        app.dependency_overrides.clear()


def test_validated_route_is_unavailable_without_changing_legacy_defaults(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app

    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = False
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/validated-cadquery/designs",
                json={"name": "Disabled", "intent": "This must remain on legacy routing."},
            )
        assert response.status_code == 404
    finally:
        settings.validated_cadquery_flow_enabled = previous


def test_bounded_revision_reuses_accepted_workflow_authority(tmp_path) -> None:
    from collections.abc import Generator

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
    from app.core.config import settings
    from app.db.base import Base
    from app.db.session import get_db
    from app.main import app
    from app.testing.e2e_fixture_server import FixtureProvider, FixtureRunner

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    previous = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_ai_provider] = lambda: FixtureProvider()
    app.dependency_overrides[get_cad_runner] = lambda: FixtureRunner(tmp_path)
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Volundr-Internal-Actor": "volundr-single-user"})
            created = client.post(
                "/api/validated-cadquery/designs",
                json={"name": "Mounting plate", "intent": "Build a simple mounting plate."},
            ).json()
            accepted = client.post(f"/api/validated-cadquery/workflows/{created['id']}/accept")
            assert accepted.status_code == 200, accepted.text
            accepted_payload = accepted.json()

            revised = client.post(
                f"/api/validated-cadquery/workflows/{created['id']}/revision",
                json={
                    "instruction": "Increase the plate width and add one irregular cable slot feature.",
                    "dimension_changes": {"plate_width": 96},
                    "added_features": [{"type": "slot", "x_mm": 12, "y_mm": 17, "length_mm": 18}],
                    "protected_facts": ["primary printable output identity", "CadQuery source authority"],
                },
            )
            assert revised.status_code == 201, revised.text
            revised_payload = revised.json()
            assert revised_payload["state"] == "revision_ready", revised_payload["diagnostics"]
            assert revised_payload["parent_workflow_id"] == created["id"]
            assert revised_payload["parent_revision_id"] == accepted_payload["revision_id"]
            assert revised_payload["verification"]["output_identity_preserved"] is True
            assert {output["output_id"] for output in revised_payload["outputs"]} == {
                output["output_id"] for output in accepted_payload["outputs"]
            }
            accepted_revision = client.post(
                f"/api/candidates/{revised_payload['revision_id']}/accept"
            )
            assert accepted_revision.status_code == 200, accepted_revision.text
            assert accepted_revision.json()["is_accepted"] is True
    finally:
        settings.validated_cadquery_flow_enabled = previous
        app.dependency_overrides.clear()


def test_validated_cadquery_flow_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.validated_cadquery_flow_enabled is False


def test_validated_workflow_state_contract_is_product_facing() -> None:
    assert VALIDATED_WORKFLOW_STATES == {
        "awaiting_clarification",
        "requirements_ready",
        "plan_ready",
        "geometry_generating",
        "worker_running",
        "partially_completed",
        "verification_failed",
        "candidate_ready",
        "revision_ready",
        "failed",
    }


def test_validated_output_state_contract_preserves_failure_ownership() -> None:
    assert VALIDATED_OUTPUT_STATES == {
        "pending",
        "completed",
        "invalid_shape",
        "semantic_verification_failed",
        "worker_timeout",
        "export_failed",
        "not_generated",
        "blocked_by_upstream_failure",
    }


def test_output_classification_marks_artifact_and_verification_evidence() -> None:
    completed = classify_validated_output(
        {
            "success": True,
            "topology_metadata": {"valid": True, "detected_solid_count": 1},
            "semantic_verification": {"status": "passed"},
            "stl_path": "stl/body.stl",
            "step_path": "step/body.step",
        },
        required=True,
    )
    assert completed.state == "completed"
    assert completed.failure_owner is None
    assert completed.artifact_available is True
    assert completed.topology_status == "passed"

    failed = classify_validated_output(
        {
            "success": False,
            "failure_class": "timeout",
            "compile_error": "worker did not complete",
        },
        required=True,
    )
    assert failed.state == "worker_timeout"
    assert failed.failure_owner == "worker"
    assert failed.artifact_available is False
