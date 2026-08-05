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

