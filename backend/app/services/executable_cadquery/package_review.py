"""Neutral measurements and independent final-package review inputs.

The report is deliberately derived from packaged artifacts, not from source
text or producer-side semantic claims.  It is safe to hand to a blind
reviewer as standardized geometry evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np
import trimesh

from app.services.geometry.invariants import GeometricToleranceProfile, _detect_axis_aligned_holes


NEUTRAL_MEASUREMENT_REPORT_VERSION = "executable-cadquery-neutral-measurement-v1"


def build_neutral_measurement_report(
    package_path: Path,
    package_manifest: Mapping[str, Any],
    *,
    previous_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure every packaged STL without consulting its design contract."""

    artifacts = package_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("package manifest has no packaged artifacts")

    outputs: list[dict[str, Any]] = []
    meshes: dict[str, dict[str, Any]] = {}
    with ZipFile(package_path) as archive:
        names = set(archive.namelist())
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or not artifact.get("output_id"):
                raise ValueError("package manifest contains an invalid artifact identity")
            output_id = str(artifact["output_id"])
            stl = artifact.get("stl")
            if not isinstance(stl, Mapping) or not stl.get("path"):
                raise ValueError(f"packaged output {output_id} has no STL")
            stl_path = str(stl["path"])
            if stl_path not in names:
                raise ValueError(f"package is missing STL for output {output_id}")
            stl_bytes = archive.read(stl_path)
            mesh = _load_mesh(stl_bytes, output_id)
            measurement = _measure_mesh(mesh, output_id)
            measurement["artifact_hashes"] = _artifact_hashes(archive, artifact, names)
            measurement["package_entry"] = stl_path
            measurement["mesh_sha256"] = sha256(stl_bytes).hexdigest()
            outputs.append(measurement)
            meshes[output_id] = {
                "min": np.asarray(mesh.bounds[0], dtype=float),
                "max": np.asarray(mesh.bounds[1], dtype=float),
            }

    outputs.sort(key=lambda item: item["output_id"])
    report = {
        "schema_version": NEUTRAL_MEASUREMENT_REPORT_VERSION,
        "units": "mm",
        "package_sha256": _sha256_file(package_path),
        "output_identities": [item["output_id"] for item in outputs],
        "outputs": outputs,
        "relationships": _relationships(meshes),
        "revision_deltas": _revision_deltas(outputs, previous_report),
    }
    return report


def _load_mesh(payload: bytes, output_id: str) -> trimesh.Trimesh:
    try:
        loaded = trimesh.load(BytesIO(payload), file_type="stl", force="mesh")
        mesh = loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)
    except Exception as exc:  # pragma: no cover - defensive package boundary
        raise ValueError(f"packaged STL for output {output_id} could not be measured") from exc
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"packaged STL for output {output_id} has no measurable faces")
    return mesh


def _measure_mesh(mesh: trimesh.Trimesh, output_id: str) -> dict[str, Any]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    size = bounds[1] - bounds[0]
    solids = len(mesh.split(only_watertight=False))
    volume = float(mesh.volume)
    if not math.isfinite(volume):
        volume_value = None
    else:
        volume_value = round(abs(volume), 6)
    return {
        "output_id": output_id,
        "solid_count": int(solids),
        "watertight": bool(mesh.is_watertight),
        "bounding_box_mm": {
            "min": _rounded(bounds[0]),
            "max": _rounded(bounds[1]),
            "size": _rounded(size),
        },
        "volume_mm3": volume_value,
        "hole_or_cylinder_measurements": _hole_measurements(mesh),
        "planar_face_measurements": _planar_face_measurements(mesh),
    }


