from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.testing.e2e_fixture_server import create_e2e_fixture_app
from app.services.projects.chat_workflow import ChatWorkflowService


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
            assert summary["provider_call_count"] == 2
            assert "planning_route_decision" in summary["artifact_types"]
            assert "cad_brief" in summary["artifact_types"]
            assert "geometry_execution_context" in summary["artifact_types"]
            assert "prompt_context_pack" in summary["artifact_types"]
            assert len(summary["revisions"]) == 1
            assert summary["revisions"][0]["is_accepted"] is True

            messages = client.get(f"/api/projects/{project['id']}/messages")
            assert messages.status_code == 200
            persisted = messages.json()
            visible = [message for message in persisted if message["role"] != "system_event"]
            assert [message["role"] for message in visible] == ["user", "assistant_success"]
            assert visible[1]["content"] == body["assistant_message"]

            after_duplicate = client.get(f"/api/projects/{project['id']}/messages").json()
            assert after_duplicate == persisted


def test_chat_generation_failure_returns_structured_blocked_outcome(monkeypatch) -> None:
    async def fail_generation(self, project, workflow_run, intent, message):
        raise ValueError("source contract failed")

    monkeypatch.setattr(ChatWorkflowService, "_dispatch", fail_generation)
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            result = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "blocked-1"},
            )
            assert result.status_code == 200
            body = result.json()
            assert body["current_stage"] == "blocked_attempt"
            assert body["input_required"] is False
            assert body["current_working_revision_id"] is None
            assert "No working version has been created yet." in body["assistant_message"]
            assert body["blocked_attempt"]["failure_class"] == "workflow_failure"
            runs = client.get(f"/api/projects/{project['id']}/workflow-runs").json()
            assert all(run["status"] != "running" for run in runs)


def test_failed_ai_revision_attaches_to_authoritative_user_message_without_crashing(monkeypatch) -> None:
    async def fail_generation(self, project, workflow_run, intent, message):
        self.service._create_failed_ai_revision(
            project=project,
            user_instruction=message,
            user_message_id=self._active_user_message_id,
            source_type="ai_initial",
            raw_ai_output="not valid geometry",
            error_message="geometry body invalid",
        )
        raise ValueError("geometry body invalid")

    monkeypatch.setattr(ChatWorkflowService, "_dispatch", fail_generation)
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            result = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create a failed bracket.", "client_message_id": "failed-revision"},
            )

            assert result.status_code == 200
            messages = client.get(f"/api/projects/{project['id']}/messages").json()
            visible = [message for message in messages if message["role"] != "system_event"]
            assert [message["role"] for message in visible] == ["user", "assistant_blocked"]
            assert visible[0]["content"] == "Create a failed bracket."


def test_chat_generation_failure_preserves_existing_current_version(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            baseline = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "baseline"},
            ).json()
            assert baseline["current_working_revision_id"]

            async def fail_generation(self, project, workflow_run, intent, message):
                raise ValueError("source contract failed")

            monkeypatch.setattr(ChatWorkflowService, "_dispatch", fail_generation)
            result = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Make a revision that fails.", "client_message_id": "blocked-2"},
            )
            assert result.status_code == 200
            body = result.json()
            assert body["current_working_revision_id"] == baseline["current_working_revision_id"]
            assert "Your Current working version is unchanged." in body["assistant_message"]


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
            summary = client.get("/api/test-fixture/latest-summary").json()
            assert "compact_cad_plan" in summary["artifact_types"]

            messages = client.get(f"/api/projects/{project['id']}/messages").json()
            visible = [message for message in messages if message["role"] != "system_event"]
            assert [message["content"] for message in visible].count("45 mm") == 1
            assert [message["content"] for message in visible].count(
                "Create a holder for my 70 mm wide device."
            ) == 1
            active = client.get(f"/api/projects/{project['id']}/requirements/active").json()["requirements"]
            assert any(item.get("source") == "clarification_user" for item in active)


