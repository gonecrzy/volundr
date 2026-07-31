from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.testing.e2e_fixture_server import create_e2e_fixture_app


def test_fixture_server_persists_real_workflow_and_exposes_bounded_summary(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Fixture plate", "original_intent": "Make a mounting plate."},
        ).json()
        requirements = client.post(
            f"/api/projects/{project['id']}/requirements",
            json={"user_instruction": "Create an 80 mm mounting plate."},
        )

        assert requirements.status_code == 201
        workflow_run_id = requirements.headers["x-workflow-run-id"]
        assert client.get(f"/api/workflow-runs/{workflow_run_id}").status_code == 200

        summary = client.get(f"/api/test-fixture/projects/{project['id']}/summary")
        assert summary.status_code == 200
        assert summary.json()["provider_call_count"] == 1
        assert summary.json()["workflow_run_ids"] == [workflow_run_id]
        assert "arbitrary_payload" not in summary.json()


def test_fixture_server_generates_a_real_candidate_after_plan_approval(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Fixture plate", "original_intent": "Make a mounting plate."},
        ).json()
        specification = client.post(
            f"/api/projects/{project['id']}/requirements",
            json={"user_instruction": "Create an 80 mm mounting plate."},
        ).json()
        plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan")

        assert plan.status_code == 201
        approved = client.post(f"/api/design-plans/{plan.json()['id']}/approve")
        assert approved.status_code == 200
        candidate = client.post(f"/api/design-plans/{plan.json()['id']}/generate")

        assert candidate.status_code == 201
        assert candidate.json()["review_state"] == "ready_with_warnings"
        outputs = client.get(f"/api/revisions/{candidate.json()['id']}/outputs")
        assert outputs.status_code == 200
        assert [output["output_id"] for output in outputs.json()] == ["plate"]
        summary = client.get(f"/api/test-fixture/projects/{project['id']}/summary").json()
        assert "source_generation" in summary["provider_calls"]
        assert "cad_execution" in summary["artifact_stages"]
        assert "candidate.classified" in summary["workflow_event_types"]


def test_fixture_server_seeds_an_accepted_configurable_organizer(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/test-fixture/scenarios/configure-organizer")

        assert response.status_code == 201
        fixture = response.json()
        assert fixture["project"]["active_revision_id"] == fixture["current_revision"]["id"]
        parameters = client.get(
            f"/api/projects/{fixture['project']['id']}/configuration/parameters"
        )
        assert parameters.status_code == 200
        assert {parameter["id"] for parameter in parameters.json()} >= {"column_count", "wall_thickness"}
        loaded = client.get(f"/api/projects/{fixture['project']['id']}")
        assert loaded.headers["x-workflow-run-id"]
        assert loaded.headers["x-workflow-correlation-id"]


def test_configured_organizer_bundle_contains_configuration_evidence(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        seeded = client.post("/api/test-fixture/scenarios/configure-organizer").json()
        project_id = seeded["project"]["id"]
        base_revision_id = seeded["current_revision"]["id"]
        preview = client.post(
            f"/api/projects/{project_id}/configuration/preview",
            json={"base_revision_id": base_revision_id, "parameter_values": {"column_count": 6}},
        )
        assert preview.status_code == 201
        change = preview.json()
        assert change["requested_changes"] == {"column_count": 6}
        candidate = client.post(f"/api/configuration-changes/{change['id']}/generate")
        assert candidate.status_code == 201
        summary = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        configuration_run = next(
            run for run in summary["workflow_runs"] if run["workflow_type"] == "configuration_change"
        )
        initial_run = next(
            run for run in summary["workflow_runs"] if run["workflow_type"] == "initial_generation"
        )
        assert configuration_run["parent_workflow_run_id"] == initial_run["id"]
        assert configuration_run["root_workflow_run_id"] == initial_run["root_workflow_run_id"]
        assert configuration_run["correlation_id"] == initial_run["correlation_id"]
        bundle = client.get(f"/api/workflow-runs/{configuration_run['id']}/debug-bundle.zip")
        assert bundle.status_code == 200
        with ZipFile(BytesIO(bundle.content)) as archive:
            names = set(archive.namelist())
            assert any(name.endswith("configuration_change_record-configuration.json") for name in names)
            assert any(name.endswith("configuration_override_manifest-parameter-overrides.json") for name in names)
            assert any(name.endswith("event-log.ndjson") for name in names)
            assert any(name.endswith("diagnosis.json") for name in names)
            assert any(name.endswith("redaction-report.json") for name in names)
