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


class DesignPlanOutcome(StrEnum):
    PLAN_READY = "plan_ready"
    PLAN_CLARIFICATION_REQUIRED = "plan_clarification_required"
    PLAN_FAILED = "plan_failed"


class DesignPlanReviewState(StrEnum):
    CLARIFICATION_REQUIRED = "clarification_required"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class RevisionPlanOutcome(StrEnum):
    REVISION_READY = "revision_ready"
    CLARIFICATION_REQUIRED = "clarification_required"
    REVISION_CONFLICT = "revision_conflict"
    UNSUPPORTED_REVISION = "unsupported_revision"
    PLANNING_FAILED = "planning_failed"


class RevisionPlanReviewState(StrEnum):
    CLARIFICATION_REQUIRED = "clarification_required"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConfigurationValidationState(StrEnum):
    CONFIGURATION_READY = "configuration_ready"
    CLARIFICATION_REQUIRED = "clarification_required"
    INVALID_CONFIGURATION = "invalid_configuration"
    REQUIRES_DESIGN_REVISION = "requires_design_revision"
    CONFIGURATION_FAILED = "configuration_failed"


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


class RevisionPlanCreate(BaseModel):
    user_instruction: str = Field(min_length=1)
    base_revision_id: str | None = Field(default=None, min_length=1)
    reason: str = "user_request"
    targeted_finding_ids: list[str] = Field(default_factory=list)
    targeted_output_ids: list[str] = Field(default_factory=list)


class ConfigurationChangeCreate(BaseModel):
    base_revision_id: str | None = Field(default=None, min_length=1)
    reason: str = "parameter_change"
    selected_preset_id: str | None = Field(default=None, min_length=1)
    parameter_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    user_overrides: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class ConfigurationPresetCreate(BaseModel):
    design_plan_id: str | None = Field(default=None, min_length=1)
    preset_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    parameter_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


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


class DesignPlanParameter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | int | str | bool | None = None
    unit: str | None = None
    editable: bool = True
    protected: bool = False
    component_id: str | None = None
    source_requirement_id: str | None = None


class DesignPlanDerivedParameter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    unit: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class DesignPlanDependencyEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)
    relationship: str = Field(min_length=1)


class DesignPlanComponent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    features: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)


