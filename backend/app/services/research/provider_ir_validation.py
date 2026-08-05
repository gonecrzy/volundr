"""Research-only paired provider study for the experimental geometry IR.

This module deliberately stops at the provider-contract boundary.  It never
changes production routing and it never converts a raw T5 response into IR.
Downstream compiler and worker results are recorded as separate evidence.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.gemini_integration.geometry_prompt_narrow_fix import T5GeometryValidator
from app.services.gemini_integration.profile import (
    SECONDARY_CREDENTIAL_ENV,
    GeminiFlashLiteContractV1,
    require_integration_profile,
)
from app.services.gemini_integration.prompts import (
    GEOMETRY_T5_PROMPT_VERSION,
    RenderedIntegrationPrompt,
    render_geometry_prompt_v2,
)
from app.services.gemini_integration.transport import load_secondary_credential
from app.services.research.geometry_ir_experimental import (
    IR_SCHEMA_ID,
    GeometryIRValidationError,
    compile_geometry_ir,
    validate_geometry_ir,
)


STUDY_ID = "provider-ir-targeted-validation-01"
T5_PROMPT_VERSION = "T5-geometry-exact-slot-contract-v1"
IR_PROMPT_VERSION = "T6-experimental-typed-geometry-ir-v1"
IR_RAW_ESCAPE_VERSION = "volundr-geometry-slots-v1"
ORDER_SEED = f"{STUDY_ID}-order-v1"
MAX_LOGICAL_OPERATIONS = 12
MAX_ATTEMPTS = 18
MAX_WORKER_JOBS = 12
SUPPORTED_IR_OPERATIONS = (
    "primitive",
    "profile",
    "extrude",
    "revolve",
    "hole",
    "counterbore",
    "countersink",
    "slot",
    "transform",
    "fixed_pattern",
    "linear_pattern",
    "circular_pattern",
    "union",
    "cut",
    "intersection",
    "fillet",
    "chamfer",
    "shell",
    "loft",
    "sweep",
    "output_assignment",
    "raw_cadquery",
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


def _number(value: int | float, unit: str = "mm") -> dict[str, Any]:
    return {"type": "number", "value": value, "unit": unit}


def _point(x: int | float, y: int | float, z: int | float = 0) -> list[dict[str, Any]]:
    return [_number(x), _number(y), _number(z)]


def _frame() -> dict[str, Any]:
    return {
        "origin": _point(0, 0, 0),
        "normal": [_number(0, "unitless"), _number(0, "unitless"), _number(1, "unitless")],
        "x_direction": [_number(1, "unitless"), _number(0, "unitless"), _number(0, "unitless")],
        "plane": "XY",
    }


def _base_ir(*operations: dict[str, Any], output_id: str = "body", parameters: dict[str, Any] | None = None, revision_obligations: list[dict[str, Any]] | None = None, output_symbols: dict[str, str] | None = None) -> dict[str, Any]:
    output_symbols = output_symbols or {output_id: "body"}
    return {
        "schema_version": IR_SCHEMA_ID,
        "parameters": parameters or {},
        "frames": {"world": _frame()},
        "operations": list(operations),
        "outputs": [
            {"output_id": item, "result_symbol": symbol, "required": True}
            for item, symbol in output_symbols.items()
        ],
        "revision_obligations": revision_obligations or [],
        "provenance": {
            "requirements": [f"{output_id}-authoritative-requirements"],
            "plan": f"{output_id}-authoritative-plan",
            "derivation": "provider-emission-study-counterfactual-fixture",
        },
    }


def _box(operation_id: str, length: int | float, width: int | float, height: int | float, *, result: str = "body", frame: str = "world", depends_on: list[str] | None = None) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "operation": "primitive",
        "primitive_type": "box",
        "frame": frame,
        "parameters": {"length": _number(length), "width": _number(width), "height": _number(height)},
        "result_symbol": result,
        **({"depends_on": depends_on} if depends_on else {}),
    }


def _hole(operation_id: str, x: int | float, y: int | float, diameter: int | float, *, depends_on: list[str]) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "operation": "hole",
        "target": "body",
        "frame": "world",
        "center": _point(x, y),
        "diameter": _number(diameter),
        "depth": {"mode": "through"},
        "result_symbol": "body",
        "depends_on": depends_on,
    }


def build_known_good_ir(task: "ProviderStudyTask") -> dict[str, Any]:
    """Return a synthetic known-good document for downstream counterfactuals."""

    if task.task_number == 1:
        document = _base_ir(
            _box("make-base", 80, 50, 6),
            _box("make-boss", 20, 20, 10, result="boss"),
            {"operation_id": "move-boss", "operation": "transform", "target": "boss", "translation": [_number(20), _number(10), _number(6)], "result_symbol": "boss", "depends_on": ["make-boss"]},
            {"operation_id": "join-boss", "operation": "union", "target": "body", "operand": "boss", "result_symbol": "body", "depends_on": ["make-base", "move-boss"]},
        )
    elif task.task_number == 2:
        document = _base_ir(
            _box("make-plate", 80, 50, 6),
            _hole("hole-1", -20, -10, 6, depends_on=["make-plate"]),
            _hole("hole-2", 7, 13, 4.5, depends_on=["hole-1"]),
            _hole("hole-3", 19, -4, 6, depends_on=["hole-2"]),
        )
    elif task.task_number == 3:
        document = _base_ir(
            _box("make-block", 60, 40, 20),
            {"operation_id": "blind-slot", "operation": "slot", "target": "body", "frame": "world", "center": _point(0, 8), "length": _number(20), "width": _number(6), "depth": {"mode": "blind", "distance": _number(10)}, "result_symbol": "body", "depends_on": ["make-block"]},
        )
    elif task.task_number == 4:
        document = _base_ir(
            _box("make-mount", 70, 50, 8),
            {"operation_id": "counterbore", "operation": "counterbore", "target": "body", "frame": "world", "center": _point(0, 0), "diameter": _number(5), "counterbore_diameter": _number(10), "counterbore_depth": _number(3), "depth": {"mode": "through"}, "result_symbol": "body", "depends_on": ["make-mount"]},
        )
    elif task.task_number == 5:
        document = _base_ir(
            _box("prior-body", 80, 50, 6),
            _hole("upright-hole-left", -16, 20, 6, depends_on=["prior-body"]),
            _hole("upright-hole-right", 16, 20, 6, depends_on=["upright-hole-left"]),
            {"operation_id": "revision-slot", "operation": "slot", "target": "body", "frame": "world", "center": _point(0, 10), "length": _number(18), "width": _number(5), "depth": {"mode": "blind", "distance": _number(3)}, "result_symbol": "body", "depends_on": ["upright-hole-right"]},
            parameters={"base_length": {"type": "number", "unit": "mm", "default": 80, "protected": True}, "base_width": {"type": "number", "unit": "mm", "default": 50, "protected": True}},
            revision_obligations=[{"kind": "preserve_parameter", "parameter_id": "base_length"}, {"kind": "preserve_parameter", "parameter_id": "base_width"}, {"kind": "preserve_output", "output_id": "body"}],
        )
    else:
        document = _base_ir(
            _box("make-transition-base", 40, 30, 10),
            {"operation_id": "advanced-transition", "operation": "raw_cadquery", "contract_version": IR_RAW_ESCAPE_VERSION, "required_inputs": [], "required_result_symbol": "body", "statements": ["advanced = cq.Workplane('XY').rect(40, 30).workplane(offset=20).circle(10).loft(combine=True)", "body = body.union(advanced)"], "result_symbol": "body", "depends_on": ["make-transition-base"]},
        )
    return document


@dataclass(frozen=True)
class ProviderStudyTask:
    task_id: str
    task_number: int
    title: str
    authoritative_request: str
    semantic_facts: dict[str, Any]
    required_ir_operations: tuple[str, ...]
    required_ir_values: tuple[int | float, ...]
    required_fixed_points: tuple[tuple[int | float, int | float], ...]
    required_t5_tokens: tuple[str, ...]
    protected_values: dict[str, int | float]
    output_ids: tuple[str, ...]
    body_initializer: str
    request: ModelGenerationRequest
    semantic_facts_hash: str

    @property
    def t5_semantic_facts_hash(self) -> str:
        return self.semantic_facts_hash

    @property
    def ir_semantic_facts_hash(self) -> str:
        return self.semantic_facts_hash


@dataclass(frozen=True)
class ProviderStudyOperation:
    operation_id: str
    task_id: str
    arm: str
    prompt_version: str
    prompt: str
    prompt_hash: str
    semantic_facts_hash: str
    request_hash: str
    task: ProviderStudyTask

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "arm": self.arm,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "semantic_facts_hash": self.semantic_facts_hash,
            "request_hash": self.request_hash,
            "task_facts": self.task.semantic_facts,
        }


def _task(
    number: int,
    title: str,
    request_text: str,
    facts: dict[str, Any],
    operations: tuple[str, ...],
    values: tuple[int | float, ...],
    tokens: tuple[str, ...],
    output_ids: tuple[str, ...] = ("body",),
    body_initializer: str = 'body = cq.Workplane("XY").box(80, 50, 6)',
    fixed_points: tuple[tuple[int | float, int | float], ...] = (),
    protected: dict[str, int | float] | None = None,
) -> ProviderStudyTask:
    output_id = output_ids[0]
    parameters = [
        {"id": f"fact_{index}", "value": value, "unit": "mm", "protected": True}
        for index, value in enumerate(values[:3])
    ]
    plan = {
        "parameters": parameters,
        "components": [{"id": "body", "name": "authoritative body", "parameters": [item["id"] for item in parameters]}],
        "features": [{"id": "task_feature", "component_id": "body", "operation": operations[-1], "description": request_text}],
        "printable_outputs": [{"id": item, "component_id": "body", "expected_solid_count": 1} for item in output_ids],
        "coordinate_frames": [{"id": "world", "plane": "XY", "origin": [0, 0, 0]}],
    }
    manifest = {
        "schema_version": "volundr-geometry-slots-v1",
        "planning_depth": "compact_plan",
        "slots": [{"slot_id": 0, "function_id": "task_feature", "signature": ["body", "params"], "required_inputs": ["body"], "authorized_parameter_ids": [item["id"] for item in parameters], "approved_helpers": [], "required_result": "body", "required_feature_ids": ["task_feature"]}],
        "output_obligations": [{"output_id": item, "expected_solid_count": 1, "integral_features": ["task_feature"], "features_permitted_to_cut_material": ["task_feature"]} for item in output_ids],
    }
    brief = {"active_requirements": [{"id": key, "value": value} for key, value in facts.items()], "components": plan["components"], "features": plan["features"], "printable_outputs": plan["printable_outputs"], "slots": manifest["slots"], "output_obligations": manifest["output_obligations"]}
    request = ModelGenerationRequest(
        project_name=f"{STUDY_ID}-{number:02d}",
        original_intent=request_text,
        user_instruction=request_text,
        design_specification={"requirements": facts},
        design_plan=plan,
        output_manifest={"outputs": [{"output_id": item, "required": True} for item in output_ids]},
        active_requirements=[{"id": key, "value": value} for key, value in facts.items()],
        generation_contract_version="v1",
        planning_depth="compact_plan",
        geometry_contract=IR_RAW_ESCAPE_VERSION,
        geometry_slot_manifest=manifest,
        geometry_slot_brief=brief,
        source_authority={"source": "frozen-provider-ir-task-corpus", "output_ids": list(output_ids)},
    )
    return ProviderStudyTask(
        task_id=f"provider-ir-validation-task-{number:02d}",
        task_number=number,
        title=title,
        authoritative_request=request_text,
        semantic_facts=facts,
        required_ir_operations=operations,
        required_ir_values=values,
        required_fixed_points=fixed_points,
        required_t5_tokens=tokens,
        protected_values=protected or {},
        output_ids=output_ids,
        body_initializer=body_initializer,
        request=request,
        semantic_facts_hash=_hash(facts),
    )


def build_frozen_task_corpus() -> tuple[ProviderStudyTask, ...]:
    return (
        _task(1, "Primitive plus transform", "Create one box with exact dimensions, a translated secondary boss, a union, and stable output identity.", {"base_length_mm": 80, "base_width_mm": 50, "base_height_mm": 6, "boss_length_mm": 20, "boss_width_mm": 20, "boss_height_mm": 10, "boss_translation_mm": [20, 10, 6], "output_id": "body"}, ("primitive", "transform", "union"), (80, 50, 6, 20, 10), ("box", "translate", "union"), body_initializer='body = cq.Workplane("XY").box(80, 50, 6)'),
        _task(2, "Fixed irregular holes", "Create one plate with three through-holes at explicitly irregular fixed positions and at least two different diameters; do not regularize the layout.", {"plate_length_mm": 80, "plate_width_mm": 50, "plate_thickness_mm": 6, "hole_positions": [[-20, -10], [7, 13], [19, -4]], "hole_diameters_mm": [6, 4.5, 6], "layout": "fixed_irregular", "output_id": "body"}, ("primitive", "hole"), (80, 50, 6, 6, 4.5), ("hole", "-20", "7", "19", "4.5"), body_initializer='body = cq.Workplane("XY").box(80, 50, 6)', fixed_points=((-20, -10), (7, 13), (19, -4))),
        _task(3, "Blind slot cut", "Create one block with a slot of exact length and width at an explicit location and orientation with blind depth and stable output identity.", {"block_length_mm": 60, "block_width_mm": 40, "block_height_mm": 20, "slot_length_mm": 20, "slot_width_mm": 6, "slot_center_mm": [0, 8], "slot_angle_degrees": 0, "slot_depth_mm": 10, "output_id": "body"}, ("primitive", "slot"), (60, 40, 20, 20, 6, 10), ("slot", "20", "6", "10"), body_initializer='body = cq.Workplane("XY").box(60, 40, 20)'),
        _task(4, "Counterbore feature", "Create one mounting part with a through-hole and an explicit counterbore diameter and depth.", {"part_length_mm": 70, "part_width_mm": 50, "part_height_mm": 8, "hole_diameter_mm": 5, "counterbore_diameter_mm": 10, "counterbore_depth_mm": 3, "output_id": "body"}, ("primitive", "counterbore"), (70, 50, 8, 5, 10, 3), ("counterbore", "10", "3", "5"), body_initializer='body = cq.Workplane("XY").box(70, 50, 8)'),
        _task(5, "Bounded revision", "Revise an authoritative prior part by changing the two upright holes to 6 mm and adding one slot while preserving protected dimensions, unrelated locations, and output identity.", {"prior_output_id": "body", "base_length_mm": 80, "base_width_mm": 50, "base_height_mm": 6, "upright_hole_diameter_before_mm": 5, "upright_hole_diameter_after_mm": 6, "slot_length_mm": 18, "slot_width_mm": 5, "preserve_unrelated_geometry": True, "output_id": "body"}, ("primitive", "hole", "slot"), (80, 50, 6, 5, 6, 18, 5), ("hole", "6", "slot", "18", "preserve"), body_initializer='body = cq.Workplane("XY").box(80, 50, 6)', protected={"base_length": 80, "base_width": 50}),
        _task(6, "Hybrid escape decision", "Create a deterministic base and one advanced rectangular-to-round transition feature that is not losslessly represented by the narrow IR; use raw escape only for the advanced portion.", {"base_length_mm": 40, "base_width_mm": 30, "base_height_mm": 10, "advanced_feature": "loft_transition", "advanced_feature_requires_raw_escape": True, "output_id": "body"}, ("primitive", "raw_cadquery"), (40, 30, 10), ("raw_cadquery", "loft", "advanced"), body_initializer='body = cq.Workplane("XY").box(40, 30, 10)'),
    )


def render_t5_prompt(task: ProviderStudyTask, profile: GeminiFlashLiteContractV1) -> RenderedIntegrationPrompt:
    require_integration_profile(profile.profile_id)
    rendered = render_geometry_prompt_v2(profile, task.request)
    if rendered.prompt_version != T5_PROMPT_VERSION:
        raise ValueError("frozen T5 renderer returned an unexpected prompt version")
    return rendered


def render_ir_prompt(task: ProviderStudyTask) -> str:
    """Render the single frozen T6 contract; task facts remain authoritative input."""

    schema = {
        "schema_version": IR_SCHEMA_ID,
        "required_top_level_fields": ["parameters", "frames", "operations", "outputs", "revision_obligations", "provenance"],
        "typed_value_forms": ["number", "parameter_ref", "expression"],
        "allowed_operations": list(SUPPORTED_IR_OPERATIONS),
        "raw_escape_contract": {"operation": "raw_cadquery", "contract_version": IR_RAW_ESCAPE_VERSION, "required_inputs": [], "required_result_symbol": "body", "statements": []},
        "rules": [
            "Return exactly one JSON object and no Markdown or prose.",
            "Represent semantics, not CadQuery method names or source syntax.",
            "Every operation has a unique operation_id, result_symbol, and explicit depends_on list.",
            "Every frame has typed origin, normal, x_direction, and an axis-aligned plane.",
            "Use exact authoritative numeric values and do not invent protected values.",
            "Use raw_cadquery only for an advanced portion outside the narrow typed vocabulary; keep its result isolated to the declared symbol.",
            "Do not add unknown fields, unknown operation names, or implicit coordinate frames.",
        ],
    }
    return "\n".join([
        f"Prompt version: {IR_PROMPT_VERSION}",
        "You emit Volundr-owned typed geometry semantics for one CAD task.",
        "Return one JSON object only. Do not return source code, Markdown, explanations, or method names.",
        "The compiler owns implementation choices, operation signatures, source assembly, runtime validation, and output identity.",
        "Typed geometry contract:",
        json.dumps(schema, indent=2, sort_keys=True),
        "Authoritative task facts (use these exactly; do not replace or complete them):",
        json.dumps(task.semantic_facts, indent=2, sort_keys=True),
        "The required output IDs are:",
        json.dumps(list(task.output_ids), sort_keys=True),
        "The task may require preservation obligations and a bounded raw escape; encode them explicitly when applicable.",
    ])


def build_execution_order(tasks: Iterable[ProviderStudyTask], *, seed: str = ORDER_SEED) -> list[dict[str, Any]]:
    operations = [
        {"operation_id": f"{task.task_id}:t5", "task_id": task.task_id, "arm": "t5_raw_cadquery"}
        for task in tasks
    ] + [
        {"operation_id": f"{task.task_id}:ir", "task_id": task.task_id, "arm": "typed_geometry_ir"}
        for task in tasks
    ]
    random.Random(seed).shuffle(operations)
    return operations


def build_paired_operations(tasks: Iterable[ProviderStudyTask], profile: GeminiFlashLiteContractV1, repository_root: Path) -> tuple[ProviderStudyOperation, ...]:
    result: list[ProviderStudyOperation] = []
    for task in tasks:
        t5 = render_t5_prompt(task, profile)
        result.append(ProviderStudyOperation(f"{task.task_id}:t5", task.task_id, "t5_raw_cadquery", t5.prompt_version, t5.prompt, t5.prompt_hash, task.semantic_facts_hash, _hash(task.request.__dict__), task))
        ir_prompt = render_ir_prompt(task)
        result.append(ProviderStudyOperation(f"{task.task_id}:ir", task.task_id, "typed_geometry_ir", IR_PROMPT_VERSION, ir_prompt, _hash(ir_prompt), task.semantic_facts_hash, _hash(task.semantic_facts), task))
    return tuple(result)


def _strict_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text.startswith("{") or not text.endswith("}") or "```" in text:
        raise ValueError("response must be one JSON object without Markdown or prose")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("response must be one JSON object")
    return value


def _values_in(value: Any) -> list[float]:
    if isinstance(value, dict):
        found: list[float] = []
        if value.get("type") == "number" and isinstance(value.get("value"), (int, float)) and not isinstance(value.get("value"), bool):
            found.append(float(value["value"]))
        for item in value.values():
            found.extend(_values_in(item))
        return found
    if isinstance(value, list):
        found: list[float] = []
        for item in value:
            found.extend(_values_in(item))
        return found
    return []


def _operation_names(document: dict[str, Any]) -> list[str]:
    return [str(item.get("operation")) for item in document.get("operations", []) if isinstance(item, dict)]


def _semantic_ir_check(document: dict[str, Any], task: ProviderStudyTask) -> list[str]:
    failures: list[str] = []
    names = _operation_names(document)
    for operation in task.required_ir_operations:
        if operation not in names:
            failures.append("missing_required_semantic_operation")
    values = _values_in(document)
    for expected in task.required_ir_values:
        if not any(abs(actual - float(expected)) < 1e-9 for actual in values):
            failures.append("authoritative_value_not_preserved")
    actual_outputs = [item.get("output_id") for item in document.get("outputs", []) if isinstance(item, dict)]
    if actual_outputs != list(task.output_ids):
        failures.append("output_identity_mismatch")
    if task.required_fixed_points:
        observed_points: set[tuple[float, float]] = set()
        for operation in document.get("operations", []):
            if not isinstance(operation, dict):
                continue
            points = operation.get("points")
            if isinstance(points, list):
                for point in points:
                    if isinstance(point, list) and len(point) >= 2 and all(isinstance(item, dict) for item in point[:2]):
                        observed_points.add((float(point[0].get("value")), float(point[1].get("value"))))
            center = operation.get("center")
            if isinstance(center, list) and len(center) >= 2 and all(isinstance(item, dict) for item in center[:2]):
                observed_points.add((float(center[0].get("value")), float(center[1].get("value"))))
        if not set((float(x), float(y)) for x, y in task.required_fixed_points).issubset(observed_points):
            failures.append("fixed_irregular_layout_not_preserved")
    if task.protected_values:
        parameters = document.get("parameters", {})
        for key, expected in task.protected_values.items():
            spec = parameters.get(key) if isinstance(parameters, dict) else None
            if not isinstance(spec, dict) or spec.get("default") != expected or spec.get("protected") is not True:
                failures.append("invented_or_unprotected_revision_value")
    return sorted(set(failures))


def classify_ir_response(raw: str, task: ProviderStudyTask) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "arm": "typed_geometry_ir",
        "provider_attempt": True,
        "synthetic": False,
        "contract_parse": False,
        "contract_valid": False,
        "semantic_obligations": False,
        "compiler": False,
        "failure_classes": [],
        "normalization_count": 0,
        "raw_response_hash": _hash(raw),
    }
    try:
        document = _strict_json(raw)
        validate_geometry_ir(document)
    except (ValueError, json.JSONDecodeError, GeometryIRValidationError) as exc:
        message = str(exc)
        if "depends on unknown" in message or "dependencies" in message:
            failure = "missing_dependency"
        elif "unknown operation" in message:
            failure = "unknown_ir_operation"
        elif "frame" in message or "typed number" in message or "plane" in message:
            failure = "ambiguous_coordinate_frame"
        elif "raw_cadquery" in message:
            failure = "raw_escape_contract_failure"
        else:
            failure = "ir_structure_failure"
        evidence["failure_classes"] = [failure]
        evidence["first_incorrect_boundary"] = "contract_parse"
        evidence["error"] = message
        return evidence
    evidence["contract_parse"] = True
    evidence["contract_valid"] = True
    evidence["parsed_response_hash"] = _hash(document)
    semantic_failures = _semantic_ir_check(document, task)
    evidence["failure_classes"] = semantic_failures
    evidence["semantic_obligations"] = not semantic_failures
    evidence["first_incorrect_boundary"] = None if not semantic_failures else "semantic_obligations"
    evidence["document"] = document
    if evidence["semantic_obligations"]:
        try:
            compiled = compile_geometry_ir(document)
        except Exception as exc:  # the exact compiler boundary is evidence
            evidence["failure_classes"] = ["compiler_failure"]
            evidence["first_incorrect_boundary"] = "compiler"
            evidence["compiler_error"] = str(exc)
        else:
            evidence["compiler"] = True
            evidence["compiled_source"] = compiled.source
            evidence["source_hash"] = _hash(compiled.source)
    return evidence


def _t5_semantic_check(
    raw: str,
    task: ProviderStudyTask,
    recognized_operations: set[str] | None = None,
) -> list[str]:
    text = raw.casefold()
    recognized_operations = recognized_operations or set()
    parameter_values = {
        str(item.get("id")): item.get("value")
        for item in (task.request.design_plan or {}).get("parameters", []) or []
        if isinstance(item, dict) and item.get("id") is not None
    }
    token_operation_aliases = {
        "advanced": {"advanced_transition"},
    }

    def contains_authoritative_value(value: int | float) -> bool:
        if str(value).casefold() in text:
            return True
        return any(
            str(parameter_id).casefold() in text and parameter_value == value
            for parameter_id, parameter_value in parameter_values.items()
        )

    failures = ["authoritative_value_not_preserved" for value in task.required_ir_values if not contains_authoritative_value(value)]
    failures.extend(
        "required_semantic_operation_missing"
        for token in task.required_t5_tokens
        if token.casefold() not in text
        and token.casefold() not in recognized_operations
        and not (token_operation_aliases.get(token.casefold(), set()) & recognized_operations)
        and token.casefold() != "raw_cadquery"
    )
    for value in task.protected_values.values():
        if not contains_authoritative_value(value):
            failures.append("protected_revision_value_missing")
    return sorted(set(failures))


def classify_t5_response(raw: str, task: ProviderStudyTask) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "arm": "t5_raw_cadquery",
        "provider_attempt": True,
        "synthetic": False,
        "contract_parse": False,
        "contract_valid": False,
        "semantic_obligations": False,
        "static_validation": False,
        "failure_classes": [],
        "normalization_count": 0,
        "raw_response_hash": _hash(raw),
    }
    if not raw.strip().startswith("{") or not raw.strip().endswith("}") or "```" in raw:
        evidence["failure_classes"] = ["t5_structure_failure"]
        evidence["first_incorrect_boundary"] = "contract_parse"
        return evidence
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        evidence["failure_classes"] = ["t5_structure_failure"]
        evidence["first_incorrect_boundary"] = "contract_parse"
        evidence["error"] = str(exc)
        return evidence
    if not isinstance(payload, dict) or payload.get("schema_version") != "volundr-geometry-slots-v1" or not isinstance(payload.get("slots"), list):
        evidence["failure_classes"] = ["t5_structure_failure"]
        evidence["first_incorrect_boundary"] = "contract_parse"
        return evidence
    evidence["contract_parse"] = True
    evidence["parsed_response_hash"] = _hash(payload)
    validation = T5GeometryValidator().validate(raw, task.request)
    evidence["t5_validation"] = validation
    evidence["contract_valid"] = bool(validation.get("passed"))
    failures = list(validation.get("failure_classes") or [])
    if not validation.get("passed"):
        failures.append("t5_contract_validation_failure")
    recognized_operations = {
        str(item.get("operation"))
        for slot in (validation.get("slots") or [])
        for item in (slot.get("semantic_operation_recognition") or [])
        if isinstance(item, dict) and item.get("operation")
    }
    semantic_failures = _t5_semantic_check(raw, task, recognized_operations)
    failures.extend(semantic_failures)
    evidence["failure_classes"] = sorted(set(failures))
    evidence["semantic_obligations"] = not semantic_failures
    evidence["static_validation"] = bool(validation.get("passed"))
    evidence["first_incorrect_boundary"] = None if not failures else ("semantic_obligations" if semantic_failures and validation.get("passed") else "contract_parse")
    evidence["payload"] = payload
    evidence["semantic_operation_recognition"] = sorted(recognized_operations)
    # Source assembly is an independent boundary.  A semantically incomplete
    # or runtime-incompatible but structurally parseable provider response must
    # still be assembled so the review can distinguish those failures.
    try:
        evidence["assembled_source"] = assemble_t5_source(task, payload)
    except (KeyError, TypeError, ValueError):
        pass
    else:
        evidence["source_hash"] = _hash(evidence["assembled_source"])
    return evidence


def assemble_t5_source(task: ProviderStudyTask, payload: dict[str, Any]) -> str:
    slots = payload.get("slots")
    if not isinstance(slots, list) or len(slots) != 1:
        raise ValueError("research T5 assembly requires exactly one validated slot")
    statements = slots[0].get("statements")
    if not isinstance(statements, list) or not all(isinstance(item, str) for item in statements):
        raise ValueError("research T5 assembly requires exact string statements")
    lines = [
        "import cadquery as cq",
        "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product",
        "",
        "PARAMETERS = [",
    ]
    for parameter in (task.request.design_plan or {}).get("parameters", []) or []:
        if not isinstance(parameter, dict) or parameter.get("id") is None:
            continue
        lines.append(
            "    ParameterSpec("
            f"id={str(parameter['id'])!r}, label={str(parameter['id'])!r}, type='float', "
            f"default={parameter.get('value', parameter.get('default', 0))!r}, unit={str(parameter.get('unit') or 'mm')!r}, "
            f"protected={bool(parameter.get('protected', False))!r}),"
        )
    lines.extend([
        "]",
        "",
        "def build(params):",
        f"    {task.body_initializer}",
    ])
    lines.extend(f"    {statement}" for statement in statements)
    lines.extend([
        "    return Product(",
        "        parameters=PARAMETERS,",
        "        outputs=[",
        f"            PrintableOutput(output_id={task.output_ids[0]!r}, component_id={task.output_ids[0]!r}, label={task.title!r}, model=body, required=True, expected_solid_count=1, allow_disconnected_solids=False),",
        "        ],",
        "    )",
    ])
    return "\n".join(lines) + "\n"


def classify_candidate_eligibility(provider_evidence: dict[str, Any], downstream: dict[str, Any]) -> dict[str, Any]:
    if not provider_evidence.get("contract_parse") or provider_evidence.get("contract_valid") is False:
        return {"candidate_eligible": False, "first_incorrect_boundary": provider_evidence.get("first_incorrect_boundary") or "contract_parse", "reason": "provider contract failed"}
    if not provider_evidence.get("semantic_obligations"):
        return {"candidate_eligible": False, "first_incorrect_boundary": "semantic_obligations", "reason": "semantic obligations failed"}
    if downstream.get("source_generation") is False:
        return {"candidate_eligible": False, "first_incorrect_boundary": "source_generation", "reason": "source generation did not run or failed"}
    if downstream.get("static_validation") is False:
        return {"candidate_eligible": False, "first_incorrect_boundary": "static_validation", "reason": "static validation did not pass"}
    if downstream.get("compiler") is False or downstream.get("worker_execution") is False or downstream.get("requirement_verification") is False:
        return {"candidate_eligible": False, "first_incorrect_boundary": next((key for key in ("compiler", "worker_execution", "topology", "requirement_verification") if downstream.get(key) is False), "downstream"), "reason": "downstream boundary failed"}
    return {"candidate_eligible": True, "first_incorrect_boundary": None, "reason": "all measured boundaries passed"}


def summarize_provider_metrics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ("t5_raw_cadquery", "typed_geometry_ir"):
        selected = [item for item in records if item.get("arm") == arm and item.get("provider_attempt") and not item.get("synthetic")]
        result[arm] = {
            "provider_operations": len(selected),
            "contract_parse_rate": _rate(selected, "contract_parse"),
            "semantic_obligation_rate": _rate(selected, "semantic_obligations"),
            "source_generation_rate": _rate(selected, "source_generation"),
            "static_validation_rate": _rate(selected, "static_validation"),
            "worker_execution_rate": _rate(selected, "worker_execution"),
            "topology_verification_rate": _rate(selected, "topology_verification"),
            "requirement_verification_rate": _rate(selected, "requirement_verification"),
            "candidate_eligibility_rate": _rate(selected, "candidate_eligible"),
            "provider_owned_failure_count": sum(bool(item.get("provider_owned_failure")) for item in selected),
            "runtime_api_failure_count": sum(bool(item.get("runtime_api_failure")) for item in selected),
            "normalization_count": sum(int(item.get("normalization_count") or 0) for item in selected),
            "unrecoverable_ambiguity_count": sum(bool(item.get("unrecoverable_ambiguity")) for item in selected),
        }
    return result


def _rate(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(sum(bool(item.get(field)) for item in records) / len(records) * 100, 3)


def require_secondary_credential() -> dict[str, Any]:
    credential = load_secondary_credential()
    if not credential.value:
        raise RuntimeError(f"{SECONDARY_CREDENTIAL_ENV} is absent; no provider call was attempted")
    return dict(credential.metadata)


def build_task_report(task: ProviderStudyTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_number": task.task_number,
        "title": task.title,
        "authoritative_request": task.authoritative_request,
        "semantic_facts": task.semantic_facts,
        "semantic_facts_hash": task.semantic_facts_hash,
        "required_ir_operations": list(task.required_ir_operations),
        "required_ir_values": list(task.required_ir_values),
        "required_fixed_points": [list(item) for item in task.required_fixed_points],
        "required_t5_tokens": list(task.required_t5_tokens),
        "protected_values": task.protected_values,
        "output_ids": list(task.output_ids),
        "request": task.request.__dict__,
    }


def frozen_contract_report(profile: GeminiFlashLiteContractV1) -> dict[str, Any]:
    return {
        "study_id": STUDY_ID,
        "model": profile.model,
        "provider_profile": profile.profile_id,
        "settings": profile.settings,
        "thinking": {"profile": "H1-provider-default", "thinkingConfig": "omitted"},
        "prompt_contracts": {"t5": T5_PROMPT_VERSION, "ir": IR_PROMPT_VERSION},
        "credential_policy": {"environment_variable": SECONDARY_CREDENTIAL_ENV, "primary_fallback": False, "credential_values_serialized": False},
        "caps": {"logical_provider_operations": MAX_LOGICAL_OPERATIONS, "maximum_provider_attempts": MAX_ATTEMPTS, "maximum_worker_jobs": MAX_WORKER_JOBS},
        "rate_limit": {"default_starts_per_rolling_60_seconds": 12, "hard_max_starts_per_rolling_60_seconds": 15, "minimum_start_gap_seconds": 5, "concurrency": 1, "clock": "monotonic"},
    }


def redacted_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(attempt, default=str))
    value.pop("credential", None)
    auth = value.get("auth_metadata")
    if isinstance(auth, dict):
        value["auth_metadata"] = {key: item for key, item in auth.items() if key != "value"}
    text = json.dumps(value, sort_keys=True)
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
        if name in text and isinstance(value.get("error_message"), str):
            value["error_message"] = value["error_message"].replace(name, "<redacted-credential-name>")
    return value


def report_names() -> tuple[str, ...]:
    return (
        "preregistration.json", "repository-snapshot.json", "frozen-task-corpus.json", "execution-order.json", "prompt-contracts.json", "provider-attempts.json", "arm-a-t5-results.json", "arm-b-ir-results.json", "paired-task-results.json", "semantic-equivalence-results.json", "compiler-results.json", "worker-results.json", "topology-results.json", "requirement-verification-results.json", "counterfactual-results.json", "normalization-report.json", "rate-limit-report.json", "retry-report.json", "provider-ir-decision.json", "wave-02-gate.json", "combined-provider-ir-evidence.json",
    )


def validate_report_completeness(root: Path) -> list[str]:
    return [name for name in report_names() if not (root / name).is_file()]


__all__ = [
    "IR_PROMPT_VERSION", "MAX_ATTEMPTS", "MAX_LOGICAL_OPERATIONS", "MAX_WORKER_JOBS", "ORDER_SEED", "ProviderStudyOperation", "ProviderStudyTask", "STUDY_ID", "T5_PROMPT_VERSION", "assemble_t5_source", "build_execution_order", "build_frozen_task_corpus", "build_known_good_ir", "build_paired_operations", "build_task_report", "classify_candidate_eligibility", "classify_ir_response", "classify_t5_response", "frozen_contract_report", "redacted_attempt", "render_ir_prompt", "render_t5_prompt", "report_names", "require_secondary_credential", "summarize_provider_metrics", "validate_report_completeness",
]
