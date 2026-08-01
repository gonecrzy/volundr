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


def test_settings_default_to_gemini_api_for_staged_generation() -> None:
    settings = Settings(_env_file=None)

    assert settings.ai_provider == "gemini_api"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_api_thinking_level == "minimal"


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


def test_settings_default_to_staged_generation_mode() -> None:
    settings = Settings(_env_file=None)

    assert settings.generation_mode == "advanced"
    assert settings.enable_design_plans is True
    assert settings.enable_multi_output is True
    assert settings.enable_structured_revisions is True


def test_settings_include_restart_recovery_and_cors_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.workflow_stale_seconds == 900
    assert settings.cors_origins == "http://localhost:5173,http://127.0.0.1:5173"
