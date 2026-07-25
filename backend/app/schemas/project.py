from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    revision_id: str
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
    orientation_dependent: bool
    affected_geometry_summary: str | None
    metadata_json: str
    finding_state: str
    dismissal_reason: str | None
    dismissed_at: datetime | None
    created_at: datetime


class ValidationFindingDismiss(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
