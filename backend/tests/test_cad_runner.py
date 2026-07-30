from pathlib import Path
from importlib.util import find_spec
import sys

import pytest

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.runner import OpenScadCliRunner


@pytest.mark.asyncio
async def test_openscad_runner_compiles_cube_and_returns_metadata(tmp_path: Path) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile("cube([10, 20, 30]);", job_id="cube-job")

    assert result.success is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stl_path is not None
    assert result.stl_path.exists()
    assert result.metadata_path is not None
    assert result.metadata_path.exists()
    assert result.metadata is not None
    assert result.metadata.triangle_count > 0
    assert result.metadata.volume_mm3 == pytest.approx(6000.0)
    assert result.metadata.size_x_mm == pytest.approx(10.0)
    assert result.metadata.size_y_mm == pytest.approx(20.0)
    assert result.metadata.size_z_mm == pytest.approx(30.0)
    assert result.metadata.connected_components == 1
    assert result.metadata.is_watertight is True


@pytest.mark.asyncio
async def test_openscad_runner_allows_comments_and_division(tmp_path: Path) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile(
        """// ===== QUALITY =====
$fn = 24;
width = 20;
module main_model() {
  translate([width / 2, 0, 0])
    cube([width, 10, 5]);
}
main_model();
""",
        job_id="commented-job",
    )

    assert result.success is True
    assert result.error_message is None


@pytest.mark.asyncio
async def test_openscad_runner_returns_structured_failure_for_invalid_scad(
    tmp_path: Path,
) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile("cube([10, 20, 30];", job_id="invalid-job")

    assert result.success is False
    assert result.exit_code != 0
    assert result.timed_out is False
    assert result.error_message is not None
    assert result.stderr_path is not None
    assert result.stderr_path.exists()
    assert result.metadata is None


@pytest.mark.asyncio
async def test_openscad_runner_rejects_successful_compile_with_undefined_symbols(
    tmp_path: Path,
) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile(
        """
module main_model() {
  union() {
    cube([1, 1, 1]);
    translate([missing_offset, 0, 0]) cube([1, 1, 1]);
  }
}
main_model();
""",
        job_id="warning-job",
    )

    assert result.success is False
    assert result.exit_code == 0
    assert result.error_message is not None
    assert "OpenSCAD emitted hard warnings" in result.error_message
    assert "unknown variable 'missing_offset'" in result.error_message
    assert result.metadata is None


@pytest.mark.asyncio
async def test_openscad_runner_rejects_successful_compile_with_ignored_child_geometry(
    tmp_path: Path,
) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile(
        """
module main_model() {
  union() {
    cube([1, 1, 1]);
    square([1, 1]);
  }
}
main_model();
""",
        job_id="ignored-child-warning-job",
    )

    assert result.success is False
    assert result.exit_code == 0
    assert result.error_message is not None
    assert "OpenSCAD emitted hard warnings" in result.error_message
    assert "Ignoring 2D child object for 3D operation" in result.error_message
    assert result.metadata is None


@pytest.mark.asyncio
async def test_openscad_runner_rejects_forbidden_file_import(tmp_path: Path) -> None:
    runner = OpenScadCliRunner(workspace_root=tmp_path, timeout_seconds=15)

    result = await runner.compile('import("/etc/passwd");', job_id="import-job")

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message == "source contains forbidden file access"
    assert result.metadata is None


@pytest.mark.asyncio
async def test_openscad_runner_times_out_slow_process(tmp_path: Path) -> None:
    fake_openscad = tmp_path / "slow-openscad"
    fake_openscad.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    fake_openscad.chmod(0o755)
    runner = OpenScadCliRunner(
        openscad_binary=str(fake_openscad),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=1,
    )

    result = await runner.compile("cube([1, 1, 1]);", job_id="timeout-job")

    assert result.success is False
    assert result.timed_out is True
    assert result.error_message == "OpenSCAD timed out after 1 seconds"


@pytest.mark.asyncio
async def test_cadquery_runner_rejects_forbidden_python_file_access(tmp_path: Path) -> None:
    result = await CadQueryCliRunner(workspace_root=tmp_path).compile(
        "import os\n\ndef build_model():\n    return None\n",
        job_id="unsafe",
    )

    assert result.success is False
    assert result.error_message == (
        "CadQuery contract violation: only `import cadquery as cq` is allowed"
    )


@pytest.mark.asyncio
async def test_cadquery_runner_collects_product_output_artifacts(tmp_path: Path) -> None:
    fake_python = _fake_cadquery_executor(tmp_path, optional_lid_success=True)

    result = await CadQueryCliRunner(
        python_binary=str(fake_python),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=5,
    ).compile(
        _cadquery_product_source(),
        job_id="product-job",
        parameter_values={"width_mm": 42.0},
        requested_outputs=[
            {"output_id": "body", "required": True},
            {"output_id": "lid", "required": False},
        ],
    )

    assert result.success is True
    assert result.stl_path is not None
    assert result.step_path is not None
    assert [output.output_id for output in result.outputs] == ["body", "lid"]
    assert [output.success for output in result.outputs] == [True, True]
    assert result.outputs[0].entrypoint == "body"
    assert result.outputs[0].stl_hash is not None
    assert result.outputs[0].step_hash is not None
    assert result.outputs[0].brep_hash is not None
    assert result.outputs[0].topology_metadata == {
        "output_id": "body",
        "valid": True,
        "volume_mm3": 1000.0,
        "detected_solid_count": 1,
        "expected_solid_count": 1,
        "allow_disconnected_solids": False,
    }
    assert result.outputs[0].metadata is not None
    assert result.outputs[0].metadata.connected_components == 1
    assert result.outputs[1].required is False
    assert result.outputs[1].stl_path is not None


