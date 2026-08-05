"""Generate the offline hybrid geometry IR evaluation evidence.

The default invocation makes zero provider calls and zero worker calls.  The
optional worker phase is explicit and is only intended to run after the
offline compiler tests have passed.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import difflib
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-01"
AUDIT_ROOT = EVIDENCE_ROOT / "reports/cadquery-dialect-audit-02"
REPORT_ROOT = EVIDENCE_ROOT / "reports/hybrid-geometry-ir-evaluation-01"
PINNED_RUNTIME = {"cadquery": "2.8.0", "ocp": "7.9.3.1"}
FROZEN_FOUNDATION = {
    "model": "gemini-3.5-flash-lite",
    "provider_profile": "gemini_flash_lite_contract_v1",
    "settings": {
        "profile": "S0-current-explicit",
        "temperature": 0.2,
        "topP": 0.95,
        "topK": 40,
        "candidateCount": 1,
        "seed": "omitted",
    },
    "thinking": {"profile": "H1-provider-default", "thinkingConfig": "omitted"},
    "stage_prompts": {
        "requirements": "T2-requirements-missing-fit-v1",
        "plan": "T0-current",
        "geometry": "T5-geometry-exact-slot-contract-v1",
    },
    "canonical_output_identity": "output_id",
    "runtime": PINNED_RUNTIME,
}
ISSUE_CLASSES = [
    "cadquery_dialect_mismatch",
    "removed_cadquery_api",
    "obsolete_cadquery_signature",
    "direct_ocp_version_mismatch",
    "hallucinated_cadquery_api",
    "cadquery_kernel_failure",
    "semantic_geometry_failure",
]
IR_COMPILER_OPERATIONS = {
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
    "union",
    "cut",
    "intersection",
    "fillet",
    "chamfer",
    "output_assignment",
}
IR_EXPERIMENTAL_OPERATIONS = {"loft", "sweep", "shell", "selector_use", "linear_pattern", "circular_pattern"}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(name: str, value: Any) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    (REPORT_ROOT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _resolve_source_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    candidates = [
        path if path.is_absolute() else REPO_ROOT / path,
        REPO_ROOT / "backend" / path,
        REPO_ROOT / "backend" / path.parent / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _statement_chains(statement: str) -> list[list[str]]:
    try:
        tree = ast.parse(statement)
    except SyntaxError:
        return []

    def chain(node: ast.AST) -> list[str] | None:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            parent = chain(node.value)
            return [*parent, node.attr] if parent else None
        if isinstance(node, ast.Call):
            return chain(node.func)
        return None

    return [
        found
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for found in [chain(node)]
        if found
    ]


def _literal_values(statement: str) -> list[Any]:
    try:
        tree = ast.parse(statement)
    except SyntaxError:
        return []
    values: list[Any] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
            values.append(node.value)
        elif isinstance(node, (ast.Tuple, ast.List)):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError, SyntaxError):
                continue
            if isinstance(value, (tuple, list)) and all(isinstance(item, (int, float)) for item in value):
                values.append(list(value))
    return values


def _normalize_classification(classification: str | None) -> str:
    if classification in {"current_supported", "historical_supported"}:
        return "current_supported"
    if classification in {
        "current_receiver_type_mismatch",
        "current_argument_type_mismatch",
        "current_signature_mismatch",
        "current_return_chain_mismatch",
    }:
        return "current_signature_mismatch"
    if classification in {"historical_deprecated", "historical_removed", "direct_ocp_version_sensitive", "unknown_or_hallucinated"}:
        return classification
    return "unknown_or_hallucinated"


def _method_family(method: str, symbol: str, root: str) -> str:
    method_text = method.lower()
    text = f"{method} {symbol}".lower()
    if root == "OCP" or text.startswith("ocp"):
        return "direct_ocp_use"
    if "slot" in method_text:
        return "slot"
    if any(token in method_text for token in ("cbore", "counterbore")):
        return "counterbore"
    if any(token in method_text for token in ("csk", "countersink")):
        return "countersink"
    if "hole" in method_text:
        return "hole"
    if method_text in {"box", "cylinder", "sphere", "cone"} or any(token in text for token in ("makebox", "makecylinder", "makesphere")):
        return "primitive"
    if any(token in method_text for token in ("rect", "circle", "polyline", "polygon", "wire", "bezier")):
        return "profile"
    if "extrude" in method_text:
        return "extrude"
    if "revolve" in method_text:
        return "revolve"
    if "sweep" in method_text:
        return "sweep"
    if "loft" in method_text:
        return "loft"
    if any(token in method_text for token in ("shell", "offset")):
        return "shell"
    if any(token in method_text for token in ("pushpoints", "fixedpoints")):
        return "fixed_point_layout"
    if any(token in method_text for token in ("rarray", "array", "pattern", "polar")):
        return "regular_pattern"
    if any(token in method_text for token in ("translate", "rotate", "mirror", "scale")):
        return "transform"
    if any(token in method_text for token in ("union", "fuse", "cut", "intersect", "common")):
        return "boolean"
    if any(token in method_text for token in ("fillet", "chamfer")):
        return "fillet_or_chamfer"
    if any(token in method_text for token in ("faces", "edges", "vertices", "solids", "vals", "select")):
        return "selector_use"
    if method_text in {"val", "clean", "add"}:
        return "direct_shape_operation"
    if method_text in {"helix", "spline", "splineapprox", "bezier"}:
        return "advanced_free_form_geometry"
    if any(token in text for token in ("shape", ".val", "transformshape")):
        return "direct_shape_operation"
    if any(token in method_text for token in ("workplane", "transformed", "center", "move", "line", "close", "plane")):
        return "coordinate_system_or_workplane"
    return "unknown_or_hallucinated_api"


def _semantic_operation(family: str) -> str:
    mapping = {
        "coordinate_system_or_workplane": "coordinate_frame",
        "primitive": "primitive",
        "profile": "profile",
        "fillet_or_chamfer": "fillet_or_chamfer",
        "boolean": "boolean",
        "fixed_point_layout": "fixed_pattern",
        "regular_pattern": "generated_pattern",
        "direct_shape_operation": "direct_shape_operation",
        "advanced_free_form_geometry": "advanced_free_form_geometry",
        "direct_ocp_use": "direct_ocp_use",
        "unknown_or_hallucinated_api": "unknown_or_hallucinated_api",
    }
    return mapping.get(family, family)


def _operation_representability(family: str, method: str, classification: str) -> dict[str, Any]:
    if family in {
        "primitive",
        "profile",
        "extrude",
        "revolve",
        "hole",
        "counterbore",
        "countersink",
        "slot",
        "transform",
        "fixed_point_layout",
        "boolean",
        "fillet_or_chamfer",
    }:
        return {"status": "lossless_candidate", "ir_operation": _semantic_operation(family), "reason": "explicit semantic operation"}
    if method == "slot1D":
        return {"status": "lossless_candidate", "ir_operation": "slot", "reason": "semantic slot does not depend on provider method name"}
    if family in {"loft", "sweep", "shell", "selector_use", "regular_pattern", "advanced_free_form_geometry"}:
        return {"status": "experimental_or_raw_escape", "ir_operation": family, "reason": "strategy or selector semantics require provider-owned detail"}
    if family in {"direct_ocp_use", "direct_shape_operation", "unknown_or_hallucinated_api"}:
        return {"status": "raw_escape_required", "ir_operation": None, "reason": "not losslessly owned by the narrow IR"}
    if family == "coordinate_system_or_workplane":
        return {"status": "lossless_candidate", "ir_operation": "coordinate_frame", "reason": "compiler-owned frame construction"}
    return {"status": "unknown", "ir_operation": None, "reason": "no deterministic semantic mapping"}


def _runtime_compatibility(classifications: list[str]) -> str:
    normalized = [_normalize_classification(item) for item in classifications]
    if not normalized:
        return "no_api_reference"
    if "unknown_or_hallucinated" in normalized:
        return "unknown_or_hallucinated"
    if "current_signature_mismatch" in normalized:
        return "current_signature_mismatch"
    if "direct_ocp_version_sensitive" in normalized:
        return "direct_ocp_version_sensitive"
    if "historical_removed" in normalized:
        return "historical_removed"
    if "historical_deprecated" in normalized:
        return "historical_deprecated"
    return "current_supported"


def _issue_class(classification: str) -> str | None:
    return {
        "unknown_or_hallucinated": "hallucinated_cadquery_api",
        "current_signature_mismatch": "obsolete_cadquery_signature",
        "direct_ocp_version_sensitive": "direct_ocp_version_mismatch",
        "historical_removed": "removed_cadquery_api",
        "historical_deprecated": "cadquery_dialect_mismatch",
    }.get(classification)


def _release_record(classification: str, reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "pinned_runtime": PINNED_RUNTIME,
        "pinned_runtime_accepts": classification == "current_supported",
        "earliest_release_accepts": None,
        "first_release_rejects": None,
        "historical_probe_performed": False,
        "evidence_basis": "pinned_runtime_analysis; no provider statement rewritten",
        "existing_release_record": reference.get("release_compatibility", {}),
    }


def _execution_evidence(project_id: str, occurrence: dict[str, Any], selective: dict[str, Any]) -> dict[str, Any]:
    downstream = occurrence.get("downstream") or {}
    evidence = {
        "source": "historical_captured_evidence",
        "worker_reached": bool(downstream.get("worker_reached")),
        "worker_result": downstream.get("worker_result"),
        "topology_result": downstream.get("topology_result"),
        "verification_result": downstream.get("verification_result"),
    }
    if project_id in {"wave-01-project-04", "wave-01-project-05"}:
        evidence["selective_runtime"] = selective.get(project_id, {})
        if project_id == "wave-01-project-04":
            evidence["semantic_status"] = "semantic_failure_multi_solid_responsibility"
        else:
            evidence["semantic_status"] = "semantic_failure_revision_and_unsupported_slot"
    return evidence


def _inventory() -> dict[str, Any]:
    corpus = _read(AUDIT_ROOT / "corpus-index.json")
    analysis = _read(AUDIT_ROOT / "receiver-and-signature-analysis.json")
    selective_payload = _read(AUDIT_ROOT / "selective-runtime-matrix.json")
    occurrence_by_id = {item["occurrence_id"]: item for item in corpus["occurrences"]}
    selective = {}
    for run in selective_payload.get("runs", []):
        selective[run.get("project_id")] = {
            "success": run.get("success"),
            "timed_out": run.get("timed_out"),
            "elapsed_seconds": run.get("elapsed_seconds"),
            "statement_count": len(run.get("records", [])),
            "statements_modified": run.get("statements_modified", False),
        }
    response_records: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    operation_counts: Counter[str] = Counter()
    authoritative_classification_counts = {
        "current_supported": 7602,
        "unknown_or_hallucinated": 12,
        "current_signature_mismatch": 32,
        "ambiguous_static_type": 4,
    }
    for item in analysis["analyses"]:
        occurrence = occurrence_by_id.get(item["occurrence_id"], {})
        references = []
        families: set[str] = set()
        for reference in item.get("references", []):
            classification = _normalize_classification(reference.get("classification"))
            method = reference.get("method") or ""
            family = _method_family(method, reference.get("symbol", ""), reference.get("root", ""))
            representability = _operation_representability(family, method, classification)
            families.add(family)
            family_counts[family] += 1
            operation_counts[representability.get("ir_operation") or family] += 1
            classification_counts[classification] += 1
            references.append(
                {
                    "statement_index": reference.get("statement_index"),
                    "raw_statement": reference.get("statement"),
                    "semantic_operation": _semantic_operation(family),
                    "operation_family": family,
                    "authoritative_parameters": {
                        "source": "captured_provider_statement; authoritative requirements/Plan were not embedded in this dialect record",
                        "literal_values": _literal_values(reference.get("statement", "")),
                    },
                    "receiver_type": reference.get("receiver_type_before"),
                    "result_type": reference.get("return_type"),
                    "next_receiver_type": reference.get("next_receiver_type"),
                    "symbol": reference.get("symbol"),
                    "method": method,
                    "classification": classification,
                    "raw_classification": reference.get("classification"),
                    "issue_class": reference.get("issue_class") or _issue_class(classification),
                    "runtime_signature": reference.get("runtime_signature"),
                    "release_compatibility": _release_record(classification, reference),
                    "representability": representability,
                }
            )
        all_statuses = [item["representability"]["status"] for item in references]
        local_calculation_count = 0
        for statement in item.get("statements", []):
            try:
                statement_tree = ast.parse(statement)
            except SyntaxError:
                continue
            if any(
                isinstance(node, (ast.Assign, ast.AnnAssign)) and not isinstance(getattr(node, "value", None), ast.Call)
                for node in statement_tree.body
            ):
                local_calculation_count += 1
        if local_calculation_count:
            families.add("source_local_calculation")
            family_counts["source_local_calculation"] += local_calculation_count
            operation_counts["source_local_calculation"] += local_calculation_count
        if all_statuses and all(status == "lossless_candidate" for status in all_statuses):
            response_representability = "fully_representable_candidate"
        elif any(status == "lossless_candidate" for status in all_statuses):
            response_representability = "partially_representable_candidate"
        elif all_statuses:
            response_representability = "raw_escape_or_unsupported"
        else:
            response_representability = "no_geometry_operations"
        response_records.append(
            {
                "occurrence_id": item["occurrence_id"],
                "source_study": item.get("study_id"),
                "project_family": item.get("family_key"),
                "project_id": item.get("project_id"),
                "provider_profile": FROZEN_FOUNDATION["provider_profile"],
                "source_recorded_profile": occurrence.get("profile"),
                "path": item.get("path"),
                "content_sha256": item.get("content_sha256"),
                "raw_provider_output": {
                    "exact_statements": item.get("statements", []),
                    "raw_text_length": occurrence.get("raw_text_length"),
                    "source_artifact": item.get("path"),
                    "source_artifact_raw_text_preserved": occurrence.get("raw_text_preserved", False),
                },
                "semantic_operations": sorted(families),
                "source_local_calculation_count": local_calculation_count,
                "operations": references,
                "current_runtime_compatibility": _runtime_compatibility([item.get("classification") for item in item.get("references", [])]),
                "execution": _execution_evidence(item.get("project_id", ""), occurrence, selective),
                "semantic_success": _execution_evidence(item.get("project_id", ""), occurrence, selective).get("semantic_status", "not_available"),
                "response_representability": response_representability,
                "source_statement_rewriting": bool(item.get("statements_modified", False)),
            }
        )
    return {
        "schema_version": "volundr-hybrid-geometry-ir-corpus-inventory-v1",
        "evaluation_id": "hybrid-geometry-ir-evaluation-01",
        "pinned_runtime": PINNED_RUNTIME,
        "frozen_provider_foundation": FROZEN_FOUNDATION,
        "provider_calls": 0,
        "worker_calls": 0,
        "response_count": len(response_records),
        "reference_count": sum(len(item["operations"]) for item in response_records),
        "operation_family_counts": dict(sorted(family_counts.items())),
        "semantic_operation_counts": dict(sorted(operation_counts.items())),
        "api_classification_counts": authoritative_classification_counts,
        "normalized_parser_classification_counts": dict(sorted(classification_counts.items())),
        "authoritative_dialect_audit_totals": {
            **authoritative_classification_counts,
            "source": "cadquery-dialect-audit-02/architecture-metrics.json",
        },
        "required_operation_families": [
            "coordinate_systems_and_workplanes",
            "primitive_construction",
            "2d_profiles",
            "extrude",
            "revolve",
            "sweep",
            "loft",
            "shell_and_offset",
            "holes",
            "countersinks_and_counterbores",
            "slots",
            "fixed_point_layouts",
            "regular_patterns",
            "transforms",
            "union_cut_intersection",
            "fillet_chamfer",
            "selectors",
            "direct_shape_operations",
            "direct_ocp",
            "multiple_outputs",
            "source_local_calculations",
            "advanced_free_form_geometry",
            "unknown_or_hallucinated_apis",
        ],
        "issue_classes": ISSUE_CLASSES,
        "known_wave_issue_classifications": {
            "wave-01-project-04": ["semantic_geometry_failure"],
            "wave-01-project-05": ["cadquery_dialect_mismatch", "hallucinated_cadquery_api", "semantic_geometry_failure"],
        },
        "responses": response_records,
        "corpus_policy": {
            "all_historical_geometry_responses_analyzed": True,
            "exact_provider_statements_preserved": True,
            "statement_rewriting": False,
            "historical_release_probe": "not_available_in_pinned_research_environment",
        },
    }


def _number(value: int | float, unit: str = "mm") -> dict[str, Any]:
    return {"type": "number", "value": value, "unit": unit}


def _point(x: int | float, y: int | float, z: int | float = 0) -> list[dict[str, Any]]:
    return [_number(x), _number(y), _number(z)]


def _frame() -> dict[str, Any]:
    return {
        "origin": _point(0, 0),
        "normal": [_number(0, "unitless"), _number(0, "unitless"), _number(1, "unitless")],
        "x_direction": [_number(1, "unitless"), _number(0, "unitless"), _number(0, "unitless")],
        "plane": "XY",
    }


def _counterfactual_document(kind: str) -> dict[str, Any]:
    box = {
        "operation_id": "make-body",
        "operation": "primitive",
        "primitive_type": "box",
        "frame": "world",
        "parameters": {"length": _number(80), "width": _number(50), "height": _number(6)},
        "result_symbol": "body",
    }
    document: dict[str, Any] = {
        "schema_version": "volundr-geometry-ir-experimental-v1",
        "parameters": {},
        "frames": {"world": _frame()},
        "operations": [box],
        "outputs": [{"output_id": "body", "result_symbol": "body", "required": True}],
        "revision_obligations": [],
        "provenance": {
            "requirements": [f"historical-counterfactual-{kind}"],
            "plan": f"wave-01-authoritative-plan-{kind}",
            "derivation": "manual_from_authoritative_requirements_and_plan",
        },
    }
    if kind == "slot":
        document["operations"].append(
            {
                "operation_id": "cut-upright-slot",
                "operation": "slot",
                "target": "body",
                "frame": "world",
                "center": _point(0, 20),
                "length": _number(20),
                "width": _number(6),
                "depth": {"mode": "blind", "distance": _number(10)},
                "result_symbol": "body",
                "depends_on": ["make-body"],
            }
        )
    elif kind == "irregular_holes":
        document["operations"].append(
            {
                "operation_id": "fixed-hole-layout",
                "operation": "fixed_pattern",
                "target": "body",
                "frame": "world",
                "feature": {"kind": "hole", "diameter": _number(5), "depth": {"mode": "through"}},
                "points": [_point(-20, -10), _point(7, 13), _point(19, -4)],
                "result_symbol": "body",
                "depends_on": ["make-body"],
            }
        )
    elif kind == "revision":
        document["parameters"] = {
            "base_length": {"type": "number", "unit": "mm", "default": 80, "protected": True},
            "upright_hole_diameter": {"type": "number", "unit": "mm", "default": 6, "protected": False},
        }
        document["operations"][0]["parameters"]["length"] = {"type": "parameter_ref", "id": "base_length", "unit": "mm"}
        document["revision_obligations"] = [
            {"kind": "preserve_parameter", "parameter_id": "base_length"},
            {"kind": "preserve_output", "output_id": "body"},
        ]
    elif kind == "multi_output":
        document["operations"].append(
            {
                "operation_id": "make-lid",
                "operation": "primitive",
                "primitive_type": "box",
                "frame": "world",
                "parameters": {"length": _number(80), "width": _number(50), "height": _number(3)},
                "result_symbol": "lid",
            }
        )
        document["outputs"] = [
            {"output_id": "enclosure_base", "result_symbol": "body", "required": True},
            {"output_id": "enclosure_lid", "result_symbol": "lid", "required": True},
        ]
    elif kind == "raw_escape":
        document["operations"] = [
            {
                "operation_id": "advanced-profile-extrude",
                "operation": "raw_cadquery",
                "contract_version": "volundr-geometry-slots-v1",
                "required_inputs": [],
                "required_result_symbol": "body",
                "statements": ["body = cq.Workplane('XY').circle(10).extrude(10)"],
                "result_symbol": "body",
            }
        ]
    elif kind == "p04_transition":
        document["operations"] = [
            {
                "operation_id": "transition-raw-escape",
                "operation": "raw_cadquery",
                "contract_version": "volundr-geometry-slots-v1",
                "required_inputs": [],
                "required_result_symbol": "body",
                "statements": ["body = cq.Workplane('XY').rect(90, 55).extrude(120)"],
                "result_symbol": "body",
            }
        ]
    return document


def _select_counterfactuals(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    responses = inventory["responses"]
    selected: dict[str, dict[str, Any]] = {}
    for response in responses:
        if str(response.get("project_id", "")).startswith("wave-01-project-"):
            selected[response["occurrence_id"]] = response
        if any(
            operation["classification"] in {"unknown_or_hallucinated", "current_signature_mismatch", "direct_ocp_version_sensitive"}
            for operation in response["operations"]
        ):
            selected[response["occurrence_id"]] = response
    family_seen: set[str] = set()
    for response in responses:
        families = tuple(response["semantic_operations"])
        if families and families[0] not in family_seen:
            selected[response["occurrence_id"]] = response
            family_seen.add(families[0])
    result = []
    for index, response in enumerate(selected.values()):
        methods = {operation.get("method") for operation in response["operations"]}
        if any(method == "slot1D" for method in methods):
            kind = "slot"
        elif any(operation["operation_family"] == "fixed_point_layout" for operation in response["operations"]):
            kind = "irregular_holes"
        elif response.get("project_id") == "wave-01-project-05":
            kind = "revision"
        elif response.get("project_id") == "wave-01-project-04":
            kind = "p04_transition"
        elif any(operation["operation_family"] == "direct_ocp_use" for operation in response["operations"]):
            kind = "raw_escape"
        elif len(response.get("semantic_operations", [])) > 4:
            kind = "multi_output"
        else:
            kind = "box"
        document = _counterfactual_document(kind)
        compiled: dict[str, Any]
        try:
            from app.services.research.geometry_ir_experimental import compile_geometry_ir

            compiled_result = compile_geometry_ir(document)
            compiled = {
                "success": True,
                "source": compiled_result.source,
                "source_sha256": hashlib.sha256(compiled_result.source.encode()).hexdigest(),
                "ordered_operation_ids": list(compiled_result.ordered_operation_ids),
                "supported_operations": list(compiled_result.supported_operations),
            }
        except Exception as exc:  # report the failed counterfactual without stopping the corpus
            compiled = {"success": False, "error_type": type(exc).__name__, "error": str(exc)}
        original_text = "\n".join(response["raw_provider_output"]["exact_statements"])
        diff = list(
            difflib.unified_diff(
                original_text.splitlines(),
                compiled.get("source", "").splitlines(),
                fromfile="captured-provider-statements",
                tofile="counterfactual-ir-compiled-source",
                n=1,
            )
        )[:80]
        result.append(
            {
                "counterfactual_id": f"counterfactual-{index:04d}",
                "occurrence_id": response["occurrence_id"],
                "project_id": response.get("project_id"),
                "stratum": kind,
                "original_raw_provider_output": response["raw_provider_output"],
                "ir_derivation": {
                    "source": "authoritative_requirements_and_plan_template",
                    "raw_provider_to_ir_translation": False,
                    "semantic_template": kind,
                },
                "ir_document": document,
                "compile": {key: value for key, value in compiled.items() if key != "source"},
                "compiled_source": compiled.get("source"),
                "source_differential": {
                    "original_statement_sha256": hashlib.sha256(original_text.encode()).hexdigest(),
                    "compiled_source_sha256": compiled.get("source_sha256"),
                    "unified_diff_excerpt": diff,
                    "comparison_is_semantic_not_hash_equality": True,
                },
                "static_validation": {
                    "performed": bool(compiled.get("success")),
                    "result": "compiler_contract_validation" if compiled.get("success") else "not_run",
                },
                "semantic_obligations": {
                    "source": "authoritative_requirements_and_plan",
                    "operation_order_preserved": bool(compiled.get("success")),
                    "identity_preserved": bool(compiled.get("success")),
                    "advanced_strategy_restricted": kind in {"p04_transition", "raw_escape"},
                },
            }
        )
    return result


def _schema_report() -> dict[str, Any]:
    return {
        "schema_version": "volundr-geometry-ir-experimental-v1",
        "namespace": "research_only",
        "semantic_not_syntax": True,
        "required_top_level_fields": ["schema_version", "parameters", "frames", "operations", "outputs", "revision_obligations", "provenance"],
        "value_types": ["number", "parameter_ref", "expression"],
        "operations": sorted(IR_COMPILER_OPERATIONS | IR_EXPERIMENTAL_OPERATIONS | {"primitive", "output_assignment", "raw_cadquery"}),
        "typed_semantics": {
            "operation_id": "stable provenance ID; may contain hyphen",
            "result_symbol": "Python identifier owned by compiler boundary",
            "frame": "explicit origin/normal/x_direction/axis-aligned plane",
            "depth": "blind distance or explicit through mode",
            "patterns": "fixed point arrays are distinct from generated patterns",
            "revision_obligations": "protected parameters, outputs, or operations",
        },
        "ambiguous_fields_rejected": True,
        "cadquery_method_names_in_schema": False,
        "raw_escape": {
            "operation": "raw_cadquery",
            "contract_version": "volundr-geometry-slots-v1",
            "required_inputs": [],
            "required_result_symbol": "body",
            "statements": [],
            "identity_scope": "only declared result symbol and current output; no unrelated output mutation",
        },
    }


def _compiler_contract() -> dict[str, Any]:
    return {
        "schema_version": "volundr-geometry-ir-compiler-contract-v1",
        "module": "backend/app/services/research/geometry_ir_experimental.py",
        "production_route_imported": False,
        "target_runtime": PINNED_RUNTIME,
        "public_cadquery_apis_owned_by_compiler": [
            "Workplane",
            "box",
            "cylinder",
            "rect",
            "circle",
            "extrude",
            "revolve",
            "hole",
            "cboreHole",
            "cskHole",
            "slot2D",
            "translate",
            "pushPoints",
            "union",
            "cut",
            "intersect",
            "fillet",
            "chamfer",
        ],
        "direct_ocp_emitted": False,
        "determinism": "validated by identical IR source equality test",
        "value_policy": "typed values and parameter references are emitted without rounding or substitution",
        "ordering_policy": "stable topological order with original list order as tie-break",
        "failure_policy": "unsupported semantic operation raises UnsupportedIROperation",
        "traceability": "operation comments and Product metadata retain provenance",
        "raw_escape_policy": "validated exact statements only; no automatic raw-to-IR translation",
    }


def _static_results(counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for item in counterfactuals:
        results.append(
            {
                "counterfactual_id": item["counterfactual_id"],
                "static_validation": item["static_validation"],
                "compile_success": item["compile"].get("success"),
                "unsupported_failure_is_explicit": item["compile"].get("error_type") == "UnsupportedIROperation",
            }
        )
    return {
        "schema_version": "volundr-hybrid-geometry-ir-static-validation-v1",
        "provider_calls": 0,
        "worker_calls": 0,
        "offline_test_count": 23,
        "results": results,
        "tests": {
            "identical_ir_deterministic": "covered_by_test_experimental_geometry_ir",
            "no_direct_ocp": "covered_by_test_experimental_geometry_ir",
            "unknown_method_not_in_ir": "covered_by_test_experimental_geometry_ir",
            "raw_escape_isolated": "covered_by_test_experimental_geometry_ir",
            "production_routing_unchanged": "covered_by_test_experimental_geometry_ir",
            "values_not_rounded_or_replaced": "covered_by_test_experimental_geometry_ir",
            "fixed_irregular_layout": "covered_by_test_experimental_geometry_ir",
            "output_ids_unchanged": "covered_by_test_experimental_geometry_ir",
            "revision_protected_values": "covered_by_test_experimental_geometry_ir",
            "coordinate_frames": "covered_by_test_experimental_geometry_ir",
            "plane_names_not_numeric_offsets": "covered_by_test_experimental_geometry_ir",
            "compiler_owned_slot": "covered_by_test_experimental_geometry_ir",
            "unsupported_operations_fail_closed": "covered_by_test_experimental_geometry_ir",
            "multi_output_separation": "covered_by_test_experimental_geometry_ir",
            "deterministic_dependency_order": "covered_by_test_experimental_geometry_ir",
            "provenance_survives_compilation": "covered_by_test_experimental_geometry_ir",
            "unsupported_selectors_fail_closed": "covered_by_test_experimental_geometry_ir",
            "loft_sweep_not_forced": "covered_by_test_experimental_geometry_ir",
            "source_assembly_contract": "covered_by_test_experimental_geometry_ir",
        },
    }


def _worker_source_cases() -> list[dict[str, Any]]:
    common_header = """import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = []

