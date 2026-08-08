from __future__ import annotations

import json

import pytest

from app.schemas.project import DesignSpecificationPayload
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    build_executable_cadquery_product_contract,
    parse_executable_cadquery_response,
)
from app.services.executable_cadquery.fixtures import valid_mounting_bracket_source
from app.services.projects.service import ProjectService


def _outputs(*, source: str = "user", protected: bool = True) -> list[dict[str, object]]:
    return [
        {
            "id": "box_body",
            "label": "Box body",
            "component_ids": ["box_body"],
            "required": True,
            "expected_solid_count": 1,
            "output_type": "printable_component",
            "source": source,
            "authority": "explicit" if protected else "flexible",
            "protected": protected,
            "aliases": ["body"],
            "raw_evidence": "separately printable box body",
        },
        {
            "id": "box_lid",
            "label": "Box lid",
            "component_ids": ["box_lid"],
            "required": True,
            "expected_solid_count": 1,
            "output_type": "printable_component",
            "source": source,
            "authority": "explicit" if protected else "flexible",
            "protected": protected,
            "aliases": ["lid"],
            "raw_evidence": "separately printable lid",
        },
    ]


def _ledger(*requirements: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "requirement_id": item["requirement_id"],
            "source": "initial_user",
            "explicit": True,
            "kind": item.get("kind", "dimension"),
            "operator": item.get("operator", "approximately"),
            "value": item.get("value"),
            "target": item.get("target"),
            "subject": item.get("subject"),
            "object_type": item.get("object_type"),
            "raw_evidence": item.get("raw_evidence"),
            "tolerance": item.get("tolerance", 0.5),
            "classification": item.get("classification", "machine_required"),
        }
        for item in requirements
    ]


def _contract_specification() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "object_type": "storage_box",
        "purpose": "A two-piece storage box.",
        "units": "mm",
        "outputs": _outputs(),
        "relationships": [
            {
                "source_output_id": "box_lid",
                "target_output_id": "box_body",
                "relationship": "mates_with",
                "source": "user",
                "authority": "explicit",
                "protected": True,
            }
        ],
    }


def test_design_specification_has_explicit_outputs_and_relationships() -> None:
    payload = {
        **_contract_specification(),
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [],
        "print_requirements": {},
        "assumptions": [],
        "conflicts": [],
        "missing_requirements": [],
        "clarification_required": False,
        "clarification_questions": [],
        "generation_ready": True,
        "outcome": "generation_ready",
    }

    specification = DesignSpecificationPayload.model_validate(payload)
    persisted = specification.model_dump(mode="json")

    assert [item["id"] for item in persisted["outputs"]] == ["box_body", "box_lid"]
    assert persisted["outputs"][0]["source"] == "user"
    assert persisted["outputs"][0]["protected"] is True
    assert persisted["relationships"][0]["source_output_id"] == "box_lid"


def test_design_specification_normalization_preserves_outputs_and_relationships() -> None:
    normalized = ProjectService._normalize_design_specification_payload(
        ProjectService.__new__(ProjectService),
        _contract_specification(),
    )

    assert [item["id"] for item in normalized["outputs"]] == ["box_body", "box_lid"]
    assert normalized["relationships"][0]["target_output_id"] == "box_body"


def test_requirement_payload_accepts_and_reloads_output_declarations_from_provider_shape() -> None:
    provider_payload = {
        "schema_version": "1.0",
        "object_type": "storage_box",
        "purpose": "A two-piece storage box.",
        "printable_outputs": [
            {"output_id": "body", "label": "Body", "source": "initial_user"},
            {"output_id": "lid", "label": "Lid", "source": "initial_user"},
        ],
        "relationships": [
            {"from_output_id": "lid", "to_output_id": "body", "type": "mates_with"}
        ],
    }

    normalized = ProjectService._normalize_design_specification_payload(
        ProjectService.__new__(ProjectService), provider_payload
    )
    payload = DesignSpecificationPayload.model_validate(normalized)
    reloaded = DesignSpecificationPayload.model_validate(payload.model_dump(mode="json"))

    assert [item.id for item in reloaded.outputs] == ["body", "lid"]
    assert reloaded.outputs[0].source.value == "user"
    assert reloaded.outputs[0].protected is True
    assert reloaded.relationships[0].source_output_id == "lid"


def test_explicit_target_scopes_even_when_subject_is_descriptive_prose() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=_contract_specification(),
        active_requirements=_ledger(
            {
                "requirement_id": "body_envelope",
                "value": {"width": 80, "depth": 60, "height": 30},
                "target": "box_body",
                "subject": "finished storage box body",
            }
        ),
    )

    assert contract["requirements"][0]["scope"] == "box_body"
    assert contract["requirements"][0]["scope_kind"] == "output_local"


def test_matching_subject_scopes_a_requirement_when_target_is_absent() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=_contract_specification(),
        active_requirements=_ledger(
            {
                "requirement_id": "body_envelope",
                "value": {"width": 80, "depth": 60, "height": 30},
                "subject": "body",
            }
        ),
    )

    assert contract["requirements"][0]["scope"] == "box_body"


