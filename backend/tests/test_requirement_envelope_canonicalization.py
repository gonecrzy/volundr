from app.services.executable_cadquery.contract import build_executable_cadquery_product_contract
from app.schemas.project import DesignSpecificationPayload
from app.services.projects.requirement_ledger import build_requirement_ledger
from app.services.projects.service import ProjectService
from app.services.requirements.trace import canonicalize_dimension_envelopes


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
