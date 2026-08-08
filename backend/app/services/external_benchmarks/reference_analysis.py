"""Deterministic, generic analysis of evaluator-only reference geometry."""

from __future__ import annotations

import hashlib
import zipfile
from xml.etree import ElementTree
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
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
    if suffix == ".3mf":
        return "3mf"
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
    if detected_type == "3mf":
        return _analyze_3mf(path, units=units)
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
        "authority": "mesh_derived",
        "quality_classification": (
            "watertight_mesh_reference" if inspected.is_watertight else "nonwatertight_mesh_reference"
        ),
        "units": units or "assumed_mm",
        "geometry": {
            "bounding_box_mm": {
                "size_x": float(extents[0]),
                "size_y": float(extents[1]),
                "size_z": float(extents[2]),
            },
            "solid_count": inspected.connected_components if mesh.is_watertight else None,
            "component_count": inspected.connected_components,
            "volume_mm3": float(abs(mesh.volume)) if inspected.is_watertight else None,
            "surface_area_mm2": float(mesh.area),
            "center_of_mass_mm": center if inspected.is_watertight else None,
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
            include_solid_pairs=False,
        )
        center = cq.Shape.centerOfMass(shape)
    except Exception as exc:
        raise ReferenceAnalysisError(f"{file_type.upper()} geometry could not be analyzed: {type(exc).__name__}") from exc
    return {
        "schema_version": "external-cad-reference-derived-v1",
        "file_type": file_type,
        "authority": "analytic_brep",
        "quality_classification": (
            "analytic_brep_authoritative" if topology.get("valid") else "invalid_or_unsupported_reference"
        ),
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


def _analyze_3mf(path: Path, *, units: str | None) -> dict[str, Any]:
    """Analyze the mesh objects explicitly built by a 3MF package.

    3MF remains evaluator-only mesh evidence.  This deliberately does not
    repair open meshes or promote them to B-Rep authority.
    """

    try:
        with zipfile.ZipFile(path) as archive:
            model_names = sorted(
                name for name in archive.namelist()
                if name.lower().endswith(".model") and not name.endswith("/")
            )
            if not model_names:
                raise ReferenceAnalysisError("3MF package contains no model XML")
            roots = {name: ElementTree.fromstring(archive.read(name)) for name in model_names}
    except ReferenceAnalysisError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ReferenceAnalysisError(
            f"3MF geometry could not be analyzed: {type(exc).__name__}"
        ) from exc

    def direct_mesh_objects(root: ElementTree.Element) -> dict[str, Trimesh]:
        objects: dict[str, Trimesh] = {}
        for object_node in root.findall(".//{*}object"):
            object_id = object_node.attrib.get("id")
            mesh_node = object_node.find("{*}mesh")
            if not object_id or mesh_node is None:
                continue
            vertices = [
                [float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
                for vertex in mesh_node.findall("./{*}vertices/{*}vertex")
            ]
            faces = [
                [int(triangle.attrib[f"v{index}"]) for index in (1, 2, 3)]
                for triangle in mesh_node.findall("./{*}triangles/{*}triangle")
            ]
            if not vertices or not faces:
                continue
            try:
                objects[object_id] = Trimesh(vertices=vertices, faces=faces, process=False)
            except (TypeError, ValueError) as exc:
                raise ReferenceAnalysisError(
                    f"3MF mesh object {object_id!r} is malformed"
                ) from exc
        return objects

    def transform_mesh(mesh: Trimesh, value: str | None) -> Trimesh:
        if not value:
            return mesh.copy()
        values = [float(item) for item in value.split()]
        if len(values) != 12:
            raise ReferenceAnalysisError("3MF transform must contain twelve numeric values")
        matrix = values[:9]
        translation = values[9:]
        transformed = mesh.copy()
        transformed.vertices = (
            transformed.vertices @ np.array(matrix, dtype=float).reshape(3, 3).T
            + np.array(translation, dtype=float)
        )
        return transformed

    model_objects = {
        name: direct_mesh_objects(root)
        for name, root in roots.items()
    }
    main_name = next(
        (name for name in model_names if name.lower().endswith("/3dmodel.model")),
        model_names[0],
    )
    main_root = roots[main_name]
    main_objects = model_objects[main_name]
    all_objects = [mesh for objects in model_objects.values() for mesh in objects.values()]
    build_items = main_root.findall(".//{*}build/{*}item")
    selected: list[Trimesh] = []
    main_object_nodes = {
        node.attrib.get("id"): node
        for node in main_root.findall(".//{*}object")
        if node.attrib.get("id")
    }
    for item in build_items:
        object_id = item.attrib.get("objectid")
        if object_id in main_objects:
            selected.append(transform_mesh(main_objects[object_id], item.attrib.get("transform")))
            continue
        object_node = main_object_nodes.get(object_id)
        if object_node is None:
            continue
        for component in object_node.findall("./{*}components/{*}component"):
            component_path = next(
                (value for key, value in component.attrib.items() if key.rsplit("}", 1)[-1] == "path"),
                None,
            )
            component_id = component.attrib.get("objectid")
            if not component_path or not component_id:
                continue
            normalized_path = component_path.lstrip("/")
            component_objects = model_objects.get(normalized_path, {})
            component_mesh = component_objects.get(component_id)
            if component_mesh is None:
                continue
            mesh = transform_mesh(component_mesh, component.attrib.get("transform"))
            selected.append(transform_mesh(mesh, item.attrib.get("transform")))
    if not selected:
        selected = list(main_objects.values()) or all_objects
    if not selected:
        raise ReferenceAnalysisError("3MF package contains no mesh objects")
    mesh = trimesh.util.concatenate(selected)
    if len(mesh.faces) == 0:
        raise ReferenceAnalysisError("3MF geometry contains no faces")

    watertight = bool(mesh.is_watertight)
    extents = mesh.bounding_box.extents
    center = tuple(float(value) for value in mesh.center_mass) if watertight else None
    volume = float(abs(mesh.volume)) if watertight and abs(float(mesh.volume)) > 0 else None
    return {
        "schema_version": "external-cad-reference-derived-v1",
        "file_type": "3mf",
        "authority": "mesh_derived",
        "quality_classification": (
            "watertight_mesh_reference" if watertight else "nonwatertight_mesh_reference"
        ),
        "units": units or "assumed_mm",
        "geometry": {
            "bounding_box_mm": {
                "size_x": float(extents[0]),
                "size_y": float(extents[1]),
                "size_z": float(extents[2]),
            },
            "solid_count": len(selected) if watertight and volume is not None else None,
            "component_count": int(len(selected)),
            "volume_mm3": volume,
            "surface_area_mm2": float(mesh.area),
            "center_of_mass_mm": center,
        },
        "mesh": {
            "vertex_count": int(len(mesh.vertices)),
            "face_count": int(len(mesh.faces)),
            "component_count": int(len(selected)),
            "watertight": watertight,
            "winding_consistent": bool(mesh.is_winding_consistent),
            "object_count": int(sum(len(objects) for objects in model_objects.values())),
            "build_item_count": int(len(build_items)),
        },
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
