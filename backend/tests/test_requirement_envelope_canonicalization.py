from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import RequirementExtractionRequest
from app.services.executable_cadquery.contract import build_executable_cadquery_product_contract
from app.schemas.project import DesignSpecificationPayload
from app.services.projects.requirement_ledger import build_requirement_ledger
from app.services.projects.service import ProjectService
from app.services.requirements.trace import (
    canonicalize_dimension_envelopes,
    validate_design_specification_trace,
)


def _dimension(
    requirement_id: str,
    value: float,
    *,
    raw_evidence: str = "Overall envelope approximately 40 x 30 x 20 mm.",
    target: str | None = "primary_output",
    operator: str = "approximately",
    source: str = "user",
    authority: str = "explicit",
    tolerance: float = 0.5,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": requirement_id,
        "requirement_id": requirement_id,
        "label": requirement_id.replace("_", " "),
        "value": value,
        "unit": "mm",
        "source": source,
        "importance": "important",
        "authority": authority,
        "protected": authority == "explicit",
        "explicit": authority == "explicit",
        "type": "exact_dimension",
        "kind": "dimension",
        "operator": operator,
        "target": target,
        "raw_evidence": raw_evidence,
        "tolerance": tolerance,
        **extra,
    }


def test_groups_width_length_height_into_one_canonical_bounds_requirement() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("overall_envelope_width", 40.0),
            _dimension("overall_envelope_length", 30.0),
            _dimension("overall_envelope_height", 20.0),
        ]
    )

    assert len(result) == 1
    envelope = result[0]
    assert envelope["requirement_id"] == "overall_envelope"
    assert envelope["value"] == {"width": 40.0, "depth": 30.0, "height": 20.0}
    assert envelope["operator"] == "approximately"
    assert envelope["tolerance"] == 0.5
    assert envelope["provenance"]["source_requirement_ids"] == [
        "overall_envelope_height",
        "overall_envelope_length",
        "overall_envelope_width",
    ]


def test_normalizes_xyz_to_width_depth_height() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("envelope_x", 11.0),
            _dimension("envelope_y", 12.0),
            _dimension("envelope_z", 13.0),
        ]
    )

    assert result[0]["value"] == {"width": 11.0, "depth": 12.0, "height": 13.0}


def test_preserves_authority_and_protected_fact_semantics() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("envelope_width", 40.0),
            _dimension("envelope_length", 30.0),
            _dimension("envelope_height", 20.0),
        ]
    )

    envelope = result[0]
    assert envelope["source"] == "user"
    assert envelope["authority"] == "explicit"
    assert envelope["explicit"] is True
    assert envelope["protected"] is True
    assert envelope["raw_evidence"] == "Overall envelope approximately 40 x 30 x 20 mm."


def test_ledger_and_contract_route_canonical_bounds_without_three_protected_facts() -> None:
    specification = {
        "schema_version": "1.0",
        "object_type": "synthetic_part",
        "purpose": "A generic part.",
        "critical_dimensions": [
            _dimension("envelope_width", 40.0),
            _dimension("envelope_length", 30.0),
            _dimension("envelope_height", 20.0),
        ],
    }
    ledger = build_requirement_ledger(
        [
            {**item, "value": item["value"]}
            for item in specification["critical_dimensions"]
        ],
        project_id="synthetic-project",
    )
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic-project",
        workflow_id="synthetic-workflow",
        revision_id="synthetic-revision",
        specification=specification,
        active_requirements=ledger["requirements"],
    )

    assert len(ledger["requirements"]) == 1
    assert len(contract["protected_facts"]) == 1
    requirement = contract["requirements"][0]
    assert requirement["expected"] == {"width": 40.0, "depth": 30.0, "height": 20.0}
    assert requirement["verification_policy"] == "final_mesh_bounds"


def test_design_specification_normalization_preserves_one_canonical_dimension() -> None:
    payload = {
        "object_type": "synthetic_part",
        "purpose": "A generic part.",
        "critical_dimensions": [
            _dimension("envelope_width", 40.0),
            _dimension("envelope_length", 30.0),
            _dimension("envelope_height", 20.0),
        ],
    }

    normalized = ProjectService._normalize_design_specification_payload(
        ProjectService.__new__(ProjectService), payload
    )

    assert len(normalized["critical_dimensions"]) == 1
    assert normalized["critical_dimensions"][0]["value"] == {
        "width": 40.0,
        "depth": 30.0,
        "height": 20.0,
    }
    DesignSpecificationPayload.model_validate(normalized)


