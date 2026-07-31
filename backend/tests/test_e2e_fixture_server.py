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


def test_project_generation_attempt_evidence_exposes_only_safe_metrics(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Evidence plate", "original_intent": "Make a mounting plate."},
        ).json()
        specification = client.post(
            f"/api/projects/{project['id']}/requirements",
            json={"user_instruction": "Create an 80 mm mounting plate."},
        ).json()
        plan = client.post(f"/api/design-specifications/{specification['id']}/design-plan").json()
        assert client.post(f"/api/design-plans/{plan['id']}/approve").status_code == 200
        assert client.post(f"/api/design-plans/{plan['id']}/generate").status_code == 201

        response = client.get(f"/api/projects/{project['id']}/generation-attempts")

        assert response.status_code == 200
        attempts = response.json()
        assert attempts
        assert all(attempt["provider"] == "fixture" for attempt in attempts)
        assert all(isinstance(attempt["duration_ms"], (int, float)) for attempt in attempts)
        assert all(isinstance(attempt["estimated_prompt_tokens"], int) for attempt in attempts)
        assert all("prompt" not in attempt and "raw_output" not in attempt for attempt in attempts)

        runs = client.get(f"/api/projects/{project['id']}/workflow-runs")
        assert runs.status_code == 200
        assert runs.json()
        assert all(run["project_id"] == project["id"] for run in runs.json())


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


