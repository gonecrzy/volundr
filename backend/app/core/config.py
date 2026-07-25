from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOLUNDR_", env_file=".env")

    data_dir: Path = Field(default=Path("/app/data"))
    openscad_binary: str = Field(default="openscad")
    cad_workspace_dir: Path = Field(default=Path("/app/data/jobs"))
    cad_timeout_seconds: int = Field(default=60)
    max_source_bytes: int = Field(default=500 * 1024)
    max_stl_bytes: int = Field(default=100 * 1024 * 1024)
    gemini_binary: str = Field(default="gemini")
    gemini_model: str | None = Field(default="gemini-3.5-flash-lite")
    gemini_timeout_seconds: int = Field(default=120)

    @cached_property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
