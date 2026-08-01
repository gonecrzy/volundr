from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.testing.e2e_fixture_server import create_e2e_fixture_app


def test_chat_initial_request_auto_progresses_and_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "msg-1"},
            )
            assert first.status_code == 200
            body = first.json()
            assert body["action"] == "initial_design"
            assert body["current_stage"] == "working_version"
            assert body["current_working_revision_id"]

            duplicate = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "msg-1"},
            )
            assert duplicate.status_code == 200
            assert duplicate.json() == body

            summary = client.get("/api/test-fixture/latest-summary").json()
            assert summary["provider_call_count"] == 3
            assert len(summary["revisions"]) == 1
            assert summary["revisions"][0]["is_accepted"] is True


def test_chat_clarification_resumes_without_an_approval_step() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create a holder for my 70 mm wide device.", "client_message_id": "msg-1"},
            ).json()
            assert first["input_required"] is True
            assert first["action"] == "initial_design"
            assert "maximum available height" in first["assistant_message"]

            resumed = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "45 mm", "client_message_id": "msg-2"},
            )
            assert resumed.status_code == 200
            assert resumed.json()["current_stage"] == "working_version"


def test_chat_parameter_change_uses_configuration_without_provider_call() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            seeded = client.post("/api/test-fixture/scenarios/configure-organizer")
            assert seeded.status_code == 201
            project_id = seeded.json()["project"]["id"]
            before = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
            result = client.post(
                f"/api/projects/{project_id}/chat",
                json={"message": "Change columns from four to six.", "client_message_id": "msg-1"},
            )
            assert result.status_code == 200
            assert result.json()["action"] == "parameter_change"
            after = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
            assert after["provider_call_count"] == before["provider_call_count"]
            assert len(after["revisions"]) == 2
            assert after["revisions"][-1]["is_accepted"] is True
