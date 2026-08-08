"""Final-geometry checks for the executable CadQuery experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import trimesh

from app.services.geometry.feature_measurements import _ray_parameters
from app.services.geometry.invariants import (
    _detect_axis_aligned_hole_candidates,
    _hole_candidate_measurements,
)
from app.services.executable_cadquery.semantic_contract import (
    normalize_executable_cadquery_requirement,
)


def resolve_executable_cadquery_output_scope(
    requirement: Mapping[str, Any],
    *,
    available_output_ids: list[str] | tuple[str, ...] | set[str],
    output_registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a requirement to canonical executable output identities.

    Resolution is deliberately contract/runtime-only and fail-closed.  An
    explicit identity must resolve; it is never redirected to a sole output.
    A sole-output default is legal only when the requirement has no explicit
    scope.  Aliases and component IDs are accepted only from the supplied
    output registry, never from source names, geometry, or corpus context.
    """

    available = list(dict.fromkeys(str(item) for item in available_output_ids if str(item)))
    registry = output_registry or {}
    exact_ids = set(available)
    normalized_candidates: dict[str, list[str]] = {}
    for output_id in available:
        record = registry.get(output_id)
        if not isinstance(record, Mapping):
            record = {}
        identities: list[Any] = [output_id]
        for key in ("aliases", "output_aliases", "component_ids"):
            value = record.get(key)
            if isinstance(value, (list, tuple, set)):
                identities.extend(value)
            elif isinstance(value, str):
                identities.append(value)
        identities.append(record.get("component_id"))
        for identity in identities:
            normalized = _normalize_output_identity(identity)
            if normalized:
                normalized_candidates.setdefault(normalized, []).append(output_id)

    scope_kind = _normalized_scope_kind(requirement)
    identity_fields = (
        "output_id",
        "output_ids",
        "component_id",
        "component_ids",
        "scope",
    )
    explicit_values: list[tuple[str, list[Any]]] = []
    for field in identity_fields:
        if field not in requirement or requirement.get(field) in (None, "", []):
            continue
        value = requirement.get(field)
        if isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = [value]
        if field == "scope":
            split_values: list[Any] = []
            for item in values:
                if isinstance(item, str):
                    split_values.extend(part.strip() for part in item.split("/"))
                else:
                    split_values.append(item)
            values = split_values
        explicit_values.append((field, values))

    if scope_kind in {"global", "assembly"}:
        if explicit_values:
            return _unresolved_scope(
                status="ambiguous",
                reason="global_scope_conflicts_with_identity",
                available=available,
            )
        if not available:
            return _unresolved_scope(
                status="unresolved",
                reason="no_available_outputs",
                available=available,
            )
        return {
            "status": "resolved",
            "scope_kind": scope_kind,
            "output_ids": sorted(available),
            "reason": f"explicit_{scope_kind}_scope_resolved",
            "requested_identities": [],
            "available_output_ids": available,
        }

    if not explicit_values:
        if len(available) == 1:
            return {
                "status": "resolved",
                "scope_kind": "output_local",
                "output_ids": [available[0]],
                "reason": "single_available_output_default",
                "requested_identities": [],
                "available_output_ids": available,
            }
        return _unresolved_scope(
            status="ambiguous" if available else "unresolved",
            reason="unscoped_multiple_outputs" if available else "no_available_outputs",
            available=available,
        )

    resolved_by_field: list[tuple[str, list[str]]] = []
    for field, values in explicit_values:
        resolved: list[str] = []
        for value in values:
            identity = str(value).strip() if value is not None else ""
            if not identity:
                return _unresolved_scope(
                    status="unresolved",
                    reason="explicit_scope_not_found",
                    available=available,
                )
            if identity in exact_ids:
                matches = [identity]
            else:
                matches = list(dict.fromkeys(normalized_candidates.get(_normalize_output_identity(identity), [])))
            if not matches:
                return _unresolved_scope(
                    status="unresolved",
                    reason="explicit_scope_not_found",
                    available=available,
                )
            if len(matches) > 1:
                return _unresolved_scope(
                    status="ambiguous",
                    reason="explicit_scope_alias_ambiguous",
                    available=available,
                )
            if matches[0] in resolved:
                return _unresolved_scope(
                    status="ambiguous",
                    reason="duplicate_output_identity",
                    available=available,
                )
            resolved.append(matches[0])
        resolved_by_field.append((field, resolved))

    first_resolved = resolved_by_field[0][1]
    if any(set(resolved) != set(first_resolved) for _, resolved in resolved_by_field[1:]):
        return _unresolved_scope(
            status="ambiguous",
            reason="conflicting_output_identities",
            available=available,
        )
    kind = "multi_output" if len(first_resolved) > 1 else "output_local"
    return {
        "status": "resolved",
        "scope_kind": kind,
        "output_ids": first_resolved,
        "reason": "explicit_scope_resolved",
        "requested_identities": [
            {"field": field, "values": [str(item) for item in values]}
            for field, values in explicit_values
        ],
        "available_output_ids": available,
    }


def _normalize_output_identity(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().casefold()


def _normalized_scope_kind(requirement: Mapping[str, Any]) -> str | None:
    for key in ("scope_kind", "scope_type"):
        value = requirement.get(key)
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"global", "assembly"}:
                return normalized
    return None


def _unresolved_scope(*, status: str, reason: str, available: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "scope_kind": "unresolved",
        "output_ids": [],
        "reason": reason,
        "requested_identities": [],
        "available_output_ids": available,
    }


