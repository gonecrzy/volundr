from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class GeminiBenchmarkModelSpec(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", "model")
    @classmethod
    def trim_model_spec_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model specification values cannot be blank")
        return value


class GeminiBenchmarkExperimentCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    corpus_version: str = Field(min_length=1, max_length=120)
    corpus_hash: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="full", pattern="^(pilot|full|five_case|study)$")
    models: list[str] = Field(min_length=1, max_length=32)
    model_specs: list[GeminiBenchmarkModelSpec] | None = Field(default=None, min_length=1, max_length=32)
    runs: int = Field(default=2, ge=2, le=3)
    model_settings: dict[str, Any] = Field(default_factory=dict)
    frontend_build_identity: str = Field(default="benchmark-runner", min_length=1, max_length=512)

    @field_validator("label", "corpus_version", "corpus_hash")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("models")
    @classmethod
    def validate_models(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("model identifiers cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("model identifiers must be unique")
        return normalized

    @field_validator("model_specs")
    @classmethod
    def validate_model_specs(cls, values: list[GeminiBenchmarkModelSpec] | None) -> list[GeminiBenchmarkModelSpec] | None:
        if values is None:
            return values
        keys = [(item.provider.casefold(), item.model) for item in values]
        if len(set(keys)) != len(keys):
            raise ValueError("provider/model specifications must be unique")
        return values

    @model_validator(mode="after")
    def validate_study_matrix(self) -> "GeminiBenchmarkExperimentCreate":
        if self.mode == "study":
            if self.runs != 3:
                raise ValueError("study mode requires exactly three repetitions")
            if len(self.models) != 1 or self.models[0] != "gemini-3.5-flash-lite":
                raise ValueError("study mode requires exactly gemini-3.5-flash-lite")
            if self.model_specs is not None and (
                len(self.model_specs) != 1
                or self.model_specs[0].provider != "gemini_api"
                or self.model_specs[0].model != "gemini-3.5-flash-lite"
            ):
                raise ValueError("study mode model_specs must contain only gemini_api/gemini-3.5-flash-lite")
            return self
        if self.runs != 2:
            raise ValueError("non-study benchmark modes require exactly two runs")
        if len(self.models) < 2:
            raise ValueError("non-study benchmark modes require at least two models")
        if self.model_specs is not None and len(self.model_specs) < 2:
            raise ValueError("non-study benchmark modes require at least two model specifications")
        return self


class GeminiBenchmarkModelRead(BaseModel):
    id: str
    provider: str
    requested_model: str
    actual_model: str | None
    actual_digest: str | None
    availability_state: str
    settings: dict[str, Any]
    model_metadata: dict[str, Any]
    resource_profile: dict[str, Any]
    position: int


class GeminiBenchmarkRunRead(BaseModel):
    id: str
    model_config_id: str
    run_index: int
    stable_run_key: str
    state: str
    identity: dict[str, Any]
    report_path: str | None
    started_at: datetime | None
    finished_at: datetime | None


class GeminiBenchmarkExperimentRead(BaseModel):
    id: str
    label: str
    corpus_version: str
    corpus_hash: str
    mode: str
    requested_runs: int
    provider: str
    git_head: str
    migration_head: str
    prompt_versions: dict[str, Any]
    configuration_hash: str
    build_identities: dict[str, Any]
    model_settings: dict[str, Any]
    state: str
    started_at: datetime
    finished_at: datetime | None
    report_root: str
    models: list[GeminiBenchmarkModelRead] = Field(default_factory=list)
    runs: list[GeminiBenchmarkRunRead] = Field(default_factory=list)


class GeminiBenchmarkClaimCreate(BaseModel):
    position: int = Field(ge=0, le=49)
    title: str = Field(min_length=1, max_length=200)
    original_intent: str = Field(min_length=1, max_length=12000)


class GeminiBenchmarkMembershipRead(BaseModel):
    id: str
    run_id: str
    corpus_case_id: str
    position: int
    stable_project_key: str
    project_id: str | None
    state: str
    clarification_rounds: int
    retry_count: int
    outcome_category: str | None
    outcome_state: str | None
    final_outcome: str | None
    metrics: dict[str, Any]
    evidence_path: str | None
    started_at: datetime | None
    completed_at: datetime | None


class GeminiBenchmarkCompletionCreate(BaseModel):
    state: str = Field(pattern="^(completed|failed|incomplete|cancelled)$")
    clarification_rounds: int = Field(default=0, ge=0, le=2)
    retry_count: int = Field(default=0, ge=0, le=1)
    outcome_category: str | None = Field(default=None, max_length=80)
    outcome_state: str | None = Field(default=None, max_length=120)
    final_outcome: str | None = Field(default=None, max_length=2000)
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_path: str | None = Field(default=None, max_length=700)


class GeminiBenchmarkFinishCreate(BaseModel):
    state: str = Field(pattern="^(completed|failed|cancelled)$")


class GeminiBenchmarkModelAvailabilityCreate(BaseModel):
    provider: str | None = Field(default=None, max_length=80)
    requested_model: str = Field(min_length=1, max_length=160)
    actual_model: str | None = Field(default=None, max_length=160)
    actual_digest: str | None = Field(default=None, max_length=200)
    availability_state: str = Field(pattern="^(available|unavailable|unverified)$")
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    resource_profile: dict[str, Any] = Field(default_factory=dict)


class GeminiBenchmarkReportRead(BaseModel):
    experiment_id: str
    state: str
    membership_count: int
    completed_count: int
    report_paths: list[str] = Field(default_factory=list)


class OllamaPreflightCreate(BaseModel):
    model: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=120000)
