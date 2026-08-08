"""Generic, evaluator-only comparison-specification qualification.

This module prepares user-suppliable design facts for reference comparison. It
does not inspect or serialize mesh topology beyond coarse derived envelopes,
and it is not part of the Volundr generation or requirement-verification path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


COMPARISON_SPEC_SCHEMA_VERSION = "external-cad-comparison-specification-v1"
COMPARISON_SPEC_METHODOLOGY_VERSION = "external-cad-comparison-extraction-v1"
ALLOWED_PROVENANCE = {
    "creator_documented",
    "reference_geometry_measured",
    "manual_benchmark_annotation",
}
MEASUREMENT_METHOD = "external-cad-reference-derived-v1.geometry.bounding_box_mm"

_GEOMETRY_TOKENS = {
    "angle",
    "clearance",
    "depth",
    "diameter",
    "distance",
    "envelope",
    "height",
    "hole",
    "interface",
    "length",
    "offset",
    "opening",
    "radius",
    "size",
    "slot",
    "spacing",
    "thickness",
    "width",
}
_NON_GEOMETRY_TOKENS = {
    "appliance",
    "application",
    "assembly",
    "device",
    "family",
    "function",
    "supported",
    "tool",
    "variant",
}
_INTERFACE_TOKENS = {
    "clearance",
    "diameter",
    "distance",
    "hole",
    "interface",
    "mating",
    "opening",
    "radius",
    "size",
    "slot",
    "spacing",
    "thickness",
    "width",
}


def _value(project: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(project, Mapping):
        return project.get(key, default)
    return getattr(project, key, default)


def _tokens(value: Any) -> set[str]:
    return {token for token in str(value).lower().replace("-", "_").split("_") if token}


def _as_fact(fact: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(fact)
    provenance = result.get("provenance")
    if provenance not in ALLOWED_PROVENANCE:
        raise ValueError(f"comparison fact has unsupported provenance: {provenance!r}")
    if provenance == "reference_geometry_measured":
        result.setdefault("measurement_method", MEASUREMENT_METHOD)
    return result


def _envelope(derived: Mapping[str, Any]) -> dict[str, float] | None:
    bounds = derived.get("geometry", {}).get("bounding_box_mm", {})
    values = {
        "x": bounds.get("size_x"),
        "y": bounds.get("size_y"),
        "z": bounds.get("size_z"),
    }
    if any(not isinstance(value, (int, float)) for value in values.values()):
        return None
    return {axis: float(value) for axis, value in values.items()}


def _derived_by_part(derived_reference: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["part_id"]): item.get("derived", {})
        for item in derived_reference.get("canonical_parts", [])
        if isinstance(item, Mapping) and item.get("part_id")
    }


def _part_records(project: Mapping[str, Any], derived_reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    derived_by_part = _derived_by_part(derived_reference)
    records = []
    for reference in sorted(_value(project, "reference_files", []) or [], key=lambda item: item["part_id"]):
        derived = derived_by_part.get(reference["part_id"], {})
        records.append(
            {
                "part_id": reference["part_id"],
                "selected_variant": reference["original_filename"],
                "selection_reason": reference.get("selection_reason"),
                "file_type": reference.get("file_type"),
                "authority": reference.get("authority"),
                "quality_classification": reference.get("quality_classification"),
                "overall_envelope_mm": _envelope(derived),
                "solid_count": derived.get("geometry", {}).get("solid_count"),
            }
        )
    return records


def _numeric_geometry_facts(facts: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result = []
    for fact in facts:
        tokens = _tokens(fact.get("id", ""))
        value = fact.get("value")
        if not tokens & _GEOMETRY_TOKENS:
            continue
        if not isinstance(value, (int, float, dict, list)):
            continue
        if tokens & _NON_GEOMETRY_TOKENS and not isinstance(value, (int, float, dict, list)):
            continue
        result.append(fact)
    return result


def _missing_design_driving_facts(
    *,
    project: Mapping[str, Any],
    facts: list[Mapping[str, Any]],
    outputs: list[Mapping[str, Any]],
) -> list[str]:
    missing: list[str] = []
    expected_count = next((fact.get("value") for fact in facts if fact.get("id") == "output_count"), None)
    if expected_count != len(outputs):
        missing.append("output_identity")
    if not outputs or any(not output.get("selected_variant") for output in outputs):
        missing.append("selected_variant")
    if any(output.get("overall_envelope_mm") is None for output in outputs):
        missing.append("major_envelope")

    numeric_geometry = _numeric_geometry_facts(facts)
    interface_geometry = [
        fact
        for fact in numeric_geometry
        if _tokens(fact.get("id", "")) & _INTERFACE_TOKENS
    ]
    if not interface_geometry:
        missing.append("principal_mating_geometry")
    if not any(
        _tokens(fact.get("id", ""))
        & {"clearance", "diameter", "hole", "offset", "radius", "spacing", "thickness", "width"}
        for fact in numeric_geometry
    ):
        missing.append("critical_hardware_or_interface_geometry")

    if len(outputs) > 1 and not _value(project, "reference_output_mapping", {}):
        missing.append("output_relationship_mapping")
    flags = set(_value(project, "ambiguity_flags", ()) or ())
    if {"canonical_subset_ambiguous", "large_assembly_scope"} & flags:
        missing.append("canonical_scope_confirmation")
    return missing


def _prompt(facts: list[Mapping[str, Any]], outputs: list[Mapping[str, Any]], premise: str) -> str:
    lines = [premise.strip(), "", "For this comparison specification:"]
    lines.append(f"- Provide exactly {len(outputs)} printed output(s).")
    for output in outputs:
        envelope = output.get("overall_envelope_mm")
        if envelope:
            lines.append(
                f"- Output {output['part_id']} should have an overall envelope of "
                f"approximately {envelope['x']} mm x {envelope['y']} mm x {envelope['z']} mm."
            )
    for fact in facts:
        if fact.get("id") == "output_count":
            continue
        lines.append(f"- {fact['id']}: {fact.get('value')} {fact.get('unit', '')}".rstrip())
    return "\n".join(lines)


def build_comparison_specification(
    project: Mapping[str, Any],
    derived_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a coarse, provenance-tagged comparison specification."""

    outputs = _part_records(project, derived_reference)
    facts = [_as_fact(fact) for fact in _value(project, "reference_spec", {}).get("facts", [])]
    if not any(fact.get("id") == "output_count" for fact in facts):
        facts.insert(
            0,
            {
                "id": "output_count",
                "value": len(outputs),
                "unit": "count",
                "provenance": "manual_benchmark_annotation",
                "source": "explicit canonical part membership",
            },
        )
    facts = sorted(facts, key=lambda fact: (str(fact.get("id", "")), json.dumps(fact, sort_keys=True)))
    missing = _missing_design_driving_facts(project=project, facts=facts, outputs=outputs)
    replacement = bool(_value(project, "replacement_recommended", False))
    status = "replacement_required" if replacement else ("comparison_ready" if not missing else "needs_spec_enrichment")
    spec = {
        "schema_version": COMPARISON_SPEC_SCHEMA_VERSION,
        "methodology_version": COMPARISON_SPEC_METHODOLOGY_VERSION,
        "benchmark_id": _value(project, "benchmark_id"),
        "category": _value(project, "category"),
        "split_assignment": _value(project, "split_assignment"),
        "source_reference_set_sha256": _value(project, "reference_set_sha256"),
        "comparison_ready": status == "comparison_ready",
        "status": status,
        "reference_similarity_status": "eligible" if status == "comparison_ready" else (
            "replacement_required" if status == "replacement_required" else "specification_underconstrained"
        ),
        "missing_design_driving_facts": missing,
        "outputs": outputs,
        "facts": facts,
        "prompt": _prompt(facts, outputs, _value(project, "premise", "")),
    }
    return spec


def comparison_specification_hash(specification: Mapping[str, Any]) -> str:
    payload = json.dumps(specification, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def build_sealed_holdout_record(specification: Mapping[str, Any]) -> dict[str, Any]:
    """Return only policy-allowed holdout metadata and a sealed spec hash."""

    return {
        "benchmark_id": specification["benchmark_id"],
        "category": specification["category"],
        "split_assignment": specification["split_assignment"],
        "comparison_specification_hash": comparison_specification_hash(specification),
        "status": "sealed",
    }
