"""Characterize, but do not route, analytic B-Rep connection diameters."""

from __future__ import annotations

import cadquery as cq

from brep_connection_diameter_characterization import (
    ConnectionTarget,
    compare_selected_diameter,
    enumerate_cylindrical_candidates,
)


def test_clean_cylinder_is_enumerated_as_authoritative_analytic_evidence() -> None:
    shape = cq.Workplane("XY").box(60, 40, 16).cut(
        cq.Workplane("XY").workplane(offset=-8).circle(17.5).extrude(16)
    ).val()

    candidates = enumerate_cylindrical_candidates(shape, source_brep_hash="synthetic")

    assert len(candidates) == 1
    assert candidates[0].diameter == 35.0
    assert candidates[0].source_brep_hash == "synthetic"
    assert candidates[0].candidate_id.startswith("face-")
    assert candidates[0].circular_boundary_edge_count == 2
    assert candidates[0].axis_origin
    assert candidates[0].axis_direction
    assert candidates[0].axial_extent[0] <= candidates[0].axial_extent[1]
    assert candidates[0].surface_area > 0
    assert candidates[0].adjacent_edge_ids
    assert candidates[0].boundary_loops


def test_outer_spigot_od_and_inner_socket_id_are_measurable_but_role_is_not_guessed() -> None:
    outer_candidates = enumerate_cylindrical_candidates(
        _hollow_spigot(), source_brep_hash="outer-spigot"
    )
    inner_candidates = enumerate_cylindrical_candidates(
        _through_hole(), source_brep_hash="inner-socket"
    )

    assert 35.0 in {candidate.diameter for candidate in outer_candidates}
    assert [candidate.diameter for candidate in inner_candidates] == [35.0]
    assert all(candidate.surface_role == "unknown" for candidate in inner_candidates)


def test_external_boss_is_not_certified_as_an_open_connection() -> None:
    shape = cq.Workplane("XY").box(60, 40, 16).union(
        cq.Workplane("XY").workplane(offset=8).circle(17.5).extrude(8)
    ).val()
    candidates = enumerate_cylindrical_candidates(shape, source_brep_hash="boss")

    result = compare_selected_diameter(
        candidates,
        target=_target_for(candidates[0]),
        expected_diameter=35,
    )

    assert result.status == "UNVERIFIABLE"


def test_repeated_enumeration_is_deterministic() -> None:
    shape = _through_hole()
    first = enumerate_cylindrical_candidates(shape, source_brep_hash="repeat")
    second = enumerate_cylindrical_candidates(shape, source_brep_hash="repeat")
    assert first == second


def _through_hole(diameter: float = 35.0) -> cq.Shape:
    return cq.Workplane("XY").box(60, 40, 16).cut(
        cq.Workplane("XY").workplane(offset=-8).circle(diameter / 2).extrude(16)
    ).val()


def _blind_recess(diameter: float = 35.0) -> cq.Shape:
    return cq.Workplane("XY").box(60, 40, 16).cut(
        cq.Workplane("XY").workplane(offset=4).circle(diameter / 2).extrude(4)
    ).val()


def _hollow_spigot(outer_diameter: float = 35.0) -> cq.Shape:
    body = cq.Workplane("XY").box(70, 70, 20)
    outer = cq.Workplane("XY").workplane(offset=10).circle(outer_diameter / 2).extrude(20)
    inner = cq.Workplane("XY").workplane(offset=-10).circle(outer_diameter / 2 - 5).extrude(40)
    return body.union(outer).cut(inner).val()


def _coaxial_two_interfaces() -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            cq.Solid.makeCylinder(17.5, 6, cq.Vector(0, 0, -18)),
            cq.Solid.makeCylinder(17.5, 6, cq.Vector(0, 0, 12)),
        ]
    )


def _two_parallel_holes() -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            cq.Solid.makeCylinder(17.5, 16, cq.Vector(-20, 0, -8)),
            cq.Solid.makeCylinder(17.5, 16, cq.Vector(20, 0, -8)),
        ]
    )


def _internal_cavity(diameter: float = 35.0) -> cq.Shape:
    return cq.Workplane("XY").box(70, 50, 30).cut(
        cq.Workplane("XY").workplane(offset=-2).circle(diameter / 2).extrude(4)
    ).val()


def _stepped_connector() -> cq.Shape:
    host = cq.Workplane("XY").box(60, 40, 16)
    small = cq.Workplane("XY").workplane(offset=-8).circle(12.5).extrude(16)
    large = cq.Workplane("XY").workplane(offset=4).circle(17.5).extrude(4)
    return host.cut(small).cut(large).val()


def _chamfered_mouth() -> cq.Shape:
    host = cq.Workplane("XY").box(60, 40, 16)
    bore = cq.Workplane("XY").workplane(offset=-8).circle(12.5).extrude(16)
    mouth = (
        cq.Workplane("XY")
        .workplane(offset=5)
        .circle(17.5)
        .workplane(offset=2)
        .circle(12.5)
        .loft()
    )
    return host.cut(bore).cut(mouth).val()


