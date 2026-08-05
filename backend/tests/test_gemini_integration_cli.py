from pathlib import Path

import pytest

import scripts.run_gemini_provider_contract_integration as integration_cli


def test_cli_rejects_non_integration_profile_before_live_calls(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        integration_cli.main(["--profile", "gemini_api", "--root", str(tmp_path)])


def test_cli_dry_run_is_preregistered_and_makes_no_live_calls(tmp_path: Path) -> None:
    result = integration_cli.main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(tmp_path),
        "--dry-run",
    ])

    assert result == 0
    assert (tmp_path / "gemini-provider-contract-integration-01/reports/study-preregistration.json").is_file()


def test_cli_replay_and_counterfactual_modes_are_offline(tmp_path: Path) -> None:
    replay_root = tmp_path / "replay"
    assert integration_cli.main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(replay_root),
        "--replay",
    ]) == 0
    replay = (replay_root / "gemini-provider-contract-integration-01/replays/offline-replay.json").read_text()
    assert '"provider_calls": 0' in replay

    counterfactual_root = tmp_path / "counterfactual"
    assert integration_cli.main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(counterfactual_root),
        "--counterfactual",
    ]) == 0
    fixtures = (counterfactual_root / "gemini-provider-contract-integration-01/counterfactuals/one-variable-fixtures.json").read_text()
    assert fixtures == "[]\n"


def test_offline_modes_preserve_captured_project_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "preserve"
    assert integration_cli.main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(root),
        "--dry-run",
    ]) == 0
    reports = root / "gemini-provider-contract-integration-01/reports"
    (reports / "all-integration-loop-evidence.json").write_text(
        '{"study":{"study_id":"gemini-provider-contract-integration-01"},'
        '"provider_attempts":[],"project_outcomes":[{"project_id":"project-001"}],'
        '"issues":[{"issue_id":"issue-001"}]}\n',
        encoding="utf-8",
    )

    assert integration_cli.main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(root),
        "--replay",
    ]) == 0

    assert '"project_id": "project-001"' in (reports / "project-outcomes.json").read_text()
    assert '"issue_id": "issue-001"' in (reports / "issue-register.json").read_text()


def test_cli_live_fails_before_provider_calls_without_secondary_credential(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "primary-secret")

    def missing_secondary_credential():
        raise RuntimeError("GEMINI_API_KEY_2 is absent; no provider call was attempted")

    monkeypatch.setattr(integration_cli, "load_secondary_credential", missing_secondary_credential)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY_2"):
        integration_cli.main([
            "--profile", "gemini_flash_lite_contract_v1",
            "--study-id", "gemini-provider-contract-integration-01",
            "--root", str(tmp_path),
            "--live",
        ])
    assert not list((tmp_path / "gemini-provider-contract-integration-01/captures").rglob("*.json"))