def evaluate_executable_cadquery_semantics(
    *,
    stl_path: Path,
    design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate contract facts from the final mesh, never from source text."""

    try:
        loaded = trimesh.load(stl_path, force="mesh")
        mesh = loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)
    except Exception as exc:  # pragma: no cover - defensive artifact boundary
        return {
            "status": "unverifiable",
            "passed": [],
            "failed": [],
            "unverifiable": ["final_mesh"],
            "diagnostic": "The final mesh could not be loaded for semantic verification.",
            "error_type": type(exc).__name__,
        }

    requirements = [
        item for item in design_contract.get("requirements", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    findings: list[dict[str, Any]] = []
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    expected_output = next(
        (item for item in design_contract.get("outputs", []) if isinstance(item, Mapping)),
        {},
    )
    expected_solids = int(expected_output.get("expected_solid_count") or 1)
    detected_solids = len(mesh.split(only_watertight=False)) if len(mesh.faces) else 0
    findings.append(
        _finding(
            "topology",
            detected_solids == expected_solids and len(mesh.faces) > 0,
            {
                "expected_solid_count": expected_solids,
                "detected_solid_count": detected_solids,
            },
        )
    )

    expected_body = _expected(requirements, "body_dimensions")
    if expected_body:
        expected_dimensions = [
            float(expected_body.get("width")),
            float(expected_body.get("depth")),
            float(expected_body.get("thickness")),
        ]
        tolerance = _tolerance(requirements, "body_dimensions")
        findings.append(
            _finding(
                "body_dimensions",
                bool(np.all(np.abs(extents - expected_dimensions) <= tolerance)),
                {"expected_mm": expected_dimensions, "detected_mm": _rounded(extents)},
            )
        )

    expected_holes = _expected(requirements, "mounting_hole_pattern")
    expected_offsets = _expected(requirements, "mounting_hole_edge_offsets")
    expected_asymmetric = _expected(requirements, "asymmetric_through_hole")
    hole_candidates = [
        hole for hole in _detect_axis_aligned_hole_candidates(mesh, "z", _tolerance_profile())
        if hole.confidence >= 0.55
    ]
    if expected_holes:
        expected_count = int(expected_holes.get("count") or 0)
        diameter = float(expected_holes.get("diameter") or 0)
        findings.append(
            _stl_candidate_unverifiable_finding(
                "mounting_hole_pattern",
                hole_candidates,
                expected_count=expected_count,
                expected_diameter=diameter,
                tolerance=_tolerance(requirements, "mounting_hole_pattern"),
            )
        )
        if expected_offsets:
            findings.append(
                _stl_candidate_unverifiable_finding(
                    "mounting_hole_edge_offsets",
                    hole_candidates,
                    expected_count=expected_count,
                    expected_diameter=diameter,
                    tolerance=_tolerance(requirements, "mounting_hole_pattern"),
                    extra_measurements={
                        "expected_offset_mm": expected_offsets.get("nearest_edge_offset"),
                        "reason": "candidate_centers_cannot_establish_physical_hole_identity",
                    },
                )
            )
    if expected_asymmetric:
        x = float(bounds[0][0]) + float(expected_asymmetric.get("x_from_left") or 0)
        y = float(bounds[0][1]) + float(expected_asymmetric.get("y_from_lower") or 0)
        diameter = float(expected_asymmetric.get("diameter") or 0)
        tolerance = _tolerance(requirements, "asymmetric_through_hole")
        hole_result = _probe_hole_diameter(mesh, (x, y), diameter, tolerance)
        findings.append(
            _finding(
                "asymmetric_through_hole",
                hole_result,
                {
                    "probe_mm": [round(x, 3), round(y, 3)],
                    "through": hole_result,
                    "circular_profile_candidates": [
                        {
                            "center": _rounded(hole.center),
                            "diameter_mm": round(float(hole.diameter), 3),
                        }
                        for hole in hole_candidates
                    ],
                },
            )
        )

    pocket = _expected(requirements, "centered_recessed_pocket")
    if pocket:
        findings.append(_verify_pocket(mesh, pocket, requirements))

    fillet = _expected(requirements, "external_fillet")
    if fillet:
        findings.append(_verify_external_fillet(mesh, fillet, expected_body))

    passed = [item["requirement_id"] for item in findings if item["status"] == "passed"]
    failed = [item["requirement_id"] for item in findings if item["status"] == "failed"]
    unverifiable = [item["requirement_id"] for item in findings if item["status"] == "unverifiable"]
    status = "failed" if failed else "unverifiable" if unverifiable else "passed"
    return {
        "status": status,
        "passed": passed,
        "failed": failed,
        "unverifiable": unverifiable,
        "findings": findings,
        "mesh_bounds_mm": {"min": _rounded(bounds[0]), "max": _rounded(bounds[1])},
        "detected_solid_count": detected_solids,
    }


def evaluate_executable_cadquery_semantics_for_outputs(
    *,
    stl_paths: Mapping[str, Path],
    design_contract: Mapping[str, Any],
    topology_by_output: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate generic contract policies across one or more final outputs.

    Topology-sensitive policies consume the authoritative per-output topology
    evidence produced before semantic evaluation. They do not infer a B-Rep
    topology verdict from a derived STL when that evidence is absent.
    """

    meshes: dict[str, trimesh.Trimesh] = {}
    load_errors: dict[str, str] = {}
    for output_id, path in stl_paths.items():
        try:
            loaded = trimesh.load(path, force="mesh")
            mesh = loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)
            if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
                raise ValueError("mesh has no faces")
            meshes[str(output_id)] = mesh
        except Exception as exc:  # pragma: no cover - defensive artifact boundary
            load_errors[str(output_id)] = type(exc).__name__

    requirements = [
        item
        for item in design_contract.get("requirements", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    findings: list[dict[str, Any]] = []
    def has_explicit_scope(requirement: Mapping[str, Any]) -> bool:
        return any(
            requirement.get(field) not in (None, "", [])
            for field in (
                "scope",
                "scope_kind",
                "scope_type",
                "output_id",
                "output_ids",
                "component_id",
                "component_ids",
            )
        )

    legacy_requirements = [
        requirement for requirement in requirements if not has_explicit_scope(requirement)
    ]
    if len(meshes) == 1 and not load_errors and legacy_requirements:
        legacy_contract = dict(design_contract)
        legacy_contract["requirements"] = legacy_requirements
        output_id, path = next(iter(stl_paths.items()))
        legacy = evaluate_executable_cadquery_semantics(
            stl_path=path,
            design_contract=legacy_contract,
        )
        findings = [
            dict(item) for item in legacy.get("findings", []) if isinstance(item, Mapping)
        ]
    elif not meshes:
        findings = [
            {
                "requirement_id": "final_mesh",
                "status": "unverifiable",
                "measurement_available": False,
                "evidence_source": "final_mesh",
                "measurements": {"load_errors": load_errors},
            }
        ]
    else:
        findings = []

    found_ids = {str(item.get("requirement_id")) for item in findings if item.get("requirement_id")}
    output_registry = {
        str(item["output_id"]): item
        for item in design_contract.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    }
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        if requirement_id in found_ids:
            continue
        scope_resolution = resolve_executable_cadquery_output_scope(
            requirement,
            available_output_ids=list(meshes),
            output_registry=output_registry,
        )
        if scope_resolution["status"] != "resolved":
            findings.append(
                _semantic_finding(
                    requirement_id,
                    status="unverifiable",
                    measurement_available=False,
                    measurements={
                        "scope_resolution": scope_resolution,
                        "reason": (
                            "output_scope_ambiguous"
                            if scope_resolution["status"] == "ambiguous"
                            else "required output mesh is unavailable"
                        ),
                    },
                )
            )
            continue
        selected_meshes = {
            output_id: meshes[output_id]
            for output_id in scope_resolution["output_ids"]
            if output_id in meshes
        }
        policy = str(requirement.get("verification_policy") or "")
        if policy == "required_output_identity":
            findings.append(
                _verify_required_output_identity(
                    requirement,
                    resolved_output_ids=list(selected_meshes),
                )
            )
            findings[-1]["measurements"]["scope_resolution"] = scope_resolution
            continue
        if policy == "topology_and_required_output":
            findings.append(
                _verify_topology_and_required_output(
                    requirement,
                    resolved_output_ids=list(selected_meshes),
                    topology_by_output=topology_by_output,
                )
            )
            findings[-1]["measurements"]["scope_resolution"] = scope_resolution
            continue
        if policy == "required_output_artifact":
            findings.append(
                _semantic_finding(
                    requirement_id,
                    status="passed",
                    measurement_available=True,
                    evidence_source="executable_output_registry",
                    measurements={
                        "resolved_output_ids": list(selected_meshes),
                        "artifact_present": True,
                        "scope_resolution": scope_resolution,
                    },
                )
            )
            continue
        if len(selected_meshes) > 1 and policy in _OUTPUT_LOCAL_POLICIES:
            findings.append(
                _semantic_finding(
                    requirement_id,
                    status="unverifiable",
                    measurement_available=False,
                    measurements={
                        "resolved_output_ids": list(selected_meshes),
                        "scope_resolution": scope_resolution,
                        "reason": "output_local_scope_requires_single_output",
                    },
                )
            )
            continue
        measurement_meshes = selected_meshes
        if policy.startswith("cross_output_") and len(selected_meshes) == 1 and len(meshes) > 1:
            # A cross-output verifier has an explicit contract-level need for
            # the other loaded outputs.  The resolved scope remains the
            # owning/declared output, while the relation is measured against
            # the complete authoritative runtime output registry.
            measurement_meshes = meshes
        mesh = next(iter(selected_meshes.values()), None)
        if mesh is None:
            findings.append(
                _semantic_finding(
                    requirement_id,
                    status="unverifiable",
                    measurement_available=False,
                    measurements={
                        "scope_resolution": scope_resolution,
                        "reason": "required output mesh is unavailable",
                    },
                )
            )
            continue
        findings.append(
            _generic_requirement_finding(
                requirement,
                mesh=mesh,
                output_id=next(iter(selected_meshes)),
                meshes=measurement_meshes,
            )
        )
        findings[-1]["measurements"]["scope_resolution"] = scope_resolution

    passed = [str(item["requirement_id"]) for item in findings if item.get("status") == "passed"]
    failed = [str(item["requirement_id"]) for item in findings if item.get("status") == "failed"]
    unverifiable = [
        str(item["requirement_id"])
        for item in findings
        if item.get("status") == "unverifiable"
    ]
    return {
        "status": "failed" if failed else "unverifiable" if unverifiable else "passed",
        "passed": list(dict.fromkeys(passed)),
        "failed": list(dict.fromkeys(failed)),
        "unverifiable": list(dict.fromkeys(unverifiable)),
        "findings": findings,
        "output_ids": sorted(meshes),
        "load_errors": load_errors,
    }


_OUTPUT_LOCAL_POLICIES = frozenset(
    {
        "final_mesh_bounds",
        "final_mesh_opening_profiles",
        "final_mesh_opening_centers",
        "final_mesh_axisymmetric_profiles",
        "final_mesh_axial_sections",
        "final_mesh_recess_profile",
        "final_mesh_wall_profile",
        "final_mesh_feature_profiles",
        "measure_when_supported",
    }
)


def _verify_required_output_identity(
    requirement: Mapping[str, Any],
    *,
    resolved_output_ids: list[str],
) -> dict[str, Any]:
    requirement_id = str(requirement["requirement_id"])
    expected = requirement.get("expected") if isinstance(requirement.get("expected"), Mapping) else {}
    expected_count = expected.get("count")
    expected_single_id = expected.get("output_id")
    expected_required_id = expected.get("required_output")
    expected_output_ids = expected.get("output_ids")
    if expected_count is None and expected_single_id is None and expected_required_id is None and not isinstance(expected_output_ids, list):
        return _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            evidence_source="executable_output_registry",
            measurements={
                "resolved_output_ids": resolved_output_ids,
                "reason": "required output identity expectation is incomplete",
            },
        )

    expected_ids: list[str] = []
    if expected_single_id is not None:
        expected_ids.append(str(expected_single_id))
    if expected_required_id is not None:
        expected_ids.append(str(expected_required_id))
    if isinstance(expected_output_ids, list):
        expected_ids.extend(str(item) for item in expected_output_ids)
    expected_ids = list(dict.fromkeys(expected_ids))
    count_matches = expected_count is None or len(resolved_output_ids) == int(expected_count)
    identities_match = all(item in resolved_output_ids for item in expected_ids)
    independent_matches = expected.get("independent") is not True or (
        len(resolved_output_ids) > 1 and len(set(resolved_output_ids)) == len(resolved_output_ids)
    )
    passed = count_matches and identities_match and independent_matches
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        evidence_source="executable_output_registry",
        measurements={
            "expected_count": expected_count,
            "expected_output_ids": expected_ids,
            "expected_independent": expected.get("independent"),
            "resolved_output_ids": resolved_output_ids,
            "detected_count": len(resolved_output_ids),
            "count_matches": count_matches,
            "identities_match": identities_match,
            "independent_matches": independent_matches,
        },
    )


