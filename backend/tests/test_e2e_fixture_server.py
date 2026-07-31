from pathlib import Path

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
