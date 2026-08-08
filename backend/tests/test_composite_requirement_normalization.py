from __future__ import annotations

from copy import deepcopy

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.services.executable_cadquery.contract import (
    build_executable_cadquery_product_contract,
)
from app.services.projects.requirement_ledger import (
    RequirementLedgerStore,
    active_requirements,
    build_requirement_ledger,
)
from app.services.projects.service import ProjectService
from app.services.requirements.trace import (
    canonicalize_dimension_envelopes,
    normalize_composite_requirement_parts,
)
from app.models.project import Project
from app.schemas.project import DesignSpecificationPayload
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import RequirementExtractionRequest


def _part(
    part_id: str,
    role: str,
    *,
    description: str,
    kind: str,
    type: str,
    operator: str,
    delegated: bool = False,
    source: str = "user",
    authority: str = "explicit",
    explicit: bool = True,
    protected: bool = True,
    value: object = None,
    target: str | None = None,
    output_id: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": part_id,
        "semantic_role": role,
        "independent": True,
        "description": description,
        "kind": kind,
        "type": type,
        "operator": operator,
        "delegated": delegated,
        "source": source,
        "authority": authority,
        "explicit": explicit,
        "protected": protected,
    }
    if value is not None:
        result["value"] = value
    if target is not None:
        result["target"] = target
    if output_id is not None:
        result["output_id"] = output_id
    return result


def _wall_clearance_composite() -> dict[str, object]:
    return {
        "id": "req_printable_wall_and_clearance",
        "description": "Choose a reasonable printable wall thickness and lid clearance.",
        "source": "user",
        "importance": "important",
        "protected": True,
        "type": "feature_presence",
        "kind": "feature",
        "operator": "present",
        "value": True,
        "raw_evidence": "Choose a reasonable printable wall thickness and lid clearance.",
        "source_fact_id": "fact_wall_clearance",
        "source_fact_type": "other",
        "source_fact_evidence": "Choose a reasonable printable wall thickness and lid clearance.",
        "semantic_parts": [
            _part(
                "wall_thickness",
                "delegated_choice",
                description="Choose a reasonable printable wall thickness.",
                kind="dimension",
                type="design_parameter",
                operator="delegated",
                delegated=True,
                authority="flexible",
                explicit=False,
                protected=False,
                output_id="box_body",
            ),
            _part(
                "lid_clearance",
                "delegated_choice",
                description="Choose a reasonable lid clearance.",
                kind="clearance",
                type="clearance",
                operator="delegated",
                delegated=True,
                authority="flexible",
                explicit=False,
                protected=False,
            ),
            _part(
                "printability",
                "qualitative_objective",
                description="Make the design printable.",
                kind="qualitative",
                type="qualitative_behavior",
                operator="qualitative",
            ),
        ],
    }


def test_delegated_composite_splits_without_inheriting_hard_authority() -> None:
    result = normalize_composite_requirement_parts([_wall_clearance_composite()])

    assert [item["requirement_id"] for item in result] == [
        "req_printable_wall_and_clearance_wall_thickness",
        "req_printable_wall_and_clearance_lid_clearance",
        "req_printable_wall_and_clearance_printability",
    ]
    delegated = result[:2]
    assert all(item["source_fact_id"] == "fact_wall_clearance" for item in result)
    assert all(item["explicit"] is False for item in delegated)
    assert all(item["authority"] == "flexible" for item in delegated)
    assert all(item["protected"] is False for item in delegated)
    assert result[2]["source"] == "user"
    assert result[2]["explicit"] is True
    assert result[2]["protected"] is True
    assert result[2]["kind"] == "qualitative"


def test_explicit_numeric_parts_remain_user_hard() -> None:
    composite = _wall_clearance_composite()
    composite["semantic_parts"] = [
        _part(
            "wall_thickness",
            "explicit_value",
            description="Use a 2 mm wall thickness.",
            kind="dimension",
            type="exact_dimension",
            operator="exact",
            value=2,
        ),
        _part(
            "lid_clearance",
            "explicit_value",
            description="Use 0.4 mm lid clearance.",
            kind="clearance",
            type="clearance",
            operator="exact",
            value=0.4,
        ),
    ]

    result = normalize_composite_requirement_parts([composite])

    assert [item["value"] for item in result] == [2, 0.4]
    assert all(item["explicit"] is True for item in result)
    assert all(item["authority"] == "explicit" for item in result)
    assert all(item["protected"] is True for item in result)


