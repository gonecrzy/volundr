from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from trimesh import Trimesh


@dataclass(frozen=True)
class MeshMetadata:
    size_x_mm: float
    size_y_mm: float
    size_z_mm: float
    volume_mm3: float
    triangle_count: int
    connected_components: int
    is_watertight: bool
    is_winding_consistent: bool
    center_of_mass: tuple[float, float, float]


def inspect_stl(path: Path) -> MeshMetadata:
    loaded = trimesh.load(path, force="mesh")
    mesh = _as_mesh(loaded)
    if mesh.faces.size == 0:
        raise ValueError("STL contains no faces")

    extents = mesh.bounding_box.extents
    center = mesh.center_mass
    center_tuple = _finite_tuple(center)

    return MeshMetadata(
        size_x_mm=float(extents[0]),
        size_y_mm=float(extents[1]),
        size_z_mm=float(extents[2]),
        volume_mm3=float(abs(mesh.volume)),
        triangle_count=int(len(mesh.faces)),
        connected_components=_connected_component_count(mesh),
        is_watertight=bool(mesh.is_watertight),
        is_winding_consistent=bool(mesh.is_winding_consistent),
        center_of_mass=center_tuple,
    )


def _as_mesh(loaded: object) -> Trimesh:
    if isinstance(loaded, trimesh.Scene):
        meshes = [geometry for geometry in loaded.geometry.values() if isinstance(geometry, Trimesh)]
        if not meshes:
            raise ValueError("STL contains no mesh geometry")
        return trimesh.util.concatenate(meshes)
    if isinstance(loaded, Trimesh):
        return loaded
    raise ValueError("unsupported STL geometry")


def _finite_tuple(values: np.ndarray) -> tuple[float, float, float]:
    if values.shape[0] != 3 or not np.all(np.isfinite(values)):
        return (0.0, 0.0, 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))


def _connected_component_count(mesh: Trimesh) -> int:
    face_count = len(mesh.faces)
    if face_count == 0:
        return 0

    parents = list(range(face_count))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left, right in mesh.face_adjacency:
        union(int(left), int(right))

    return len({find(index) for index in range(face_count)})
