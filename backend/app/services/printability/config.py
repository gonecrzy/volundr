from dataclasses import dataclass

from app.schemas.printability import PRINTABILITY_PROFILE_VERSION, PrintabilityProfile


@dataclass(frozen=True)
class ThicknessThresholds:
    critical_below_mm: float
    warning_below_mm: float
    notice_below_mm: float
    functional_recommendation_mm: float


@dataclass(frozen=True)
class OverhangThresholds:
    critical_below_degrees: float = 30.0
    warning_below_degrees: float = 45.0
    notice_below_degrees: float = 60.0


@dataclass(frozen=True)
class BridgeThresholds:
    pass_max_mm: float = 5.0
    notice_max_mm: float = 15.0
    warning_max_mm: float = 30.0
    strong_warning_max_mm: float = 50.0


@dataclass(frozen=True)
class PrintabilityConfig:
    version: str = PRINTABILITY_PROFILE_VERSION
    build_plate_tolerance_mm: float = 0.05
    contact_area_ratio_notice_below: float = 0.03
    contact_area_ratio_warning_below: float = 0.01
    horizontal_face_angle_degrees: float = 5.0
    overhang_min_area_mm2: float = 1.0
    bridge: BridgeThresholds = BridgeThresholds()
    overhang: OverhangThresholds = OverhangThresholds()

    def thickness_for(self, profile: PrintabilityProfile) -> ThicknessThresholds:
        nozzle = profile.nozzle_diameter_mm
        return ThicknessThresholds(
            critical_below_mm=1.0 * nozzle,
            warning_below_mm=2.0 * nozzle,
            notice_below_mm=3.0 * nozzle,
            functional_recommendation_mm=4.0 * nozzle,
        )


PRINTABILITY_CONFIG = PrintabilityConfig()
