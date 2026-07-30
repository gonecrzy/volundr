import json
from pathlib import Path

from scripts.run_live_generation_benchmarks import main


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generation_benchmarks"


def test_live_benchmark_cli_phase_validation_flag_runs_three_scenarios(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "--suite",
            str(FIXTURE_DIR / "core.json"),
            "--output-dir",
            str(tmp_path),
            "--run-label",
            "phase-cli",
            "--phase-validation",
            "--provider",
            "dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Case runs: 3" in output

    manifests = list(tmp_path.glob("*/run-manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["config"]["phase_validation"] is True
    assert manifest["selected_benchmark_ids"] == [
        "creative_fish_shelf_bracket",
        "honeycomb_angle_bracket",
        "threaded_control_knob",
    ]


def test_live_benchmark_cli_accepts_cadquery_source_language(
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "--suite",
            str(FIXTURE_DIR / "core.json"),
            "--output-dir",
            str(tmp_path),
            "--run-label",
            "cadquery-cli",
            "--benchmark-id",
            "simple_mounting_plate",
            "--source-probe",
            "--source-language",
            "cadquery",
            "--provider",
            "dry-run",
        ]
    )

    assert exit_code == 0
    manifests = list(tmp_path.glob("*/run-manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["config"]["source_language"] == "cadquery"


def test_live_benchmark_cli_accepts_configuration_probe(
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "--suite",
            str(FIXTURE_DIR / "full.json"),
            "--output-dir",
            str(tmp_path),
            "--run-label",
            "configuration-cli",
            "--benchmark-id",
            "configuration_exceeds_build_volume",
            "--source-probe",
            "--configuration-probe",
            "--provider",
            "dry-run",
        ]
    )

    assert exit_code == 0
    manifests = list(tmp_path.glob("*/run-manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["config"]["configuration_probe"] is True


def test_live_benchmark_cli_staged_product_gate_enables_strict_probes(
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "--suite",
            str(FIXTURE_DIR / "full.json"),
            "--output-dir",
            str(tmp_path),
            "--run-label",
            "staged-gate-cli",
            "--staged-product-gate",
            "--provider",
            "dry-run",
            "--max-runs",
            "12",
        ]
    )

    assert exit_code == 0
    manifests = list(tmp_path.glob("*/run-manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["config"]["staged_product_gate"] is True
    assert manifest["config"]["source_probe"] is True
    assert manifest["config"]["source_probe_repair"] is True
    assert manifest["config"]["source_brief"] is True
    assert manifest["config"]["design_plan_probe"] is True
    assert manifest["config"]["configuration_probe"] is True
    assert manifest["prompt_versions"]["cadquery_execution_repair"] == (
        "cadquery-execution-repair-v2"
    )
    assert manifest["selected_benchmark_ids"] == [
        "simple_mounting_plate",
        "parametric_adapter",
        "parametric_electronics_enclosure",
        "parametric_repeated_slot_rack",
        "parametric_multi_part_hinged_box",
        "parametric_case_carrier",
        "parametric_configurable_organizer",
        "component_revision_lid_only",
        "vague_clarification",
        "box_with_lid",
        "accidental_multiple_solids",
        "configuration_exceeds_build_volume",
    ]
    assert manifest["staged_product_gate_scenario_set"]["benchmark_ids"] == (
        manifest["selected_benchmark_ids"]
    )
