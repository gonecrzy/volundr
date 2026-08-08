"""Characterize analytic B-Rep facts relevant to future hole evidence.

These tests intentionally describe current OpenCascade observations only.  They
do not implement physical-hole recognition or make semantic verification
authoritative.  The shapes use arbitrary dimensions so the characterization is
independent of the development corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

import cadquery as cq
import pytest


@dataclass(frozen=True)
class CylinderObservation:
    radius: float
    axis_direction: tuple[float, float, float]
    axis_location: tuple[float, float, float]
    z_interval: tuple[float, float]
    orientation: str
    circular_edge_count: int


def _round_tuple(values: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(round(value, 6) for value in values)


def _cylinder_observations(shape: cq.Shape) -> list[CylinderObservation]:
    observations: list[CylinderObservation] = []
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        adaptor = face._geomAdaptor()
        axis = adaptor.Axis()
        bbox = face.BoundingBox()
        observations.append(
            CylinderObservation(
                radius=round(adaptor.Radius(), 6),
                axis_direction=_round_tuple(axis.Direction().Coord()),
                axis_location=_round_tuple(axis.Location().Coord()),
                z_interval=(round(bbox.zmin, 6), round(bbox.zmax, 6)),
                orientation=str(face.wrapped.Orientation()),
                circular_edge_count=sum(
                    edge.geomType() == "CIRCLE" for edge in face.Edges()
                ),
            )
        )
    return sorted(
        observations,
        key=lambda item: (
            item.axis_direction,
            item.axis_location,
            item.z_interval,
            item.radius,
        ),
    )


def _circular_edges(shape: cq.Shape):
    return [
        edge
        for edge in shape.Edges()
        if edge.geomType() == "CIRCLE"
    ]


def _box_with_cylinders(*, holes: list[tuple[float, float, float, float]]) -> cq.Shape:
    """Make a box with cylinders removed.

    Each tuple is ``(x, y, radius, depth)``.  The host is deliberately much
    larger than the features and is not a frozen-project fixture.
    """

    model = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    for x, y, radius, depth in holes:
        cutter = cq.Workplane("XY").workplane(offset=-8.0).center(x, y).circle(radius).extrude(depth)
        model = model.cut(cutter)
    return model.val()


def _box_with_x_hole() -> cq.Shape:
    return cq.Workplane("YZ").box(40.0, 16.0, 60.0).cut(
        cq.Workplane("YZ").workplane(offset=-30.0).center(0.0, 0.0).circle(3.0).extrude(60.0)
    ).val()


def _box_with_y_hole() -> cq.Shape:
    return cq.Workplane("XZ").box(60.0, 16.0, 40.0).cut(
        cq.Workplane("XZ").workplane(offset=-20.0).center(0.0, 0.0).circle(3.0).extrude(40.0)
    ).val()


def _blind_hole() -> cq.Shape:
    return cq.Workplane("XY").box(60.0, 40.0, 16.0).cut(
        cq.Workplane("XY").workplane(offset=4.0).circle(4.0).extrude(4.0)
    ).val()


def _cylindrical_recess() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    cutter = cq.Workplane("XY").workplane(offset=2.0).circle(4.0).extrude(3.0)
    return host.cut(cutter).val()


def _counterbored_hole() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    small = cq.Workplane("XY").workplane(offset=-8.0).circle(2.5).extrude(20.0)
    large = cq.Workplane("XY").workplane(offset=4.0).circle(5.0).extrude(4.0)
    return host.cut(small).cut(large).val()


def _countersunk_hole() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    bore = cq.Workplane("XY").workplane(offset=-8.0).circle(2.5).extrude(20.0)
    sink = cq.Workplane("XY").workplane(offset=5.0).circle(5.0).workplane(offset=2.0).circle(2.5).loft()
    return host.cut(bore).cut(sink).val()


def _coaxial_separate_blind_features() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    lower = cq.Workplane("XY").workplane(offset=-8.0).circle(3.0).extrude(3.0)
    upper = cq.Workplane("XY").workplane(offset=5.0).circle(3.0).extrude(3.0)
    return host.cut(lower).cut(upper).val()


def _exterior_cylindrical_boss() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0)
    boss = cq.Workplane("XY").workplane(offset=8.0).circle(5.0).extrude(8.0)
    return host.union(boss).val()


def _solid_cylindrical_pin() -> cq.Shape:
    return cq.Solid.makeCylinder(5.0, 12.0)


def _filleted_host_with_hole() -> cq.Shape:
    host = cq.Workplane("XY").box(60.0, 40.0, 16.0).edges("|Z").fillet(4.0)
    cutter = cq.Workplane("XY").workplane(offset=-8.0).circle(3.0).extrude(16.0)
    return host.cut(cutter).val()


@pytest.mark.parametrize(
    ("name", "shape_factory", "expected_cylinders", "expected_edges"),
    [
        ("single_through", lambda: _box_with_cylinders(holes=[(0.0, 0.0, 3.0, 16.0)]), 1, 2),
        ("two_through", lambda: _box_with_cylinders(holes=[(-12.0, 0.0, 3.0, 16.0), (12.0, 0.0, 3.0, 16.0)]), 2, 4),
        ("blind", _blind_hole, 1, 2),
        ("cylindrical_recess", _cylindrical_recess, 1, 2),
        ("counterbore", _counterbored_hole, 2, 4),
        # This construction has two analytic cylindrical bands separated by a
        # conical transition; it is still one physical opening, not two holes.
        ("countersink", _countersunk_hole, 2, 5),
        ("stepped_cylindrical", _counterbored_hole, 2, 4),
        ("stepped_multiple_bands", _counterbored_hole, 2, 4),
        ("exterior_boss", _exterior_cylindrical_boss, 1, 2),
        ("solid_pin", _solid_cylindrical_pin, 1, 2),
        ("filleted_host", _filleted_host_with_hole, 5, 10),
        ("coaxial_separate", _coaxial_separate_blind_features, 2, 4),
        ("multiple_diameters", lambda: _box_with_cylinders(holes=[(-15.0, 0.0, 2.5, 16.0), (0.0, 0.0, 3.5, 16.0), (15.0, 0.0, 5.0, 16.0)]), 3, 6),
        ("x_axis", _box_with_x_hole, 1, 2),
        ("y_axis", _box_with_y_hole, 1, 2),
        ("z_axis", lambda: _box_with_cylinders(holes=[(0.0, 0.0, 3.0, 16.0)]), 1, 2),
    ],
)
def test_analytic_cylinders_and_circular_edges_are_observable(
    name: str,
    shape_factory,
    expected_cylinders: int,
    expected_edges: int,
) -> None:
    shape = shape_factory()

    assert name
    assert shape.isValid()
    assert len(_cylinder_observations(shape)) == expected_cylinders
    assert len(_circular_edges(shape)) == expected_edges


def test_axis_direction_is_preserved_for_all_principal_directions() -> None:
    shapes = [_box_with_cylinders(holes=[(0.0, 0.0, 3.0, 16.0)]), _box_with_x_hole(), _box_with_y_hole()]

    directions = {
        tuple(abs(value) for value in observation.axis_direction)
        for shape in shapes
        for observation in _cylinder_observations(shape)
    }

    assert directions == {(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)}


def test_radius_and_edge_radius_are_analytic_and_not_mesh_approximations() -> None:
    shape = _box_with_cylinders(holes=[(0.0, 0.0, 3.75, 16.0)])
    cylinder = _cylinder_observations(shape)[0]
    radii = [round(edge.radius(), 6) for edge in _circular_edges(shape)]

    assert isclose(cylinder.radius, 3.75, abs_tol=1e-6)
    assert radii == [3.75, 3.75]


def test_through_and_blind_shapes_have_different_cap_adjacency() -> None:
    through = _box_with_cylinders(holes=[(0.0, 0.0, 3.0, 16.0)])
    blind = _blind_hole()

    def adjacent_faces(shape: cq.Shape, edge) -> list[cq.Face]:
        return [
            face
            for face in shape.Faces()
            if any(edge.wrapped.IsSame(candidate.wrapped) for candidate in face.Edges())
        ]

    through_adjacencies = [adjacent_faces(through, edge) for edge in _circular_edges(through)]
    blind_adjacencies = [adjacent_faces(blind, edge) for edge in _circular_edges(blind)]

    # In this simple planar-host construction, each through opening boundary
    # reaches an exterior planar face with two wires.  A blind opening has one
    # such exterior boundary and one one-wire internal cap.  The same
    # relationship must be generalized cautiously for non-planar hosts.
    through_planar_wire_counts = sorted(
        len(face.Wires())
        for faces in through_adjacencies
        for face in faces
        if face.geomType() == "PLANE"
    )
    blind_planar_wire_counts = sorted(
        len(face.Wires())
        for faces in blind_adjacencies
        for face in faces
        if face.geomType() == "PLANE"
    )
    assert through_planar_wire_counts == [2, 2]
    assert blind_planar_wire_counts == [1, 2]


def test_shared_transition_face_is_observable_for_one_stepped_opening() -> None:
    shape = _counterbored_hole()
    cylinders = [face for face in shape.Faces() if face.geomType() == "CYLINDER"]
    assert len(cylinders) == 2

    shared_faces = set()
    for first_edge in cylinders[0].Edges():
        for second_edge in cylinders[1].Edges():
            if first_edge.wrapped.IsSame(second_edge.wrapped):
                shared_faces.add(first_edge.wrapped.HashCode(2**31 - 1))

    assert shared_faces == set()
    assert any(
        face.geomType() == "PLANE"
        and len(face.Wires()) == 2
        and sum(
            edge.wrapped.IsSame(candidate.wrapped)
            for edge in face.Edges()
            for candidate in cylinders[0].Edges() + cylinders[1].Edges()
        ) >= 2
        for face in shape.Faces()
    )


def test_coaxial_separate_features_have_disjoint_cylindrical_intervals() -> None:
    observations = _cylinder_observations(_coaxial_separate_blind_features())

    assert len(observations) == 2
    assert observations[0].axis_direction == observations[1].axis_direction
    assert observations[0].axis_location[:2] == observations[1].axis_location[:2]
    assert observations[0].z_interval[1] < observations[1].z_interval[0]


def test_cylinder_orientation_alone_cannot_identify_physical_holes() -> None:
    observations = _cylinder_observations(_filleted_host_with_hole())

    assert len(observations) > 1
    assert any("REVERSED" in observation.orientation for observation in observations)
    assert any("FORWARD" in observation.orientation for observation in observations)


def test_different_hole_diameters_remain_independent_features() -> None:
    shape = _box_with_cylinders(
        holes=[(-15.0, 0.0, 2.5, 16.0), (0.0, 0.0, 3.5, 16.0), (15.0, 0.0, 5.0, 16.0)]
    )
    observations = _cylinder_observations(shape)

    assert [item.radius for item in observations] == [2.5, 3.5, 5.0]
    assert len(observations) == 3
