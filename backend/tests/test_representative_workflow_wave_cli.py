import json
from pathlib import Path

import pytest

import scripts.run_representative_workflow_wave as wave_cli


def _manifest(path: Path) -> Path:
    projects = [
        {
            "project_id": f"wave-test-project-{index:02d}",
            "title": f"project {index}",
            "user_request": f"Create project {index}.",
            "frozen_facts": {"one_printed_part": True},
            "expected_output_count": 1,
            "expected_solid_counts": {"body": 1},
        }
        for index in range(1, 6)
    ]
    path.write_text(json.dumps({
        "schema_version": "volundr-representative-wave-v1",
        "wave_id": "wave-test",
        "provider_profile": "gemini_flash_lite_contract_v1",
        "projects": projects,
        "execution_policy": {"baseline_before_corrections": True},
        "diagnostic_policy": {},
        "call_caps": {"provider_logical_operations": 40, "provider_attempts": 50, "worker_jobs": 10},
        "stopping_rules": {},
    }), encoding="utf-8")
    return path


def test_prepare_is_provider_free(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    root = tmp_path / "wave"

    assert wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--prepare"]) == 0
    assert (root / "reports/wave-preregistration.json").is_file()
    profile = json.loads((root / "reports/provider-profile.json").read_text())
    assert profile["model"] == "gemini-3.5-flash-lite"
    assert profile["resolved_stage_prompt_versions"]["geometry"] == "T5-geometry-exact-slot-contract-v1"
    assert profile["seed"] == "omitted"
    assert profile["thinkingConfig"] == "omitted"
    assert not list((root / "provider-attempts").glob("*.json"))


def test_prepare_records_preregistered_t5_parameter_map_version(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    payload = json.loads(manifest.read_text())
    payload["execution_policy"]["geometry_prompt_version"] = "T5-geometry-exact-slot-contract-v2-parameter-map"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / "wave"

    assert wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--prepare"]) == 0
    profile = json.loads((root / "reports/provider-profile.json").read_text())
    assert profile["resolved_stage_prompt_versions"]["geometry"] == "T5-geometry-exact-slot-contract-v2-parameter-map"


def test_live_fails_before_provider_calls_without_secondary_credential(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    root = tmp_path / "wave"
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "primary-secret")

    def missing_secondary_credential():
        raise RuntimeError("GEMINI_API_KEY_2 is absent; no provider call was attempted")

    monkeypatch.setattr(wave_cli, "load_secondary_credential", missing_secondary_credential)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY_2"):
        wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--baseline", "--live"])

    assert not list((root / "provider-attempts").glob("*.json"))


def test_replay_is_offline_and_preserves_zero_call_counts(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    root = tmp_path / "wave"
    assert wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--prepare"]) == 0

    assert wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--replay"]) == 0
    replay = json.loads((root / "reports/counterfactual-replays.json").read_text())
    assert replay["provider_calls"] == 0
    assert replay["worker_calls"] == 0


def test_offline_replay_does_not_reinitialize_repository_snapshot(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    root = tmp_path / "wave"

    def unexpected_initialization(*args, **kwargs):
        raise AssertionError("offline replay must not initialize or rewrite repository snapshot")

    monkeypatch.setattr(wave_cli, "initialize_wave", unexpected_initialization)

    assert wave_cli.main(["--manifest", str(manifest), "--root", str(root), "--replay"]) == 0


def test_finalize_records_wave_decision_and_fresh_next_wave_recommendation(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path / "manifest.json")
    root = tmp_path / "wave"
    assert wave_cli.main(["--manifest", str(manifest_path), "--root", str(root), "--prepare"]) == 0
    project_ids = [f"wave-test-project-{index:02d}" for index in range(1, 6)]
    reports = root / "reports"
    (reports / "wave-state.json").write_text(json.dumps({
        "wave_id": "wave-test",
        "manifest_hash": json.loads((reports / "wave-preregistration.json").read_text())["manifest_hash"],
        "baseline": {
            "completed_project_ids": project_ids,
            "analyzed": True,
            "issues_registered": True,
            "clusters_complete": True,
            "priority_complete": True,
        },
    }))
    (reports / "project-outcomes.json").write_text(json.dumps([{"project_id": item} for item in project_ids]))
    (reports / "issue-register.json").write_text(json.dumps([{
        "issue_id": "wave-test-project-01-issue-01",
        "project_id": "wave-test-project-01",
        "recommended_fix_boundary": "plan_adapter",
        "status": "open",
    }]))
    (reports / "differential-replays.json").write_text(json.dumps([{
        "project_id": "wave-test-project-01",
        "single_variable_changed": "plan_adapter",
        "fix_confirmed": True,
    }]))
    (reports / "regression-replay.json").write_text(json.dumps([{"project_id": item, "provider_calls": 0, "worker_calls": 0} for item in project_ids]))

    assert wave_cli.main(["--manifest", str(manifest_path), "--root", str(root), "--finalize"]) == 0
    decision = json.loads((reports / "wave-decision.json").read_text())
    recommendation = json.loads((reports / "next-wave-recommendation.json").read_text())
    assert decision["decision"] == "wave_requires_generalized_narrow_fix"
    assert len(recommendation["projects"]) == 5
    assert json.loads((reports / "corrections-applied.json").read_text())[0]["boundary"] == "plan_adapter"

    template_path = tmp_path / "wave-02-manifest.json"
    assert wave_cli.main([
        "--manifest", str(manifest_path),
        "--root", str(root),
        "--next-wave-template",
        "--output", str(template_path),
    ]) == 0
    template = json.loads(template_path.read_text())
    assert template["wave_id"] == "wave-02"
    assert [project["project_id"] for project in template["projects"]] == [
        f"wave-02-project-{index:02d}" for index in range(1, 6)
    ]
