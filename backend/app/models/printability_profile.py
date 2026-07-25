from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SavedPrintabilityProfile(Base):
    __tablename__ = "printability_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    printer_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    process: Mapped[str] = mapped_column(String(40), nullable=False)
    material_behavior: Mapped[str] = mapped_column(String(80), nullable=False)
    build_volume_x_mm: Mapped[float] = mapped_column(Float, nullable=False)
    build_volume_y_mm: Mapped[float] = mapped_column(Float, nullable=False)
    build_volume_z_mm: Mapped[float] = mapped_column(Float, nullable=False)
    nozzle_diameter_mm: Mapped[float] = mapped_column(Float, nullable=False)
    default_layer_height_mm: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
