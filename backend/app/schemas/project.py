from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequirementSource(StrEnum):
    USER = "user"
    CLARIFICATION = "clarification"
    CALCULATED = "calculated"
    PRINTER_PROFILE = "printer_profile"
    PRODUCT_DEFAULT = "product_default"
    AI_ASSUMPTION = "ai_assumption"


class RequirementImportance(StrEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    OPTIONAL = "optional"
    COSMETIC = "cosmetic"


class RequirementOutcome(StrEnum):
    GENERATION_READY = "generation_ready"
    CLARIFICATION_REQUIRED = "clarification_required"
    REQUIREMENTS_CONFLICT = "requirements_conflict"
    UNSUPPORTED_REQUEST = "unsupported_request"
    EXTRACTION_FAILED = "extraction_failed"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    original_intent: str = Field(min_length=1)


class ProjectSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    original_intent: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    original_intent: str | None = Field(default=None, min_length=1)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    original_intent: str
    status: str
    active_revision_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_id: str | None
    role: str
    content: str
    created_at: datetime


class ManualRevisionCreate(BaseModel):
    scad_source: str = Field(min_length=1)
    user_instruction: str | None = None

    @field_validator("scad_source")
    @classmethod
    def require_non_blank_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("OpenSCAD source cannot be blank")
        return value


class GenerationCreate(BaseModel):
    user_instruction: str = Field(min_length=1)
    design_specification_id: str | None = None


class RequirementExtractionCreate(BaseModel):
    user_instruction: str = Field(min_length=1)


class DesignDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | int | str | bool | None = None
    unit: str | None = None
    tolerance: float | int | str | None = None
    source: RequirementSource
    importance: RequirementImportance
    protected: bool = False


class DesignParameter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | int | str | bool | None = None
    unit: str | None = None
    source: RequirementSource
    importance: RequirementImportance
    protected: bool = False
    editable: bool = True
    explanation: str | None = None


class DesignFunctionalRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: RequirementSource
    importance: RequirementImportance
    protected: bool = False


class DesignAssumption(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: Literal["product_default", "printer_profile", "ai_assumption", "calculated"]
    requires_approval: bool = False


class DesignClarificationQuestionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reason: str | None = None
    related_requirement_id: str | None = None


class DesignSpecificationPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    project_id: str | None = None
    generation_attempt_id: str | None = None
    object_type: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    units: str = "mm"
    supported_scope: bool = True
    critical_dimensions: list[DesignDimension] = Field(default_factory=list)
    parameters: list[DesignParameter] = Field(default_factory=list)
    functional_requirements: list[DesignFunctionalRequirement] = Field(default_factory=list)
    print_requirements: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[DesignAssumption] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    missing_requirements: list[dict[str, Any]] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_questions: list[DesignClarificationQuestionPayload] = Field(default_factory=list)
    generation_ready: bool = False
    outcome: RequirementOutcome | None = None


class ClarificationQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    design_specification_id: str
    requirement_id: str | None
    question: str
    reason: str | None
    display_order: int
    created_at: datetime


class DesignSpecificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    generation_attempt_id: str | None
    superseded_specification_id: str | None
    version_number: int
    schema_version: str
    prompt_template_version: str
    gemini_ruleset_version: str
    provider: str
    provider_model: str | None
    user_instruction: str
    raw_response_path: str | None
    specification_path: str
    content_hash: str
    outcome: RequirementOutcome
    supported_scope: bool
    clarification_required: bool
    generation_ready: bool
    created_at: datetime
    specification: dict[str, Any]
    clarification_questions: list[ClarificationQuestionRead] = Field(default_factory=list)


class ClarificationAnswerCreate(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ClarificationAnswersCreate(BaseModel):
    answers: list[ClarificationAnswerCreate] = Field(min_length=1, max_length=5)


class MeshMetadataRead(BaseModel):
    size_x_mm: float
    size_y_mm: float
    size_z_mm: float
    volume_mm3: float
    triangle_count: int
    connected_components: int
    is_watertight: bool
    is_winding_consistent: bool
    center_of_mass: tuple[float, float, float]


class ValidationSummaryRead(BaseModel):
    blocking_count: int = 0
    advisory_count: int = 0
    dismissed_count: int = 0


class RevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    parent_revision_id: str | None
    design_specification_id: str | None = None
    revision_number: int
    source_type: str
    user_instruction: str | None
    scad_source_path: str
    stl_path: str | None
    compile_log_path: str | None
    ai_output_path: str | None
    status: str
    is_accepted: bool
    review_state: str | None = None
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    metadata: MeshMetadataRead | None = None
    error_message: str | None = None
    validation_summary: ValidationSummaryRead = Field(default_factory=ValidationSummaryRead)


class ValidationFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    revision_id: str | None
    generation_attempt_id: str | None = None
    design_specification_id: str | None = None
    source_validation_result_id: str | None = None
    rule_id: str
    category: str
    severity: str
    is_blocking: bool
    title: str
    explanation: str
    suggested_correction: str
    detected_value: str | None
    unit: str | None
    threshold_value: str | None
    source_line_start: int | None = None
    source_line_end: int | None = None
    orientation_dependent: bool
    affected_geometry_summary: str | None
    metadata_json: str
    finding_state: str
    dismissal_reason: str | None
    dismissed_at: datetime | None
    created_at: datetime


class ValidationFindingDismiss(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class GeometricFindingRead(BaseModel):
    validation_finding_id: str | None = None
    rule_id: str
    requirement_id: str | None
    verification_state: str
    expected_value: float | int | str | None
    detected_value: float | int | str | None
    unit: str | None
    tolerance: float | None
    confidence: float
    severity: str
    is_blocking: bool
    title: str
    explanation: str
    suggested_correction: str
    feature_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeometricAnalysisRead(BaseModel):
    id: str
    revision_id: str
    design_specification_id: str | None
    analysis_version: str
    tolerance_profile_version: str
    mesh_hash: str
    source_hash: str | None
    analysis_ms: float
    created_at: datetime
    findings: list[GeometricFindingRead]
