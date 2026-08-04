from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.ollama_benchmark.calibration import (
    ADMISSION_STATUSES,
    CALIBRATION_STATES,
    CalibrationIssue,
    CalibrationProfile,
    HoldoutFrozenError,
    ModelIdentity,
    admission_gate,
    build_resolution_queue,
    classify_calibration_failure,
    freeze_profile,
    normalize_native_source,
    normalize_structured_response,
    ProfileIterationLimitError,
    can_count_cad_quality,
    classify_native_and_production,
    EXPECTED_MODEL_IDENTITIES,
    load_calibration_profile,
    run_models_serially,
    require_formal_benchmark_admission,
    verify_model_identity,
    wrap_native_source_for_worker,
)


def test_calibration_vocabulary_keeps_quality_dimensions_separate() -> None:
    assert {"discovered", "identity_verified", "operational", "admitted", "deferred"} <= CALIBRATION_STATES
    assert {"admitted_production", "admitted_native_diagnostic", "deferred_for_profile_resolution"} <= ADMISSION_STATUSES

    infrastructure = classify_calibration_failure(
        stage="native",
        error_code="ollama.server_unreachable",
        message="server unavailable",
    )
    cad = classify_calibration_failure(
        stage="native",
        error_code="cad.missing_operation",
        message="extrusion omitted",
        worker_validated=True,
    )

    assert infrastructure.owner == "infrastructure"
    assert infrastructure.counts_against_cad_quality is False
    assert cad.owner == "cad"
    assert cad.counts_against_cad_quality is True


def test_identity_requires_exact_name_and_expected_digest_prefix() -> None:
    expected = ModelIdentity(
        model_name="volundr-cad-coder-native:q8_0",
        digest_prefix="78a442269750",
        quantization="Q8_0",
    )
    verified = verify_model_identity(
        expected,
        {"name": expected.model_name, "digest": "sha256:78a442269750abcdef", "quantization": "Q8_0"},
    )
    assert verified.full_digest == "sha256:78a442269750abcdef"

    with pytest.raises(ValueError, match="identity mismatch"):
        verify_model_identity(expected, {"name": "volundr-cad-coder:q8_0", "digest": "sha256:78a442269750abcdef", "quantization": "Q8_0"})


def test_calibration_inventory_uses_exact_installed_model_names() -> None:
    assert [item.model_name for item in EXPECTED_MODEL_IDENTITIES] == [
        "volundr-cad-coder-native:q8_0",
        "volundr-procad-coder-native:q8_0",
        "hf.co/yuvit-batra/qwen2.5-coder-7b-cadquery-gguf:Q4_K_M",
        "qwen2.5-coder:14b-instruct-q5_K_M",
        "deepseek-coder-v2:16b-lite-instruct-q4_K_M",
        "joshuaokolo/C3Dv0:latest",
    ]


def test_all_calibration_profiles_have_full_digests_and_allowed_fields() -> None:
    profile_dir = Path(__file__).parents[2] / "benchmarks" / "ollama-prompts" / "profiles"
    profile_names = {
        "cad-coder-q8.yaml",
        "procad-coder-q8.yaml",
        "qwen25-cadquery-q4.yaml",
        "qwen25-coder-14b-q5.yaml",
        "deepseek-coder-v2-lite-q4.yaml",
        "c3dv0.yaml",
    }
    for name in profile_names:
        profile = load_calibration_profile(profile_dir / name)
        assert profile.model_digest.startswith("sha256:") is False
        assert len(profile.model_digest) == 64
        assert profile.profile_hash is None or len(profile.profile_hash) == 64


def test_safe_normalization_preserves_raw_and_repairs_only_representation() -> None:
    raw = "<think>draft</think>\n```json\n{\"slots\":[{\"slot_id\":2},{\"slot_id\":1}]}\n```"
    normalized = normalize_structured_response(raw)

    assert normalized.raw_response == raw
    assert json.loads(normalized.normalized_response) == {"slots": [{"slot_id": 2}, {"slot_id": 1}]}
    assert "representation.reasoning_wrapped" in normalized.codes
    assert "representation.markdown_wrapped" in normalized.codes


def test_native_normalization_maps_one_unambiguous_final_alias_only() -> None:
    normalized = normalize_native_source(
        "import cadquery as cq\nshape = cq.Workplane('XY').box(10, 10, 10)\n"
    )
    assert "result = shape" in normalized.normalized_response
    assert "representation.final_symbol_alias" in normalized.codes

    with pytest.raises(ValueError, match="multiple plausible"):
        normalize_native_source(
            "import cadquery as cq\na = cq.Workplane('XY').box(1, 1, 1)\n"
            "b = cq.Workplane('XY').box(2, 2, 2)\n"
        )
    wrapped = wrap_native_source_for_worker(normalized.normalized_response)
    assert "return Product" in wrapped
    assert "result = shape" in wrapped


def test_profile_hash_is_frozen_and_holdout_rejects_profile_change() -> None:
    profile = CalibrationProfile(
        profile_version="ollama-calibration-v1",
        model_name="model-a",
        model_digest="sha256:abc",
        response_modes=("native", "production_slot"),
        chat_template="{{ .Prompt }}",
        temperature=0.2,
        top_p=0.8,
        top_k=20,
        total_timeout_seconds=120,
    )
    frozen = freeze_profile(profile)
    assert frozen.profile_hash
    assert freeze_profile(frozen) == frozen
    with pytest.raises(HoldoutFrozenError):
        frozen.assert_holdout_compatible({**frozen.to_dict(), "temperature": 0.7, "profile_hash": frozen.profile_hash})