def test_flexible_model_envelope_remains_unprotected() -> None:
    dimensions = [
        _dimension(
            "envelope_width",
            40.0,
            source="ai_assumption",
            authority="flexible",
        ),
        _dimension(
            "envelope_length",
            30.0,
            source="ai_assumption",
            authority="flexible",
        ),
        _dimension(
            "envelope_height",
            20.0,
            source="ai_assumption",
            authority="flexible",
        ),
    ]
    specification = {
        "schema_version": "1.0",
        "object_type": "synthetic_part",
        "purpose": "A generic part.",
        "critical_dimensions": dimensions,
    }
    ledger = build_requirement_ledger(dimensions, project_id="synthetic-project")
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic-project",
        workflow_id="synthetic-workflow",
        revision_id="synthetic-revision",
        specification=specification,
        active_requirements=ledger["requirements"],
    )

    requirement = contract["requirements"][0]
    assert requirement["authority"] == "flexible"
    assert requirement["origin"] == "model_design_choice"
    assert contract["protected_facts"] == []


def test_different_source_statements_do_not_combine() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("body_width", 40.0, raw_evidence="Body width is 40 mm."),
            _dimension("body_length", 30.0, raw_evidence="Body length is 30 mm."),
            _dimension("body_height", 20.0, raw_evidence="Body height is 20 mm."),
        ]
    )

    assert len(result) == 3


def test_different_output_scopes_do_not_combine() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("envelope_width", 40.0, target="base"),
            _dimension("envelope_length", 30.0, target="lid"),
            _dimension("envelope_height", 20.0, target="base"),
        ]
    )

    assert len(result) == 3


def test_unrelated_scalar_dimensions_do_not_combine() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("wall_width", 4.0, raw_evidence="Wall width is 4 mm."),
            _dimension("body_depth", 30.0, raw_evidence="Body depth is 30 mm."),
            _dimension("body_height", 20.0, raw_evidence="Body height is 20 mm."),
        ]
    )

    assert len(result) == 3


def test_mixed_exact_and_approximate_semantics_fail_closed() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("envelope_width", 40.0),
            _dimension("envelope_length", 30.0),
            _dimension("envelope_height", 20.0, operator="exact"),
        ]
    )

    assert len(result) == 3


def test_flexible_dimensions_do_not_combine_with_required_dimensions() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("envelope_width", 40.0),
            _dimension("envelope_length", 30.0),
            _dimension("envelope_height", 20.0, authority="flexible", source="ai_assumption"),
        ]
    )

    assert len(result) == 3