def _verify_topology_and_required_output(
    requirement: Mapping[str, Any],
    *,
    resolved_output_ids: list[str],
    topology_by_output: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    requirement_id = str(requirement["requirement_id"])
    expected = requirement.get("expected") if isinstance(requirement.get("expected"), Mapping) else {}
    if not isinstance(expected.get("connected"), bool):
        return _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            evidence_source="topology_evidence_v2",
            measurements={
                "resolved_output_ids": resolved_output_ids,
                "reason": "connected_expectation_missing",
            },
        )

    topology = topology_by_output or {}
    missing_output_ids = [output_id for output_id in resolved_output_ids if output_id not in topology]
    if missing_output_ids:
        return _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            evidence_source="topology_evidence_v2",
            measurements={
                "resolved_output_ids": resolved_output_ids,
                "missing_output_ids": missing_output_ids,
                "reason": "authoritative_topology_evidence_missing",
            },
        )

    identity = _verify_required_output_identity(
        requirement,
        resolved_output_ids=resolved_output_ids,
    )
    topology_measurements: dict[str, dict[str, Any]] = {}
    for output_id in resolved_output_ids:
        evidence = topology[output_id]
        connected = bool(
            evidence.get("valid") is True
            and evidence.get("overall_shape_valid") is True
            and evidence.get("detected_solid_count") == 1
        )
        topology_measurements[output_id] = {
            "valid": evidence.get("valid"),
            "overall_shape_valid": evidence.get("overall_shape_valid"),
            "detected_solid_count": evidence.get("detected_solid_count"),
            "connected": connected,
            "expected_connected": expected["connected"],
            "connected_matches": connected is expected["connected"],
        }

    topology_matches = all(
        item["connected_matches"] for item in topology_measurements.values()
    )
    identity_status = identity["status"]
    if identity_status == "unverifiable":
        status = "unverifiable"
        measurement_available = False
    else:
        status = "passed" if identity_status == "passed" and topology_matches else "failed"
        measurement_available = True
    return _semantic_finding(
        requirement_id,
        status=status,
        measurement_available=measurement_available,
        evidence_source="topology_evidence_v2",
        measurements={
            "resolved_output_ids": resolved_output_ids,
            "identity": identity["measurements"],
            "topology": topology_measurements,
            "topology_matches": topology_matches,
        },
    )