def test_structural_and_qualitative_parts_remain_independent() -> None:
    composite = {
        "id": "req_instrument_usability",
        "description": "Encloses the instrument while keeping it usable.",
        "source": "user",
        "importance": "critical",
        "protected": True,
        "source_fact_id": "fact_instrument_usability",
        "source_fact_type": "composite_function",
        "source_fact_evidence": "Encloses the instrument while keeping it usable.",
        "semantic_parts": [
            _part(
                "containment",
                "structural_intent",
                description="Enclose and support the instrument.",
                kind="relationship",
                type="relationship",
                operator="present",
            ),
            _part(
                "usability",
                "qualitative_objective",
                description="Keep the instrument usable.",
                kind="qualitative",
                type="qualitative_behavior",
                operator="qualitative",
            ),
        ],
    }

    result = normalize_composite_requirement_parts([composite])

    assert {item["semantic_role"] for item in result} == {
        "structural_intent",
        "qualitative_objective",
    }
    assert all(item["source_fact_id"] for item in result)
    assert all(item["explicit"] is True for item in result)
    assert all(item["protected"] is True for item in result)


def test_uncertain_composite_is_left_unchanged_fail_closed() -> None:
    item = {
        "id": "mixed_dimensions",
        "kind": "dimension",
        "value": 4,
        "description": "Use a 4 mm wall and place a 12 mm hole 30 mm from the edge.",
        "semantic_parts": [
            {"id": "wall", "semantic_role": "dimension", "independent": False},
            {"id": "hole", "semantic_role": "dimension", "independent": False},
        ],
    }

    result = normalize_composite_requirement_parts([item])

    assert result == [item]


def test_split_ids_and_source_identity_are_deterministic() -> None:
    first = normalize_composite_requirement_parts([_wall_clearance_composite()])
    second = normalize_composite_requirement_parts([_wall_clearance_composite()])

    assert first == second
    assert len({item["requirement_id"] for item in first}) == 3
    assert all(item["parent_requirement_id"] == "req_printable_wall_and_clearance" for item in first)
    assert all(item["source_fact_evidence"].startswith("Choose a reasonable") for item in first)


def test_output_scope_survives_split_and_ambiguous_scope_is_not_invented() -> None:
    composite = _wall_clearance_composite()
    result = normalize_composite_requirement_parts([composite])
    wall = next(item for item in result if item["composite_part_id"] == "wall_thickness")
    clearance = next(item for item in result if item["composite_part_id"] == "lid_clearance")

    assert wall["output_id"] == "box_body"
    assert "output_id" not in clearance
    assert "target" not in clearance


def test_legacy_policy_fields_are_preserved_for_later_b_routing() -> None:
    composite = _wall_clearance_composite()
    composite["classification"] = "machine_required"
    composite["verification_policy"] = "unsupported"

    result = normalize_composite_requirement_parts([composite])

    assert all(item["classification"] == "machine_required" for item in result)
    assert all(item["verification_policy"] == "unsupported" for item in result)


