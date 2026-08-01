from functools import cached_property
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOLUNDR_",
        env_file=(".env", "../.env"),
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Field(default=Path("/app/data"))
    cad_workspace_dir: Path = Field(default=Path("/app/data/jobs"))
    cad_timeout_seconds: int = Field(default=60)
    max_source_bytes: int = Field(default=500 * 1024)
    max_stl_bytes: int = Field(default=100 * 1024 * 1024)
    ai_provider: str = Field(default="gemini_api")
    ollama_base_url: str = Field(default="http://10.1.20.25:11434")
    ollama_model: str = Field(default="qwen2.5-coder:14b")
    ollama_timeout_seconds: int = Field(default=300)
    ollama_think: str | None = Field(default=None)
    gemini_binary: str = Field(default="gemini")
    gemini_model: str | None = Field(default="gemini-3.5-flash-lite")
    gemini_timeout_seconds: int = Field(default=120)
    gemini_policy_path: Path | None = Field(default=None)
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "VOLUNDR_GEMINI_API_KEY"),
    )
    gemini_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta"
    )
    gemini_api_temperature: float = Field(default=0.2)
    gemini_api_max_output_tokens: int = Field(default=8192)
    gemini_api_thinking_level: str | None = Field(default="minimal")
    gemini_api_max_retries: int = Field(default=2)
    gemini_api_max_retry_sleep_seconds: float = Field(default=60.0)
    generation_mode: str = Field(default="advanced")
    enable_design_plans: bool = Field(default=True)
    enable_multi_output: bool = Field(default=True)
    enable_structured_revisions: bool = Field(default=True)
    chat_first: bool = Field(default=False)

    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
