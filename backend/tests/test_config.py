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


def test_settings_default_to_ollama_for_development() -> None:
    settings = Settings()

    assert settings.ai_provider == "ollama"
    assert settings.ollama_base_url == "http://10.1.20.25:11434"
    assert settings.ollama_model == "qwen3.5:9b"
    assert settings.ollama_timeout_seconds == 300
