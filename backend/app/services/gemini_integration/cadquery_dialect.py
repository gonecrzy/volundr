"""Offline CadQuery/OCP dialect characterization for captured geometry responses.

This module deliberately treats provider geometry statements as evidence.  It
never rewrites them, executes them through a repair pass, or substitutes a
different CadQuery expression before classifying the runtime compatibility.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from typing import Any, Iterable


API_REFERENCE_CLASSIFICATIONS = frozenset(
    {
        "current_supported",
        "current_receiver_type_mismatch",
        "current_argument_type_mismatch",
        "current_signature_mismatch",
        "current_return_chain_mismatch",
        "historical_supported",
        "historical_deprecated",
        "historical_removed",
        "direct_ocp_version_sensitive",
        "unknown_or_hallucinated",
        "ambiguous_static_type",
    }
)
CADQUERY_ISSUE_CLASSES = frozenset(
    {
        "cadquery_dialect_mismatch",
        "removed_cadquery_api",
        "obsolete_cadquery_signature",
        "direct_ocp_version_mismatch",
        "hallucinated_cadquery_api",
        "cadquery_kernel_failure",
        "semantic_geometry_failure",
    }
)


def _safe_signature(value: Any) -> str | None:
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return None


def _runtime() -> dict[str, Any]:
    try:
        cadquery = importlib.import_module("cadquery")
    except ImportError:
        cadquery = None
    try:
        ocp = importlib.import_module("OCP")
    except ImportError:
        ocp = None

    exact: dict[tuple[str, ...], tuple[Any, str | None]] = {}
    method_signatures: dict[str, list[str]] = {}
    method_parameters: dict[str, list[tuple[set[str], bool]]] = {}
    if cadquery is not None:
        for name in dir(cadquery):
            if name.startswith("_"):
                continue
            value = getattr(cadquery, name, None)
            if not isinstance(value, type):
                continue
            exact[("cq", name)] = (value, _safe_signature(value))
            for method_name in dir(value):
                if method_name.startswith("_"):
                    continue
                method = getattr(value, method_name, None)
                if not callable(method):
                    continue
                signature = _safe_signature(method)
                if signature is None:
                    continue
                exact[("cq", name, method_name)] = (method, signature)
                method_signatures.setdefault(method_name, []).append(signature)
                method_parameters.setdefault(method_name, []).append(_signature_parameter_names(method))

    return {
        "cadquery": cadquery,
        "ocp": ocp,
        "cadquery_version": getattr(cadquery, "__version__", None),
        "ocp_version": getattr(ocp, "__version__", None),
        "exact": exact,
        "method_signatures": method_signatures,
        "method_parameters": method_parameters,
    }


def _attribute_chain(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        parent = _attribute_chain(node.value)
        return [*parent, node.attr] if parent else None
    if isinstance(node, ast.Call):
        return _attribute_chain(node.func)
    return None


def _reference_chain(node: ast.Call, imported_aliases: dict[str, tuple[str, ...]]) -> tuple[list[str], str | None]:
    chain = _attribute_chain(node.func) or []
    if chain and chain[0] in imported_aliases:
        chain = [*imported_aliases[chain[0]], *chain[1:]]
    root = chain[0] if chain else None
    return chain, root


def _resolve_exact(chain: list[str], runtime: dict[str, Any]) -> tuple[Any, str | None] | None:
    if not chain:
        return None
    if chain[0] == "cq":
        return runtime["exact"].get(tuple(chain))
    if chain[0] != "OCP":
        return None
    ocp = runtime.get("ocp")
    if ocp is None:
        return None
    value: Any = ocp
    for part in chain[1:]:
        try:
            value = getattr(value, part)
        except AttributeError:
            value = None
            break
    if value is not None:
        return value, _safe_signature(value)
    # OCP exposes many classes through submodules rather than the package root.
    for module_end in range(len(chain) - 1, 1, -1):
        try:
            module = importlib.import_module(".".join(chain[:module_end]))
            value = module
            for part in chain[module_end:]:
                value = getattr(value, part)
            return value, _safe_signature(value)
        except (AttributeError, ImportError):
            continue
    return None


def _runtime_candidates(chain: list[str], runtime: dict[str, Any]) -> list[str]:
    exact = _resolve_exact(chain, runtime)
    if exact and exact[1]:
        return [exact[1]]
    method = chain[-1] if chain else ""
    return list(dict.fromkeys(runtime["method_signatures"].get(method, [])))


def _signature_parameter_names(value: Any) -> tuple[set[str], bool]:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return set(), False
    names: set[str] = set()
    arbitrary = False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            arbitrary = True
        elif parameter.name != "self":
            names.add(parameter.name)
    return names, arbitrary


def _classify_reference(
    chain: list[str],
    keywords: list[str],
    runtime: dict[str, Any],
) -> tuple[str, str | None, list[str], bool]:
    root = chain[0] if chain else ""
    if root == "OCP":
        resolved = _resolve_exact(chain, runtime)
        signatures = [resolved[1]] if resolved and resolved[1] else []
        if resolved and resolved[0] is not None:
            names, arbitrary = _signature_parameter_names(resolved[0])
            if not arbitrary and any(keyword not in names for keyword in keywords):
                return "direct_ocp_version_sensitive", "direct_ocp_version_mismatch", signatures, True
            return "direct_ocp_version_sensitive", None, signatures, True
        return "direct_ocp_version_sensitive", "direct_ocp_version_mismatch", signatures, False

    signatures = _runtime_candidates(chain, runtime)
    resolved = _resolve_exact(chain, runtime)
    if not signatures:
        return "unknown_or_hallucinated", "hallucinated_cadquery_api", [], False
    if resolved:
        names, arbitrary = _signature_parameter_names(resolved[0])
        if not arbitrary and any(keyword not in names for keyword in keywords):
            return "current_signature_mismatch", "obsolete_cadquery_signature", signatures, True
    elif keywords:
        parameter_sets = runtime["method_parameters"].get(chain[-1], [])
        if parameter_sets and not any(
            arbitrary or all(keyword in names for keyword in keywords)
            for names, arbitrary in parameter_sets
        ):
            return "current_signature_mismatch", "obsolete_cadquery_signature", signatures, True
    return "current_supported", None, signatures, True


def _release_compatibility(classification: str, runtime: dict[str, Any], *, root: str | None = None) -> dict[str, Any]:
    pinned = (
        runtime.get("ocp_version") if root == "OCP" else runtime.get("cadquery_version")
    ) or "unknown"
    if classification in {"current_supported", "direct_ocp_version_sensitive"}:
        earliest = pinned
        first_rejects = None
    else:
        earliest = None
        first_rejects = pinned
    return {
        "earliest_release_accepts": earliest,
        "first_release_rejects": first_rejects,
        "historical_probe_performed": False,
        "evidence_basis": "pinned_runtime_introspection_only",
    }


def _issue_class_for(classification: str, issue_class: str | None) -> str | None:
    if issue_class in CADQUERY_ISSUE_CLASSES:
        return issue_class
    if classification not in {"current_supported", "direct_ocp_version_sensitive"}:
        return "cadquery_dialect_mismatch"
    return None


def _import_references(tree: ast.AST, imported_aliases: dict[str, tuple[str, ...]], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    new_aliases: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cadquery":
                    local = alias.asname or alias.name.split(".")[-1]
                    imported_aliases[local] = ("cq",)
                    new_aliases.append((local, ("cq",)))
                if alias.name == "OCP" or alias.name.startswith("OCP."):
                    local = alias.asname or alias.name.split(".")[-1]
                    chain = tuple(["OCP", *alias.name.split(".")[1:]])
                    imported_aliases[local] = chain
                    new_aliases.append((local, chain))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "cadquery":
                for alias in node.names:
                    local = alias.asname or alias.name
                    chain = ("cq", alias.name)
                    imported_aliases[local] = chain
                    new_aliases.append((local, chain))
            elif node.module == "OCP" or node.module.startswith("OCP."):
                for alias in node.names:
                    local = alias.asname or alias.name
                    chain = tuple(["OCP", *node.module.split(".")[1:], alias.name])
                    imported_aliases[local] = chain
                    new_aliases.append((local, chain))

    for local, chain in new_aliases:
        if chain[0] not in {"cq", "OCP"}:
            continue
        classification, issue_class, signatures, resolved = _classify_reference(chain, [], runtime)
        if chain[0] == "OCP":
            classification = "direct_ocp_version_sensitive"
        references.append({
            "kind": "import_symbol",
            "root": chain[0],
            "symbol": ".".join(chain),
            "method": None,
            "local_name": local,
            "keywords": [],
            "positional_argument_count": 0,
            "runtime_signature": signatures[0] if signatures else None,
            "runtime_signatures": signatures,
            "runtime_resolved": resolved,
            "classification": classification,
            "issue_class": _issue_class_for(classification, issue_class),
            "release_compatibility": _release_compatibility(classification, runtime, root=chain[0]),
            "statement": None,
        })
    return references


def characterize_geometry_statements(
    statements: Iterable[str],
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Characterize exact provider statements against the installed worker runtime."""

    exact_statements = [str(statement) for statement in statements]
    runtime = _runtime()
    references: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    imported_aliases: dict[str, tuple[str, ...]] = {}
    for statement_index, statement in enumerate(exact_statements):
        try:
            tree = ast.parse(statement, mode="exec")
        except SyntaxError as exc:
            parse_errors.append({
                "statement_index": statement_index,
                "statement": statement,
                "error": exc.msg,
                "issue_class": "cadquery_dialect_mismatch",
            })
            continue
        references.extend(_import_references(tree, imported_aliases, runtime))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_keywords = [keyword.arg for keyword in node.keywords if keyword.arg is not None]
            chain, root = _reference_chain(node, imported_aliases)
            if not chain or root not in {"cq", "OCP"}:
                # Calls on a prior CadQuery value (body.faces, solid.cut,
                # etc.) still need to be checked against the worker method set.
                raw_chain = _attribute_chain(node.func) or []
                if len(raw_chain) < 2:
                    continue
                chain = raw_chain
                root = chain[0]
                if root in imported_aliases:
                    chain = [*imported_aliases[root], *chain[1:]]
                    root = chain[0]
                if root in {"cq", "OCP"}:
                    pass
                elif chain[-1] not in runtime["method_signatures"]:
                    # No CadQuery receiver can be inferred and the method is
                    # absent from every inspected CadQuery class.
                    classification = "unknown_or_hallucinated"
                    issue_class = "hallucinated_cadquery_api"
                    signatures: list[str] = []
                    resolved = False
                else:
                    classification, issue_class, signatures, resolved = _classify_reference(chain, call_keywords, runtime)
            else:
                classification, issue_class, signatures, resolved = _classify_reference(
                    chain,
                    call_keywords,
                    runtime,
                )
            method = chain[-1] if len(chain) >= 2 else None
            symbol = ".".join(chain[:-1]) if method else ".".join(chain)
            if root in {"cq", "OCP"} and len(chain) == 2:
                method = None
                symbol = ".".join(chain)
            references.append({
                "kind": "call",
                "root": root,
                "symbol": symbol,
                "method": method,
                "keywords": call_keywords,
                "positional_argument_count": len(node.args),
                "runtime_signature": signatures[0] if signatures else None,
                "runtime_signatures": signatures,
                "runtime_resolved": resolved,
                "classification": classification,
                "issue_class": _issue_class_for(classification, issue_class),
                "release_compatibility": _release_compatibility(classification, runtime, root=root),
                "statement_index": statement_index,
                "statement": statement,
            })

    issue_classes = sorted({
        item["issue_class"]
        for item in [*references, *parse_errors]
        if item.get("issue_class") in CADQUERY_ISSUE_CLASSES
    })
    classifications = sorted({item["classification"] for item in references})
    return {
        "project_id": project_id,
        "statements": exact_statements,
        "statements_modified": False,
        "references": references,
        "symbols": sorted({str(item.get("symbol")) for item in references if item.get("symbol")}),
        "methods": sorted({str(item.get("method")) for item in references if item.get("method")}),
        "keywords": sorted({keyword for item in references for keyword in item.get("keywords", [])}),
        "signatures": [
            {
                "symbol": item.get("symbol"),
                "method": item.get("method"),
                "observed_keyword_names": item.get("keywords", []),
                "observed_positional_argument_count": item.get("positional_argument_count", 0),
                "runtime_signature": item.get("runtime_signature"),
            }
            for item in references if item.get("kind") == "call"
        ],
        "classifications": classifications,
        "issue_classes": issue_classes,
        "parse_errors": parse_errors,
        "pinned_runtime": {
            "cadquery_version": runtime.get("cadquery_version"),
            "ocp_version": runtime.get("ocp_version"),
            "runtime_probe": "introspection_without_provider_statement_execution",
        },
    }