def _target_for(candidate) -> ConnectionTarget:
    return ConnectionTarget(
        axis_origin=candidate.axis_origin,
        axis_direction=candidate.axis_direction,
        interface_point=None,
        opening_required=True,
    )


def test_wrong_diameter_fails_after_target_selection() -> None:
    candidates = enumerate_cylindrical_candidates(
        _through_hole(32), source_brep_hash="wrong-diameter"
    )

    result = compare_selected_diameter(
        candidates,
        target=_target_for(candidates[0]),
        expected_diameter=35,
        tolerance_mm=0.1,
    )

    assert result.status == "FAIL"
    assert result.measured_diameter == 32.0


def test_blind_recess_never_passes_as_open_connection() -> None:
    candidates = enumerate_cylindrical_candidates(
        _blind_recess(), source_brep_hash="blind-recess"
    )

    result = compare_selected_diameter(
        candidates,
        target=_target_for(candidates[0]),
        expected_diameter=35,
    )

    assert result.status == "UNVERIFIABLE"


def test_expected_diameter_never_resolves_multiple_candidates() -> None:
    candidates = enumerate_cylindrical_candidates(
        _coaxial_two_interfaces(), source_brep_hash="ambiguous"
    )
    target = ConnectionTarget(
        axis_origin=(0, 0, 0),
        axis_direction=(0, 0, 1),
        interface_point=None,
        opening_required=False,
    )

    result = compare_selected_diameter(
        candidates,
        target=target,
        expected_diameter=35,
    )

    assert result.status == "UNVERIFIABLE"
    assert result.selection.status == "ambiguous"
    assert len(result.selection.candidate_ids) == 2


def test_parallel_same_diameter_interfaces_are_ambiguous_without_target_identity() -> None:
    candidates = enumerate_cylindrical_candidates(
        _two_parallel_holes(), source_brep_hash="parallel"
    )
    assert len(candidates) == 2
    assert {candidate.diameter for candidate in candidates} == {35.0}


def test_internal_cavity_is_not_certified_as_external_connection() -> None:
    candidates = enumerate_cylindrical_candidates(
        _internal_cavity(), source_brep_hash="internal-cavity"
    )
    assert candidates
    result = compare_selected_diameter(
        candidates,
        target=_target_for(candidates[0]),
        expected_diameter=35,
    )
    assert result.status == "UNVERIFIABLE"


def test_stepped_connector_is_ambiguous_without_axial_interface_identity() -> None:
    candidates = enumerate_cylindrical_candidates(
        _stepped_connector(), source_brep_hash="stepped"
    )
    assert {candidate.diameter for candidate in candidates} == {25.0, 35.0}
    target = ConnectionTarget(
        axis_origin=(0, 0, 0),
        axis_direction=(0, 0, 1),
        opening_required=False,
    )
    result = compare_selected_diameter(
        candidates, target=target, expected_diameter=35
    )
    assert result.status == "UNVERIFIABLE"
    assert result.selection.status == "ambiguous"


def test_chamfered_mouth_is_not_certified_from_cylinder_radius_alone() -> None:
    candidates = enumerate_cylindrical_candidates(
        _chamfered_mouth(), source_brep_hash="chamfered"
    )
    assert candidates
    target = ConnectionTarget(
        axis_origin=candidates[0].axis_origin,
        axis_direction=candidates[0].axis_direction,
        opening_required=True,
    )
    result = compare_selected_diameter(
        candidates, target=target, expected_diameter=35
    )
    assert result.status == "UNVERIFIABLE"


def test_outer_and_inner_roles_are_not_claimed_without_role_evidence() -> None:
    for shape in (_hollow_spigot(), _through_hole()):
        candidates = enumerate_cylindrical_candidates(shape, source_brep_hash="role")
        assert candidates
        assert all(candidate.surface_role in {"inner", "outer", "unknown"} for candidate in candidates)
    # The characterization must not silently infer the requirement's ID/OD
    # meaning from a cylinder's orientation or from the expected value.
    assert any(
        candidate.surface_role == "unknown"
        for candidate in enumerate_cylindrical_candidates(
            _through_hole(), source_brep_hash="role-unknown"
        )
    )


def test_rotated_target_uses_analytic_axis_without_xyz_assumption() -> None:
    shape = _through_hole().rotate((0, 0, 0), (1, 1, 0), 31)
    candidates = enumerate_cylindrical_candidates(shape, source_brep_hash="rotated")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert max(abs(value) for value in candidate.axis_direction[:2]) > 0.1

    result = compare_selected_diameter(
        candidates,
        target=_target_for(candidate),
        expected_diameter=35,
    )

    assert result.status == "PASS"


def test_acceptance_tolerance_is_separate_from_analytic_measurement() -> None:
    candidates = enumerate_cylindrical_candidates(
        _through_hole(35.05), source_brep_hash="tolerance"
    )
    target = _target_for(candidates[0])

    assert compare_selected_diameter(
        candidates, target=target, expected_diameter=35, tolerance_mm=0.1
    ).status == "PASS"
    assert compare_selected_diameter(
        candidates, target=target, expected_diameter=35, tolerance_mm=0.01
    ).status == "FAIL"
