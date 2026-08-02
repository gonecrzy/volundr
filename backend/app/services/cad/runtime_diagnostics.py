"""Defensive classification of source-scope failures reported by the CAD worker."""

from __future__ import annotations

import re
from typing import Any


_NAME_ERROR_RE = re.compile(r"NameError:\s+name ['\"](?P<symbol>[A-Za-z_]\w*)['\"] is not defined")
_UNBOUND_LOCAL_RE = re.compile(
    r"UnboundLocalError:\s+cannot access local variable ['\"](?P<symbol>[A-Za-z_]\w*)['\"]"
)
_FUNCTION_RE = re.compile(r"\bin (?P<function>_ai_[A-Za-z_]\w*)\b")


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
        and isinstance(finding.get("symbol"), str)
    )