class DesignPlanFeature(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    component_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: list[str] = Field(default_factory=list)
    protected: bool = False


class DesignPlanPreset(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    parameter_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class DesignPlanPrintableOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    component_ids: list[str] = Field(min_length=1)
    component_id: str | None = None
    module_name: str | None = None
    filename: str | None = None
    quantity: int = Field(default=1, ge=1)
    required: bool = True
    output_type: str = "printable_component"
    orientation: str | None = None
    preferred_orientation: str | None = None
    notes: str | None = None


class DesignPlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    project_id: str | None = None
    design_specification_id: str | None = None
    generation_attempt_id: str | None = None
    design_level: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    units: str = "mm"
    parameters: list[DesignPlanParameter] = Field(default_factory=list)
    derived_parameters: list[DesignPlanDerivedParameter] = Field(default_factory=list)
    dependency_edges: list[DesignPlanDependencyEdge] = Field(default_factory=list)
    components: list[DesignPlanComponent] = Field(default_factory=list)
    features: list[DesignPlanFeature] = Field(default_factory=list)
    presets: list[DesignPlanPreset] = Field(default_factory=list)
    assembly_strategy: dict[str, Any] = Field(default_factory=dict)
    printable_outputs: list[DesignPlanPrintableOutput] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_questions: list[dict[str, Any]] = Field(default_factory=list)
    plan_ready: bool = False
    outcome: DesignPlanOutcome | None = None


class DesignPlanClarificationQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    design_plan_id: str
    related_plan_field: str | None
    question: str
    reason: str | None
    display_order: int
    created_at: datetime


class DesignPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    design_specification_id: str
    generation_attempt_id: str | None
    superseded_design_plan_id: str | None
    version_number: int
    schema_version: str
    prompt_template_version: str
    gemini_ruleset_version: str
    provider: str
    provider_model: str | None
    raw_response_path: str | None
    plan_path: str
    content_hash: str
    outcome: DesignPlanOutcome
    review_state: DesignPlanReviewState
    clarification_required: bool
    plan_ready: bool
    approved_at: datetime | None
    rejected_at: datetime | None
    created_at: datetime
    plan: dict[str, Any]
    clarification_questions: list[DesignPlanClarificationQuestionRead] = Field(default_factory=list)


class ConfigurationParameterRead(BaseModel):
    id: str
    label: str
    value: float | int | str | bool | None = None
    unit: str | None = None
    type: str
    editable: bool
    protected: bool
    component_id: str | None = None
    source_requirement_id: str | None = None
    description: str | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    allowed_values: list[str | int | float | bool] = Field(default_factory=list)
    source_mapped: bool = False
    affected_components: list[str] = Field(default_factory=list)
    affected_outputs: list[str] = Field(default_factory=list)


class OpenScadParameterRead(BaseModel):
    id: str
    name: str
    display_name: str
    type: str
    value: float | int | str | bool
    default_value: float | int | str | bool
    group: str | None = None
    description: str | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    options: list[str] = Field(default_factory=list)
    option_labels: dict[str, str] = Field(default_factory=dict)
    source_line: int | None = None


class ConfigurationPresetRead(BaseModel):
    id: str
    project_id: str
    design_plan_id: str
    preset_id: str
    label: str
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    source: str = "project"
    created_at: datetime | None = None


class ConfigurationChangeRead(BaseModel):
    id: str
    project_id: str
    base_revision_id: str
    generated_revision_id: str | None = None
    design_specification_id: str | None = None
    design_plan_id: str
    schema_version: str
    reason: str
    selected_preset_id: str | None = None
    validation_state: ConfigurationValidationState
    base_source_hash: str | None = None
    content_hash: str
    requested_changes: dict[str, Any] = Field(default_factory=dict)
    preset_values: dict[str, Any] = Field(default_factory=dict)
    user_overrides: dict[str, Any] = Field(default_factory=dict)
    resolved_parameters: dict[str, Any] = Field(default_factory=dict)
    affected_parameters: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    affected_outputs: list[str] = Field(default_factory=list)
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    override_manifest_path: str | None = None
    configuration_path: str | None = None
    created_at: datetime
    approved_at: datetime | None = None


class ConfigurationOverrideManifestRead(BaseModel):
    schema_version: str
    configuration_change_id: str
    base_revision_id: str
    base_source_hash: str | None = None
    selected_preset_id: str | None = None
    preset_values: dict[str, Any] = Field(default_factory=dict)
    user_overrides: dict[str, Any] = Field(default_factory=dict)
    resolved_parameters: dict[str, Any] = Field(default_factory=dict)
    openscad_defines: dict[str, Any] = Field(default_factory=dict)
    affected_parameters: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    affected_outputs: list[str] = Field(default_factory=list)


class RevisionRequestedChange(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    current_value: float | int | str | bool | None = None
    requested_value: float | int | str | bool | None = None
    change_type: str = Field(min_length=1)
    source: str = Field(min_length=1)


class RevisionDependencyChange(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter_id: str = Field(min_length=1)
    affects: list[str] = Field(default_factory=list)


class RevisionProtectedParameter(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter_id: str = Field(min_length=1)
    expected_value: float | int | str | bool | None = None
    unit: str | None = None


class RevisionSuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    expected_value: float | int | str | bool | None = None
    unit: str | None = None
    tolerance: float | None = None


class RevisionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "revision-plan-v1"
    project_id: str | None = None
    base_revision_id: str | None = None
    base_design_specification_id: str | None = None
    base_design_plan_id: str | None = None
    generation_attempt_id: str | None = None
    reason: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    requested_changes: list[RevisionRequestedChange] = Field(default_factory=list)
    targeted_components: list[str] = Field(default_factory=list)
    targeted_features: list[str] = Field(default_factory=list)
    targeted_outputs: list[str] = Field(default_factory=list)
    targeted_findings: list[str] = Field(default_factory=list)
    allowed_parameter_changes: list[str] = Field(default_factory=list)
    required_dependency_changes: list[RevisionDependencyChange] = Field(default_factory=list)
    allowed_component_changes: list[str] = Field(default_factory=list)
    allowed_feature_changes: list[str] = Field(default_factory=list)
    protected_parameters: list[RevisionProtectedParameter] = Field(default_factory=list)
    protected_components: list[str] = Field(default_factory=list)
    protected_features: list[str] = Field(default_factory=list)
    protected_outputs: list[str] = Field(default_factory=list)
    prohibited_changes: list[str] = Field(default_factory=list)
    success_criteria: list[RevisionSuccessCriterion] = Field(default_factory=list)
    requires_design_specification_version: bool = False
    requires_design_plan_version: bool = False
    clarification_questions: list[dict[str, Any]] = Field(default_factory=list)
    outcome: RevisionPlanOutcome


class RevisionPlanClarificationQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_plan_id: str
    requirement_id: str | None
    question: str
    reason: str | None
    display_order: int
    created_at: datetime


class RevisionPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    base_revision_id: str
    base_design_specification_id: str | None
    base_design_plan_id: str | None
    generation_attempt_id: str | None
    superseded_revision_plan_id: str | None
    generated_revision_id: str | None
    revised_design_specification_id: str | None
    revised_design_plan_id: str | None
    version_number: int
    schema_version: str
    prompt_template_version: str
    gemini_ruleset_version: str
    provider: str
    provider_model: str | None
    user_instruction: str
    reason: str
    raw_response_path: str | None
    plan_path: str
    content_hash: str
    base_source_hash: str | None
    base_output_manifest_hash: str | None
    base_design_specification_hash: str | None
    base_design_plan_hash: str | None
    outcome: RevisionPlanOutcome
    review_state: RevisionPlanReviewState
    clarification_required: bool
    revision_ready: bool
    approved_at: datetime | None
    rejected_at: datetime | None
    created_at: datetime
    revision_plan: dict[str, Any]
    clarification_questions: list[RevisionPlanClarificationQuestionRead] = Field(default_factory=list)


class RevisionComplianceResultRead(BaseModel):
    id: str
    project_id: str
    revision_plan_id: str
    generation_attempt_id: str | None
    revision_id: str | None
    base_source_hash: str | None
    revised_source_hash: str | None
    passed: bool
    validation_ms: float
    created_at: datetime
    findings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevisionSuccessResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    revision_plan_id: str
    generation_attempt_id: str | None
    revision_id: str | None
    criterion_type: str
    target_id: str
    verification_state: str
    expected_value: Any = None
    detected_value: Any = None
    unit: str | None
    tolerance: float | None
    confidence: float
    is_blocking: bool
    explanation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComponentRevisionSummaryRead(BaseModel):
    id: str
    project_id: str
    revision_plan_id: str
    revision_id: str | None
    base_revision_id: str | None
    generation_attempt_id: str | None
    base_source_hash: str | None
    revised_source_hash: str | None
    equivalence_profile_version: str
    created_at: datetime
    summary: dict[str, Any] = Field(default_factory=dict)


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
    design_plan_id: str | None = None
    configuration_change_id: str | None = None
    revision_number: int
    source_type: str
    user_instruction: str | None
    scad_source_path: str
    stl_path: str | None
    compile_log_path: str | None
    ai_output_path: str | None
    output_manifest_path: str | None = None
    expected_output_count: int | None = None
    required_output_count: int | None = None
    successful_output_count: int | None = None
    blocked_output_count: int | None = None
    failed_output_count: int | None = None
    status: str
    is_accepted: bool
    review_state: str | None = None
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    metadata: MeshMetadataRead | None = None
    error_message: str | None = None
    validation_summary: ValidationSummaryRead = Field(default_factory=ValidationSummaryRead)


class RevisionOutputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    revision_id: str
    design_plan_id: str | None = None
    design_specification_id: str | None = None
    output_id: str
    component_id: str | None = None
    component_ids: list[str] = Field(default_factory=list)
    output_state: str
    output_type: str
    label: str
    filename: str
    quantity: int
    required: bool
    module_name: str
    source_hash: str | None = None
    stl_path: str | None = None
    stl_hash: str | None = None
    compile_log_path: str | None = None
    compile_ms: float | None = None
    compile_error: str | None = None
    compile_command: list[str] = Field(default_factory=list)
    metadata: MeshMetadataRead | None = None
    validation_summary: ValidationSummaryRead = Field(default_factory=ValidationSummaryRead)
    preferred_orientation: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ValidationFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    revision_id: str | None
    revision_output_id: str | None = None
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
    revision_output_id: str | None = None
    design_specification_id: str | None
    analysis_version: str
    tolerance_profile_version: str
    mesh_hash: str
    source_hash: str | None
    analysis_ms: float
    created_at: datetime
    findings: list[GeometricFindingRead]
