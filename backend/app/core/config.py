from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOLUNDR_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("/app/data"))
    openscad_binary: str = Field(default="openscad")
    cad_workspace_dir: Path = Field(default=Path("/app/data/jobs"))
    cad_timeout_seconds: int = Field(default=60)
    max_source_bytes: int = Field(default=500 * 1024)
    max_stl_bytes: int = Field(default=100 * 1024 * 1024)
    ai_provider: str = Field(default="ollama")
    ollama_base_url: str = Field(default="http://10.1.20.25:11434")
    ollama_model: str = Field(default="qwen3.5:9b")
    ollama_timeout_seconds: int = Field(default=300)
    gemini_binary: str = Field(default="gemini")
    gemini_model: str | None = Field(default="gemini-3.5-flash-lite")
    gemini_timeout_seconds: int = Field(default=120)
    gemini_policy_path: Path | None = Field(default=None)
    generation_mode: str = Field(default="simple")
    enable_design_plans: bool = Field(default=False)
    enable_multi_output: bool = Field(default=False)
    enable_structured_revisions: bool = Field(default=False)
    enable_strict_marker_contract: bool = Field(default=False)

    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
