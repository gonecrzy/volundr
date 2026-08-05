from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IntegrationProject:
    project_id: str
    title: str
    user_request: str
    frozen_facts: dict[str, Any]
    clarification_answers: tuple[dict[str, Any], ...] = ()
    fit_critical_missing: tuple[str, ...] = ()
    expected_output_count: int = 1
    expected_solid_counts: dict[str, int] = None  # type: ignore[assignment]
    semantic_obligations: tuple[str, ...] = ()
    unsafe_claims: tuple[str, ...] = ("physical certification", "structural safety", "universal fit", "manufacturing suitability")
    revision_of: str | None = None
    requirement_delta: tuple[dict[str, Any], ...] = ()
    protected_facts: tuple[str, ...] = ()
    expected_requirements_outcome: dict[str, Any] | None = None
    clarification_expectations: dict[str, Any] | None = None
    expected_output_ids: tuple[str, ...] = ()
    exact_fixed_points: dict[str, Any] | None = None
    coordinate_frame_obligations: tuple[dict[str, Any], ...] = ()
    expected_verification_checks: tuple[str, ...] = ()
    permissible_proposal_fields: tuple[str, ...] = ()
    forbidden_substitutions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.expected_solid_counts is None:
            object.__setattr__(self, "expected_solid_counts", {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "user_request": self.user_request,
            "frozen_facts": self.frozen_facts,
            "clarification_answers": list(self.clarification_answers),
            "fit_critical_missing": list(self.fit_critical_missing),
            "expected_output_count": self.expected_output_count,
            "expected_solid_counts": dict(self.expected_solid_counts or {}),
            "semantic_obligations": list(self.semantic_obligations),
            "unsafe_claims": list(self.unsafe_claims),
            "revision_of": self.revision_of,
            "requirement_delta": list(self.requirement_delta),
            "protected_facts": list(self.protected_facts),
            "expected_requirements_outcome": dict(self.expected_requirements_outcome or {}),
            "clarification_expectations": dict(self.clarification_expectations or {}),
            "expected_output_ids": list(self.expected_output_ids),
            "exact_fixed_points": self.exact_fixed_points or {},
            "coordinate_frame_obligations": list(self.coordinate_frame_obligations),
            "expected_verification_checks": list(self.expected_verification_checks),
            "permissible_proposal_fields": list(self.permissible_proposal_fields),
            "forbidden_substitutions": list(self.forbidden_substitutions),
        }


def build_integration_corpus() -> tuple[IntegrationProject, ...]:
    return (
        IntegrationProject(
            "project-001", "simple dimensional part", "Create a printable 100 mm by 80 mm plate with a 20 mm centered through-hole.",
            {"width_mm": 100, "depth_mm": 80, "thickness_mm": 10, "hole_diameter_mm": 20},
            semantic_obligations=("one printable output", "centered subtractive through-hole", "preserve explicit dimensions"),
            expected_solid_counts={"body-output": 1},
        ),
        IntegrationProject(
            "project-002", "underspecified wall-mounted cable guide", "Design a wall-mounted cable guide.",
            {"cable_diameter": "missing", "mounting_pattern": "missing", "wall_mounted": True},
            clarification_answers=(
                {"fact": "cable diameter", "answer": "8 mm"},
                {"fact": "mounting pattern", "answer": "two holes, 40 mm center-to-center"},
            ),
            fit_critical_missing=("cable diameter",),
            semantic_obligations=("request missing cable diameter", "request missing mounting pattern", "continue with frozen answers"),
        ),
        IntegrationProject(
            "project-003", "fully specified phone stand", "Create a one-part phone stand for a 78 mm wide, 12 mm thick phone including its case, at 65 degrees, with a centered charging opening.",
            {"phone_width_mm": 78, "phone_thickness_with_case_mm": 12, "backrest_angle_deg": 65, "charging_opening": "centered", "one_part": True},
            semantic_obligations=("mating phone fit", "charging access", "one connected printable solid"),
        ),
        IntegrationProject(
            "project-004", "repeated hole pattern", "Create a plate with five 6 mm holes at 25 mm spacing, fixed rather than configurable.",
            {"hole_count": 5, "hole_spacing_mm": 25, "hole_diameter_mm": 6, "configurable": False},
            semantic_obligations=("fixed count", "fixed spacing", "preserve arrangement and hole axes"),
        ),
        IntegrationProject(
            "project-005", "two-output enclosure", "Create exactly two printable outputs: a base and removable lid enclosure with ventilation and a cable exit.",
            {"outputs": ["base", "lid"], "ventilation": True, "cable_exit": True},
            expected_output_count=2,
            expected_solid_counts={"base": 1, "lid": 1},
            semantic_obligations=("exactly two printable outputs", "removable lid", "ventilation", "cable exit"),
        ),
        IntegrationProject(
            "project-006", "rectangular-to-round transition", "Create a hollow rectangular-to-round adapter, 100 mm long, with 3 mm walls and flanges on both ends.",
            {"length_mm": 100, "wall_thickness_mm": 3, "rectangular_opening": True, "circular_opening": True, "flanges": 2},
            semantic_obligations=("connected loft", "hollow passage", "preserve wall thickness", "two flanges"),
        ),
        IntegrationProject(
            "project-007", "additive boss or handle", "Create a base part with an additive handle that overlaps and unions into the base body.",
            {"additive_feature": "handle", "must_overlap_base": True},
            semantic_obligations=("overlapping additive union", "one connected solid"),
        ),
        IntegrationProject(
            "project-008", "subtractive access opening", "Create a part with a through access opening cut through the defined front face.",
            {"opening": "front through-opening", "cut_through": True, "face": "front"},
            semantic_obligations=("authorized cutter", "Boolean subtraction", "opening traceability"),
        ),
        IntegrationProject(
            "project-009", "irregular fixed feature layout", "Create a plate with four holes at fixed nonuniform positions: (10,10), (40,15), (75,30), and (90,65) mm.",
            {"positions_mm": [[10, 10], [40, 15], [75, 30], [90, 65]], "layout_mode": "fixed_positions", "configurable": False},
            semantic_obligations=("preserve all four positions", "do not parameterize fixed layout"),
        ),
        IntegrationProject(
            "project-010", "revision workflow", "Revise project-009 by changing only the second fixed hole position to (45,15) mm.",
            {"base_project_id": "project-009", "new_second_position_mm": [45, 15]},
            revision_of="project-009",
            requirement_delta=({"path": "positions_mm[1]", "old": [40, 15], "new": [45, 15]},),
            protected_facts=("positions_mm[0]", "positions_mm[2]", "positions_mm[3]", "layout_mode", "configurable=false"),
            semantic_obligations=("bounded revision", "preserve unrelated dimensions", "preserve unrelated features"),
        ),
    )


def corpus_hash(corpus: tuple[IntegrationProject, ...] | None = None) -> str:
    value = [project.as_dict() for project in (corpus or build_integration_corpus())]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = ["IntegrationProject", "build_integration_corpus", "corpus_hash"]
