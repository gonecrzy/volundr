from pathlib import Path

import pytest

from app.services.ollama_benchmark.manifest import (
    ALLOWED_INSTALLATION_STATUSES,
    ALLOWED_VERIFICATION_STATUSES,
    load_model_manifest,
    validate_model_manifest,
)
from app.services.ollama_benchmark.readiness import (
    classify_native_cad_output,
    classify_production_slot_output,
    classify_structured_output,
    classify_installation_path,
    evaluate_installation_gate,
    evaluate_sustained_generation,
)


MANIFEST_PATH = Path(__file__).parents[2] / "benchmarks" / "ollama-models-v1.yaml"


def test_model_manifest_has_complete_candidate_records() -> None:
    manifest = load_model_manifest(MANIFEST_PATH)

    assert manifest["version"] == "ollama-models-v1"
    assert {item["model_id"] for item in manifest["models"]} >= {
        "cad-coder",
        "procad-coder",
        "qwen25-cadquery",
        "qwen25-coder-14b",
        "deepseek-coder-v2-lite",
        "c3dv0",
    }
    assert "volundr-cad-coder:q8_0" not in {item["ollama_name"] for item in manifest["models"]}
    assert "volundr-cad-coder-chatml:q8_0" not in {item["ollama_name"] for item in manifest["models"]}
    validate_model_manifest(manifest)
    for item in manifest["models"]:
        assert item["installation_status"] in ALLOWED_INSTALLATION_STATUSES
        assert item["verification_status"] in ALLOWED_VERIFICATION_STATUSES
        assert "exclusion_reason" in item


def test_installation_path_distinguishes_api_registry_and_host_import() -> None:
    assert classify_installation_path(
        source_kind="ollama_registry",
        server_supports_pull=True,
        host_access=False,
    ) == "api_registry_install"
    assert classify_installation_path(
        source_kind="safetensors",
        server_supports_pull=False,
        host_access=False,
    ) == "host_import_required"


def test_sustained_generation_requires_two_warm_successes_but_not_speed() -> None:
    result = evaluate_sustained_generation(
        [
            {"status": "success", "generated_tokens": 40, "stream_complete": True},
            {"status": "success", "generated_tokens": 35, "stream_complete": True},
            {"status": "success", "generated_tokens": 33, "stream_complete": True},
        ]
    )

    assert result["verification_status"] == "sustained_generation_verified"
    assert result["accepted_slow_model"] is True


def test_sustained_generation_rejects_timeout_or_corrupt_stream() -> None:
    result = evaluate_sustained_generation(
        [
            {"status": "success", "generated_tokens": 40, "stream_complete": True},
            {"status": "ollama_idle_timeout", "generated_tokens": 0, "stream_complete": False},
            {"status": "success", "generated_tokens": 33, "stream_complete": True},
        ]
    )

    assert result["verification_status"] == "rejected"
    assert result["accepted_slow_model"] is False


def test_formal_gate_requires_specialist_and_generic_baseline() -> None:
    with pytest.raises(ValueError, match="specialist"):
        evaluate_installation_gate(
            [
                {"model_id": "qwen25-coder-14b-instruct", "purpose": "generic coding baseline", "verification_status": "admitted"}
            ]
        )

    result = evaluate_installation_gate(
        [
            {"model_id": "qwen25-coder-14b-instruct", "purpose": "generic coding baseline", "verification_status": "admitted"},
            {"model_id": "c3dv0", "purpose": "CadQuery specialist", "verification_status": "admitted"},
        ]
    )
    assert result["formal_benchmark_authorized"] is True


def test_structured_output_gate_classifies_exact_json_schema() -> None:
    assert classify_structured_output('{"status":"ok","items":[1,2,3]}') == "native_schema_success"
    assert classify_structured_output('Here is the JSON: {"status":"ok","items":[1,2,3]}') == "prose_wrapped_json"
    assert classify_structured_output('{"status":"wrong","items":[]}') == "valid_json_wrong_schema"
    assert classify_structured_output("not json") == "malformed_json"


def test_production_and_native_cad_contracts_are_classified_separately() -> None:
    production = classify_production_slot_output(
        '{"schema_version":"geometry-slots-v1","slots":[{"slot_id":"base","statements":["result = cq.Workplane(\\\"XY\\\")"],"result_symbol":"result"}]}',
        expected_slot_ids=["base"],
    )
    native = classify_native_cad_output("import cadquery as cq\nresult = cq.Workplane(\"XY\").box(10, 10, 10)")

    assert production == "production_slot_compatible"
    assert native == "native_cad_capable"
    assert classify_production_slot_output("import cadquery as cq", expected_slot_ids=["base"]) == "production_slot_invalid"
    assert classify_native_cad_output("```python\nimport cadquery as cq\nresult = cq.Workplane(\"XY\")\n```") == "native_cad_invalid"