def test_chat_multipart_request_keeps_detailed_plan_compatibility() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            result = client.post(
                f"/api/projects/{project['id']}/chat",
                json={
                    "message": "Create a two-piece enclosure with a removable lid and four screws.",
                    "client_message_id": "detailed-1",
                },
            )
            assert result.status_code == 200
            assert result.json()["current_stage"] == "working_version"
            summary = client.get("/api/test-fixture/latest-summary").json()
            assert "detailed_design_plan" in summary["artifact_types"]
            assert "design_plan_generation" in summary["artifact_stages"]


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


def test_ordinary_numeric_revision_does_not_route_as_configuration() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "ordinary-1"},
            ).json()
            before = client.get("/api/test-fixture/latest-summary").json()

            revised = client.post(
                f"/api/projects/{project['id']}/chat",
                json={
                    "message": "Change plate width to 90 mm.",
                    "client_message_id": "ordinary-2",
                },
            )
            assert revised.status_code == 200
            assert revised.json()["action"] == "structural_revision"
            after = client.get("/api/test-fixture/latest-summary").json()
            assert after["provider_call_count"] > before["provider_call_count"]
            assert "revision_plan_generation" not in after["provider_calls"]
            assert "cad_revision_brief" in after["artifact_types"]
            assert revised.json()["current_working_revision_id"] != first["current_working_revision_id"]


def test_twenty_ordinary_revisions_remain_recoverable_without_preexisting_controls() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "long-0"},
            ).json()
            current_revision_id = first["current_working_revision_id"]

            for index in range(1, 21):
                response = client.post(
                    f"/api/projects/{project['id']}/chat",
                    json={
                        "message": f"Change plate width to {80 + index} mm.",
                        "client_message_id": f"long-{index}",
                    },
                )
                assert response.status_code == 200, response.json()
                body = response.json()
                assert body["current_working_revision_id"]
                current_revision_id = body["current_working_revision_id"]

            revisions = client.get(f"/api/projects/{project['id']}/revisions").json()
            assert len(revisions) == 21
            assert revisions[-1]["id"] == current_revision_id
            assert revisions[-1]["is_accepted"] is True
            assert all(revision["is_accepted"] for revision in revisions)
            active = client.get(f"/api/projects/{project['id']}/requirements/active").json()
            width = next(item for item in active["requirements"] if item["requirement_id"] == "plate_width")
            assert width["value"] == 100


def test_chat_start_over_creates_recoverable_child_lineage() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "start-1"},
            ).json()
            first_revision_id = first["current_working_revision_id"]

            restarted = client.post(
                f"/api/projects/{project['id']}/chat",
                json={
                    "message": "Start over, but keep the 80 mm plate. Try a different approach.",
                    "client_message_id": "start-2",
                },
            )
            assert restarted.status_code == 200
            body = restarted.json()
            assert body["current_working_revision_id"] != first_revision_id

            summary = client.get(f"/api/test-fixture/projects/{project['id']}/summary").json()
            revisions = summary["revisions"]
            assert len(revisions) == 2
            assert revisions[1]["is_accepted"] is True
            assert client.get(f"/api/revisions/{revisions[1]['id']}/diff").status_code == 200


def test_explicit_control_request_is_revisionable_and_activates_only_that_control() -> None:
    with TemporaryDirectory() as directory:
        with TestClient(create_e2e_fixture_app(Path(directory))) as client:
            project = client.post("/api/projects/draft").json()
            first = client.post(
                f"/api/projects/{project['id']}/chat",
                json={"message": "Create an 80 mm mounting plate.", "client_message_id": "control-1"},
            ).json()
            before = client.get(f"/api/test-fixture/projects/{project['id']}/summary").json()

            revised = client.post(
                f"/api/projects/{project['id']}/chat",
                json={
                    "message": "Expose plate width as an adjustable control.",
                    "client_message_id": "control-2",
                },
            )
            assert revised.status_code == 200
            assert revised.json()["current_working_revision_id"]
            after = client.get(f"/api/test-fixture/projects/{project['id']}/summary").json()
            assert after["provider_call_count"] == before["provider_call_count"] + 2

            plan = client.get(f"/api/projects/{project['id']}/design-plan").json()["plan"]
            assert [item["parameter_id"] for item in plan["exposed_controls"]] == ["plate_width"]
            assert first["current_working_revision_id"] != revised.json()["current_working_revision_id"]