def test_product_contract_materializes_all_authoritative_outputs_and_scopes_requirements() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic-project",
        workflow_id="synthetic-workflow",
        revision_id="synthetic-revision",
        specification=_contract_specification(),
        active_requirements=_ledger(
            {
                "requirement_id": "body_envelope",
                "value": {"width": 80, "depth": 60, "height": 30},
                "target": "box_body",
                "subject": "box_body",
                "object_type": "box_body",
                "raw_evidence": "The separately printable box body is 80 x 60 x 30 mm.",
            },
            {
                "requirement_id": "lid_envelope",
                "value": {"width": 82, "depth": 62, "height": 8},
                "target": "box_lid",
                "subject": "box_lid",
                "object_type": "box_lid",
                "raw_evidence": "The separately printable lid is 82 x 62 x 8 mm.",
            },
            {
                "requirement_id": "assembly_usability",
                "kind": "relationship",
                "operator": "qualitative",
                "value": "The lid mates with the body.",
                "target": "assembly",
                "classification": "review_required",
            },
        ),
    )

    assert [item["output_id"] for item in contract["outputs"]] == ["box_body", "box_lid"]
    assert contract["relationships"][0]["source_output_id"] == "box_lid"
    body = next(item for item in contract["requirements"] if item["requirement_id"] == "body_envelope")
    lid = next(item for item in contract["requirements"] if item["requirement_id"] == "lid_envelope")
    assembly = next(item for item in contract["requirements"] if item["requirement_id"] == "assembly_usability")
    assert body["scope"] == "box_body"
    assert lid["scope"] == "box_lid"
    assert assembly["scope_kind"] == "assembly"
    assert body["verification_policy"] == "final_mesh_bounds"


def test_explicit_outputs_disable_object_type_fallback_and_legacy_fallback_remains() -> None:
    explicit = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=_contract_specification(),
        active_requirements=_ledger({"requirement_id": "body", "value": True, "kind": "feature", "operator": "present"}),
    )
    legacy = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification={"schema_version": "1.0", "object_type": "single_part", "purpose": "One part."},
        active_requirements=_ledger({"requirement_id": "feature", "value": True, "kind": "feature", "operator": "present"}),
    )

    assert [item["output_id"] for item in explicit["outputs"]] == ["box_body", "box_lid"]
    assert [item["output_id"] for item in legacy["outputs"]] == ["single_part"]


def test_output_count_requirement_routes_to_authoritative_output_identity() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=_contract_specification(),
        active_requirements=_ledger(
            {
                "requirement_id": "printed_output_count",
                "kind": "count",
                "operator": "exact",
                "value": 2,
                "subject": "printed_outputs",
                "object_type": "printable_outputs",
            }
        ),
    )

    requirement = contract["requirements"][0]
    assert requirement["expected"] == {"count": 2, "independent": True}
    assert requirement["verification_policy"] == "required_output_identity"
    assert requirement["scope_kind"] == "assembly"


def test_ambiguous_requirement_scope_is_not_redirected_to_first_output() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=_contract_specification(),
        active_requirements=_ledger(
            {
                "requirement_id": "ambiguous_envelope",
                "value": {"width": 80, "depth": 60, "height": 30},
                "target": "not_declared",
                "subject": "not_declared",
            }
        ),
    )

    assert contract["requirements"][0]["scope"] == "not_declared"


def test_model_proposed_outputs_remain_flexible() -> None:
    specification = {**_contract_specification(), "outputs": _outputs(source="ai_assumption", protected=False)}
    contract = build_executable_cadquery_product_contract(
        project_id="project",
        workflow_id="workflow",
        revision_id="revision",
        specification=specification,
        active_requirements=_ledger({"requirement_id": "concept", "value": True, "kind": "feature", "operator": "present"}),
    )

    assert all(item["authority"] == "flexible" for item in contract["outputs"])
    assert all(item["protected"] is False for item in contract["outputs"])


def test_executable_cad_prompt_contains_every_contract_output_id() -> None:
    provider = GeminiCliProvider.__new__(GeminiCliProvider)
    contract = {
        "outputs": [
            {"output_id": "box_body", "required": True, "expected_solid_count": 1, "output_type": "printable_component"},
            {"output_id": "box_lid", "required": True, "expected_solid_count": 1, "output_type": "printable_component"},
        ],
    }
    prompt = provider.build_executable_cadquery_prompt(
        ModelGenerationRequest(
            project_name="synthetic",
            original_intent="two-piece box",
            user_instruction="two-piece box",
            executable_design_contract=contract,
        )
    )

    assert '"box_body"' in prompt
    assert '"box_lid"' in prompt


def test_source_contract_rejects_missing_required_output() -> None:
    contract = {
        "schema_version": "executable-cadquery-design-contract-v1",
        "project_id": "project",
        "workflow_id": "workflow",
        "revision_id": "revision",
        "units": "mm",
        "outputs": [
            {"output_id": "box_body", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
            {"output_id": "box_lid", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
        ],
        "requirements": [],
        "relationships": [],
        "protected_facts": [],
    }

    with pytest.raises(ExecutableCadQueryContractError, match="canonical output identity"):
        parse_executable_cadquery_response(
            valid_mounting_bracket_source(),
            contract,
        )