def test_explicit_source_fact_identity_and_envelope_evidence_group_live_shaped_axes() -> None:
    source_fact = "fact_tray_envelope"
    source_evidence = "Keep the finished tray within approximately 80 mm wide by 60 mm deep by 25 mm high."
    result = canonicalize_dimension_envelopes(
        [
            _dimension("tray_width", 80.0, raw_evidence="approximately 80 mm wide", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
            _dimension("tray_depth", 60.0, raw_evidence="60 mm deep", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
            _dimension("tray_height", 25.0, raw_evidence="25 mm high", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
        ]
    )

    assert len(result) == 1
    assert result[0]["value"] == {"width": 80.0, "depth": 60.0, "height": 25.0}
    assert result[0]["provenance"]["source_fact_id"] == source_fact
    assert result[0]["provenance"]["source_fact_evidence"] == source_evidence


def test_same_message_does_not_group_unrelated_source_facts() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("plate_width", 100.0, raw_evidence="Make the plate 100 mm wide.", source_fact_id="plate_width_fact", source_fact_evidence="Make the plate 100 mm wide."),
            _dimension("wall_thickness", 4.0, raw_evidence="Use a 4 mm wall.", source_fact_id="wall_thickness_fact", source_fact_evidence="Use a 4 mm wall."),
            _dimension("hole_depth", 12.0, raw_evidence="Use a 12 mm hole 30 mm from the edge.", source_fact_id="hole_fact", source_fact_evidence="Use a 12 mm hole 30 mm from the edge."),
        ]
    )

    assert len(result) == 3


def test_two_explicit_envelope_source_facts_remain_separate() -> None:
    result = canonicalize_dimension_envelopes(
        [
            _dimension("base_width", 80.0, raw_evidence="Base envelope 80 x 60 x 20 mm.", source_fact_id="base_envelope", source_fact_evidence="Base envelope 80 x 60 x 20 mm."),
            _dimension("base_depth", 60.0, raw_evidence="Base envelope 80 x 60 x 20 mm.", source_fact_id="base_envelope", source_fact_evidence="Base envelope 80 x 60 x 20 mm."),
            _dimension("base_height", 20.0, raw_evidence="Base envelope 80 x 60 x 20 mm.", source_fact_id="base_envelope", source_fact_evidence="Base envelope 80 x 60 x 20 mm."),
            _dimension("lid_width", 82.0, raw_evidence="Lid envelope 82 x 62 x 8 mm.", source_fact_id="lid_envelope", source_fact_evidence="Lid envelope 82 x 62 x 8 mm."),
            _dimension("lid_depth", 62.0, raw_evidence="Lid envelope 82 x 62 x 8 mm.", source_fact_id="lid_envelope", source_fact_evidence="Lid envelope 82 x 62 x 8 mm."),
            _dimension("lid_height", 8.0, raw_evidence="Lid envelope 82 x 62 x 8 mm.", source_fact_id="lid_envelope", source_fact_evidence="Lid envelope 82 x 62 x 8 mm."),
        ]
    )

    assert len(result) == 2
    assert {item["provenance"]["source_fact_id"] for item in result} == {"base_envelope", "lid_envelope"}


def test_source_fact_identity_does_not_cross_output_scope() -> None:
    source_fact = "shared_message_but_distinct_outputs"
    source_evidence = "Keep each printed output within its own stated envelope."
    result = canonicalize_dimension_envelopes(
        [
            _dimension("base_width", 80.0, target="base", source_fact_id=source_fact, source_fact_evidence=source_evidence),
            _dimension("base_depth", 60.0, target="base", source_fact_id=source_fact, source_fact_evidence=source_evidence),
            _dimension("lid_height", 8.0, target="lid", source_fact_id=source_fact, source_fact_evidence=source_evidence),
        ]
    )

    assert len(result) == 3


def test_source_fact_identity_survives_design_specification_ledger_and_contract() -> None:
    source_fact = "tray_envelope_fact"
    source_evidence = "Keep the tray within approximately 80 x 60 x 25 mm."
    dimensions = [
            _dimension("tray_width", 80.0, raw_evidence="80 mm wide", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
            _dimension("tray_depth", 60.0, raw_evidence="60 mm deep", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
            _dimension("tray_height", 25.0, raw_evidence="25 mm high", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
    ]
    payload = ProjectService._normalize_design_specification_payload(
        ProjectService.__new__(ProjectService),
        {"object_type": "synthetic_tray", "purpose": "A generic tray.", "critical_dimensions": dimensions},
    )
    ledger = build_requirement_ledger(payload["critical_dimensions"], project_id="synthetic-project")
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic-project",
        workflow_id="synthetic-workflow",
        revision_id="synthetic-revision",
        specification=payload,
        active_requirements=ledger["requirements"],
    )

    assert payload["critical_dimensions"][0]["provenance"]["source_fact_id"] == source_fact
    assert ledger["requirements"][0]["provenance"]["source_fact_id"] == source_fact
    assert contract["requirements"][0]["provenance"]["source_fact_id"] == source_fact
    assert contract["requirements"][0]["verification_policy"] == "final_mesh_bounds"


def test_source_fact_identity_does_not_make_model_choice_required() -> None:
    source_fact = "model_selected_envelope"
    source_evidence = "Choose a reasonable compact envelope for the concept."
    dimensions = [
        _dimension("concept_width", 40.0, source="ai_assumption", authority="flexible", raw_evidence="40 mm wide", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
        _dimension("concept_depth", 30.0, source="ai_assumption", authority="flexible", raw_evidence="30 mm deep", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
        _dimension("concept_height", 20.0, source="ai_assumption", authority="flexible", raw_evidence="20 mm high", source_fact_id=source_fact, source_fact_type="overall_envelope", source_fact_evidence=source_evidence),
    ]

    result = canonicalize_dimension_envelopes(dimensions)

    assert len(result) == 1
    assert result[0]["source"] == "ai_assumption"
    assert result[0]["protected"] is False


def test_source_fact_identity_survives_design_specification_trace() -> None:
    source_fact = "tray_envelope_fact"
    source_evidence = "Keep the finished tray within approximately 80 x 60 x 25 mm."
    payload = {
        "critical_dimensions": [],
        "explicit_requirements": [],
        "functional_requirements": [],
        "clarification_required": False,
        "generation_ready": True,
    }
    inventory = [
        {
            **_dimension("overall_envelope", {"width": 80, "depth": 60, "height": 25}),
            "source_fact_id": source_fact,
            "source_fact_type": "overall_envelope",
            "source_fact_evidence": source_evidence,
            "authority_rank": 1,
        }
    ]

    normalized, trace = validate_design_specification_trace(payload, inventory)

    assert trace["status"] in {"passed", "repaired"}
    assert normalized["critical_dimensions"][0]["source_fact_id"] == source_fact
    assert normalized["critical_dimensions"][0]["source_fact_evidence"] == source_evidence


def test_requirement_prompt_defines_generic_source_fact_provenance() -> None:
    provider = GeminiCliProvider.__new__(GeminiCliProvider)
    prompt = provider._build_requirement_prompt(
        RequirementExtractionRequest(
            project_name="synthetic-project",
            original_intent="Design a simple tray.",
            user_instruction="Keep it within 80 x 60 x 25 mm.",
        )
    )

    assert "source_fact_id" in prompt
    assert "source_fact_type" in prompt
    assert "source_fact_evidence" in prompt
    assert "Do not reuse a source_fact_id for unrelated constraints" in prompt
    assert "do not require an envelope when the user did not state one" in prompt
