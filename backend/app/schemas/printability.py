from typing import Literal

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRINTABILITY_PROFILE_VERSION = "printability-fdm-v1"

PrintabilitySeverity = Literal["Pass", "Notice", "Warning", "Critical"]


class BuildVolumeProfile(BaseModel):
    x_mm: float = Field(default=256.0, gt=0)
    y_mm: float = Field(default=256.0, gt=0)
    z_mm: float = Field(default=256.0, gt=0)


class PrintabilityProfile(BaseModel):
    profile_version: str = PRINTABILITY_PROFILE_VERSION
    printer_name: str = Field(default="Generic FDM 256", min_length=1, max_length=120)
    process: str = Field(default="FDM", min_length=1, max_length=40)
    material_behavior: str = Field(default="general PLA/PETG", min_length=1, max_length=80)
    build_volume: BuildVolumeProfile = Field(default_factory=BuildVolumeProfile)
    nozzle_diameter_mm: float = Field(default=0.4, gt=0)
    default_layer_height_mm: float = Field(default=0.2, gt=0)

    @field_validator("printer_name", "process", "material_behavior")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped


class SavedPrintabilityProfileRead(PrintabilityProfile):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class PrintabilityDetectedValue(BaseModel):
    value: float | int | str
    units: str


class PrintabilityHighlight(BaseModel):
    rule_id: str
    severity: PrintabilitySeverity
    type: str
    bounds_min_mm: tuple[float, float, float] | None = None
    bounds_max_mm: tuple[float, float, float] | None = None
    face_indices: list[int] | None = None


class PrintabilityResult(BaseModel):
    severity: PrintabilitySeverity
    rule_id: str
    detected_value: PrintabilityDetectedValue
    explanation: str
    suggested_correction: str
    orientation_dependent: bool
    dismissed: bool = False
    affected_count: int | None = None
    affected_area_mm2: float | None = None
    highlight: PrintabilityHighlight | None = None


class PrintabilityReport(BaseModel):
    profile_version: str = PRINTABILITY_PROFILE_VERSION
    profile: PrintabilityProfile
    results: list[PrintabilityResult]
    highlights: list[PrintabilityHighlight] = Field(default_factory=list)
