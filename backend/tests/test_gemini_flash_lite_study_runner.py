from pathlib import Path

import pytest

from app.services.gemini_consistency.study import (
    FLASH_LITE_MODEL,
    FlashLiteStudyConfig,
    FlashLiteStudyRunner,
    model_identity_matches,
    validate_flash_lite_study_config,
)


CORPUS_PATH = Path(__file__).parents[2] / "benchmarks" / "gemini-flash-lite-study-v1.json"


def test_study_dry_run_is_exactly_sixty_project_operations(tmp_path: Path) -> None:
    runner = FlashLiteStudyRunner(
        FlashLiteStudyConfig(
            corpus_path=CORPUS_PATH,
            output_root=tmp_path / "study",
            dry_run=True,
        )
    )

    manifest = runner.run()

    assert manifest["model"] == FLASH_LITE_MODEL
    assert manifest["case_ids"] == [f"case-{index:03d}" for index in range(1, 11)]
    assert manifest["repetitions_per_round"] == 3
    assert manifest["rounds"] == ["baseline", "validation"]
    assert manifest["project_operations"] == 60
    assert manifest["provider_calls"] == 0


def test_study_config_rejects_model_substitution() -> None:
    config = FlashLiteStudyConfig(corpus_path=CORPUS_PATH, model="gemini-2.5-pro")

    with pytest.raises(ValueError, match="gemini-3.5-flash-lite"):
        validate_flash_lite_study_config(config)


def test_provider_version_suffix_is_not_model_substitution() -> None:
    assert model_identity_matches("gemini-3.5-flash-lite", "gemini-3.5-flash-lite-20260801")
    assert not model_identity_matches("gemini-3.5-flash-lite", "gemini-3.5-flash")