def test_fixture_server_seeds_an_accepted_enclosure_with_stable_parts(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        seeded = client.post("/api/test-fixture/scenarios/revise-enclosure-lid")

        assert seeded.status_code == 201
        fixture = seeded.json()
        project_id = fixture["project"]["id"]
        outputs = client.get(f"/api/revisions/{fixture['current_revision']['id']}/outputs")
        plan = client.get(f"/api/projects/{project_id}/design-plan")

        assert outputs.status_code == 200
        assert {output["output_id"] for output in outputs.json()} == {"base", "lid"}
        assert plan.status_code == 200
        assert {component["id"] for component in plan.json()["plan"]["components"]} == {
            "base_shell",
            "snap_lid",
        }
        assert fixture["project"]["active_revision_id"] == fixture["current_revision"]["id"]


def test_enclosure_fixture_runs_approved_lid_revision_without_early_source_call(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        seeded = client.post("/api/test-fixture/scenarios/revise-enclosure-lid").json()
        project_id = seeded["project"]["id"]
        base_revision_id = seeded["current_revision"]["id"]

        plan_response = client.post(
            f"/api/projects/{project_id}/revision-plans",
            json={
                "base_revision_id": base_revision_id,
                "user_instruction": "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
                "reason": "user_request",
            },
        )
        assert plan_response.status_code == 201
        plan = plan_response.json()
        assert plan["revision_plan"]["targeted_components"] == ["snap_lid"]
        assert plan["revision_plan"]["targeted_outputs"] == ["lid"]
        assert plan["revision_plan"]["protected_components"] == ["base_shell"]
        assert plan["revision_plan"]["protected_outputs"] == ["base"]
        assert client.get(f"/api/test-fixture/projects/{project_id}/summary").json()["provider_call_count"] == 4

        before_approval = client.post(f"/api/revision-plans/{plan['id']}/generate")
        assert before_approval.status_code == 409
        assert client.get(f"/api/test-fixture/projects/{project_id}/summary").json()["provider_call_count"] == 4

        approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()
        candidate_response = client.post(f"/api/revision-plans/{approved['id']}/generate")
        assert candidate_response.status_code == 201
        candidate = candidate_response.json()
        assert candidate["review_state"] in {"ready", "ready_with_warnings"}
        assert client.get(f"/api/test-fixture/projects/{project_id}/summary").json()["provider_call_count"] == 5
        outputs = client.get(f"/api/revisions/{candidate['id']}/outputs").json()
        assert {output["output_id"] for output in outputs} == {"base", "lid"}
        assert all(output["detected_solid_count"] == 1 for output in outputs)


def test_enclosure_revision_bundle_contains_scope_and_preservation_evidence(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        seeded = client.post("/api/test-fixture/scenarios/revise-enclosure-lid").json()
        project_id = seeded["project"]["id"]
        plan = client.post(
            f"/api/projects/{project_id}/revision-plans",
            json={
                "base_revision_id": seeded["current_revision"]["id"],
                "user_instruction": "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
                "reason": "user_request",
            },
        ).json()
        approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()
        candidate = client.post(f"/api/revision-plans/{approved['id']}/generate").json()
        summary = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        revision_run = next(
            run for run in summary["workflow_runs"] if run["workflow_type"] == "component_revision"
        )

        bundle = client.get(f"/api/workflow-runs/{revision_run['id']}/debug-bundle.zip")

        assert bundle.status_code == 200
        with ZipFile(BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            assert any(name.endswith("approved_revision_plan-parsed-revision-plan.json") for name in names)
            assert any(name.endswith("source_contract_result-source-contract.json") for name in names)
            assert any(name.endswith("scope_compliance_result-revision-compliance.json") for name in names)
            assert any(name.endswith("output_preservation_result-component-revision-summary.json") for name in names)
            assert any(name.endswith("design_consistency_result-design-artifact-consistency.json") for name in names)
            assert any("component_revised_source-" in name and name.endswith(".py") for name in names)
            assert any(name.endswith("execution_manifest-execution-manifest.json") for name in names)
            assert any(name.endswith("output_manifest-output-manifest.json") for name in names)
            assert any(name.endswith("event-log.ndjson") for name in names)
            assert any(name.endswith("redaction-report.json") for name in names)
            assert "AIza" not in bundle.content.decode("utf-8", errors="ignore")


def test_enclosure_revision_scope_and_identity_fail_before_worker(tmp_path: Path) -> None:
    for mode in ("protected_base_drift", "identity_replacement"):
        app = create_e2e_fixture_app(tmp_path / mode)
        with TestClient(app) as client:
            seeded = client.post(
                f"/api/test-fixture/scenarios/revise-enclosure-lid?mode={mode}"
            ).json()
            project_id = seeded["project"]["id"]
            plan = client.post(
                f"/api/projects/{project_id}/revision-plans",
                json={
                    "base_revision_id": seeded["current_revision"]["id"],
                    "user_instruction": "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
                    "reason": "user_request",
                },
            ).json()
            approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()
            failed = client.post(f"/api/revision-plans/{approved['id']}/generate")

            assert failed.status_code == 409
            summary = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
            assert len(summary["worker_calls"]) == 1
            assert all(call["output_ids"] == ["base", "lid"] for call in summary["worker_calls"])
            expected_event = "geometry_body.failed" if mode == "identity_replacement" else "revision_scope.failed"
            assert expected_event in summary["workflow_event_types"]
            failed_run = next(
                run for run in summary["workflow_runs"] if run["workflow_type"] == "component_revision"
            )
            diagnosis = client.get(f"/api/workflow-runs/{failed_run['id']}/diagnosis")
            assert diagnosis.status_code == 200
            assert diagnosis.json()["root_cause"]["stage"] in {
                "source_extraction",
                "source_contract_validation",
                "revision_scope_validation",
                "scope_correction",
            }
            assert not any(
                revision["is_accepted"] is False and revision["id"] != seeded["current_revision"]["id"]
                for revision in summary["revisions"]
            )


def test_enclosure_revision_duplicate_generation_does_not_create_second_candidate(tmp_path: Path) -> None:
    app = create_e2e_fixture_app(tmp_path)
    with TestClient(app) as client:
        seeded = client.post("/api/test-fixture/scenarios/revise-enclosure-lid").json()
        project_id = seeded["project"]["id"]
        plan = client.post(
            f"/api/projects/{project_id}/revision-plans",
            json={
                "base_revision_id": seeded["current_revision"]["id"],
                "user_instruction": "Add a recessed finger pull to the lid only. Keep the enclosure body and lid fit unchanged.",
                "reason": "user_request",
            },
        ).json()
        approved = client.post(f"/api/revision-plans/{plan['id']}/approve").json()
        first = client.post(f"/api/revision-plans/{approved['id']}/generate")
        second = client.post(f"/api/revision-plans/{approved['id']}/generate")

        assert first.status_code == 201
        assert second.status_code == 409
        summary = client.get(f"/api/test-fixture/projects/{project_id}/summary").json()
        assert summary["provider_calls"].count("component_revision") == 1
        assert len([revision for revision in summary["revisions"] if not revision["is_accepted"]]) == 1


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