def _boundary_name(boundary: dict[str, Any]) -> str:
    return str(boundary.get("boundary") or "")


def diagnose_wave_geometry_compatibility(evidence_store: Any) -> dict[str, Any]:
    """Diagnose every captured raw geometry response in a wave offline."""

    runtime = _runtime()
    boundaries = list(evidence_store.boundaries())
    by_project: dict[str, list[dict[str, Any]]] = {}
    for boundary in boundaries:
        by_project.setdefault(str(boundary.get("project_id") or ""), []).append(boundary)
    projects: list[dict[str, Any]] = []
    for project_id in sorted(by_project):
        project_boundaries = by_project[project_id]
        raw_responses: list[dict[str, Any]] = []
        all_references: list[dict[str, Any]] = []
        all_issue_classes: set[str] = set()
        for boundary in project_boundaries:
            if _boundary_name(boundary) != "provider_geometry":
                continue
            output = boundary.get("output") or {}
            raw_text = str(output.get("text") or "")
            slots: list[dict[str, Any]] = []
            try:
                parsed = json.loads(raw_text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict) and isinstance(parsed.get("slots"), list):
                for slot in parsed["slots"]:
                    if not isinstance(slot, dict):
                        continue
                    exact_statements = [str(item) for item in slot.get("statements", []) or []]
                    characterization = characterize_geometry_statements(exact_statements, project_id=project_id)
                    slots.append({
                        "slot_id": slot.get("slot_id"),
                        "result_symbol": slot.get("result_symbol"),
                        "statements": exact_statements,
                        "characterization": characterization,
                    })
                    all_references.extend(characterization["references"])
                    all_issue_classes.update(characterization["issue_classes"])
            else:
                characterization = characterize_geometry_statements([raw_text], project_id=project_id)
                slots.append({"slot_id": None, "result_symbol": None, "statements": [raw_text], "characterization": characterization})
                all_references.extend(characterization["references"])
                all_issue_classes.update(characterization["issue_classes"])
            raw_responses.append({
                "boundary_id": boundary.get("boundary_id"),
                "attempt_ids": list(output.get("attempt_ids", []) or []),
                "text": raw_text,
                "slots": slots,
                "statements": [statement for slot in slots for statement in slot["statements"]],
                "statements_modified": False,
            })

        worker = next((item for item in project_boundaries if _boundary_name(item) in {"worker", "worker_runtime"}), None)
        worker_output = (worker or {}).get("output") or {}
        if all_issue_classes:
            primary_issue_class = next(
                (item for item in (
                    "hallucinated_cadquery_api",
                    "obsolete_cadquery_signature",
                    "removed_cadquery_api",
                    "direct_ocp_version_mismatch",
                    "cadquery_dialect_mismatch",
                ) if item in all_issue_classes),
                "cadquery_dialect_mismatch",
            )
        elif worker_output and worker_output.get("success") is False:
            primary_issue_class = (
                None
                if str(worker_output.get("failure_class") or "") == "timeout"
                else "semantic_geometry_failure"
            )
        else:
            primary_issue_class = None
        projects.append({
            "project_id": project_id,
            "raw_provider_responses": raw_responses,
            "statements_modified": False,
            "references": all_references,
            "issue_classes": sorted({*all_issue_classes, *({primary_issue_class} if primary_issue_class else set())}),
            "primary_issue_class": primary_issue_class,
            "worker_execution": {
                "boundary_id": (worker or {}).get("boundary_id"),
                "success": worker_output.get("success"),
                "failure_class": worker_output.get("failure_class"),
                "error_message": worker_output.get("error_message"),
                "execution_source": "pinned_worker_runtime" if worker else None,
                "timeout_requires_runtime_compatibility_audit": bool(
                    worker_output and str(worker_output.get("failure_class") or "") == "timeout"
                ),
            },
            "execution_policy": {
                "raw_statements_executed": False,
                "reason": "captured statements are context-dependent geometry slots; existing worker evidence is retained separately",
            },
        })
    return {
        "schema_version": "volundr-cadquery-dialect-diagnosis-v1",
        "diagnosis_mode": "offline_exact_provider_statement_characterization",
        "statement_rewriting": False,
        "api_reference_classification_taxonomy": sorted(API_REFERENCE_CLASSIFICATIONS),
        "issue_class_taxonomy": sorted(CADQUERY_ISSUE_CLASSES),
        "pinned_worker_runtime": {
            "cadquery_version": runtime.get("cadquery_version"),
            "ocp_version": runtime.get("ocp_version"),
            "runtime_probe": "the same backend worker environment used for offline analysis",
        },
        "projects": projects,
        "issue_classes": sorted({item for project in projects for item in project["issue_classes"]}),
        "runtime": {
            "cadquery_version": runtime.get("cadquery_version"),
            "ocp_version": runtime.get("ocp_version"),
        },
    }


