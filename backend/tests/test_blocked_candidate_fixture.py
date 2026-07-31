from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.testing.e2e_fixture_server import create_e2e_fixture_app


def _seed(client: TestClient, failure_mode: str) -> dict:
    response = client.post(
        f"/api/test-fixture/scenarios/recoverable-blocked-part?failure_mode={failure_mode}"
    )
    assert response.status_code == 201
    return response.json()


def test_multiple_solids_fixture_preserves_current_design_and_diagnoses_topology(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        fixture = _seed(client, "multiple_solids")
        project_id = fixture["project"]["id"]
        candidate = fixture["blocked_revision"]

        assert fixture["project"]["active_revision_id"] == fixture["current_revision"]["id"]
        assert candidate["review_state"] == "blocked"
        output = client.get(f"/api/revisions/{candidate['id']}/outputs").json()[0]
        assert output["output_id"] == "plate"
        assert output["required"] is True
        assert output["expected_solid_count"] == 1
        assert output["detected_solid_count"] > 1

        acceptance = client.post(f"/api/candidates/{candidate['id']}/accept")
        assert acceptance.status_code == 409
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["active_revision_id"] == fixture["current_revision"]["id"]

        summary = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        diagnosis = client.get(f"/api/workflow-runs/{fixture['blocked_workflow_run_id']}/diagnosis")
        assert diagnosis.status_code == 200
        assert diagnosis.json()["root_cause"]["stage"] == "topology_validation"
        assert diagnosis.json()["downstream_effects"]


def test_worker_failure_fixture_retries_without_provider_and_preserves_failed_evidence(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        fixture = _seed(client, "worker_failure")
        project_id = fixture["project"]["id"]
        candidate_id = fixture["blocked_revision"]["id"]
        output = client.get(f"/api/revisions/{candidate_id}/outputs").json()[0]
        assert output["execution_state"] == "failed"
        source_hash = output["source_hash"]
        parameter_hash = output["parameter_hash"]
        before = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        assert "worker.failed" in before["workflow_event_types"]

        retry = client.post(f"/api/revision-outputs/{output['id']}/retry")

        assert retry.status_code == 200
        retried = retry.json()
        assert retried["execution_state"] in {"ready", "ready_with_warnings"}
        assert retried["source_hash"] == source_hash
        assert retried["parameter_hash"] == parameter_hash
        after = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        assert after["provider_call_count"] == before["provider_call_count"]
        assert len(after["worker_calls"]) == len(before["worker_calls"]) + 1
        assert after["workflow_event_types"].count("output_retry.started") == 1
        assert "worker.submitted" in after["workflow_event_types"]
        assert "candidate.classified" in after["workflow_event_types"]

        revision = client.get(f"/api/candidates/{candidate_id}").json()
        assert revision["review_state"] in {"ready", "ready_with_warnings"}
        accepted = client.post(f"/api/candidates/{candidate_id}/accept")
        assert accepted.status_code == 200

        duplicate_retry = client.post(f"/api/revision-outputs/{output['id']}/retry")
        assert duplicate_retry.status_code == 409
        assert len(client.get(f"/api/test-fixture/projects/{project_id}/summary").json()["worker_calls"]) == len(after["worker_calls"])

        retry_run = next(run for run in after["workflow_runs"] if run["workflow_type"] == "output_retry")
        assert retry_run["parent_workflow_run_id"] == retry_run["root_workflow_run_id"]
        bundle = client.get(f"/api/workflow-runs/{retry_run['id']}/debug-bundle.zip")
        assert bundle.status_code == 200
        with ZipFile(BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            assert any("pre_retry_worker_result" in name for name in names)
            assert any("retry_output_manifest" in name for name in names)
            assert any(name.endswith("redaction-report.json") for name in names)
