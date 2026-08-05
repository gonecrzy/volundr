from pathlib import Path

import pytest

from app.services.gemini_integration.profile import (
    INTEGRATION_PROFILE_ID,
    GeminiFlashLiteContractV1,
    require_integration_profile,
)
from app.services.ai.model_policy import GeminiModelPolicy
from app.core.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_profile_is_explicit_and_binds_the_selected_provider_contract() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)

    assert profile.profile_id == INTEGRATION_PROFILE_ID
    assert profile.model == "gemini-3.5-flash-lite"
    assert profile.settings == {
        "temperature": 0.2,
        "topP": 0.95,
        "topK": 40,
        "candidateCount": 1,
    }
    assert profile.thinking_configuration is None
    assert profile.stage_prompt_versions == {
        "requirements": "T2-requirements-missing-fit-v1",
        "plan": "T0-current",
        "geometry": "T0-current",
    }
    assert profile.stage_output_tokens == {
        "requirements": 8192,
        "plan": 8192,
        "geometry": 8192,
    }


def test_profile_serialization_omits_thinking_config_and_has_stable_hash() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)
    payload = profile.request_configuration("requirements")

    assert payload == {
        "model": "gemini-3.5-flash-lite",
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.95,
            "topK": 40,
            "candidateCount": 1,
            "maxOutputTokens": 8192,
        },
    }
    assert "thinkingConfig" not in payload["generationConfig"]
    assert len(profile.settings_hash) == 64
    assert profile.settings_hash == GeminiFlashLiteContractV1.from_repository(REPO_ROOT).settings_hash


def test_profile_guard_rejects_normal_production_selection() -> None:
    assert require_integration_profile(INTEGRATION_PROFILE_ID) == INTEGRATION_PROFILE_ID

    with pytest.raises(ValueError, match="integration profile"):
        require_integration_profile("gemini_api")


def test_production_default_policy_remains_unchanged() -> None:
    policy = GeminiModelPolicy.from_settings(Settings(_env_file=None))

    assert policy.general_model == "gemini-3.5-flash-lite"
    assert policy.temperature == 0.2
    assert policy.thinking_level == "minimal"