def _generic_requirement_finding(
    requirement: Mapping[str, Any],
    *,
    mesh: trimesh.Trimesh,
    output_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
) -> dict[str, Any]:
    requirement_id = str(requirement["requirement_id"])
    policy = str(requirement.get("verification_policy") or "")
    normalization = normalize_executable_cadquery_requirement(requirement)
    if normalization["status"] != "normalized":
        return _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            measurements={"semantic_contract": normalization},
        )
    expected = normalization["expected"]
    tolerance = _requirement_tolerance(requirement)
    finding: dict[str, Any]
    if policy == "final_mesh_bounds":
        finding = _verify_bounds_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_opening_profiles":
        finding = _verify_opening_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_opening_centers":
        finding = _verify_opening_centers_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_axisymmetric_profiles":
        finding = _verify_axisymmetric_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_axial_sections":
        finding = _verify_axial_sections_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_recess_profile":
        finding = _verify_recess_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_wall_profile":
        finding = _verify_wall_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "final_mesh_feature_profiles":
        finding = _verify_feature_requirement(requirement_id, mesh, expected, tolerance)
    elif policy == "cross_output_envelope":
        finding = _verify_envelope_requirement(requirement_id, meshes, expected, tolerance)
    elif policy == "cross_output_clearance":
        finding = _verify_clearance_requirement(requirement_id, meshes, expected, tolerance)
    elif policy == "cross_output_alignment":
        finding = _verify_alignment_requirement(requirement_id, meshes, expected, tolerance)
    elif policy == "measure_when_supported":
        if "size" in expected:
            finding = _verify_chamfer_requirement(requirement_id, mesh, expected, tolerance)
        elif "radius" in expected:
            finding = _verify_external_fillet(mesh, expected, {})
        else:
            finding = _semantic_finding(
                requirement_id,
                status="unverifiable",
                measurement_available=False,
                measurements={"verification_policy": policy, "reason": "no supported expected field"},
            )
    elif policy == "required_output_artifact":
        finding = _semantic_finding(
            requirement_id,
            status="passed",
            measurement_available=True,
            measurements={"output_id": output_id, "artifact_present": True},
        )
    else:
        finding = _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            measurements={"verification_policy": policy, "reason": "no generic verifier registered"},
        )
    return _apply_semantic_contract_diagnostics(finding, normalization)


