from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelGenerationRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    current_source: str | None = None
    contract_diagnostics: str | None = None
    compiler_diagnostics: str | None = None
    design_specification: dict[str, Any] | None = None
    generation_contract_version: str = "v1"


@dataclass(frozen=True)
class ModelGenerationResult:
    raw_output: str
    provider: str
    provider_model: str | None = None


@dataclass(frozen=True)
class RequirementExtractionRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    previous_specification: dict[str, Any] | None = None
    clarification_questions: list[dict[str, Any]] = field(default_factory=list)
    clarification_answers: list[dict[str, Any]] = field(default_factory=list)
    schema_repair_of_raw_output: str | None = None
    schema_validation_error: str | None = None
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequirementExtractionResult:
    raw_output: str
    provider: str
    provider_model: str | None = None


class AiProvider(Protocol):
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        ...

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        ...