def _hole_measurements(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    tolerance = GeometricToleranceProfile()
    measurements: list[dict[str, Any]] = []
    for axis in ("x", "y", "z"):
        for hole in _detect_axis_aligned_holes(mesh, axis, tolerance):
            measurements.append(
                {
                    "axis": axis,
                    "center_mm": _rounded(hole.center),
                    "diameter_mm": round(float(hole.diameter), 4),
                    "confidence": round(float(hole.confidence), 4),
                }
            )
    measurements.sort(key=lambda item: (item["axis"], item["center_mm"], item["diameter_mm"]))
    return measurements


def _planar_face_measurements(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    measurements: list[dict[str, Any]] = []
    for axis_index, axis in enumerate(("x", "y", "z")):
        for sign in (-1, 1):
            mask = (np.abs(normals[:, axis_index]) >= 0.999) & (np.sign(normals[:, axis_index]) == sign)
            if not np.any(mask):
                continue
            measurements.append(
                {
                    "axis": axis,
                    "normal_sign": sign,
                    "face_count": int(np.count_nonzero(mask)),
                    "total_area_mm2": round(float(np.sum(areas[mask])), 6),
                    "plane_positions_mm": sorted(
                        {round(float(value), 4) for value in centers[mask, axis_index]}
                    ),
                }
            )
    return measurements


def _artifact_hashes(
    archive: ZipFile,
    artifact: Mapping[str, Any],
    names: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for kind in ("stl", "step", "brep"):
        reference = artifact.get(kind)
        if not isinstance(reference, Mapping) or not reference.get("path"):
            continue
        path = str(reference["path"])
        if path not in names:
            result[kind] = {
                "path": path,
                "declared_sha256": reference.get("sha256"),
                "observed_sha256": None,
                "available": False,
            }
            continue
        payload = archive.read(path)
        result[kind] = {
            "path": path,
            "declared_sha256": reference.get("sha256"),
            "observed_sha256": sha256(payload).hexdigest(),
            "available": True,
        }
    return result


def _relationships(meshes: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ids = sorted(meshes)
    relationships: list[dict[str, Any]] = []
    for index, left_id in enumerate(ids):
        left = meshes[left_id]
        for right_id in ids[index + 1 :]:
            right = meshes[right_id]
            left_min, left_max = np.asarray(left["min"]), np.asarray(left["max"])
            right_min, right_max = np.asarray(right["min"]), np.asarray(right["max"])
            axis_gap = np.maximum(np.maximum(left_min - right_max, right_min - left_max), 0.0)
            relationships.append(
                {
                    "left_output_id": left_id,
                    "right_output_id": right_id,
                    "aabb_intersects": bool(np.all(axis_gap == 0.0)),
                    "aabb_axis_gap_mm": _rounded(axis_gap),
                    "center_distance_mm": round(
                        float(
                            np.linalg.norm(
                                ((left_min + left_max) / 2.0) - ((right_min + right_max) / 2.0)
                            )
                        ),
                        6,
                    ),
                }
            )
    return relationships


def _revision_deltas(
    outputs: list[Mapping[str, Any]],
    previous_report: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(previous_report, Mapping):
        return []
    previous = {
        str(item.get("output_id")): item
        for item in previous_report.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    }
    deltas: list[dict[str, Any]] = []
    for output in outputs:
        output_id = str(output["output_id"])
        prior = previous.get(output_id)
        if prior is None:
            continue
        current_size = output["bounding_box_mm"]["size"]
        prior_size = prior.get("bounding_box_mm", {}).get("size", [])
        current_volume = output.get("volume_mm3")
        prior_volume = prior.get("volume_mm3")
        current_hash = output.get("artifact_hashes", {}).get("stl", {}).get("observed_sha256")
        prior_hash = prior.get("artifact_hashes", {}).get("stl", {}).get("observed_sha256")
        deltas.append(
            {
                "output_id": output_id,
                "artifact_hash_changed": current_hash != prior_hash,
                "solid_count_delta": int(output["solid_count"]) - int(prior.get("solid_count", 0)),
                "volume_delta_mm3": _number_or_none(
                    None if current_volume is None or prior_volume is None else float(current_volume) - float(prior_volume)
                ),
                "bounding_box_size_delta_mm": _rounded(
                    np.asarray(current_size, dtype=float) - np.asarray(prior_size, dtype=float)
                ),
            }
        )
    return deltas


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rounded(values: Any) -> list[float]:
    return [round(float(value), 6) for value in np.asarray(values, dtype=float).tolist()]


def _number_or_none(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, 6)

