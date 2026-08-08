from __future__ import annotations

from app.services.external_benchmarks.comparison_specs import (
    build_comparison_specification,
    build_sealed_holdout_record,
    comparison_specification_hash,
)


def _project(*, facts: list[dict], part_count: int = 1) -> dict:
    return {
        "benchmark_id": "synthetic-comparison-001",
        "category": "synthetic_parts",
        "source_title": "hidden source title",
        "split_assignment": "development",
        "canonical_part_count": part_count,
        "reference_files": [
            {
                "part_id": "body",
                "original_filename": "body.stl",
                "file_type": "stl",
                "authority": "mesh_derived",
                "quality_classification": "watertight_mesh_reference",
                "sha256": "a" * 64,
                "selection_reason": "synthetic canonical part",
            }
        ],
        "reference_output_mapping": {"body": "body"},
        "premise": "Design a compact synthetic component.",
        "reference_spec": {"facts": facts},
    }


def _derived() -> dict:
    return {
        "canonical_parts": [
            {
                "part_id": "body",
                "derived": {
                    "file_type": "stl",
                    "authority": "mesh_derived",
                    "quality_classification": "watertight_mesh_reference",
                    "geometry": {
                        "bounding_box_mm": {"size_x": 40.0, "size_y": 30.0, "size_z": 12.0},
                        "solid_count": 1,
                    },
                },
            }
        ]
    }


def test_underconstrained_spec_cannot_be_comparison_ready() -> None:
    spec = build_comparison_specification(
        _project(facts=[{"id": "output_count", "value": 1, "provenance": "manual_benchmark_annotation"}]),
        _derived(),
    )

    assert spec["comparison_ready"] is False
    assert spec["status"] == "needs_spec_enrichment"
    assert "principal_mating_geometry" in spec["missing_design_driving_facts"]


def test_explicit_design_driving_facts_can_qualify_without_mesh_dump() -> None:
    spec = build_comparison_specification(
        _project(
            facts=[
                {"id": "output_count", "value": 1, "provenance": "manual_benchmark_annotation"},
                {
                    "id": "interface_diameter",
                    "value": 20.0,
                    "unit": "mm",
                    "provenance": "manual_benchmark_annotation",
                },
                {
                    "id": "interface_length",
                    "value": 18.0,
                    "unit": "mm",
                    "provenance": "manual_benchmark_annotation",
                },
                {
                    "id": "wall_thickness",
                    "value": 2.0,
                    "unit": "mm",
                    "provenance": "reference_geometry_measured",
                    "measurement_method": "synthetic-envelope-v1",
                },
                {
                    "id": "clearance",
                    "value": 0.3,
                    "unit": "mm",
                    "provenance": "manual_benchmark_annotation",
                },
            ]
        ),
        _derived(),
    )

    assert spec["comparison_ready"] is True
    assert spec["status"] == "comparison_ready"
    assert "vertices" not in spec["prompt"]
    assert "faces" not in spec["prompt"]
    assert "hidden source title" not in spec["prompt"]
    assert spec["outputs"][0]["overall_envelope_mm"] == {"x": 40.0, "y": 30.0, "z": 12.0}
    assert spec["outputs"][0]["selected_variant"] == "body.stl"


def test_geometry_facts_require_measurement_method_and_hash_is_deterministic() -> None:
    spec = build_comparison_specification(
        _project(
            facts=[
                {"id": "output_count", "value": 1, "provenance": "manual_benchmark_annotation"},
                {
                    "id": "interface_diameter",
                    "value": 20.0,
                    "unit": "mm",
                    "provenance": "reference_geometry_measured",
                },
            ]
        ),
        _derived(),
    )

    measured_fact = next(fact for fact in spec["facts"] if fact["id"] == "interface_diameter")
    assert measured_fact["measurement_method"]
    assert comparison_specification_hash(spec) == comparison_specification_hash(spec)


def test_holdout_sealing_exposes_no_project_details_or_fact_values() -> None:
    sealed = build_sealed_holdout_record(
        {
            "benchmark_id": "synthetic-holdout-001",
            "category": "synthetic_parts",
            "split_assignment": "holdout",
            "premise": "hidden premise",
            "source_title": "hidden title",
            "reference_spec": {"facts": [{"id": "hidden", "value": 42}]},
            "comparison_specification": {"facts": [{"id": "hidden", "value": 42}]},
        }
    )

    assert set(sealed) == {
        "benchmark_id",
        "category",
        "split_assignment",
        "comparison_specification_hash",
        "status",
    }
    assert "hidden" not in str(sealed)


def test_replacement_required_is_not_comparison_ready() -> None:
    project = _project(
        facts=[{"id": "output_count", "value": 1, "provenance": "manual_benchmark_annotation"}]
    )
    project["replacement_recommended"] = True

    spec = build_comparison_specification(project, _derived())

    assert spec["status"] == "replacement_required"
    assert spec["comparison_ready"] is False