def test_admission_requires_specialist_and_generic_and_final_statuses() -> None:
    models = [
        {"model_id": "specialist", "purpose": "CAD specialist", "admission": "admitted_native_diagnostic", "state": "admitted"},
        {"model_id": "generic", "purpose": "generic coding baseline", "admission": "admitted_production", "state": "admitted"},
    ]
    result = admission_gate(models, intended_model_ids=["specialist", "generic"])
    assert result.formal_benchmark_authorized is True

    blocked = admission_gate(
        models + [{"model_id": "deferred", "purpose": "specialist", "admission": "deferred_for_resolution", "state": "deferred"}],
        intended_model_ids=["specialist", "generic", "deferred"],
    )
    assert blocked.formal_benchmark_authorized is False
    assert "deferred" in blocked.blocking_model_ids


def test_resolution_queue_records_owner_and_evidence() -> None:
    queue = build_resolution_queue(
        [
            CalibrationIssue(
                issue_id="issue-1",
                model="model-a",
                stage="structured",
                owner="adapter",
                error_code="adapter.response_parse_failed",
                message="bad stream",
                evidence_path="structured/raw.ndjson",
                blocking_calibration=True,
                blocking_other_models=False,
                recommended_resolution="inspect parser",
            )
        ]
    )
    assert queue[0]["owner"] == "adapter"
    assert queue[0]["status"] == "open"


@pytest.mark.asyncio
async def test_model_failure_does_not_stop_serial_calibration() -> None:
    seen: list[str] = []

    async def calibrate(model: str) -> dict[str, str]:
        seen.append(model)
        if model == "first":
            raise RuntimeError("model-specific failure")
        return {"model": model, "state": "admitted"}

    results = await run_models_serially(["first", "second"], calibrate)
    assert seen == ["first", "second"]
    assert results[0]["state"] == "deferred"
    assert results[1]["state"] == "admitted"


def test_missing_geometry_cannot_be_normalized_into_source() -> None:
    with pytest.raises(ValueError, match="cannot normalize CAD intent"):
        normalize_native_source(
            "import cadquery as cq\nresult = cq.Workplane('XY').box(10, 10, 10)\n",
            required_operations=["extrude"],
        )


def test_cad_quality_requires_validated_profile_and_worker() -> None:
    issue = classify_calibration_failure(
        stage="native",
        error_code="cad.missing_operation",
        message="missing extrusion",
        worker_validated=False,
    )
    assert can_count_cad_quality(issue, profile_validated=False) is False
    assert can_count_cad_quality(issue, profile_validated=True) is False
    validated = classify_calibration_failure(
        stage="native",
        error_code="cad.missing_operation",
        message="missing extrusion",
        worker_validated=True,
    )
    assert can_count_cad_quality(validated, profile_validated=True) is True


def test_native_and_production_capabilities_are_independent() -> None:
    result = classify_native_and_production(native_validated=True, production_validated=False, production_tested=True)
    assert result.native_capability == "validated"
    assert result.production_compatibility == "incompatible"
    assert result.admission == "admitted_native_diagnostic"

    result = classify_native_and_production(native_validated=False, production_validated=True)
    assert result.native_capability == "not_tested"
    assert result.production_compatibility == "compatible"
    assert result.admission == "admitted_production"
    partial = classify_native_and_production(
        native_validated=False,
        production_validated=False,
        production_partial=True,
        production_tested=True,
    )
    assert partial.production_compatibility == "partially_compatible"
    assert partial.admission == "deferred_for_profile_resolution"


def test_profile_iteration_budget_is_three() -> None:
    profile = CalibrationProfile(profile_version="v1", model_name="model", model_digest="sha256:a")
    current = profile
    for iteration in range(3):
        current = current.next_iteration(iteration + 1)
    with pytest.raises(ProfileIterationLimitError):
        current.next_iteration(4)


def test_shared_infrastructure_failure_stops_serial_calibration() -> None:
    seen: list[str] = []

    class SharedFailure(RuntimeError):
        blocking_other_models = True

    async def calibrate(model: str) -> dict[str, str]:
        seen.append(model)
        raise SharedFailure("worker unavailable")

    with pytest.raises(SharedFailure):
        asyncio.run(run_models_serially(["first", "second"], calibrate))
    assert seen == ["first"]


def test_native_success_cannot_promote_a_normal_production_project() -> None:
    result = classify_native_and_production(native_validated=True, production_validated=False)
    assert result.admission != "admitted_production"


def test_formal_benchmark_requires_frozen_admission_evidence(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="benchmark is blocked"):
        require_formal_benchmark_admission(tmp_path)
    admission = tmp_path / "calibration-1" / "admission.json"
    admission.parent.mkdir()
    admission.write_text(json.dumps({"formal_benchmark_authorized": False}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="benchmark is blocked"):
        require_formal_benchmark_admission(tmp_path)
    admission.write_text(json.dumps({"formal_benchmark_authorized": True}), encoding="utf-8")
    assert require_formal_benchmark_admission(tmp_path)["formal_benchmark_authorized"] is True
