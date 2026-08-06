import pytest

from app.core.config import Settings


def test_settings_ignore_unrelated_env_file_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VOLUNDR_DATA_DIR=./data",
                "VOLUNDR_WEB_PORT=8080",
                "VOLUNDR_GEMINI_DIR=./data/gemini",
                "GEMINI_API_KEY=secret-value",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.data_dir.as_posix() == "data"


def test_settings_load_both_gemini_credentials_from_repository_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY_2=secondary-fixture-key\nGEMINI_API_KEY=primary-fixture-key\n",
        encoding="utf-8",
    )

    configured = Settings(_env_file=env_file)

    assert configured.gemini_api_key_2 == "secondary-fixture-key"
    assert configured.gemini_api_key == "primary-fixture-key"


def test_settings_support_explicit_executable_gemini_credential_slots() -> None:
    configured = Settings(
        _env_file=None,
        gemini_primary_credential_env="GEMINI_API_KEY",
        gemini_fallback_credential_env="",
    )

    assert configured.gemini_primary_credential_env == "GEMINI_API_KEY"
    assert configured.gemini_fallback_credential_env == ""


def test_settings_reject_unsupported_executable_gemini_credential_slot() -> None:
    with pytest.raises(ValueError, match="credential environment variable"):
        Settings(_env_file=None, gemini_primary_credential_env="GEMINI_API_KEY_3")


def test_settings_default_to_gemini_api_with_typed_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.ai_provider == "gemini_api"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_api_thinking_level == "minimal"
    assert settings.cad_workspace_dir == settings.data_dir / "jobs"


def test_settings_support_stage_specific_gemini_models(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VOLUNDR_GEMINI_MODEL=general-model",
                "VOLUNDR_GEMINI_REQUIREMENTS_MODEL=requirements-model",
                "VOLUNDR_GEMINI_DESIGN_PLAN_MODEL=plan-model",
                "VOLUNDR_GEMINI_GEOMETRY_MODEL=geometry-model",
                "VOLUNDR_GEMINI_GEOMETRY_REPAIR_MODEL=repair-model",
                "VOLUNDR_GEMINI_REVISION_PLANNING_MODEL=revision-model",
                "VOLUNDR_GEMINI_COMPONENT_REVISION_MODEL=component-model",
            ]
        ),
        encoding="utf-8",
    )

    configured = Settings(_env_file=env_file)

    assert configured.gemini_requirements_model == "requirements-model"
    assert configured.gemini_design_plan_model == "plan-model"
    assert configured.gemini_geometry_model == "geometry-model"
    assert configured.gemini_geometry_repair_model == "repair-model"
    assert configured.gemini_revision_planning_model == "revision-model"
    assert configured.gemini_component_revision_model == "component-model"


def test_settings_no_longer_exposes_completed_rollout_switches() -> None:
    settings = Settings(_env_file=None)

    assert not hasattr(settings, "generation_mode")
    assert not hasattr(settings, "enable_design_plans")
    assert not hasattr(settings, "enable_multi_output")
    assert not hasattr(settings, "enable_structured_revisions")
    assert not hasattr(settings, "chat_first")


def test_settings_derives_workspace_from_data_dir_and_keeps_explicit_override(tmp_path) -> None:
    derived = Settings(_env_file=None, data_dir=tmp_path / "data")
    explicit = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        cad_workspace_dir=tmp_path / "custom-jobs",
    )

    assert derived.cad_workspace_dir == tmp_path / "data" / "jobs"
    assert explicit.cad_workspace_dir == tmp_path / "custom-jobs"


def test_settings_include_restart_recovery_and_cors_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.workflow_stale_seconds == 900
    assert settings.cors_origins == "http://localhost:5173,http://127.0.0.1:5173"


def test_empty_optional_gemini_policy_path_is_unset(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VOLUNDR_GEMINI_POLICY_PATH=\n", encoding="utf-8")

    configured = Settings(_env_file=env_file)

    assert configured.gemini_policy_path is None


def test_empty_optional_build_boolean_values_are_treated_as_unset() -> None:
    settings = Settings(_env_file=None, build_dirty="", worker_build_dirty="")

    assert settings.build_dirty is None
    assert settings.worker_build_dirty is None
