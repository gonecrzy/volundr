from __future__ import annotations

import pytest

from app.services.executable_cadquery.contract import (
    build_executable_cadquery_product_contract,
)


def _product_state() -> tuple[dict[str, object], list[dict[str, object]]]:
    specification = {
        "schema_version": "1.0",
        "object_type": "wall_mount",
        "purpose": "Design a useful wall-mounted tool holder.",
        "units": "mm",
        "critical_dimensions": [
            {
                "id": "overall_envelope",
                "label": "Overall envelope",
                "value": {"x": 24.0, "y": 18.0, "z": 12.0},
                "unit": "mm",
                "tolerance": 0.5,
                "source": "user",
                "importance": "important",
                "protected": True,
            }
        ],
        "functional_requirements": [
            {
                "id": "tool_retention",
                "description": "Keep the tool secure during ordinary use.",
                "source": "user",
                "importance": "critical",
                "protected": True,
                "type": "qualitative_behavior",
                "classification": "review_required",
            }
        ],
    }
    ledger = [
        {
            "requirement_id": "overall_envelope",
            "source": "initial_user",
            "type": "exact_dimension",
            "value": {"x": 24.0, "y": 18.0, "z": 12.0},
            "unit": "mm",
            "tolerance": 0.5,
            "explicit": True,
            "kind": "dimension",
            "operator": "exact",
        },
        {
            "requirement_id": "tool_retention",
            "source": "initial_user",
            "type": "qualitative_behavior",
            "value": "Keep the tool secure during ordinary use.",
            "explicit": True,
            "kind": "qualitative_behavior",
            "operator": "qualitative",
            "classification": "review_required",
        },
    ]
    return specification, ledger


def test_product_contract_preserves_explicit_and_qualitative_requirements() -> None:
    specification, ledger = _product_state()

    contract = build_executable_cadquery_product_contract(
        project_id="project-123",
        workflow_id="workflow-123",
        revision_id="revision-123",
        specification=specification,
        active_requirements=ledger,
    )

    assert contract["outputs"] == [
        {
            "output_id": "wall_mount",
            "required": True,
            "output_type": "printable_component",
            "expected_solid_count": 1,
        }
    ]
    dimensions = next(item for item in contract["requirements"] if item["requirement_id"] == "overall_envelope")
    assert dimensions["expected"] == {"width": 24.0, "depth": 18.0, "height": 12.0}
    assert dimensions["verification_policy"] == "final_mesh_bounds"
    retention = next(item for item in contract["requirements"] if item["requirement_id"] == "tool_retention")
    assert retention["classification"] == "review_required"
    assert retention["expected"]["value"] == "Keep the tool secure during ordinary use."


def test_product_contract_does_not_silently_create_an_empty_requirement_set() -> None:
    specification = {
        "schema_version": "1.0",
        "object_type": "generic_part",
        "purpose": "Design a useful part.",
    }

    with pytest.raises(ValueError, match="authoritative requirements"):
        build_executable_cadquery_product_contract(
            project_id="project-123",
            workflow_id="workflow-123",
            revision_id="revision-123",
            specification=specification,
            active_requirements=[],
        )


def test_product_contract_has_no_benchmark_specific_semantics() -> None:
    specification, ledger = _product_state()

    contract = build_executable_cadquery_product_contract(
        project_id="project-123",
        workflow_id="workflow-123",
        revision_id="revision-123",
        specification=specification,
        active_requirements=ledger,
    )

    serialized = repr(contract)
    assert "mounting-bracket" not in serialized
    assert "Printables" not in serialized