__all__ = [
    "API_REFERENCE_CLASSIFICATIONS",
    "CADQUERY_ISSUE_CLASSES",
    "analyze_geometry_statements",
    "characterize_geometry_statements",
    "diagnose_wave_geometry_compatibility",
]


# Static type information is intentionally conservative.  It describes the
# public CadQuery return contracts needed to validate a generated call chain;
# it does not execute provider code or infer semantic geometry from names.
_RETURN_TYPES = {
    ("Workplane", "workplane"): "Workplane",
    ("Workplane", "box"): "Workplane",
    ("Workplane", "rect"): "Workplane",
    ("Workplane", "circle"): "Workplane",
    ("Workplane", "wire"): "Workplane",
    ("Workplane", "val"): "Shape",
    ("Workplane", "faces"): "Workplane",
    ("Workplane", "edges"): "Workplane",
    ("Workplane", "vertices"): "Workplane",
    ("Workplane", "pushPoints"): "Workplane",
    ("Workplane", "center"): "Workplane",
    ("Workplane", "polyline"): "Workplane",
    ("Workplane", "close"): "Workplane",
    ("Workplane", "extrude"): "Workplane",
    ("Workplane", "translate"): "Workplane",
    ("Workplane", "union"): "Workplane",
    ("Workplane", "cut"): "Workplane",
    ("Workplane", "cutBlind"): "Workplane",
    ("Workplane", "hole"): "Workplane",
    ("Workplane", "fillet"): "Workplane",
    ("Workplane", "chamfer"): "Workplane",
    ("Workplane", "shell"): "Workplane",
    ("Workplane", "loft"): "Workplane",
    ("Solid", "makeBox"): "Solid",
    ("Solid", "makeLoft"): "Solid",
    ("Solid", "cut"): "Shape",
    ("Solid", "fuse"): "Shape",
    ("Shape", "cut"): "Shape",
    ("Shape", "fuse"): "Shape",
}
_PARAMETER_TYPE_OVERRIDES = {
    ("Workplane", "workplane", "offset"): "number",
    ("Workplane", "workplane", "invert"): "bool",
    ("Workplane", "workplane", "centerOption"): "str",
    ("Workplane", "workplane", "origin"): "tuple_or_vector",
    ("Workplane", "box", "length"): "number",
    ("Workplane", "box", "width"): "number",
    ("Workplane", "box", "height"): "number",
    ("Workplane", "box", "centered"): "bool_or_tuple",
    ("Workplane", "box", "combine"): "bool_or_str",
    ("Workplane", "box", "clean"): "bool",
    ("Workplane", "rect", "xLen"): "number",
    ("Workplane", "rect", "yLen"): "number",
    ("Workplane", "rect", "centered"): "bool_or_tuple",
    ("Workplane", "rect", "forConstruction"): "bool",
    ("Workplane", "circle", "radius"): "number",
    ("Workplane", "circle", "forConstruction"): "bool",
    ("Workplane", "hole", "diameter"): "number",
    ("Workplane", "hole", "depth"): "number_or_none",
    ("Workplane", "hole", "clean"): "bool",
    ("Workplane", "cutBlind", "until"): "number_or_str_or_face",
    ("Workplane", "cutBlind", "clean"): "bool",
    ("Workplane", "cutBlind", "both"): "bool",
    ("Workplane", "cutBlind", "taper"): "number_or_none",
    ("Workplane", "pushPoints", "pntList"): "iterable",
    ("Workplane", "polyline", "listOfXYTuple"): "iterable",
    ("Workplane", "extrude", "until"): "number_or_str_or_face",
    ("Workplane", "extrude", "combine"): "bool_or_str",
    ("Workplane", "extrude", "clean"): "bool",
    ("Workplane", "extrude", "both"): "bool",
    ("Workplane", "fillet", "radius"): "number",
    ("Workplane", "chamfer", "length"): "number",
    ("Workplane", "chamfer", "length2"): "number_or_none",
    ("Workplane", "translate", "vec"): "tuple_or_vector",
    ("Solid", "makeBox", "length"): "number",
    ("Solid", "makeBox", "width"): "number",
    ("Solid", "makeBox", "height"): "number",
    ("Solid", "makeLoft", "listOfWire"): "iterable",
    ("Solid", "makeLoft", "ruled"): "bool",
}
_TYPE_NAMES = {"Workplane", "Shape", "Solid", "Compound", "Wire", "Face", "Edge", "Vector", "Location"}