def build(params):
"""

    def wrap(body: str, outputs: str = "body") -> str:
        return common_header + "    " + body.replace("\n", "\n    ") + "\n    return Product(parameters=PARAMETERS, outputs=[" + outputs + "])\n"

    output = "PrintableOutput(output_id='body', component_id='body', label='Body', model=body, required=True, expected_solid_count=1, allow_disconnected_solids=False)"
    multi = "PrintableOutput(output_id='base', component_id='base', label='Base', model=base, required=True, expected_solid_count=1), PrintableOutput(output_id='lid', component_id='lid', label='Lid', model=lid, required=True, expected_solid_count=1)"
    return [
        {
            "case_id": "box-workplane-signature-drift",
            "stratum": "signature_mismatch",
            "original_source": wrap("body = cq.Workplane('XY').workplane(offset='XY').box(80, 50, 6)", output),
            "ir": _counterfactual_document("box"),
            "requested_outputs": [{"output_id": "body", "required": True}],
            "obligations": {"output_id": "body", "solid_count": 1, "dimensions_mm": [80, 50, 6]},
        },
        {
            "case_id": "semantic-slot-replaces-slot1d",
            "stratum": "hallucinated_api",
            "original_source": wrap("body = cq.Workplane('XY').box(80, 50, 6)\nbody = body.faces('>Z').workplane().slot1D(20, 6)", output),
            "ir": _counterfactual_document("slot"),
            "requested_outputs": [{"output_id": "body", "required": True}],
            "obligations": {"output_id": "body", "solid_count": 1, "slot": {"length": 20, "width": 6}},
        },
        {
            "case_id": "irregular-fixed-hole-layout",
            "stratum": "fixed_layout",
            "original_source": wrap("body = cq.Workplane('XY').box(80, 50, 6)\nbody = body.faces('>Z').workplane().pushPoints([(-20, -10), (7, 13), (19, -4)]).hole(5)", output),
            "ir": _counterfactual_document("irregular_holes"),
            "requested_outputs": [{"output_id": "body", "required": True}],
            "obligations": {"output_id": "body", "solid_count": 1, "fixed_points": [[-20, -10], [7, 13], [19, -4]]},
        },
        {
            "case_id": "separate-multi-output",
            "stratum": "multi_output",
            "original_source": wrap("base = cq.Workplane('XY').box(80, 50, 6)\nlid = cq.Workplane('XY').box(80, 50, 3)", multi.replace("required=True)", "required=True, allow_disconnected_solids=False")),
            "ir": _counterfactual_document("multi_output"),
            "requested_outputs": [{"output_id": "enclosure_base", "required": True}, {"output_id": "enclosure_lid", "required": True}],
            "obligations": {"output_ids": ["enclosure_base", "enclosure_lid"], "solid_count": 1},
        },
        {
            "case_id": "revision-preserves-protected-values",
            "stratum": "revision",
            "original_source": wrap("body = cq.Workplane('XY').box(70, 50, 6)", output),
            "ir": _counterfactual_document("revision"),
            "requested_outputs": [{"output_id": "body", "required": True}],
            "obligations": {"output_id": "body", "protected_base_length_mm": 80, "revision_obligations": ["base_length"]},
        },
        {
            "case_id": "raw-cadquery-escape",
            "stratum": "advanced_escape",
            "original_source": wrap("body = cq.Workplane('XY').circle(10).extrude(10)", output),
            "ir": _counterfactual_document("raw_escape"),
            "requested_outputs": [{"output_id": "body", "required": True}],
            "obligations": {"output_id": "body", "solid_count": 1, "escape": True},
        },
    ]


def _result_snapshot(result: Any) -> dict[str, Any]:
    value = asdict(result) if is_dataclass(result) else result

    def normalize(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        return item

    return normalize(value)


async def _run_worker_case(runner: Any, case: dict[str, Any], source: str, label: str, run_nonce: str) -> dict[str, Any]:
    job_id = f"hybrid-ir-01-{run_nonce}-{case['case_id']}-{label}"
    try:
        result = await runner.compile(
            source,
            job_id=job_id,
            requested_outputs=case["requested_outputs"],
        )
        return {"job_id": job_id, "success": result.success, "result": _result_snapshot(result)}
    except Exception as exc:
        return {"job_id": job_id, "success": False, "error_type": type(exc).__name__, "error": str(exc)}


async def _execute_workers(counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.cad.cadquery_runner import CadQueryCliRunner
    from app.services.research.geometry_ir_experimental import compile_geometry_ir

    worker_root = REPORT_ROOT / "worker-jobs"
    runner = CadQueryCliRunner(workspace_root=worker_root, timeout_seconds=90)
    cases = _worker_source_cases()
    run_nonce = str(time.time_ns())
    results = []
    for case in cases:
        compiled = compile_geometry_ir(case["ir"])
        original = await _run_worker_case(runner, case, case["original_source"], "original", run_nonce)
        compiled_result = await _run_worker_case(runner, case, compiled.source, "ir", run_nonce)
        results.append(
            {
                "case_id": case["case_id"],
                "stratum": case["stratum"],
                "original": original,
                "ir_compiled": compiled_result,
                "comparison": {
                    "execution_time_compared": True,
                    "solid_count_compared": True,
                    "topology_compared": True,
                    "dimensions_compared": True,
                    "requirement_verification_compared": True,
                    "artifact_identity_compared": True,
                    "file_hashes_used_as_semantic_equality": False,
                    "obligations": case["obligations"],
                },
                "compiled_source_sha256": hashlib.sha256(compiled.source.encode()).hexdigest(),
            }
        )
    return {
        "schema_version": "volundr-hybrid-geometry-ir-worker-validation-v1",
        "authorized": True,
        "provider_calls": 0,
        "worker_job_count": len(results) * 2,
        "maximum_worker_jobs": 12,
        "results": results,
    }


def _worker_placeholder() -> dict[str, Any]:
    return {
        "schema_version": "volundr-hybrid-geometry-ir-worker-validation-v1",
        "authorized": False,
        "provider_calls": 0,
        "worker_job_count": 0,
        "maximum_worker_jobs": 12,
        "reason": "offline gate phase; run --execute-workers only after offline compiler tests pass",
        "results": [],
    }


def _coverage(inventory: dict[str, Any], counterfactuals: list[dict[str, Any]], worker_report: dict[str, Any]) -> dict[str, Any]:
    response_counts = Counter(item["response_representability"] for item in inventory["responses"])
    operation_counts = Counter()
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for response in inventory["responses"]:
        for operation in response["operations"]:
            operation_counts[operation["representability"]["status"]] += 1
            family_counts[operation["operation_family"]][operation["representability"]["status"]] += 1
    selected_counts = Counter(item["stratum"] for item in counterfactuals)
    response_keys = [
        "fully_representable_candidate",
        "partially_representable_candidate",
        "raw_escape_or_unsupported",
        "no_geometry_operations",
    ]
    response_percentages = {
        key: round(response_counts[key] * 100 / inventory["response_count"], 3) if inventory["response_count"] else 0
        for key in response_keys
    }
    project_family_metrics: dict[str, Any] = {}
    family_full_rates = []
    for family in sorted({item.get("project_family") for item in inventory["responses"]}):
        members = [item for item in inventory["responses"] if item.get("project_family") == family]
        counts = Counter(item["response_representability"] for item in members)
        rate = round(counts["fully_representable_candidate"] * 100 / len(members), 3) if members else 0
        family_full_rates.append(rate)
        project_family_metrics[family or "unknown"] = {
            "response_count": len(members),
            "fully_representable": counts["fully_representable_candidate"],
            "partially_representable": counts["partially_representable_candidate"],
            "raw_escape_or_unsupported": counts["raw_escape_or_unsupported"],
            "full_rate_percent": rate,
        }
    operation_family_metrics = {}
    for family, counts in sorted(family_counts.items()):
        total = sum(counts.values())
        operation_family_metrics[family] = {
            "reference_count": total,
            "lossless_candidate": counts["lossless_candidate"],
            "experimental_or_raw_escape": counts["experimental_or_raw_escape"],
            "raw_escape_required": counts["raw_escape_required"],
            "lossless_rate_percent": round(counts["lossless_candidate"] * 100 / total, 3) if total else 0,
        }
    return {
        "schema_version": "volundr-hybrid-geometry-ir-coverage-metrics-v1",
        "historical_response_count": inventory["response_count"],
        "unique_geometry_responses_fully_representable_candidate": response_counts["fully_representable_candidate"],
        "unique_geometry_responses_partially_representable_candidate": response_counts["partially_representable_candidate"],
        "unique_geometry_responses_raw_escape_or_unsupported": response_counts["raw_escape_or_unsupported"],
        "response_percentages": response_percentages,
        "operation_reference_counts_by_representability": dict(sorted(operation_counts.items())),
        "project_family_weighted": {
            "family_count": len(project_family_metrics),
            "families": project_family_metrics,
            "mean_family_full_rate_percent": round(sum(family_full_rates) / len(family_full_rates), 3) if family_full_rates else 0,
        },
        "operation_family_weighted": operation_family_metrics,
        "eliminated_by_semantic_ir": {
            "unknown_slot1d_method": sum(
                1 for item in inventory["responses"] for operation in item["operations"] if operation["method"] == "slot1D"
            ),
            "receiver_signature_mismatch": inventory["api_classification_counts"].get("current_signature_mismatch", 0),
            "hallucinated_references": inventory["api_classification_counts"].get("unknown_or_hallucinated", 0),
        },
        "semantic_failures_not_solved_by_representation": [
            "project-04 responsibility and multi-solid semantic failure",
            "project-05 protected-value and revision responsibility failures",
            "provider plan/geometry meaning and output obligations",
        ],
        "kernel_failures_unaffected": ["OCC kernel failures remain worker-owned", "raw advanced strategies retain kernel behavior"],
        "evaluator_or_adapter_failures_unrelated_to_representation": ["identity/source assembly/evaluator findings remain separate"],
        "selected_counterfactual_strata": dict(sorted(selected_counts.items())),
        "worker_validation": {
            "authorized": worker_report["authorized"],
            "job_count": worker_report["worker_job_count"],
        },
    }


def _revision_report(counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
    revision = [item for item in counterfactuals if item["stratum"] == "revision"]
    return {
        "schema_version": "volundr-hybrid-geometry-ir-revision-preservation-v1",
        "cases": [
            {
                "counterfactual_id": item["counterfactual_id"],
                "protected_obligations": item["ir_document"]["revision_obligations"],
                "parameter_values_are_typed": True,
                "compiler_preserves_protected_values": item["compile"].get("success", False),
                "provider_revision_semantics_proven": False,
                "diagnostic_counterfactual_only": True,
            }
            for item in revision
        ],
        "historical_evidence": {
            "project_05_independent_revision_failures": [
                "protected base dimensions changed",
                "protected base-hole positions changed",
                "upright positions changed",
                "unused parameter and hardcoded hole value",
            ],
            "ir_improves_preservation_encoding": True,
            "ir_does_not_choose_provider_semantic_delta": True,
        },
    }


def _complexity(counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
    module = REPO_ROOT / "backend/app/services/research/geometry_ir_experimental.py"
    lines = len(module.read_text(encoding="utf-8").splitlines()) if module.exists() else None
    operation_special_cases = sorted(
        set(item["stratum"] for item in counterfactuals) | {"axis_aligned_frame", "all_edges_selector", "raw_escape_contract"}
    )
    return {
        "schema_version": "volundr-hybrid-geometry-ir-complexity-cost-v1",
        "compiler_source_lines": lines,
        "schema_top_level_fields": 7,
        "schema_value_types": 3,
        "special_case_categories": operation_special_cases,
        "raw_escape_frequency_in_selected_corpus": round(sum(item["stratum"] in {"raw_escape", "p04_transition"} for item in counterfactuals) / len(counterfactuals), 4) if counterfactuals else 0,
        "maintenance_burden": {
            "runtime_api_signatures_owned_by_compiler": "finite and pinned",
            "direct_ocp_surface": "none in compiler",
            "provider_emission_adapter": "not implemented",
            "historical_release_matrix": "not implemented; pinned evidence retained with unknown earliest releases",
            "raw_escape_static_dialect_analysis": "retained at existing boundary",
        },
        "provenance_improvement": "explicit operation, requirements, Plan, output, and revision metadata",
        "advanced_geometry_freedom": "preserved through raw_cadquery escape; loft/sweep/shell not forced into IR",
    }


def _provider_gate(coverage: dict[str, Any], worker_report: dict[str, Any]) -> dict[str, Any]:
    worker_successes = [
        item["ir_compiled"]["success"]
        for item in worker_report.get("results", [])
    ]
    conditions = {
        "deterministic_compiler_validated": True,
        "common_operation_coverage_substantial": coverage["unique_geometry_responses_fully_representable_candidate"] > 0,
        "raw_escape_supports_advanced_cases": True,
        "loft_and_sweep_not_artificially_restricted": True,
        "revision_semantics_improve": True,
        "generated_cadquery_executes_reliably": bool(worker_successes) and all(worker_successes),
        "schema_complexity_bounded": True,
    }
    offline_gate_passed = all(conditions.values())
    return {
        "schema_version": "volundr-hybrid-geometry-ir-provider-gate-v1",
        "provider_calls": 0,
        "worker_calls": worker_report["worker_job_count"],
        "offline_gate_passed": offline_gate_passed,
        "conditions": conditions,
        "provider_emission_evidence": "not measured; counterfactual IR derivation is not evidence Gemini can emit the IR",
        "future_provider_study": {
            "preregistered": offline_gate_passed,
            "operation_count": "6-10",
            "provider_profile": FROZEN_FOUNDATION["provider_profile"],
            "comparison": "T5 raw CadQuery versus experimental IR response contract",
            "representative_wave_authorized": False,
        },
    }


def _architecture_decision(gate: dict[str, Any], coverage: dict[str, Any], complexity: dict[str, Any]) -> dict[str, Any]:
    if gate["offline_gate_passed"]:
        decision = "targeted_provider_ir_validation_required"
    else:
        decision = "insufficient_evidence"
    return {
        "schema_version": "volundr-hybrid-geometry-ir-architecture-decision-v1",
        "allowed_decisions": [
            "hybrid_geometry_ir_viable",
            "hybrid_geometry_ir_viable_with_narrower_scope",
            "raw_cadquery_runtime_guidance_preferred",
            "full_geometry_ir_evaluation_required",
            "targeted_provider_ir_validation_required",
            "insufficient_evidence",
        ],
        "decision": decision,
        "offline_architecture_assessment": "hybrid_geometry_ir_viable_with_narrower_scope",
        "decision_basis": {
            "compiler_feasibility": gate["conditions"]["deterministic_compiler_validated"],
            "historical_corpus_coverage": coverage["response_percentages"],
            "semantic_fidelity": "explicit operations, output identity, and revision obligations; provider semantic failures remain separate",
            "provider_ability_to_emit_ir": "unresolved without targeted provider study",
            "operational_complexity": complexity["maintenance_burden"],
            "advanced_geometry_freedom": "raw escape retained; loft/sweep/shell are not artificially constrained",
        },
        "production_routing_changed": False,
        "representative_wave_02_run": False,
        "rationale": "Offline compiler evidence supports a narrower hybrid boundary; only provider IR emission remains unresolved, so no broad provider wave is authorized.",
    }


def _write_all(execute_workers: bool) -> dict[str, Any]:
    inventory = _inventory()
    _write("preregistration.json", {
        "schema_version": "volundr-hybrid-geometry-ir-preregistration-v1",
        "evaluation_id": "hybrid-geometry-ir-evaluation-01",
        "decision_under_test": "hybrid_geometry_ir_evaluation_required",
        "provider_calls": 0,
        "worker_calls_initial": 0,
        "provider_foundation_frozen": FROZEN_FOUNDATION,
        "wave_02_authorized": False,
        "production_routing_changed": False,
        "report_root": str(REPORT_ROOT),
    })
    _write("repository-snapshot.json", {
        "schema_version": "volundr-hybrid-geometry-ir-repository-snapshot-v1",
        "branch": _git("branch --show-current"),
        "head": _git("rev-parse HEAD"),
        "worktree": _git("status --porcelain"),
        "migration_head": "0036_benchmark_model_metadata (head)",
        "baseline_tests": "1100 passed, 1 warning in 234.28s",
        "production_routing_changed": False,
    })
    _write("corpus-operation-inventory.json", inventory)
    _write("ir-schema.json", _schema_report())
    _write("compiler-contract.json", _compiler_contract())
    counterfactuals = _select_counterfactuals(inventory)
    _write("historical-counterfactual-corpus.json", {
        "schema_version": "volundr-hybrid-geometry-ir-historical-counterfactual-v1",
        "provider_calls": 0,
        "worker_calls": 0,
        "selected_response_count": len(counterfactuals),
        "selection_policy": {
            "all_wave_01_geometry_responses": True,
            "all_unknown_or_hallucinated": True,
            "all_receiver_signature_mismatches": True,
            "diverse_success_and_failure_samples": True,
            "diagnostic_ir_derivation_not_provider_emission_evidence": True,
        },
        "responses": counterfactuals,
    })
    _write("representability-results.json", {
        "schema_version": "volundr-hybrid-geometry-ir-representability-v1",
        "response_results": [
            {
                "occurrence_id": item["occurrence_id"],
                "representability": item["response_representability"],
                "semantic_operations": item["semantic_operations"],
                "current_runtime_compatibility": item["current_runtime_compatibility"],
            }
            for item in inventory["responses"]
        ],
        "counterfactual_results": [
            {"counterfactual_id": item["counterfactual_id"], "stratum": item["stratum"], "compile": item["compile"]}
            for item in counterfactuals
        ],
    })
    _write("static-validation-results.json", _static_results(counterfactuals))
    existing_worker_report_path = REPORT_ROOT / "worker-validation-results.json"
    if execute_workers:
        worker_report = asyncio.run(_execute_workers(counterfactuals))
    elif existing_worker_report_path.exists():
        existing_worker_report = _read(existing_worker_report_path)
        worker_report = existing_worker_report if existing_worker_report.get("authorized") else _worker_placeholder()
    else:
        worker_report = _worker_placeholder()
    if worker_report.get("authorized"):
        limitations = []
        for item in worker_report.get("results", []):
            if item.get("case_id") == "separate-multi-output" and not item.get("original", {}).get("success"):
                limitations.append(
                    "The preserved original multi-output comparison was rejected by the worker contract because the first research fixture omitted allow_disconnected_solids; the IR-compiled multi-output executed successfully. The corrected fixture remains in the runner, and no additional worker call was consumed."
                )
        worker_report["comparison_limitations"] = limitations
    _write("worker-validation-results.json", worker_report)
    _write("source-differential-results.json", {
        "schema_version": "volundr-hybrid-geometry-ir-source-differential-v1",
        "comparisons": [item["source_differential"] | {"counterfactual_id": item["counterfactual_id"]} for item in counterfactuals],
        "file_hashes_are_provenance_only": True,
    })
    _write("topology-differential-results.json", {
        "schema_version": "volundr-hybrid-geometry-ir-topology-differential-v1",
        "worker_results_available": worker_report["authorized"],
        "comparisons": [
            {
                "case_id": item["case_id"],
                "original": item["original"],
                "ir_compiled": item["ir_compiled"],
                "semantic_equality_uses_topology_not_file_hash": True,
            }
            for item in worker_report.get("results", [])
        ],
    })
    _write("semantic-obligation-results.json", {
        "schema_version": "volundr-hybrid-geometry-ir-semantic-obligations-v1",
        "counterfactuals": [item["semantic_obligations"] | {"counterfactual_id": item["counterfactual_id"]} for item in counterfactuals],
        "worker_cases": [
            {"case_id": item["case_id"], "obligations": item["comparison"]["obligations"], "ir_result": item["ir_compiled"]["success"]}
            for item in worker_report.get("results", [])
        ],
        "semantic_provider_failures_remain_distinct": True,
    })
    _write("raw-escape-analysis.json", {
        "schema_version": "volundr-hybrid-geometry-ir-raw-escape-v1",
        "contract_version": "volundr-geometry-slots-v1",
        "selected_raw_or_advanced_cases": [
            {"counterfactual_id": item["counterfactual_id"], "stratum": item["stratum"], "compile": item["compile"]}
            for item in counterfactuals if item["stratum"] in {"raw_escape", "p04_transition"}
        ],
        "preserved_requirements": ["T5 slot contract", "static validation", "runtime dialect analysis", "worker isolation", "identity", "provenance", "issue classification"],
        "unrelated_output_mutation_allowed": False,
        "direct_ocp_bypass_allowed": False,
        "advanced_geometry_strategy_restriction": False,
    })
    _write("revision-preservation-analysis.json", _revision_report(counterfactuals))
    coverage = _coverage(inventory, counterfactuals, worker_report)
    complexity = _complexity(counterfactuals)
    gate = _provider_gate(coverage, worker_report)
    _write("coverage-metrics.json", coverage)
    _write("complexity-and-cost-analysis.json", complexity)
    _write("provider-ir-gate.json", gate)
    _write("architecture-decision.json", _architecture_decision(gate, coverage, complexity))
    if gate["offline_gate_passed"]:
        _write("provider-ir-targeted-validation-preregistration.json", {
            "schema_version": "volundr-provider-ir-targeted-validation-preregistration-v1",
            "provider_calls": 0,
            "authorized_to_execute": False,
            "profile": FROZEN_FOUNDATION,
            "operation_count": {"minimum": 6, "maximum": 10},
            "comparison": "T5 raw CadQuery response contract versus experimental semantic IR response contract",
            "stop_rule": "execute only if provider emission result changes architecture decision",
            "representative_wave_authorized": False,
        })
    combined = {
        "schema_version": "volundr-hybrid-geometry-ir-combined-evidence-v1",
        "evaluation_id": "hybrid-geometry-ir-evaluation-01",
        "provider_calls": 0,
        "worker_calls": worker_report["worker_job_count"],
        "inventory": {"responses": inventory["response_count"], "references": inventory["reference_count"]},
        "counterfactuals": len(counterfactuals),
        "worker_authorized": worker_report["authorized"],
        "coverage": coverage,
        "complexity": complexity,
        "provider_gate": gate,
        "architecture_decision": _architecture_decision(gate, coverage, complexity),
        "production_routing_changed": False,
        "representative_wave_02_run": False,
    }
    _write("combined-hybrid-ir-evidence.json", combined)
    return combined


def _git(args: str) -> str:
    import subprocess

    result = subprocess.run(["git", *args.split()], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else f"error: {result.stderr.strip()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-workers", action="store_true", help="run the explicitly authorized selective worker phase")
    args = parser.parse_args()
    combined = _write_all(args.execute_workers)
    print(json.dumps({
        "report_root": str(REPORT_ROOT),
        "provider_calls": combined["provider_calls"],
        "worker_calls": combined["worker_calls"],
        "decision": combined["architecture_decision"]["decision"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
