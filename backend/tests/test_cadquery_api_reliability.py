from __future__ import annotations

import cadquery as cq
import pytest

from app.services.cad.cadquery_contract import validate_cadquery_source
from app.services.cad.cadquery_runner import CadQueryCliRunner
from volundr_cad.runtime import place_pattern_cutters


def test_component_local_pattern_cutters_are_translated_and_unionable() -> None:
    profile = cq.Workplane("XY").rect(4, 4).extrude(25)

    cutters = place_pattern_cutters(
        profile,
        [(-5, 0, -2), (5, 0, -2)],
        coordinate_space="component_local_3d",
    )
    body = cq.Workplane("XY").box(20, 20, 20).cut(cutters)

    assert body.val().isValid()
    assert len(body.val().Solids()) == 1
    assert body.val().Volume() < 20 * 20 * 20


def test_pattern_cutter_helper_is_allowed_by_the_cadquery_source_contract() -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product, place_pattern_cutters

def build(params):
    body = cq.Workplane("XY").box(20, 20, 20)
    profile = cq.Workplane("XY").rect(4, 4).extrude(25)
    tool = place_pattern_cutters(
        profile,
        [(-5, 0, -2), (5, 0, -2)],
        coordinate_space="component_local_3d",
    )
    body = body.cut(tool)
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ]
    )
"""

    validate_cadquery_source(source)


def test_workplane_assembly_is_not_an_available_cadquery_api() -> None:
    assert not hasattr(cq.Workplane("XY"), "assembly")
    assert hasattr(cq, "Assembly")


def test_worker_cadquery_child_has_bounded_numeric_thread_pools() -> None:
    env = CadQueryCliRunner()._subprocess_env()

    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["NUMEXPR_NUM_THREADS"] == "1"
    assert env["VTK_SMP_MAX_THREADS"] == "1"


def test_pattern_cutter_helper_rejects_non_component_3d_points() -> None:
    profile = cq.Workplane("XY").rect(4, 4).extrude(25)

    with pytest.raises(ValueError, match="component_local_3d"):
        place_pattern_cutters(profile, [(0, 0, 0)], coordinate_space="world_3d")


def test_pattern_cutter_helper_rejects_a_non_volumetric_profile() -> None:
    profile = cq.Workplane("XY").rect(4, 4)

    with pytest.raises(TypeError, match="volumetric Solid or Compound"):
        place_pattern_cutters(profile, [(0, 0, 0)])


@pytest.mark.asyncio
async def test_worker_executes_the_supported_placed_cutter_pattern(tmp_path) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product, place_pattern_cutters

def build(params):
    body = cq.Workplane("XY").box(20, 20, 20)
    profile = cq.Workplane("XY").rect(4, 4).extrude(25)
    cutters = place_pattern_cutters(
        profile,
        [(-5, 0, -2), (5, 0, -2)],
        coordinate_space="component_local_3d",
    )
    body = body.cut(cutters)
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ]
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="placed-cutter-worker")

    assert result.success is True
    assert result.outputs[0].stl_path is not None
    assert result.outputs[0].step_path is not None


@pytest.mark.asyncio
async def test_worker_rejects_a_wire_pattern_profile_without_hanging(tmp_path) -> None:
    source = """
import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product, place_pattern_cutters

def build(params):
    body = cq.Workplane("XY").box(20, 20, 20)
    profile = cq.Workplane("XY").rect(4, 4)
    cutters = place_pattern_cutters(profile, [(0, 0, 0)], coordinate_space="component_local_3d")
    body = body.cut(cutters)
    return Product(
        outputs=[
            PrintableOutput(
                output_id="body",
                label="Body",
                model=body,
                component_id="body",
                expected_solid_count=1,
                allow_disconnected_solids=False,
            )
        ]
    )
"""

    result = await CadQueryCliRunner(
        workspace_root=tmp_path / "jobs",
        timeout_seconds=10,
    ).compile(source, job_id="wire-profile-worker")

    assert result.success is False
    assert result.timed_out is False
    assert result.error_message is not None
    assert "volumetric Solid or Compound" in result.error_message