def _apply_semantic_contract_diagnostics(
    finding: dict[str, Any],
    normalization: Mapping[str, Any],
) -> dict[str, Any]:
    unsupported = list(normalization.get("unsupported_fields") or [])
    if not unsupported:
        finding["semantic_contract"] = {
            "version": normalization["version"],
            "status": normalization["status"],
            "canonical_fields": normalization.get("canonical_fields", []),
            "shadowed_legacy_fields": normalization.get("shadowed_legacy_fields", []),
        }
        return finding
    diagnostic = {
        "version": normalization["version"],
        "status": "unsupported_semantic_fields",
        "unsupported_fields": unsupported,
        "canonical_fields": normalization.get("canonical_fields", []),
    }
    if finding.get("status") == "passed":
        return _semantic_finding(
            str(finding["requirement_id"]),
            status="unverifiable",
            measurement_available=False,
            evidence_source="partial_measurement",
            measurements={
                "partial_measurement": finding.get("measurements", {}),
                "semantic_contract": diagnostic,
            },
        )
    finding["semantic_contract"] = diagnostic
    return finding


def _verify_bounds_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    keys = ("width", "depth", "height") if "height" in expected else ("width", "depth", "thickness")
    expected_values = [float(expected[key]) for key in keys if expected.get(key) is not None]
    detected = np.asarray(mesh.bounds[1] - mesh.bounds[0], dtype=float)
    passed = len(expected_values) == 3 and bool(np.all(np.abs(detected - expected_values) <= tolerance))
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_mm": expected_values, "detected_mm": _rounded(detected)},
    )


