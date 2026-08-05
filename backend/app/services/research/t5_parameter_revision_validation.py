"""Research-only T5 parameter-access and bounded-revision validation corpus."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from app.services.ai.provider import ModelGenerationRequest
from app.services.research.provider_ir_validation import ProviderStudyTask


STUDY_ID = "t5-parameter-revision-validation-01"
PROMPT_VERSION = "T5-geometry-exact-slot-contract-v2-parameter-map"
REPO_ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_PATH = Path(__file__).with_name("fixtures") / "t5_revision_authority_v1.json"


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


def load_revision_authority() -> dict[str, Any]:
    authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
    required_top_level = {
        "authority_id",
        "schema_version",
        "prior_output_id",
        "prior_source_reference",
        "prior_geometry",
        "protected_parameters",
        "protected_features",
        "prior_source",
        "prior_body_expression",
    }
    missing = sorted(required_top_level - set(authority))
    if missing:
        raise ValueError(f"revision authority is incomplete: {missing}")
    source = str(authority.get("prior_source") or "")
    if not source:
        raise ValueError("revision authority has no prior source")
    source_reference = authority.get("prior_source_reference")
    geometry = authority.get("prior_geometry")
    if not isinstance(source_reference, dict) or not all(source_reference.get(key) for key in ("source_id", "source_path", "source_kind")):
        raise ValueError("revision authority has incomplete prior source reference")
    if not isinstance(geometry, dict) or not isinstance(geometry.get("base_dimensions_mm"), dict) or not isinstance(geometry.get("upright_dimensions_mm"), dict):
        raise ValueError("revision authority has incomplete base dimensions")
    holes = geometry.get("holes")
    if not isinstance(holes, list) or not holes:
        raise ValueError("revision authority has no prior holes")
    hole_fields = {"feature_id", "location_mm", "axis", "owning_face", "diameter_mm", "depth_mode"}
    if any(not isinstance(hole, dict) or not hole_fields.issubset(hole) for hole in holes):
        raise ValueError("revision authority has incomplete hole authority")
    if not isinstance(authority.get("protected_features"), list) or not authority["protected_features"]:
        raise ValueError("revision authority has no protected features")
    protected_ids = {
        str(item.get("id"))
        for item in authority.get("protected_parameters", [])
        if isinstance(item, dict)
    }
    required_protected_ids = {
        "base_length_mm",
        "base_width_mm",
        "base_height_mm",
        "upright_length_mm",
        "upright_width_mm",
        "upright_thickness_mm",
        "output_id",
    }
    if not required_protected_ids.issubset(protected_ids):
        raise ValueError("revision authority is missing protected base/upright/output parameters")
    authority["prior_source_reference"]["source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return authority


def _parameters(values: Iterable[tuple[str, Any]], *, protected: Iterable[str] = ()) -> list[dict[str, Any]]:
    protected_ids = set(protected)
    return [
        {"id": parameter_id, "value": value, "unit": "mm", "protected": parameter_id in protected_ids}
        for parameter_id, value in values
    ]


def _make_task(
    number: int,
    title: str,
    intent: str,
    facts: dict[str, Any],
    parameters: list[dict[str, Any]],
    operations: tuple[str, ...],
    tokens: tuple[str, ...],
    *,
    body_initializer: str = 'body = cq.Workplane("XY").box(80, 50, 6)',
    authority: dict[str, Any] | None = None,
    revision_delta: dict[str, Any] | None = None,
    output_id: str = "body",
    study_id: str = STUDY_ID,
) -> ProviderStudyTask:
    result_symbol = "body"
    facts = copy.deepcopy(facts)
    facts["output_id"] = output_id
    facts["required_parameter_ids"] = [str(item["id"]) for item in parameters if item.get("id")]
    if revision_delta is not None:
        facts["revision_delta"] = copy.deepcopy(revision_delta)
    features = [{
        "id": "task_feature",
        "component_id": output_id,
        "operation": operations[-1],
        "description": intent,
        "protected": bool(authority),
    }]
    plan = {
        "parameters": parameters,
        "components": [{"id": output_id, "name": "authoritative body", "parameters": [item["id"] for item in parameters]}],
        "features": features,
        "printable_outputs": [{"id": output_id, "component_id": output_id, "expected_solid_count": 1, "required": True}],
        "coordinate_frames": [{"id": "world", "plane": "XY", "origin": [0, 0, 0]}],
    }
    if authority is not None:
        plan["revision_authority"] = copy.deepcopy(authority)
    manifest = {
        "schema_version": "volundr-geometry-slots-v1",
        "planning_depth": "compact_plan",
        "slots": [{
            "slot_id": 0,
            "function_id": "task_feature",
            "signature": ["body", "params"],
            "required_inputs": ["body"],
            "authorized_parameter_ids": [str(item["id"]) for item in parameters],
            "approved_helpers": [],
            "required_result": result_symbol,
            "required_feature_ids": ["task_feature"],
        }],
        "output_obligations": [{
            "output_id": output_id,
            "expected_solid_count": 1,
            "integral_features": ["task_feature"],
            "features_permitted_to_cut_material": ["task_feature"],
        }],
    }
    brief = {
        "active_requirements": [{"id": key, "value": value} for key, value in facts.items() if key != "required_parameter_ids"],
        "components": plan["components"],
        "features": features,
        "printable_outputs": plan["printable_outputs"],
        "slots": manifest["slots"],
        "output_obligations": manifest["output_obligations"],
        "parameter_access_obligations": {"required_parameter_ids": facts["required_parameter_ids"]},
    }
    if authority is not None:
        brief["revision_authority"] = copy.deepcopy(authority)
    request = ModelGenerationRequest(
        project_name=f"{study_id}-{number:02d}",
        original_intent=intent,
        user_instruction=intent,
        design_specification={"requirements": facts},
        design_plan=plan,
        revision_plan=(
            {"mode": "bounded_revision", "prior_output_id": authority["prior_output_id"], "authority": copy.deepcopy(authority)}
            if authority is not None else None
        ),
        scoped_revision_context=(copy.deepcopy(authority) if authority is not None else None),
        output_manifest={"outputs": [{"output_id": output_id, "required": True}]},
        active_requirements=[{"id": key, "value": value} for key, value in facts.items() if key != "required_parameter_ids"],
        generation_contract_version="v1",
        planning_depth="compact_plan",
        geometry_contract="volundr-geometry-slots-v1",
        geometry_slot_manifest=manifest,
        geometry_slot_brief=brief,
        source_authority={
            "source": "t5-parameter-revision-validation-corpus-v1",
            "output_ids": [output_id],
            "prior_source_reference": authority.get("prior_source_reference") if authority else None,
        },
    )
    return ProviderStudyTask(
        task_id=f"{study_id}-task-{number:02d}",
        task_number=number,
        title=title,
        authoritative_request=intent,
        semantic_facts=facts,
        required_ir_operations=operations,
        required_ir_values=tuple(
            value for value in facts.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ),
        required_fixed_points=tuple(
            tuple(point)
            for point in facts.get("fixed_points", [])
            if isinstance(point, (list, tuple)) and len(point) == 2
        ),
        required_t5_tokens=tokens,
        protected_values={
            str(item["id"]): item.get("value")
            for item in parameters
            if item.get("protected") is True and isinstance(item.get("value"), (int, float))
        },
        output_ids=(output_id,),
        body_initializer=body_initializer,
        request=request,
        semantic_facts_hash=_hash(facts),
        revision_authority=copy.deepcopy(authority),
    )


def build_candidate_tasks() -> tuple[ProviderStudyTask, ...]:
    authority = load_revision_authority()
    prior_body = str(authority["prior_body_expression"])
    return (
        _make_task(
            1,
            "Parameterized primitive and union",
            "Create one output from a parameterized box and a translated boss using authorized mapping access, union, and stable output identity.",
            {"output_id": "body", "required_parameter_ids": []},
            _parameters([
                ("base_length_mm", 80), ("base_width_mm", 50), ("base_height_mm", 6),
                ("boss_length_mm", 20), ("boss_width_mm", 20), ("boss_height_mm", 10),
                ("boss_x_mm", 20), ("boss_y_mm", 10), ("boss_z_mm", 6),
            ]),
            ("primitive", "union"),
            ("box", "union"),
        ),
        _make_task(
            2,
            "Parameterized irregular holes",
            "Create one plate with three fixed irregular through-holes; use authorized mapping access for dimensions and diameters and preserve the exact point layout.",
            {"output_id": "body", "fixed_points": [[-20, -10], [7, 13], [19, -4]], "layout": "fixed_irregular"},
            _parameters([
                ("plate_length_mm", 80), ("plate_width_mm", 50), ("plate_thickness_mm", 6),
                ("hole_diameter_a_mm", 6), ("hole_diameter_b_mm", 4.5),
            ]),
            ("primitive", "hole"),
            ("box", "pushPoints", "hole"),
        ),
        _make_task(
            3,
            "Revision: change one upright hole",
            "Starting from the authoritative prior body, change only the left upright hole from 5 mm to 6 mm and preserve the right upright hole, base dimensions, mounting holes, rear boss, axes, owning faces, and output identity.",
            {"output_id": "body", "required_parameter_ids": ["upright_hole_left_diameter_after_mm"]},
            _parameters([("upright_hole_left_diameter_after_mm", 6)]),
            ("revision", "hole"),
            ("faces", "pushPoints", "hole"),
            body_initializer=f"body = {prior_body}",
            authority=authority,
            revision_delta={"feature_id": "upright_hole_left", "from_diameter_mm": 5, "to_diameter_mm": 6},
            output_id=authority["prior_output_id"],
        ),
        _make_task(
            4,
            "Revision: add a bounded slot",
            "Starting from the authoritative prior body, add one blind slot at the stated position and preserve every prior hole, base dimension, rear boss, axis, owning face, and output identity.",
            {"output_id": "body", "required_parameter_ids": ["slot_length_mm", "slot_width_mm", "slot_depth_mm"]},
            _parameters([("slot_length_mm", 18), ("slot_width_mm", 5), ("slot_depth_mm", 3)]),
            ("revision", "slot"),
            ("faces", "slot2D", "cutBlind"),
            body_initializer=f"body = {prior_body}",
            authority=authority,
            revision_delta={"feature_id": "new_bounded_slot", "location_mm": [10, 0, 0], "length_mm": 18, "width_mm": 5, "depth_mm": 3},
            output_id=authority["prior_output_id"],
        ),
        _make_task(
            5,
            "Combined revision and parameter access",
            "Starting from the authoritative prior body, change only the right upright hole from 5 mm to 6 mm and add one blind slot; all feature dimensions, locations, axes, owning faces, protected features, prior output identity, and unrelated geometry must remain authoritative.",
            {"output_id": "body", "required_parameter_ids": ["upright_hole_right_diameter_after_mm", "slot_length_mm", "slot_width_mm", "slot_depth_mm"]},
            _parameters([("upright_hole_right_diameter_after_mm", 6), ("slot_length_mm", 18), ("slot_width_mm", 5), ("slot_depth_mm", 3)]),
            ("revision", "hole", "slot"),
            ("faces", "pushPoints", "hole", "slot2D", "cutBlind"),
            body_initializer=f"body = {prior_body}",
            authority=authority,
            revision_delta={"feature_id": "upright_hole_right", "from_diameter_mm": 5, "to_diameter_mm": 6, "slot_location_mm": [10, 0, 0]},
            output_id=authority["prior_output_id"],
        ),
        _make_task(
            6,
            "Advanced parameterized loft",
            "Create a parameterized base and a connected rectangular-to-round loft transition using several authorized mapping values; preserve output identity and use valid raw CadQuery statements.",
            {"output_id": "body", "required_parameter_ids": ["base_length_mm", "base_width_mm", "base_height_mm", "transition_height_mm", "transition_radius_mm"]},
            _parameters([
                ("base_length_mm", 40), ("base_width_mm", 30), ("base_height_mm", 10),
                ("transition_height_mm", 10), ("transition_radius_mm", 10),
            ]),
            ("primitive", "loft", "union"),
            ("box", "loft", "union"),
        ),
    )


def _parameter_subscripts(statement: str) -> tuple[str, ...]:
    tree = ast.parse(statement, mode="exec")
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found.append(key.value)
            else:
                found.append("<dynamic>")
    return tuple(found)


def validate_parameter_access(statements: Iterable[str], authorized_ids: set[str] | Iterable[str]) -> dict[str, Any]:
    authorized = {str(item) for item in authorized_ids}
    failures: list[str] = []
    observed: list[str] = []
    for statement in statements:
        tree = ast.parse(statement, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "params":
                failures.append("attribute_access_forbidden")
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
                key = node.slice.value if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) else "<dynamic>"
                observed.append(str(key))
                if key not in authorized:
                    failures.append("unauthorized_parameter_id")
    return {"passed": not failures, "failures": sorted(set(failures)), "observed_ids": observed, "authorized_ids": sorted(authorized)}


def evaluate_revision_preservation(task: ProviderStudyTask, statements: Iterable[str]) -> dict[str, Any]:
    authority = task.revision_authority
    if not authority:
        return {
            "status": "fixture_incomplete",
            "provider_failure": False,
            "prior_geometry_authority_complete": False,
            "unresolved": ["authoritative_prior_geometry_missing"],
            "failures": [],
        }
    statements = list(statements)
    text = "\n".join(statements)
    compact = text.replace(" ", "")
    failures: list[str] = []
    if not any(statement.lstrip().startswith("body = body") for statement in statements):
        failures.append("output_identity_not_reassigned")
    if any(token in text for token in ("body.translate(", "body.rotate(", "body.scale(")):
        failures.append("protected_geometry_transformed")
    if any(statement.lstrip().startswith("body = cq.") for statement in statements):
        failures.append("protected_base_reconstructed_without_authority")
    delta = task.semantic_facts.get("revision_delta") or {}
    if task.task_number in {3, 5} and "hole(" not in text:
        failures.append("requested_hole_change_missing")
    if task.task_number in {4, 5} and "slot2D" not in text:
        failures.append("requested_slot_missing")
    changed_feature = str(delta.get("feature_id") or "")
    changed_hole = next(
        (hole for hole in authority.get("prior_geometry", {}).get("holes", []) if hole.get("feature_id") == changed_feature),
        None,
    )
    if changed_hole is not None:
        location = changed_hole.get("location_mm") or []
        if len(location) >= 2 and not all(str(value) in compact for value in location[:2]):
            failures.append("changed_hole_location_missing")
        if not any(face in text for face in (">Z", "<Y", ">Y", "top_z_face", "outer_negative_y_face")):
            failures.append("changed_hole_owning_face_missing")
    if delta.get("to_diameter_mm") is not None:
        parameter_ids = {
            str(item.get("id"))
            for item in (task.request.design_plan or {}).get("parameters", []) or []
            if isinstance(item, dict) and item.get("id") is not None
        }
        changed_parameter = next(
            (parameter_id for parameter_id in parameter_ids if "diameter" in parameter_id and "after" in parameter_id),
            None,
        )
        if str(delta["to_diameter_mm"]) not in text and (changed_parameter is None or f'params["{changed_parameter}"]' not in text):
            failures.append("changed_diameter_missing")
    if task.task_number in {4, 5}:
        location = delta.get("slot_location_mm") or delta.get("location_mm") or []
        if len(location) >= 2 and not all(str(value) in compact for value in location[:2]):
            failures.append("slot_location_missing")
    if task.task_number in {4, 5} and not any(
        token in text for token in ("faces(\">Z\")", "faces(\"<Y\")", "faces(\">Y\")", "top_z_face", "outer_negative_y_face", "workplane")
    ):
        failures.append("slot_owning_face_missing")
    if task.task_number in {3, 5} and changed_hole is None:
        failures.append("changed_diameter_missing")
    return {
        "status": "provider_failure" if failures else "pass",
        "provider_failure": bool(failures),
        "prior_geometry_authority_complete": True,
        "output_identity_preserved": "output_identity_not_reassigned" not in failures,
        "changed_feature_id": changed_feature,
        "changed_feature_authority": changed_hole,
        "protected_geometry_preserved_by_authoritative_receiver": not any(
            item in failures for item in ("protected_geometry_transformed", "protected_base_reconstructed_without_authority")
        ),
        "protected_feature_ids": [str(item.get("feature_id")) for item in authority.get("protected_features", [])],
        "failures": sorted(set(failures)),
        "unresolved": [],
    }


__all__ = [
    "AUTHORITY_PATH",
    "PROMPT_VERSION",
    "STUDY_ID",
    "build_candidate_tasks",
    "evaluate_revision_preservation",
    "load_revision_authority",
    "validate_parameter_access",
]