def _value_type(node: ast.AST, env: dict[str, str], parameter_types: dict[str, str]) -> str:
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        if isinstance(node.value, bool):
            return "bool"
        if isinstance(node.value, int):
            return "int"
        if isinstance(node.value, float):
            return "float"
        if isinstance(node.value, str):
            return "str"
        return type(node.value).__name__
    if isinstance(node, ast.Name):
        return env.get(node.id, "unknown")
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name) and node.value.id == "params":
            key = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if key is not None:
                return parameter_types.get(str(key), _parameter_name_type(str(key)))
        return "unknown"
    if isinstance(node, (ast.Tuple, ast.List)):
        element_types = [_value_type(item, env, parameter_types) for item in node.elts]
        container = "tuple" if isinstance(node, ast.Tuple) else "list"
        if not element_types:
            return container
        return f"{container}[{element_types[0]}]" if len(set(element_types)) == 1 else container
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.UnaryOp):
        return _value_type(node.operand, env, parameter_types)
    if isinstance(node, ast.BinOp):
        left = _value_type(node.left, env, parameter_types)
        right = _value_type(node.right, env, parameter_types)
        if left in {"int", "float", "number"} and right in {"int", "float", "number"}:
            return "float"
        return "unknown"
    return "unknown"


def _parameter_name_type(name: str) -> str:
    token = name.casefold()
    if any(part in token for part in ("width", "height", "length", "thickness", "diameter", "radius", "angle", "spacing", "count", "offset", "depth", "size", "t")):
        return "float"
    if any(part in token for part in ("enabled", "preserve", "centered", "invert")):
        return "bool"
    return "unknown"


