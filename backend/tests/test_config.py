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


def test_settings_default_to_staged_generation_mode() -> None:
    settings = Settings(_env_file=None)

    assert settings.generation_mode == "advanced"
    assert settings.enable_design_plans is True
    assert settings.enable_multi_output is True
    assert settings.enable_structured_revisions is True
