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
    scope_diagnostics: str | None = None
    design_specification: dict[str, Any] | None = None
    design_plan: dict[str, Any] | None = None
    revision_plan: dict[str, Any] | None = None
    output_manifest: dict[str, Any] | None = None
    selected_findings: list[dict[str, Any]] = field(default_factory=list)
    source_metadata: dict[str, Any] | None = None
    scoped_revision_context: dict[str, Any] | None = None
    configuration_context: dict[str, Any] | None = None
    source_authority: dict[str, Any] | None = None
    geometry_body_diagnostics: str | None = None
    active_requirements: list[dict[str, Any]] = field(default_factory=list)
    requirement_delta: list[dict[str, Any]] = field(default_factory=list)
    generation_contract_version: str = "v1"


@dataclass(frozen=True)
class ModelGenerationResult:
    raw_output: str
    provider: str
    provider_model: str | None = None
    usage_metadata: dict[str, Any] | None = None
    provider_request_id: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None


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
    usage_metadata: dict[str, Any] | None = None
    provider_request_id: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None


@dataclass(frozen=True)
class SourceBriefRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    expected_parameters: list[str] = field(default_factory=list)
    expected_geometric_invariants: list[dict[str, Any]] = field(default_factory=list)
    mesh_expectation: str | None = None


@dataclass(frozen=True)
class SourceBriefResult:
    raw_output: str
    provider: str
    provider_model: str | None = None
    usage_metadata: dict[str, Any] | None = None
    provider_request_id: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None


@dataclass(frozen=True)
class DesignPlanRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    design_specification: dict[str, Any]
    previous_design_plan: dict[str, Any] | None = None
    clarification_questions: list[dict[str, Any]] = field(default_factory=list)
    clarification_answers: list[dict[str, Any]] = field(default_factory=list)
    schema_repair_of_raw_output: str | None = None
    schema_validation_error: str | None = None
    defaults: dict[str, Any] = field(default_factory=dict)
    active_requirements: list[dict[str, Any]] = field(default_factory=list)
    requirement_delta: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DesignPlanResult:
    raw_output: str
    provider: str
    provider_model: str | None = None
    usage_metadata: dict[str, Any] | None = None
    provider_request_id: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None


@dataclass(frozen=True)
class RevisionPlanRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    reason: str
    base_revision_id: str
    design_specification: dict[str, Any] | None
    design_plan: dict[str, Any]
    product_parameters: list[dict[str, Any]] = field(default_factory=list)
    dependency_edges: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    features: list[dict[str, Any]] = field(default_factory=list)
    printable_outputs: list[dict[str, Any]] = field(default_factory=list)
    output_manifest: dict[str, Any] | None = None
    source_metadata: dict[str, Any] | None = None
    selected_findings: list[dict[str, Any]] = field(default_factory=list)
    geometric_measurements: list[dict[str, Any]] = field(default_factory=list)
    clarification_questions: list[dict[str, Any]] = field(default_factory=list)
    clarification_answers: list[dict[str, Any]] = field(default_factory=list)
    previous_revision_plan: dict[str, Any] | None = None
    schema_repair_of_raw_output: str | None = None
    schema_validation_error: str | None = None
    active_requirements: list[dict[str, Any]] = field(default_factory=list)
    requirement_delta: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RevisionPlanResult:
    raw_output: str
    provider: str
    provider_model: str | None = None
    usage_metadata: dict[str, Any] | None = None
    provider_request_id: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    provider_latency_ms: int | None = None


class AiProvider(Protocol):
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        ...

    async def generate_cadquery_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        ...

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        ...

    async def create_source_brief(self, request: SourceBriefRequest) -> SourceBriefResult:
        ...

    async def create_design_plan(self, request: DesignPlanRequest) -> DesignPlanResult:
        ...

    async def create_revision_plan(self, request: RevisionPlanRequest) -> RevisionPlanResult:
        ...
