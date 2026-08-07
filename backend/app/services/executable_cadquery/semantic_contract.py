"""Canonical semantic requirement fields for executable-CadQuery verification.

The persisted contract remains the source of truth.  This module derives a
canonical verifier input at the application boundary so that equivalent legacy
field names are handled once, while semantically narrower or unsupported
fields remain visible and fail closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


SEMANTIC_CONTRACT_NORMALIZATION_VERSION = "executable-cadquery-semantic-contract-v1"

_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "final_mesh_wall_profile": {
        "canonical": {"wall_thickness": ("wall", "value")},
        "supported": {"wall_thickness", "wall", "value"},
        "required_all": ("wall_thickness",),
    },
    "final_mesh_opening_profiles": {
        "canonical": {
            "hole_count": ("count",),
            "hole_diameter": ("diameter",),
        },
        "supported": {"hole_count", "count", "hole_diameter", "diameter", "through"},
        "required_any": ("hole_count", "hole_diameter"),
    },
    "final_mesh_opening_centers": {
        "canonical": {
            "hole_count": ("count",),
            "hole_diameter": ("diameter",),
        },
        "supported": {
            "hole_count",
            "count",
            "hole_diameter",
            "diameter",
            "pitch_circle_diameter",
        },
        "required_any": ("hole_count", "hole_diameter"),
    },
}


def normalize_executable_cadquery_requirement(
    requirement: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a canonical, provenance-bearing verifier view of a requirement.

    Canonical fields win when a canonical and legacy representation coexist.
    When canonical data is absent, equivalent legacy aliases may populate it;
    conflicting aliases fail closed.  Unknown fields are not discarded: they
    are reported as unsupported semantic qualifiers so a generic verifier can
    never turn a partial measurement into a false PASS.
    """

    source = deepcopy(dict(requirement))
    expected_value = source.get("expected")
    raw_expected = dict(expected_value) if isinstance(expected_value, Mapping) else {}
    policy = str(source.get("verification_policy") or "")
    spec = _FIELD_SPECS.get(policy)
    if spec is None:
        return {
            "version": SEMANTIC_CONTRACT_NORMALIZATION_VERSION,
            "status": "normalized",
            "policy": policy,
            "requirement": source,
            "expected": raw_expected,
            "unsupported_fields": [],
            "missing_fields": [],
            "conflicts": [],
            "shadowed_legacy_fields": [],
            "canonical_fields": [],
        }

    canonical_expected = dict(raw_expected)
    conflicts: list[str] = []
    shadowed_legacy_fields: list[str] = []
    canonical_fields: list[str] = []

    for canonical_field, aliases in spec["canonical"].items():
        canonical_present = _present(raw_expected, canonical_field)
        alias_values = [
            (alias, raw_expected[alias])
            for alias in aliases
            if _present(raw_expected, alias)
        ]
        if canonical_present:
            canonical_fields.append(canonical_field)
            shadowed_legacy_fields.extend(alias for alias, _ in alias_values)
            continue
        if not alias_values:
            continue
        first_value = alias_values[0][1]
        if any(not _equivalent(first_value, value) for _, value in alias_values[1:]):
            conflicts.append(canonical_field)
            continue
        canonical_expected[canonical_field] = first_value
        canonical_fields.append(canonical_field)

    supported_fields = set(spec["supported"])
    unsupported_fields = sorted(field for field in raw_expected if field not in supported_fields)
    missing_fields = [
        field
        for field in spec.get("required_all", ())
        if not _present(canonical_expected, field)
    ]
    required_any = tuple(spec.get("required_any", ()))
    if required_any and not any(_present(canonical_expected, field) for field in required_any):
        missing_fields.extend(required_any)

    status = "conflict" if conflicts else "unverifiable" if missing_fields else "normalized"
    normalized_requirement = deepcopy(source)
    normalized_requirement["expected"] = canonical_expected
    return {
        "version": SEMANTIC_CONTRACT_NORMALIZATION_VERSION,
        "status": status,
        "policy": policy,
        "requirement": normalized_requirement,
        "expected": canonical_expected,
        "unsupported_fields": sorted(unsupported_fields),
        "missing_fields": list(dict.fromkeys(missing_fields)),
        "conflicts": sorted(conflicts),
        "shadowed_legacy_fields": sorted(shadowed_legacy_fields),
        "canonical_fields": canonical_fields,
    }


def _present(values: Mapping[str, Any], key: str) -> bool:
    return key in values and values[key] is not None


def _equivalent(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False