def _type_compatible(actual: str, expected: str) -> bool:
    if actual == "unknown" or expected in {"unknown", "iterable", "tuple_or_vector", "number_or_str_or_face"}:
        if expected == "iterable":
            return actual in {"unknown", "list", "tuple"} or actual.startswith(("list[", "tuple["))
        return True
    if expected == "number":
        return actual in {"int", "float", "number"}
    if expected == "number_or_none":
        return actual in {"None", "int", "float", "number"}
    if expected == "bool":
        return actual == "bool"
    if expected == "str":
        return actual == "str"
    if expected == "bool_or_tuple":
        return actual == "bool" or actual.startswith("tuple[") or actual == "tuple"
    if expected == "bool_or_str":
        return actual in {"bool", "str"}
    if expected == "tuple_or_vector":
        return actual.startswith("tuple[") or actual in {"tuple", "Vector", "unknown"}
    if expected == "number_or_str_or_face":
        return actual in {"int", "float", "number", "str", "Face", "unknown"}
    return actual == expected


def _class_for_type(type_name: str, runtime: dict[str, Any]) -> Any:
    cadquery = runtime.get("cadquery")
    if cadquery is None:
        return None
    return getattr(cadquery, type_name, None)


def _method_value(type_name: str, method: str, runtime: dict[str, Any]) -> Any:
    cls = _class_for_type(type_name, runtime)
    if cls is None:
        return None
    return getattr(cls, method, None)