@pytest.mark.asyncio
async def test_cadquery_runner_allows_optional_output_failure(tmp_path: Path) -> None:
    fake_python = _fake_cadquery_executor(tmp_path, optional_lid_success=False)

    result = await CadQueryCliRunner(
        python_binary=str(fake_python),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=5,
    ).compile(
        _cadquery_product_source(),
        job_id="partial-job",
        requested_outputs=[
            {"output_id": "body", "required": True},
            {"output_id": "lid", "required": False},
        ],
    )

    assert result.success is True
    assert [output.success for output in result.outputs] == [True, False]
    assert result.outputs[1].compile_error == "optional lid failed"
    assert result.error_message is None


@pytest.mark.asyncio
async def test_cadquery_runner_blocks_required_output_failure(tmp_path: Path) -> None:
    fake_python = _fake_cadquery_executor(
        tmp_path,
        required_body_success=False,
        optional_lid_success=True,
    )

    result = await CadQueryCliRunner(
        python_binary=str(fake_python),
        workspace_root=tmp_path / "jobs",
        timeout_seconds=5,
    ).compile(
        _cadquery_product_source(),
        job_id="required-failure-job",
        requested_outputs=[
            {"output_id": "body", "required": True},
            {"output_id": "lid", "required": False},
        ],
    )

    assert result.success is False
    assert result.error_message == "required body failed"
    assert [output.success for output in result.outputs] == [False, True]


@pytest.mark.asyncio
async def test_cadquery_runner_reports_missing_cadquery_dependency(tmp_path: Path) -> None:
    if find_spec("cadquery") is not None:
        pytest.skip("CadQuery is installed in this environment")

    result = await CadQueryCliRunner(workspace_root=tmp_path).compile(
        "import cadquery as cq\n\ndef build_model():\n    return cq.Workplane('XY').box(1, 1, 1)\n",
        job_id="missing-cadquery",
    )

    assert result.success is False
    assert result.stderr_path is not None
    assert "No module named 'cadquery'" in result.error_message


def _cadquery_product_source() -> str:
    return """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product

PARAMETERS = [ParameterSpec(id="width_mm", label="Width", type="float", default=20.0)]

def build(params):
    body = cq.Workplane("XY").box(params["width_mm"], 10, 5)
    lid = cq.Workplane("XY").box(params["width_mm"], 10, 2)
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(output_id="body", component_id="body", label="Body", model=body),
            PrintableOutput(output_id="lid", component_id="lid", label="Lid", model=lid, required=False),
        ],
    )
"""


def _fake_cadquery_executor(
    tmp_path: Path,
    *,
    optional_lid_success: bool,
    required_body_success: bool = True,
) -> Path:
    fake_python = tmp_path / "fake-cadquery-python"
    fake_python.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "import trimesh\n"
        "\n"
        "output_dir = Path(sys.argv[2])\n"
        "result_path = Path(sys.argv[3])\n"
        "output_dir.mkdir(parents=True, exist_ok=True)\n"
        "\n"
        "def write_output(output_id, extents):\n"
        "    out = output_dir / output_id\n"
        "    out.mkdir()\n"
        "    stl_path = out / f'{output_id}.stl'\n"
        "    step_path = out / f'{output_id}.step'\n"
        "    brep_path = out / f'{output_id}.brep'\n"
        "    trimesh.creation.box(extents=extents).export(stl_path)\n"
        "    step_path.write_text(f'step-{output_id}', encoding='utf-8')\n"
        "    brep_path.write_text(f'brep-{output_id}', encoding='utf-8')\n"
        "    return {\n"
        "        'output_id': output_id,\n"
        "        'entrypoint': output_id,\n"
        "        'required': output_id == 'body',\n"
        "        'success': True,\n"
        "        'stl_path': str(stl_path),\n"
        "        'step_path': str(step_path),\n"
        "        'brep_path': str(brep_path),\n"
        "        'topology_metadata': {\n"
        "            'output_id': output_id,\n"
        "            'valid': True,\n"
        "            'volume_mm3': 1000.0,\n"
        "            'detected_solid_count': 1,\n"
        "            'expected_solid_count': 1,\n"
        "            'allow_disconnected_solids': False,\n"
        "        },\n"
        "    }\n"
        "\n"
        f"required_body_success = {required_body_success!r}\n"
        "if required_body_success:\n"
        "    outputs = [write_output('body', (10, 10, 10))]\n"
        "else:\n"
        "    outputs = [{\n"
        "        'output_id': 'body',\n"
        "        'entrypoint': 'body',\n"
        "        'required': True,\n"
        "        'success': False,\n"
        "        'compile_error': 'required body failed',\n"
        "    }]\n"
        f"optional_lid_success = {optional_lid_success!r}\n"
        "if optional_lid_success:\n"
        "    outputs.append(write_output('lid', (10, 10, 2)))\n"
        "else:\n"
        "    outputs.append({\n"
        "        'output_id': 'lid',\n"
        "        'entrypoint': 'lid',\n"
        "        'required': False,\n"
        "        'success': False,\n"
        "        'compile_error': 'optional lid failed',\n"
        "    })\n"
        "result_path.write_text(json.dumps({'outputs': outputs}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    return fake_python
