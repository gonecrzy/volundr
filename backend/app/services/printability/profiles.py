from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.printability_profile import SavedPrintabilityProfile
from app.schemas.printability import (
    BuildVolumeProfile,
    PrintabilityProfile,
    SavedPrintabilityProfileRead,
)


class PrintabilityProfileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_profiles(self) -> list[SavedPrintabilityProfileRead]:
        profiles = self.db.scalars(
            select(SavedPrintabilityProfile).order_by(SavedPrintabilityProfile.printer_name)
        )
        return [self._to_read_model(profile) for profile in profiles]

    def create_profile(self, payload: PrintabilityProfile) -> SavedPrintabilityProfileRead:
        profile = SavedPrintabilityProfile()
        self._apply_payload(profile, payload)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return self._to_read_model(profile)

    def update_profile(
        self,
        profile_id: str,
        payload: PrintabilityProfile,
    ) -> SavedPrintabilityProfileRead | None:
        profile = self.db.get(SavedPrintabilityProfile, profile_id)
        if profile is None:
            return None
        self._apply_payload(profile, payload)
        self.db.commit()
        self.db.refresh(profile)
        return self._to_read_model(profile)

    def delete_profile(self, profile_id: str) -> bool:
        profile = self.db.get(SavedPrintabilityProfile, profile_id)
        if profile is None:
            return False
        self.db.delete(profile)
        self.db.commit()
        return True

    def _apply_payload(
        self,
        profile: SavedPrintabilityProfile,
        payload: PrintabilityProfile,
    ) -> None:
        profile.profile_version = payload.profile_version
        profile.printer_name = payload.printer_name
        profile.process = payload.process
        profile.material_behavior = payload.material_behavior
        profile.build_volume_x_mm = payload.build_volume.x_mm
        profile.build_volume_y_mm = payload.build_volume.y_mm
        profile.build_volume_z_mm = payload.build_volume.z_mm
        profile.nozzle_diameter_mm = payload.nozzle_diameter_mm
        profile.default_layer_height_mm = payload.default_layer_height_mm

    def _to_read_model(
        self,
        profile: SavedPrintabilityProfile,
    ) -> SavedPrintabilityProfileRead:
        return SavedPrintabilityProfileRead(
            id=profile.id,
            profile_version=profile.profile_version,
            printer_name=profile.printer_name,
            process=profile.process,
            material_behavior=profile.material_behavior,
            build_volume=BuildVolumeProfile(
                x_mm=profile.build_volume_x_mm,
                y_mm=profile.build_volume_y_mm,
                z_mm=profile.build_volume_z_mm,
            ),
            nozzle_diameter_mm=profile.nozzle_diameter_mm,
            default_layer_height_mm=profile.default_layer_height_mm,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
