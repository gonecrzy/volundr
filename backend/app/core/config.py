from functools import cached_property
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOLUNDR_",
        env_file=(".env", "../.env"),
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Field(default=Path("/app/data"))
    cad_workspace_dir: Path | None = Field(default=None)
    cad_timeout_seconds: int = Field(default=60)
    workflow_stale_seconds: int = Field(default=900)
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")
    max_source_bytes: int = Field(default=500 * 1024)
    max_stl_bytes: int = Field(default=100 * 1024 * 1024)
    ai_provider: str = Field(default="gemini_api")
    build_git_sha: str | None = Field(default=None)
    build_branch: str | None = Field(default=None)
    build_timestamp: str | None = Field(default=None)
    build_dirty: bool | None = Field(default=None)
    build_release_label: str | None = Field(default=None)
    worker_build_git_sha: str | None = Field(default=None)
    worker_build_timestamp: str | None = Field(default=None)
    worker_build_dirty: bool | None = Field(default=None)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen2.5-coder:14b")
    ollama_timeout_seconds: int = Field(default=300)
    ollama_think: str | None = Field(default=None)
    gemini_binary: str = Field(default="gemini")
    gemini_model: str = Field(default="gemini-3.5-flash-lite")
    gemini_requirements_model: str | None = Field(default=None)
    gemini_design_plan_model: str | None = Field(default=None)
    gemini_geometry_model: str | None = Field(default=None)
    gemini_geometry_repair_model: str | None = Field(default=None)
    gemini_revision_planning_model: str | None = Field(default=None)
    gemini_component_revision_model: str | None = Field(default=None)
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
    snapshots_enabled: bool = Field(default=True)
    # Advanced deployment switch. It is intentionally absent from the minimal
    # .env.example and is exposed to the browser only as a safe boolean.
    developer_tools_enabled: bool = Field(default=False)
    snapshot_image_width: int = Field(default=768, ge=128, le=2048)
    snapshot_image_height: int = Field(default=768, ge=128, le=2048)
    snapshot_timeout_seconds: int = Field(default=30, ge=1, le=300)
    snapshot_max_whole_design_views: int = Field(default=5, ge=1, le=8)
    snapshot_max_components: int = Field(default=24, ge=1, le=100)
    snapshot_section_enabled: bool = Field(default=True)
    snapshot_background: str = Field(default="neutral_light")

    @field_validator("gemini_policy_path", mode="before")
    @classmethod
    def normalize_empty_gemini_policy_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def derive_storage_paths(self) -> "Settings":
        if self.cad_workspace_dir is None:
            self.cad_workspace_dir = self.data_dir / "jobs"
        return self

    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
