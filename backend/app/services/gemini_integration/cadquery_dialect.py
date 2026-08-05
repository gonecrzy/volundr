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
        "current_signature_mismatch",
        "historical_deprecated",
        "historical_removed",
        "direct_ocp_version_sensitive",
        "unknown_or_hallucinated",
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
                "cadquery_kernel_failure"
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
    "characterize_geometry_statements",
    "diagnose_wave_geometry_compatibility",
]