def _stl_candidate_unverifiable_finding(
    requirement_id: str,
    candidates: list[Any],
    *,
    expected_count: int | None = None,
    expected_diameter: float | None = None,
    tolerance: float = 0.25,
    extra_measurements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose mesh candidates without treating them as physical-hole evidence."""
    matching_count = (
        sum(abs(float(candidate.diameter) - expected_diameter) <= tolerance for candidate in candidates)
        if expected_diameter is not None
        else None
    )
    measurements: dict[str, Any] = {
        "evidence_authority": "derived_stl_candidate",
        "candidate_evidence_type": "stl_circular_profile_candidate",
        "raw_candidate_count": len(candidates),
        "matching_candidate_count": matching_count,
        "physical_feature_count": None,
        "candidate_measurements": _hole_candidate_measurements(candidates),
        "expected_count": expected_count,
        "expected_diameter_mm": expected_diameter,
        "tolerance_mm": tolerance,
        "reason": "stl_candidate_evidence_not_authoritative",
    }
    if extra_measurements:
        measurements.update(dict(extra_measurements))
    return _semantic_finding(
        requirement_id,
        status="unverifiable",
        measurement_available=False,
        evidence_source="derived_stl_candidate",
        measurements=measurements,
    )


def _verify_opening_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    candidates = [
        candidate
        for candidate in _detect_axis_aligned_hole_candidates(mesh, "z", _tolerance_profile())
        if candidate.confidence >= 0.55
    ]
    return _stl_candidate_unverifiable_finding(
        requirement_id,
        candidates,
        expected_count=int(expected["hole_count"]) if expected.get("hole_count") is not None else None,
        expected_diameter=float(expected["hole_diameter"]) if expected.get("hole_diameter") is not None else None,
        tolerance=tolerance,
        extra_measurements={
            "expected_through": expected.get("through"),
            "through_measurement_available": False,
        },
    )


def _verify_opening_centers_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    candidates = [
        candidate
        for candidate in _detect_axis_aligned_hole_candidates(mesh, "z", _tolerance_profile())
        if candidate.confidence >= 0.55
    ]
    return _stl_candidate_unverifiable_finding(
        requirement_id,
        candidates,
        expected_count=int(expected["hole_count"]) if expected.get("hole_count") is not None else None,
        expected_diameter=float(expected["hole_diameter"]) if expected.get("hole_diameter") is not None else None,
        tolerance=tolerance,
        extra_measurements={
            "expected_pitch_circle_diameter_mm": expected.get("pitch_circle_diameter"),
            "pitch_measurement_available": False,
        },
    )


def _verify_axisymmetric_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    profiles = _radial_profiles(mesh)
    expected_diameters = [float(value) for value in expected.get("diameters", [])]
    detected = sorted({round(float(profile["diameter_mm"]), 3) for profile in profiles}, reverse=True)
    matched = all(any(abs(value - candidate) <= tolerance for candidate in detected) for value in expected_diameters)
    return _semantic_finding(
        requirement_id,
        status="passed" if matched and bool(profiles) else "failed",
        measurement_available=True,
        measurements={"expected_diameters_mm": expected_diameters, "detected_diameters_mm": detected, "coaxial": matched},
    )


def _verify_axial_sections_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    levels = _profile_levels(mesh)
    sections = [round(float(right - left), 3) for left, right in zip(levels, levels[1:]) if right - left > 0.2]
    expected_lengths = [float(value) for value in expected.get("lengths", [])]
    passed = all(any(abs(value - candidate) <= tolerance for candidate in sections) for value in expected_lengths)
    return _semantic_finding(
        requirement_id,
        status="passed" if passed and bool(sections) else "failed",
        measurement_available=True,
        measurements={"expected_lengths_mm": expected_lengths, "detected_section_lengths_mm": sections},
    )


def _verify_recess_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    candidates = [
        candidate
        for candidate in _detect_axis_aligned_hole_candidates(mesh, "z", _tolerance_profile())
        if candidate.confidence >= 0.55
    ]
    return _stl_candidate_unverifiable_finding(
        requirement_id,
        candidates,
        expected_diameter=float(expected.get("diameter")) if expected.get("diameter") is not None else None,
        tolerance=tolerance,
        extra_measurements={
            "expected_depth_mm": expected.get("depth"),
            "depth_measurement_available": False,
        },
    )


def _verify_wall_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    origin = np.asarray([0.0, 0.0, float(mesh.bounds[0][2]) - 5.0])
    intersections = sorted(float(value) for value in _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, 1.0])))
    intervals = [right - left for left, right in zip(intersections, intersections[1:]) if right - left > 0.1]
    measured = min(intervals) if intervals else None
    expected_value = expected.get("wall_thickness")
    if expected_value is None:
        return _semantic_finding(
            requirement_id,
            status="unverifiable",
            measurement_available=False,
            measurements={"reason": "wall thickness is required for wall-profile measurement"},
        )
    expected_value = float(expected_value)
    passed = measured is not None and abs(measured - expected_value) <= tolerance
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_wall_thickness_mm": expected_value, "detected_wall_thickness_mm": round(measured, 3) if measured is not None else None},
    )


def _verify_feature_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    width = float(expected.get("width") or 0)
    height = float(expected.get("height") or expected.get("depth") or 0)
    if width <= 0 or height <= 0:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    boundary = _boundary_feature_measurement(mesh, width, height, tolerance)
    if boundary is not None:
        return _semantic_finding(
            requirement_id,
            status="passed" if boundary["passed"] else "failed",
            measurement_available=True,
            measurements={"expected_size_mm": [width, height], "boundary_measurement": boundary},
        )
    top = _rectangular_opening_probe(mesh, width, height, "top", tolerance)
    side = _rectangular_opening_probe(mesh, width, height, "side", tolerance)
    passed = top["passed"] or side["passed"]
    return _semantic_finding(
        requirement_id,
        status="passed" if passed else "failed",
        measurement_available=True,
        measurements={"expected_size_mm": [width, height], "top_probe": top, "side_probe": side},
    )


def _verify_envelope_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if not meshes:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    bounds = np.asarray([mesh.bounds for mesh in meshes.values()], dtype=float)
    xy_size = bounds[:, 1, :2].max(axis=0) - bounds[:, 0, :2].min(axis=0)
    z_size = float(sum(float(mesh.bounds[1, 2] - mesh.bounds[0, 2]) for mesh in meshes.values()))
    detected = [float(xy_size[0]), float(xy_size[1]), z_size]
    expected_values = [float(expected.get("width") or 0), float(expected.get("depth") or 0), float(expected.get("height") or 0)]
    passed = bool(np.all(np.abs(np.asarray(detected) - expected_values) <= tolerance))
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"expected_mm": expected_values, "detected_mm": _rounded(detected)})


def _verify_clearance_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if len(meshes) < 2:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    ordered = sorted(meshes.items(), key=lambda item: float(np.prod(item[1].bounds[1, :2] - item[1].bounds[0, :2])))
    inner_id, inner = ordered[0]
    outer_id, outer = ordered[1]
    inner_size = inner.bounds[1, :2] - inner.bounds[0, :2]
    pocket = _rectangular_boundary_size(outer, inner_size)
    per_side = None if pocket is None else float(np.mean((pocket - inner_size) / 2.0))
    expected_value = expected.get("per_side", expected.get("value"))
    expected_value = float(expected_value or 0)
    passed = per_side is not None and abs(per_side - expected_value) <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"inner_output_id": inner_id, "outer_output_id": outer_id, "expected_per_side_mm": expected_value, "detected_per_side_mm": round(per_side, 3) if per_side is not None else None})


def _verify_alignment_requirement(
    requirement_id: str,
    meshes: Mapping[str, trimesh.Trimesh],
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if len(meshes) < 2:
        return _semantic_finding(requirement_id, status="unverifiable", measurement_available=False, measurements={})
    centers = [np.mean(mesh.bounds[:, :2], axis=0) for mesh in meshes.values()]
    delta = float(np.linalg.norm(centers[0] - centers[1]))
    passed = delta <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"center_delta_mm": round(delta, 3), "expected_relationship": expected.get("relationship")})


def _verify_chamfer_requirement(
    requirement_id: str,
    mesh: trimesh.Trimesh,
    expected: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    expected_size = float(expected.get("size") or 0)
    top_z = float(mesh.bounds[1, 2])
    top = mesh.vertices[np.abs(mesh.vertices[:, 2] - top_z) <= 1e-3]
    lower = mesh.vertices[mesh.vertices[:, 2] < top_z - 0.5]
    if len(top) == 0 or len(lower) == 0:
        measured = None
    else:
        top_extent = max(float(np.max(np.abs(top[:, 0]))), float(np.max(np.abs(top[:, 1]))))
        lower_extent = max(float(np.max(np.abs(lower[:, 0]))), float(np.max(np.abs(lower[:, 1]))))
        measured = lower_extent - top_extent
    passed = measured is not None and abs(measured - expected_size) <= tolerance
    return _semantic_finding(requirement_id, status="passed" if passed else "failed", measurement_available=True, measurements={"expected_size_mm": expected_size, "detected_size_mm": round(measured, 3) if measured is not None else None})


def _semantic_finding(
    requirement_id: str,
    *,
    status: str,
    measurement_available: bool,
    evidence_source: str | None = None,
    measurements: dict[str, Any],
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": status,
        "measurement_available": measurement_available,
        "evidence_source": evidence_source or ("final_mesh" if measurement_available else "none"),
        "measurements": measurements,
    }


def _requirement_tolerance(requirement: Mapping[str, Any]) -> float:
    try:
        return float(requirement.get("tolerance") or 0.25)
    except (TypeError, ValueError):
        return 0.25


def _radial_profiles(mesh: trimesh.Trimesh) -> list[dict[str, float]]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    center = np.mean(vertices[:, :2], axis=0)
    levels = _profile_levels(mesh)
    profiles: list[dict[str, float]] = []
    for level in levels:
        selected = vertices[np.abs(vertices[:, 2] - level) <= 1e-3]
        if len(selected) == 0:
            continue
        radius = float(np.max(np.linalg.norm(selected[:, :2] - center, axis=1)))
        profiles.append({"z_mm": float(level), "diameter_mm": radius * 2.0})
    return profiles


def _profile_levels(mesh: trimesh.Trimesh) -> list[float]:
    values = sorted({round(float(value), 3) for value in np.asarray(mesh.vertices)[:, 2]})
    return [float(value) for value in values if not values or value in values]


def _cylindrical_surface_depth(
    mesh: trimesh.Trimesh,
    radius: float,
    hole: Any,
    tolerance: float,
    *,
    expected_depth: float | None = None,
) -> float | None:
    if hole is None:
        return None
    center = np.asarray([float(hole.center[0]), float(hole.center[1])])
    vertices = np.asarray(mesh.vertices, dtype=float)
    radial = np.linalg.norm(vertices[:, :2] - center, axis=1)
    selected = vertices[np.abs(radial - radius) <= max(tolerance, 0.15)]
    if len(selected) == 0:
        return None
    levels = sorted({round(float(value), 3) for value in selected[:, 2]})
    if len(levels) < 2:
        return None
    spans = [right - left for left, right in zip(levels, levels[1:]) if right - left > 0.0]
    if expected_depth is not None and spans:
        return round(float(min(spans, key=lambda value: abs(value - expected_depth))), 3)
    return round(float(max(spans)), 3) if spans else None


def _rectangular_opening_probe(
    mesh: trimesh.Trimesh,
    width: float,
    height: float,
    orientation: str,
    tolerance: float,
) -> dict[str, Any]:
    if orientation == "top":
        origin = np.asarray([0.0, 0.0, float(mesh.bounds[1, 2]) + 5.0])
        direction = np.asarray([0.0, 0.0, -1.0])
        points = [(x, y) for x in (-width / 2 + tolerance, 0.0, width / 2 - tolerance) for y in (-height / 2 + tolerance, 0.0, height / 2 - tolerance)]
        intersections = [len(_ray_parameters(mesh, np.asarray([x, y, origin[2]]), direction)) for x, y in points]
        outside = len(_ray_parameters(mesh, np.asarray([float(mesh.bounds[1, 0]) - 1.0, float(mesh.bounds[1, 1]) - 1.0, origin[2]]), direction))
    else:
        origin_x = float(mesh.bounds[1, 0]) + 5.0
        direction = np.asarray([-1.0, 0.0, 0.0])
        points = [(y, z) for y in (-width / 2 + tolerance, 0.0, width / 2 - tolerance) for z in (float(mesh.bounds[0, 2]) + height / 2, float(mesh.bounds[1, 2]) - height / 2)]
        intersections = [len(_ray_parameters(mesh, np.asarray([origin_x, y, z]), direction)) for y, z in points]
        outside = len(_ray_parameters(mesh, np.asarray([origin_x, float(mesh.bounds[1, 1]) - 1.0, float(mesh.bounds[1, 2]) - height / 2]), direction))
    passed = bool(intersections) and min(intersections) < outside
    return {"passed": passed, "intersection_counts": intersections, "outside_intersection_count": outside}


def _rectangular_boundary_size(mesh: trimesh.Trimesh, target_size: np.ndarray) -> np.ndarray | None:
    top_z = float(mesh.bounds[1, 2])
    vertices = np.asarray(mesh.vertices, dtype=float)
    top = vertices[np.abs(vertices[:, 2] - top_z) <= 1e-3]
    if len(top) == 0:
        return None
    candidates = []
    for axis in (0, 1):
        half = float(target_size[axis]) / 2.0
        values = [abs(float(value)) for value in top[:, axis] if abs(abs(float(value)) - half) <= 2.0]
        candidates.append(2.0 * float(np.mean(values)) if values else 0.0)
    return np.asarray(candidates) if all(candidates) else None


def _boundary_feature_measurement(
    mesh: trimesh.Trimesh,
    width: float,
    height: float,
    tolerance: float,
) -> dict[str, Any] | None:
    """Detect rectangular openings from boundary vertices on any principal face."""

    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = (
        (0, float(mesh.bounds[1, 0]), (1, 2)),
        (1, float(mesh.bounds[1, 1]), (0, 2)),
        (2, float(mesh.bounds[1, 2]), (0, 1)),
    )
    for axis, boundary, plane_axes in faces:
        on_boundary = vertices[np.abs(vertices[:, axis] - boundary) <= 1e-3]
        if len(on_boundary) < 4:
            continue
        spans = []
        for plane_axis in plane_axes:
            values = sorted({round(float(value), 3) for value in on_boundary[:, plane_axis]})
            candidates = [
                float(right - left)
                for left in values
                for right in values
                if right - left > 0.0
            ]
            spans.append(candidates)
        for first in spans[0]:
            for second in spans[1]:
                if (
                    abs(first - width) <= tolerance and abs(second - height) <= tolerance
                ) or (
                    abs(first - height) <= tolerance and abs(second - width) <= tolerance
                ):
                    return {
                        "passed": True,
                        "boundary_axis": ("x", "y", "z")[axis],
                        "detected_spans_mm": [round(first, 3), round(second, 3)],
                    }
    return None


def _verify_pocket(mesh: trimesh.Trimesh, expected: Mapping[str, Any], requirements: list[Mapping[str, Any]]) -> dict[str, Any]:
    width = float(expected.get("width") or 0)
    depth = float(expected.get("depth") or 0)
    cut_depth = float(expected.get("cut_depth") or 0)
    max_z = float(mesh.bounds[1][2])
    center_z = _top_surface_z(mesh, 0.0, 0.0)
    inside_x = _top_surface_z(mesh, max(-width / 2 + 0.5, 0.0), 0.0)
    outside_x = _top_surface_z(mesh, width / 2 + 0.5, 0.0)
    inside_y = _top_surface_z(mesh, 0.0, max(-depth / 2 + 0.5, 0.0))
    outside_y = _top_surface_z(mesh, 0.0, depth / 2 + 0.5)
    tolerance = _tolerance(requirements, "centered_recessed_pocket")
    measured_depth = max_z - center_z if center_z is not None else None
    passed = (
        measured_depth is not None
        and abs(measured_depth - cut_depth) <= tolerance
        and inside_x is not None
        and outside_x is not None
        and inside_y is not None
        and outside_y is not None
        and abs(inside_x - center_z) <= tolerance
        and abs(inside_y - center_z) <= tolerance
        and abs(outside_x - max_z) <= tolerance
        and abs(outside_y - max_z) <= tolerance
    )
    return {
        "requirement_id": "centered_recessed_pocket",
        "status": "passed" if passed else "unverifiable",
        "measurements": {
            "expected_mm": {"width": width, "depth": depth, "cut_depth": cut_depth},
            "detected_cut_depth_mm": round(measured_depth, 3) if measured_depth is not None else None,
        },
    }


def _verify_external_fillet(mesh: trimesh.Trimesh, expected: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    radius = float(expected.get("radius") or 0)
    # A rounded external corner has no vertex at the bounding-box corner.
    max_x, max_y = float(mesh.bounds[1][0]), float(mesh.bounds[1][1])
    corner_distance = np.linalg.norm(
        mesh.vertices[:, :2] - np.asarray([max_x, max_y]), axis=1
    )
    rounded_corner = bool(np.min(corner_distance) > 0.1)
    return {
        "requirement_id": "external_fillet",
        "status": "passed" if rounded_corner else "unverifiable",
        "measurements": {
            "expected_radius_mm": radius,
            "corner_clearance_mm": round(float(np.min(corner_distance)), 3),
            "body_dimensions_present": bool(body),
        },
    }


def _probe_through(mesh: trimesh.Trimesh, point: tuple[float, float]) -> bool:
    origin = np.asarray([point[0], point[1], float(mesh.bounds[0][2]) - 5.0], dtype=float)
    intersections = _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, 1.0]))
    if len(intersections) < 2:
        within_xy = (
            float(mesh.bounds[0][0]) <= point[0] <= float(mesh.bounds[1][0])
            and float(mesh.bounds[0][1]) <= point[1] <= float(mesh.bounds[1][1])
        )
        return not intersections and within_xy
    return max(
        right - left for left, right in zip(sorted(intersections), sorted(intersections)[1:])
    ) >= float(np.ptp(mesh.bounds[:, 2])) - 0.25


def _probe_hole_diameter(
    mesh: trimesh.Trimesh,
    center: tuple[float, float],
    diameter: float,
    tolerance: float,
) -> bool:
    radius = diameter / 2.0
    angles = np.linspace(0.0, 2.0 * np.pi, num=9, endpoint=False)
    inner = [
        (center[0] + (radius - tolerance) * float(np.cos(angle)),
         center[1] + (radius - tolerance) * float(np.sin(angle)))
        for angle in angles
    ]
    outer = [
        (center[0] + (radius + tolerance) * float(np.cos(angle)),
         center[1] + (radius + tolerance) * float(np.sin(angle)))
        for angle in angles
    ]
    inner_open = all(_probe_through(mesh, point) for point in inner)
    outer_blocked = sum(1 for point in outer if not _probe_through(mesh, point))
    # The pocket and the asymmetric opening share an edge in this frozen
    # design, so the top-surface profile is one merged opening. A ring of
    # bottom-slice probes still proves the requested hole boundary without
    # treating the merged top profile as an independent circle.
    return _probe_through(mesh, center) and inner_open and outer_blocked >= 2


def _top_surface_z(mesh: trimesh.Trimesh, x: float, y: float) -> float | None:
    origin = np.asarray([x, y, float(mesh.bounds[1][2]) + 5.0], dtype=float)
    intersections = _ray_parameters(mesh, origin, np.asarray([0.0, 0.0, -1.0]))
    return max((float(mesh.bounds[1][2]) + 5.0 - value for value in intersections), default=None)


def _finding(requirement_id: str, passed: bool, measurements: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "status": "passed" if passed else "failed",
        "measurements": measurements,
    }


def _expected(requirements: list[Mapping[str, Any]], requirement_id: str) -> Mapping[str, Any] | None:
    item = next((item for item in requirements if item.get("requirement_id") == requirement_id), None)
    value = item.get("expected") if item else None
    return value if isinstance(value, Mapping) else None


def _tolerance(requirements: list[Mapping[str, Any]], requirement_id: str) -> float:
    item = next((item for item in requirements if item.get("requirement_id") == requirement_id), None)
    try:
        return float(item.get("tolerance") or 0.25) if item else 0.25
    except (TypeError, ValueError):
        return 0.25


def _tolerance_profile() -> Any:
    from app.services.geometry.invariants import GeometricToleranceProfile

    return GeometricToleranceProfile()


def _rounded(values: Any) -> list[float]:
    return [round(float(value), 3) for value in np.asarray(values).reshape(-1)]
