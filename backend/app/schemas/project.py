from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    original_intent: str = Field(min_length=1)


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


class ManualRevisionCreate(BaseModel):
    scad_source: str = Field(min_length=1)
    user_instruction: str | None = None


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
    created_at: datetime
    metadata: MeshMetadataRead | None = None
    error_message: str | None = None
