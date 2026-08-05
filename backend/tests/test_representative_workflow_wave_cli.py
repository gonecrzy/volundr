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
    assert not list((root / "provider-attempts").glob("*.json"))


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