def _expected_parameters(type_name: str | None, method: str, runtime: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    if not type_name:
        return {}, None
    value = _method_value(type_name, method, runtime)
    if value is None:
        return {}, None
    signature = _safe_signature(value)
    if signature is None:
        return {}, None
    try:
        parameters = inspect.signature(value).parameters
    except (TypeError, ValueError):
        return {}, signature
    expected: dict[str, str] = {}
    for name, parameter in parameters.items():
        if name == "self":
            continue
        expected[name] = _PARAMETER_TYPE_OVERRIDES.get((type_name, method, name), "unknown")
    return expected, signature


def _method_available(type_name: str | None, method: str, runtime: dict[str, Any]) -> bool | None:
    if not type_name:
        return None
    return callable(_method_value(type_name, method, runtime))


def _method_available_anywhere(method: str, runtime: dict[str, Any]) -> bool:
    return bool(runtime.get("method_signatures", {}).get(method))


def _return_type(type_name: str | None, method: str, *, is_constructor: bool = False) -> str | None:
    if is_constructor:
        return type_name
    if type_name is None:
        return None
    if (type_name, method) in _RETURN_TYPES:
        return _RETURN_TYPES[(type_name, method)]
    if type_name == "Compound" and method in {"cut", "fuse", "union"}:
        return "Shape"
    return type_name if type_name == "Workplane" else None


def _namespace_provenance(root: str | None, imported_aliases: dict[str, tuple[str, ...]], alias: str | None) -> str:
    if root == "OCP":
        return "direct_ocp_import"
    if alias and alias in imported_aliases:
        return "explicit_cadquery_import"
    if root == "cq":
        return "approved_slot_context"
    return "unknown_namespace"


def analyze_geometry_statements(
    statements: Iterable[str],
    *,
    project_id: str | None = None,
    initial_types: dict[str, str] | None = None,
    parameter_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Analyze exact statements with conservative receiver and value typing."""

    runtime = _runtime()
    env = dict(initial_types or {})
    parameter_types = dict(parameter_types or {})
    exact_statements = [str(statement) for statement in statements]
    references: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    imported_aliases: dict[str, tuple[str, ...]] = {}

    def imported_chain(chain: list[str]) -> tuple[list[str], str | None]:
        if chain and chain[0] in imported_aliases:
            alias = chain[0]
            return [*imported_aliases[alias], *chain[1:]], alias
        return chain, None

    def infer(node: ast.AST, statement: str) -> tuple[str | None, dict[str, Any] | None]:
        if isinstance(node, ast.Call):
            return analyze_call(node, statement)
        if isinstance(node, ast.Name):
            return env.get(node.id), None
        if isinstance(node, ast.Subscript):
            return _value_type(node, env, parameter_types), None
        return _value_type(node, env, parameter_types), None

    def analyze_call(node: ast.Call, statement: str) -> tuple[str | None, dict[str, Any] | None]:
        raw_chain = _attribute_chain(node.func) or []
        chain, alias = imported_chain(raw_chain)
        root = chain[0] if chain else None
        namespace = _namespace_provenance(root, imported_aliases, alias)
        method: str | None = None
        receiver_type: str | None = None
        receiver_ref: dict[str, Any] | None = None
        class_method = False
        constructor = False
        class_type: str | None = None
        if root in {"cq", "OCP"}:
            if root == "cq" and len(chain) == 2 and chain[1] in _TYPE_NAMES:
                constructor = True
                class_type = chain[1]
                method = chain[1]
                receiver_type = None
                class_method = True
            elif root == "cq" and len(chain) >= 3 and chain[1] in _TYPE_NAMES:
                class_type = chain[1]
                method = chain[-1]
                receiver_type = class_type
                class_method = True
            elif root == "OCP":
                method = chain[-1] if len(chain) > 1 else None
                receiver_type = None
                class_method = True
            elif len(chain) >= 2:
                method = chain[-1]
        elif isinstance(node.func, ast.Attribute):
            method = node.func.attr
            receiver_type, receiver_ref = infer(node.func.value, statement)
        elif isinstance(node.func, ast.Name):
            # Imported class calls (including direct OCP imports) are resolved
            # through the alias map above.
            method = chain[-1] if chain else node.func.id
            if root == "cq" and len(chain) == 2 and chain[1] in _TYPE_NAMES:
                constructor = True
                class_type = chain[1]
                class_method = True
        if method is None:
            return "unknown", None

        # Only CadQuery/OCP references belong in the dialect corpus.  Calls
        # such as params.get(), int(), math.radians(), and Volundr-owned
        # helpers are ordinary Python and must not inflate hallucinated API
        # or mixed-dialect rates.
        if root not in {"cq", "OCP"} and receiver_type not in _TYPE_NAMES:
            if receiver_type is None and not _method_available_anywhere(method, runtime):
                return "unknown", None
            if receiver_type not in _TYPE_NAMES:
                return "unknown", None

        if root in {"cq", "OCP"} and root == "cq" and len(chain) == 2 and chain[1] in _TYPE_NAMES:
            method_value = _class_for_type(chain[1], runtime)
            expected, signature = _expected_parameters(chain[1], "__init__", runtime)
            if not expected:
                try:
                    signature = _safe_signature(method_value)
                    params = inspect.signature(method_value).parameters if method_value else {}
                    expected = {name: "str" if name == "inPlane" else "unknown" for name in params if name != "self"}
                except (TypeError, ValueError):
                    expected = {}
            return_type = chain[1]
            available = method_value is not None
        elif root == "OCP":
            signature = _runtime_candidates(chain, runtime)[0] if _runtime_candidates(chain, runtime) else None
            expected = {}
            return_type = "OCP"
            available = _resolve_exact(chain, runtime) is not None
        else:
            available = _method_available(receiver_type, method, runtime)
            expected, signature = _expected_parameters(receiver_type, method, runtime)
            return_type = _return_type(receiver_type, method)
            if receiver_type is None and _method_available_anywhere(method, runtime):
                signatures = runtime.get("method_signatures", {}).get(method, [])
                signature = signatures[0] if signatures else signature

        argument_types = [_value_type(arg, env, parameter_types) for arg in node.args]
        keyword_names = [keyword.arg for keyword in node.keywords if keyword.arg is not None]
        expected_parameter_types = dict(expected)
        parameter_names = list(expected)
        signature_mismatch = False
        if len(argument_types) > len(parameter_names) and not any("*" in str(signature or "") for _ in [0]):
            signature_mismatch = True
        if any(keyword not in expected for keyword in keyword_names) and expected:
            signature_mismatch = True
        type_mismatch = False
        for index, actual in enumerate(argument_types):
            if index < len(parameter_names) and not _type_compatible(actual, expected.get(parameter_names[index], "unknown")):
                type_mismatch = True
        for keyword in node.keywords:
            if keyword.arg is not None and keyword.arg in expected:
                actual = _value_type(keyword.value, env, parameter_types)
                if not _type_compatible(actual, expected[keyword.arg]):
                    type_mismatch = True

        if root == "OCP":
            classification = "direct_ocp_version_sensitive"
        elif not available:
            if receiver_type is not None and _method_available_anywhere(method, runtime):
                # A value returned by ``val()`` is a Shape, not a Workplane.
                # Keep this distinct from a wrong receiver supplied by the
                # caller (for example Solid.workplane), which is a receiver
                # mismatch rather than a broken fluent return chain.
                classification = "current_return_chain_mismatch" if receiver_type == "Shape" else "current_receiver_type_mismatch"
            elif receiver_type is None and _method_available_anywhere(method, runtime):
                classification = "ambiguous_static_type"
            else:
                classification = "unknown_or_hallucinated"
        elif type_mismatch:
            classification = "current_argument_type_mismatch"
        elif signature_mismatch:
            classification = "current_signature_mismatch"
        else:
            classification = "current_supported"

        if root == "cq" and class_method and class_type:
            return_type = _return_type(class_type, method, is_constructor=constructor) or class_type
        reference = {
            "kind": "call",
            "project_id": project_id,
            "statement": statement,
            "root": root,
            "symbol": ".".join(chain[:-1]) if len(chain) > 1 else ".".join(chain),
            "method": method,
            "namespace_provenance": namespace,
            "receiver_type_before": receiver_type,
            "method_available_on_receiver": available,
            "method_available_anywhere": _method_available_anywhere(method, runtime),
            "argument_count": len(argument_types),
            "argument_types": argument_types,
            "keywords": keyword_names,
            "expected_parameter_types": expected_parameter_types,
            "runtime_signature": signature,
            "return_type": return_type,
            "next_receiver_type": return_type,
            "classification": classification,
            "release_compatibility": _release_compatibility(classification, runtime, root=root),
            "statement_index": exact_statements.index(statement) if statement in exact_statements else None,
        }
        references.append(reference)
        if receiver_ref is not None:
            receiver_ref["next_receiver_type"] = receiver_type
        return return_type, reference

    for statement_index, statement in enumerate(exact_statements):
        try:
            tree = ast.parse(statement, mode="exec")
        except SyntaxError as exc:
            parse_errors.append({"statement_index": statement_index, "statement": statement, "error": exc.msg})
            continue
        # Imports are provenance, not generated geometry operations.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "cadquery":
                        imported_aliases[alias.asname or "cadquery"] = ("cq",)
                    elif alias.name == "OCP" or alias.name.startswith("OCP."):
                        imported_aliases[alias.asname or alias.name.split(".")[-1]] = tuple(["OCP", *alias.name.split(".")[1:]])
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "cadquery":
                    for alias in node.names:
                        imported_aliases[alias.asname or alias.name] = ("cq", alias.name)
                elif node.module == "OCP" or node.module.startswith("OCP."):
                    for alias in node.names:
                        imported_aliases[alias.asname or alias.name] = tuple(["OCP", *node.module.split(".")[1:], alias.name])
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value_type, _ = infer(node.value, statement)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = value_type or "unknown"
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                env[node.target.id] = infer(node.value, statement)[0] or "unknown"
            elif isinstance(node, ast.Expr):
                infer(node.value, statement)

    issue_classes = sorted({
        item["classification"] for item in references
        if item.get("classification") in API_REFERENCE_CLASSIFICATIONS
    })
    return {
        "project_id": project_id,
        "statements": exact_statements,
        "statements_modified": False,
        "syntax_valid": not parse_errors,
        "references": references,
        "classifications": issue_classes,
        "parse_errors": parse_errors,
        "symbols": sorted({str(item.get("symbol")) for item in references if item.get("symbol")}),
        "methods": sorted({str(item.get("method")) for item in references if item.get("method")}),
        "keywords": sorted({key for item in references for key in item.get("keywords", [])}),
        "pinned_runtime": {
            "cadquery_version": runtime.get("cadquery_version"),
            "ocp_version": runtime.get("ocp_version"),
            "runtime_probe": "static receiver, signature, argument, and return-chain analysis",
        },
    }
