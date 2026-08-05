from pathlib import Path

import pytest

from scripts.run_gemini_provider_contract_integration import main


def test_cli_rejects_non_integration_profile_before_live_calls(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--profile", "gemini_api", "--root", str(tmp_path)])


def test_cli_dry_run_is_preregistered_and_makes_no_live_calls(tmp_path: Path) -> None:
    result = main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(tmp_path),
        "--dry-run",
    ])

    assert result == 0
    assert (tmp_path / "gemini-provider-contract-integration-01/reports/study-preregistration.json").is_file()


def test_cli_replay_and_counterfactual_modes_are_offline(tmp_path: Path) -> None:
    replay_root = tmp_path / "replay"
    assert main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(replay_root),
        "--replay",
    ]) == 0
    replay = (replay_root / "gemini-provider-contract-integration-01/replays/offline-replay.json").read_text()
    assert '"provider_calls": 0' in replay

    counterfactual_root = tmp_path / "counterfactual"
    assert main([
        "--profile", "gemini_flash_lite_contract_v1",
        "--study-id", "gemini-provider-contract-integration-01",
        "--root", str(counterfactual_root),
        "--counterfactual",
    ]) == 0
    fixtures = (counterfactual_root / "gemini-provider-contract-integration-01/counterfactuals/one-variable-fixtures.json").read_text()
    assert fixtures == "[]\n"