def test_flexible_envelope_canonicalization_preserves_authority() -> None:
    source_fact = "model_selected_envelope"
    source_evidence = "Choose a reasonable compact envelope for the concept."
    dimensions = [
        {
            "id": "concept_width",
            "requirement_id": "concept_width",
            "label": "Concept width",
            "value": 40,
            "unit": "mm",
            "source": "ai_assumption",
            "authority": "flexible",
            "explicit": False,
            "protected": False,
            "kind": "dimension",
            "operator": "approximately",
            "source_fact_id": source_fact,
            "source_fact_type": "overall_envelope",
            "source_fact_evidence": source_evidence,
        },
        {
            "id": "concept_depth",
            "requirement_id": "concept_depth",
            "label": "Concept depth",
            "value": 30,
            "unit": "mm",
            "source": "ai_assumption",
            "authority": "flexible",
            "explicit": False,
            "protected": False,
            "kind": "dimension",
            "operator": "approximately",
            "source_fact_id": source_fact,
            "source_fact_type": "overall_envelope",
            "source_fact_evidence": source_evidence,
        },
        {
            "id": "concept_height",
            "requirement_id": "concept_height",
            "label": "Concept height",
            "value": 20,
            "unit": "mm",
            "source": "ai_assumption",
            "authority": "flexible",
            "explicit": False,
            "protected": False,
            "kind": "dimension",
            "operator": "approximately",
            "source_fact_id": source_fact,
            "source_fact_type": "overall_envelope",
            "source_fact_evidence": source_evidence,
        },
    ]

    result = canonicalize_dimension_envelopes(dimensions)

    assert len(result) == 1
    assert result[0]["authority"] == "flexible"
    assert result[0]["explicit"] is False
    assert result[0]["protected"] is False


def test_split_records_survive_ledger_reload_and_contract_without_policy_routing() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    specification = {
        "object_type": "storage_box",
        "outputs": [
            {"id": "box_body", "source": "user", "authority": "explicit", "protected": True},
            {"id": "box_lid", "source": "user", "authority": "explicit", "protected": True},
        ],
        "functional_requirements": [_wall_clearance_composite()],
    }
    normalized = ProjectService._normalize_design_specification_payload(
        ProjectService.__new__(ProjectService), deepcopy(specification)
    )

    with Session(engine) as session:
        project = Project(name="Composite", slug="composite", original_intent="Make a box")
        session.add(project)
        session.flush()
        ledger = RequirementLedgerStore(session).ensure_from_specification(
            project_id=project.id,
            specification=normalized,
            originating_message="Choose a reasonable wall thickness and lid clearance.",
        )
        session.commit()
        project_id = project.id

    with Session(engine) as session:
        loaded = RequirementLedgerStore(session).load(project_id)
        active = active_requirements(loaded)
        assert len(active) == 3
        wall = next(item for item in active if item["composite_part_id"] == "wall_thickness")
        assert wall["explicit"] is False
        assert wall["authority"] == "flexible"
        assert wall["protected"] is False
        contract = build_executable_cadquery_product_contract(
            project_id=project_id,
            workflow_id="workflow",
            revision_id="revision",
            specification=normalized,
            active_requirements=active,
        )
        delegated = [
            item for item in contract["requirements"] if item["requirement_id"].endswith("wall_thickness")
        ]
        assert len(delegated) == 1
        assert delegated[0]["authority"] == "flexible"
        protected_ids = {item["requirement_id"] for item in contract["protected_facts"]}
        assert "req_printable_wall_and_clearance_wall_thickness" not in protected_ids
        assert "req_printable_wall_and_clearance_printability" in protected_ids


def test_uncertain_structured_composite_is_an_explicit_schema_field() -> None:
    payload = {
        "object_type": "generic_part",
        "purpose": "A generic part.",
        "functional_requirements": [
            {
                "id": "mixed_requirement",
                "description": "Two possible meanings.",
                "source": "user",
                "importance": "important",
                "semantic_parts": [
                    {
                        "id": "first",
                        "semantic_role": "other",
                        "independent": False,
                    },
                    {
                        "id": "second",
                        "semantic_role": "other",
                        "independent": False,
                    },
                ],
            }
        ],
    }

    validated = DesignSpecificationPayload.model_validate(payload)

    assert len(validated.functional_requirements[0].semantic_parts) == 2


def test_requirement_prompt_requires_structured_semantic_parts_and_delegation() -> None:
    provider = GeminiCliProvider.__new__(GeminiCliProvider)
    prompt = provider._build_requirement_prompt(
        RequirementExtractionRequest(
            project_name="synthetic-project",
            original_intent="Design a generic holder.",
            user_instruction="Choose a reasonable wall thickness.",
        )
    )

    assert "semantic_parts" in prompt
    assert "independently actionable semantic parts" in prompt
    assert "delegated choices must be flexible" in prompt
    assert "If the semantic split is uncertain, do not invent semantic_parts" in prompt
