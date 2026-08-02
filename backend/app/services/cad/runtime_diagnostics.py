"""Defensive classification of source-scope failures reported by the CAD worker."""

from __future__ import annotations

import re
from typing import Any


_NAME_ERROR_RE = re.compile(r"NameError:\s+name ['\"](?P<symbol>[A-Za-z_]\w*)['\"] is not defined")
_UNBOUND_LOCAL_RE = re.compile(
    r"UnboundLocalError:\s+cannot access local variable ['\"](?P<symbol>[A-Za-z_]\w*)['\"]"
)
_FUNCTION_RE = re.compile(r"\bin (?P<function>_ai_[A-Za-z_]\w*)\b")
_STATEMENT_RE = re.compile(r"^\s+(?P<statement>(?:body|modified|result|[A-Za-z_]\w*)\s*=.*)$", re.MULTILINE)
_SELECTOR_RE = re.compile(r"\.(?:edges|faces|vertices|solids|shells|wires)\(\s*(['\"])(?P<selector>.*?)\1\s*\)")
_ATTRIBUTE_ERROR_RE = re.compile(r"AttributeError:\s+(?P<message>.+)")
_TYPE_ERROR_RE = re.compile(r"TypeError:\s+(?P<message>.+)")
_NONPLANAR_RE = re.compile(r"wires?\s+not\s+planar|Cannot build face\(s\):\s*wires?\s+not\s+planar", re.IGNORECASE)


def classify_worker_name_failure(
    error_message: str | None,
    *,
    traceback: str | None = None,
) -> dict[str, Any] | None:
    """Classify only safely identifiable NameError-style provider failures."""

    text = "\n".join(item for item in (error_message or "", traceback or "") if item)
    match = _NAME_ERROR_RE.search(text)
    rule_id = "geometry_body.unbound_name"
    if match is None:
        match = _UNBOUND_LOCAL_RE.search(text)
        rule_id = "geometry_body.conditionally_bound_name"
    if match is None:
        return None
    function_match = _FUNCTION_RE.search(text)
    statement_match = _STATEMENT_RE.search(traceback or "")
    function_id = function_match.group("function") if function_match else None
    symbol = match.group("symbol")
    return {
        "rule_id": rule_id,
        "category": "source_runtime",
        "severity": "critical",
        "is_blocking": True,
        "blocking": True,
        "symbol": symbol,
        "function_id": function_id,
        "source_statement": statement_match.group("statement").strip() if statement_match else None,
        "repair_available": bool(function_id),
        "safe_function_identified": bool(function_id),
        "message": f"CAD worker reported an unresolved source name `{symbol}`.",
        "traceback": traceback or error_message or "",
    }


def runtime_repair_is_eligible(finding: dict[str, Any] | None) -> bool:
    """Return true only for one provider function with a known source symbol."""

    return bool(
        finding
        and finding.get("repair_available")
        and isinstance(finding.get("function_id"), str)
        and (
            isinstance(finding.get("symbol"), str)
            or isinstance(finding.get("source_statement"), str)
        )
    )


def classify_worker_diagnostic(
    error_message: str | None,
    *,
    traceback: str | None = None,
    pattern_manifest: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Classify one safely localized provider-owned worker source failure."""

    name_failure = classify_worker_name_failure(error_message, traceback=traceback)
    if name_failure is not None:
        return name_failure
    text = "\n".join(item for item in (error_message or "", traceback or "") if item)
    if _NONPLANAR_RE.search(text):
        function_match = _FUNCTION_RE.search(text)
        statement_match = _STATEMENT_RE.search(traceback or "")
        function_id = function_match.group("function") if function_match else None
        source_statement = statement_match.group("statement").strip() if statement_match else None
        finding = {
            "rule_id": "worker.pattern_points_not_planar_for_workplane",
            "category": "worker_runtime",
            "severity": "critical",
            "is_blocking": True,
            "blocking": True,
            "function_id": function_id,
            "source_statement": source_statement,
            "exception_type": "CadQuery nonplanar point construction failure",
            "message": "CadQuery received repeated placements that are not planar in the consuming workplane.",
            "repair_available": bool(function_id and source_statement),
            "safe_function_identified": bool(function_id),
            "traceback": traceback or error_message or "",
        }
        patterns = [item for item in pattern_manifest or [] if isinstance(item, dict)]
        if len(patterns) == 1:
            pattern = patterns[0]
            finding["pattern_id"] = pattern.get("pattern_id")
            finding["pattern_coordinate_evidence"] = {
                key: pattern.get(key)
                for key in (
                    "pattern_id",
                    "owning_component_id",
                    "owning_feature_id",
                    "coordinate_space",
                    "coordinate_frame_id",
                    "point_dimensionality",
                    "arrangement_axis",
                    "host_plane",
                    "consumer_operation",
                    "resolved_points",
                    "resolved_point_hash",
                )
                if pattern.get(key) is not None
            }
        return finding
    if not re.search(r"(?:ParseException|StringSyntaxSelector|selector)", text, re.IGNORECASE):
        attribute_match = _ATTRIBUTE_ERROR_RE.search(text)
        type_match = _TYPE_ERROR_RE.search(text)
        if attribute_match is None and type_match is None:
            return None
        statement_match = _STATEMENT_RE.search(traceback or "")
        if statement_match is None or not re.search(
            r"\b(?:cq\.|body\.)",
            statement_match.group("statement"),
        ):
            return None
        function_match = _FUNCTION_RE.search(text)
        function_id = function_match.group("function") if function_match else None
        return {
            "rule_id": "geometry_body.cadquery_api_failure",
            "category": "worker_runtime",
            "severity": "critical",
            "is_blocking": True,
            "blocking": True,
            "function_id": function_id,
            "source_statement": statement_match.group("statement").strip(),
            "exception_type": "CadQuery API attribute failure" if attribute_match else "CadQuery API type failure",
            "message": "CadQuery raised an API error in a provider-owned statement.",
            "repair_available": bool(function_id),
            "safe_function_identified": bool(function_id),
            "traceback": traceback or error_message or "",
        }
    function_match = _FUNCTION_RE.search(text)
    statement_match = _STATEMENT_RE.search(traceback or "")
    selector_match = _SELECTOR_RE.search(traceback or "")
    function_id = function_match.group("function") if function_match else None
    source_statement = statement_match.group("statement").strip() if statement_match else None
    selector = selector_match.group("selector") if selector_match else None
    return {
        "rule_id": "geometry_body.cadquery_selector_failure",
        "category": "worker_runtime",
        "severity": "critical",
        "is_blocking": True,
        "blocking": True,
        "function_id": function_id,
        "source_statement": source_statement,
        "selector": selector,
        "exception_type": "CadQuery selector parse failure",
        "repair_available": bool(function_id and source_statement),
        "safe_function_identified": bool(function_id),
        "message": "CadQuery rejected a provider-owned selector expression.",
        "traceback": traceback or error_message or "",
    }
