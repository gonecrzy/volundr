import json
from pathlib import Path

import pytest

from app.services.gemini_integration.representative_waves import (
    REQUIRED_WAVE_DIRECTORIES,
    REQUIRED_WAVE_REPORTS,
    WaveEvidenceStore,
    WaveBaselineState,
    WaveManifest,
    WaveRunner,
    analyze_wave_issues,
    initialize_wave,
    load_wave_state,
    load_wave_manifest,
)


def _project(project_id: str, title: str) -> dict:
    return {
        "project_id": project_id,
        "title": title,
        "user_request": f"Create {title}.",
        "frozen_facts": {"one_printed_part": True},
        "expected_output_count": 1,
        "expected_solid_counts": {"body": 1},
        "semantic_obligations": ["one connected solid"],
    }


def _manifest_payload(wave_id: str = "wave-test") -> dict:
    return {
        "schema_version": "volundr-representative-wave-v1",
        "wave_id": wave_id,
        "provider_profile": "gemini_flash_lite_contract_v1",
        "projects": [
            _project(f"{wave_id}-project-{index:02d}", f"project {index}")
            for index in range(1, 6)
        ],
        "execution_policy": {"baseline_before_corrections": True},
        "diagnostic_policy": {"preserve_multiple_issues": True},
        "call_caps": {"provider_logical_operations": 40, "provider_attempts": 50, "worker_jobs": 10},
        "stopping_rules": {"unsafe_blocker": "stop_project_advance_continue_forensics"},
    }


def test_manifest_loads_five_projects_with_stable_identity(tmp_path: Path) -> None:
    path = tmp_path / "wave.json"
    path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

    manifest = load_wave_manifest(path)

    assert isinstance(manifest, WaveManifest)
    assert manifest.schema_version == "volundr-representative-wave-v1"
    assert manifest.wave_id == "wave-test"
    assert [project.project_id for project in manifest.projects] == [
        "wave-test-project-01",
        "wave-test-project-02",
        "wave-test-project-03",
        "wave-test-project-04",
        "wave-test-project-05",
    ]
    assert manifest.provider_profile == "gemini_flash_lite_contract_v1"


def test_manifest_rejects_duplicate_or_missing_project_ids(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["projects"][1]["project_id"] = payload["projects"][0]["project_id"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="project_id values must be unique"):
        load_wave_manifest(path)


def test_initialize_wave_creates_repeatable_evidence_tree_and_preregistration(tmp_path: Path) -> None:
    manifest_path = tmp_path / "wave.json"
    manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    manifest = load_wave_manifest(manifest_path)

    root = tmp_path / "evidence" / "representative-workflow-wave-01"
    result = initialize_wave(root, manifest, repository_root=Path(__file__).resolve().parents[2])

    assert result["wave_id"] == "wave-test"
    assert all((root / directory).is_dir() for directory in REQUIRED_WAVE_DIRECTORIES)
    assert all((root / "reports" / report).is_file() for report in REQUIRED_WAVE_REPORTS)
    preregistration = json.loads((root / "reports/wave-preregistration.json").read_text())
    assert preregistration["projects"] == [project.project_id for project in manifest.projects]
    assert preregistration["baseline_before_corrections"] is True
    assert json.loads((root / "reports/frozen-project-corpus.json").read_text())["projects"][0]["project_id"] == "wave-test-project-01"


def test_corrections_are_blocked_until_all_baseline_projects_and_analysis_are_complete(tmp_path: Path) -> None:
    manifest = WaveManifest.from_dict(_manifest_payload())
    runner = WaveRunner(manifest, tmp_path / "wave")

    with pytest.raises(RuntimeError, match="baseline"):
        runner.authorize_corrections()

    runner.state = WaveBaselineState(
        completed_project_ids=tuple(project.project_id for project in manifest.projects),
        analyzed=True,
        issues_registered=True,
        clusters_complete=True,
        priority_complete=True,
    )
    assert runner.authorize_corrections()["authorized"] is True


def test_a_new_wave_is_loaded_from_data_without_orchestration_changes(tmp_path: Path) -> None:
    first = tmp_path / "wave-01.json"
    second = tmp_path / "wave-02.json"
    first.write_text(json.dumps(_manifest_payload("wave-01")), encoding="utf-8")
    second.write_text(json.dumps(_manifest_payload("wave-02")), encoding="utf-8")

    one = load_wave_manifest(first)
    two = load_wave_manifest(second)

    assert one.wave_id != two.wave_id
    assert two.projects[0].project_id == "wave-02-project-01"
    assert two.to_dict()["schema_version"] == one.to_dict()["schema_version"]


def test_wave_state_resume_is_idempotent(tmp_path: Path) -> None:
    manifest = WaveManifest.from_dict(_manifest_payload())
    runner = WaveRunner(manifest, tmp_path / "wave")

    runner.record_baseline_project(manifest.projects[0].project_id)
    runner.record_baseline_project(manifest.projects[0].project_id)
    runner.save_state()

    resumed = WaveRunner(manifest, tmp_path / "wave")
    load_wave_state(resumed)

    assert resumed.state.completed_project_ids == (manifest.projects[0].project_id,)


def test_wave_evidence_is_redacted_and_immutable(tmp_path: Path) -> None:
    store = WaveEvidenceStore(tmp_path / "wave", wave_id="wave-test")
    attempt = {
        "attempt_id": "wave-test-project-01:attempt-01",
        "project_id": "wave-test-project-01",
        "request": {"params": {"key": "secret-value"}},
        "auth_metadata": {"credential_value": "secret-value"},
    }

    store.record_provider_attempt(attempt)
    stored = store.provider_attempts()[0]
    serialized = json.dumps(stored)
    assert "secret-value" not in serialized

    with pytest.raises(RuntimeError, match="immutable"):
        store.record_provider_attempt({**attempt, "request": {"changed": True}})


def test_issue_analysis_preserves_multiple_issues_for_one_project(tmp_path: Path) -> None:
    manifest = WaveManifest.from_dict(_manifest_payload())
    store = WaveEvidenceStore(tmp_path / "wave", wave_id=manifest.wave_id)
    project_id = manifest.projects[0].project_id
    store.record_boundary({
        "boundary_id": f"{project_id}:requirements_adapter",
        "boundary": "requirements_adapter",
        "project_id": project_id,
        "output": {
            "accepted": False,
            "failure_class": "missing_fit_fact",
            "findings": [
                {"rule_id": "fit.fact.missing", "blocking": True, "message": "width missing"},
                {"rule_id": "unsafe.claim", "blocking": False, "message": "unsafe claim"},
            ],
        },
    })

    result = analyze_wave_issues(
        manifest,
        [{"project_id": project_id, "earliest_blocker": "requirements_adapter", "furthest_valid_stage": "requirements"}],
        store,
    )

    project_issues = [issue for issue in result["issues"] if issue["project_id"] == project_id]
    assert len(project_issues) >= 2
    assert {issue["classification"] for issue in project_issues} >= {"root_cause", "latent_independent_defect"}
