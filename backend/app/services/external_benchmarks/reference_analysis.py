"""Deterministic, generic analysis of evaluator-only reference geometry."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import cadquery as cq
import trimesh
from trimesh import Trimesh

from app.services.cad.topology_evidence import collect_topology_evidence
from app.services.mesh.inspect import inspect_stl


class ReferenceAnalysisError(ValueError):
    """Raised when reference geometry cannot be read or measured."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReferenceAnalysisError(f"unable to read reference file: {path}") from exc
    return digest.hexdigest()


def identify_reference_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".stl":
        return "stl"
    if suffix in {".step", ".stp"}:
        return "step"
    if suffix == ".brep":
        return "brep"
    raise ReferenceAnalysisError(f"unsupported reference file type: {path.suffix or '<none>'}")


def analyze_reference(path: Path, *, file_type: str | None = None, units: str | None = None) -> dict[str, Any]:
    if not path.exists():
        raise ReferenceAnalysisError(f"reference file does not exist: {path}")
    if not path.is_file():
        raise ReferenceAnalysisError(f"reference path is not a file: {path}")
    detected_type = file_type or identify_reference_type(path)
    if detected_type == "stl":
        return _analyze_stl(path, units=units)
    if detected_type in {"step", "brep"}:
        return _analyze_brep(path, file_type=detected_type, units=units)
    raise ReferenceAnalysisError(f"unsupported reference file type: {detected_type}")


def _analyze_stl(path: Path, *, units: str | None) -> dict[str, Any]:
    try:
        inspected = inspect_stl(path)
        mesh = _as_mesh(trimesh.load(path, force="mesh"))
    except Exception as exc:
        raise ReferenceAnalysisError(f"STL geometry could not be analyzed: {type(exc).__name__}") from exc
    if len(mesh.faces) == 0:
        raise ReferenceAnalysisError("STL geometry contains no faces")
    extents = mesh.bounding_box.extents
    center = tuple(float(value) for value in mesh.center_mass)
    return {
        "schema_version": "external-cad-reference-derived-v1",
        "file_type": "stl",
        "units": units or "assumed_mm",
        "geometry": {
            "bounding_box_mm": {
                "size_x": float(extents[0]),
                "size_y": float(extents[1]),
                "size_z": float(extents[2]),
            },
            "solid_count": 1 if mesh.is_watertight and abs(float(mesh.volume)) > 0 else None,
            "component_count": int(len(mesh.split(only_watertight=False))),
            "volume_mm3": float(abs(mesh.volume)),
            "surface_area_mm2": float(mesh.area),
            "center_of_mass_mm": center,
        },
        "mesh": {
            "vertex_count": int(len(mesh.vertices)),
            "face_count": int(len(mesh.faces)),
            "component_count": inspected.connected_components,
            "watertight": inspected.is_watertight,
            "winding_consistent": inspected.is_winding_consistent,
        },
    }


def _analyze_brep(path: Path, *, file_type: str, units: str | None) -> dict[str, Any]:
    try:
        imported = cq.importers.importStep(str(path)) if file_type == "step" else cq.importers.importBrep(str(path))
        shape = imported.val() if hasattr(imported, "val") else imported
        solids = list(shape.Solids())
        bounding_box = shape.BoundingBox()
        surface_area = sum(float(face.Area()) for face in shape.Faces())
        topology = collect_topology_evidence(
            shape,
            expected_solid_count=len(solids),
            allow_disconnected_solids=True,
        )
        center = cq.Shape.centerOfMass(shape)
    except Exception as exc:
        raise ReferenceAnalysisError(f"{file_type.upper()} geometry could not be analyzed: {type(exc).__name__}") from exc
    return {
        "schema_version": "external-cad-reference-derived-v1",
        "file_type": file_type,
        "units": units or "unverified_model_units",
        "geometry": {
            "bounding_box_mm": {
                "size_x": float(bounding_box.xlen),
                "size_y": float(bounding_box.ylen),
                "size_z": float(bounding_box.zlen),
            },
            "solid_count": len(solids),
            "component_count": len(solids),
            "volume_mm3": float(shape.Volume()),
            "surface_area_mm2": surface_area,
            "center_of_mass_mm": tuple(float(value) for value in center.toTuple()),
        },
        "topology": topology,
    }


def _as_mesh(loaded: object) -> Trimesh:
    if isinstance(loaded, trimesh.Scene):
        meshes = [item for item in loaded.geometry.values() if isinstance(item, Trimesh)]
        if not meshes:
            raise ReferenceAnalysisError("STL contains no mesh geometry")
        return trimesh.util.concatenate(meshes)
    if isinstance(loaded, Trimesh):
        return loaded
    raise ReferenceAnalysisError("unsupported mesh geometry")
