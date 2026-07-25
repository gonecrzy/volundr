from pathlib import Path

import pytest

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
