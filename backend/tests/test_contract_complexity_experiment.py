import json
from pathlib import Path

import pytest

from app.services.diagnostics.contract_complexity import (
    CURRENT_CONTRACT,
    SIMPLIFIED_EXECUTION_BRIEF,
    build_attempt_matrix,
    build_simplified_execution_brief,
    build_simplified_function_specs,
    build_current_generation_request,
    build_simplified_generation_request,
    build_simplified_prompt,
    extract_simplified_functions,
    run_diagnostic_attempt,
    worker_feedback_function_id,
)
from app.services.ai.provider import ModelGenerationResult


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "diagnostic_inputs"


def _package(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def test_simplified_brief_uses_frozen_inputs_without_current_contract_metadata() -> None:
    package = _package("desktop_organizer")

    brief = build_simplified_execution_brief(package)
    prompt = build_simplified_prompt(package)

    assert set(brief) == {
        "brief_version",
        "requirements",
        "proposals",
        "component_slots",
        "output_slots",
        "functional_feature_slots",
        "coordinate_frames",
        "explicit_dimensions",
        "qualitative_review_items",
        "optional_controls",
        "required_artifacts",
    }
    assert brief["brief_version"] == "simplified-execution-brief-v1"
    assert brief["required_artifacts"] == ["STEP", "STL", "BREP"]
    assert brief["optional_controls"] == []
    assert "source_plan" not in brief
    assert "provider_contract_manifest" not in brief
    assert "prompt_context_pack" not in brief

    for identity in (
        [item.get("id") for item in package["source_plan"].get("components", [])]
        + [item.get("id") for item in package["source_plan"].get("features", [])]
        + [item.get("id") for item in package["source_plan"].get("printable_outputs", [])]
    ):
        assert identity not in prompt
    assert '"provenance":' not in prompt.lower()
    assert '"validation_target' not in prompt.lower()


def test_current_strategy_keeps_existing_contract_context_and_simplified_drops_it() -> None:
    package = _package("five_tray_wall_carrier")

    current = build_current_generation_request(package)
    simplified = build_simplified_generation_request(package)

    assert current.design_plan
    assert current.geometry_execution_context
    assert current.source_authority
    assert current.prompt_context_pack
    assert current.provider_contract_manifest
    assert simplified.design_plan is None
    assert simplified.geometry_execution_context is None
    assert simplified.source_authority is None
    assert simplified.prompt_context_pack is None
    assert simplified.provider_contract_manifest is None


def test_simplified_function_sources_are_mapped_by_order_to_volundr_owned_ids() -> None:
    package = _package("screw_lid_container")
    specs = build_simplified_function_specs(package)
    function_sources = ["import cadquery as cq"]
    for spec in specs:
        args = spec["signature"].strip("()")
        function_sources.extend(
            [
                f"def function_{spec['slot']}({args}):",
                '    body = cq.Workplane("XY").box(10, 10, 10)',
                "    return body",
                "",
            ]
        )
    raw = "```python\n" + "\n".join(function_sources) + "```"

    functions = extract_simplified_functions(raw, specs)

    assert list(functions) == [spec["function_id"] for spec in specs]
    assert all(not name.startswith("function_") for name in functions)
    assert all(f"def {name}(" in source for name, source in functions.items())


def test_simplified_function_parser_rejects_provider_authored_identity_names() -> None:
    specs = [
        {
            "slot": 1,
            "function_id": "_diag_component_001",
            "signature": "(params)",
        }
    ]

    with pytest.raises(ValueError, match="ordered function"):
        extract_simplified_functions(
            "```python\ndef _diag_component_001(params):\n    return params\n```",
            specs,
        )


def test_matrix_is_exactly_two_attempts_for_each_project_strategy_and_model() -> None:
    matrix = build_attempt_matrix(
        [_package("five_tray_wall_carrier"), _package("desktop_organizer"), _package("screw_lid_container")],
        ["configured-model", "stronger-model"],
    )

    assert len(matrix) == 24
    assert {item["strategy"] for item in matrix} == {
        CURRENT_CONTRACT,
        SIMPLIFIED_EXECUTION_BRIEF,
    }
    assert {item["attempt_number"] for item in matrix} == {1, 2}
    assert len({(item["family"], item["model"], item["strategy"]) for item in matrix}) == 12


def test_worker_feedback_can_name_only_one_provider_function() -> None:
    specs = [
        {"function_id": "_diag_component_001"},
        {"function_id": "_diag_feature_002"},
    ]

    assert (
        worker_feedback_function_id(
            "Traceback (most recent call last):\n  in _diag_component_001\nCadQuery error",
            specs,
        )
        == "_diag_component_001"
    )
    assert worker_feedback_function_id("_diag_component_001 and _diag_feature_002", specs) is None
    assert worker_feedback_function_id("worker timed out", specs) is None


def test_fake_provider_and_worker_record_complete_metrics_and_one_repair(monkeypatch) -> None:
    package = _package("desktop_organizer")

    class FakeProvider:
        calls = 0

        async def generate_cadquery_model(self, request):
            self.calls += 1
            return ModelGenerationResult(
                raw_output="diagnostic response",
                provider="gemini_api",
                provider_model="configured-model",
                usage_metadata={
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 20,
                    "totalTokenCount": 30,
                },
                provider_latency_ms=7,
            )

    class FailedWorkerResult:
        success = False
        timed_out = False
        error_message = "Traceback (most recent call last): in _ai_component_organizer_body\nCadQuery error"
        outputs = []

    class FakeWorker:
        calls = 0

        async def compile(self, source, job_id, **kwargs):
            self.calls += 1
            return FailedWorkerResult()

    monkeypatch.setattr(
        "app.services.diagnostics.contract_complexity._assemble_source",
        lambda package, strategy, raw: (
            "source",
            {"_ai_component_organizer_body": "def _ai_component_organizer_body(params): return params"},
            [],
            [{"function_id": "_ai_component_organizer_body", "body_hash": "hash"}],
        ),
    )
    monkeypatch.setattr(
        "app.services.diagnostics.contract_complexity._validate_source",
        lambda package, source: [],
    )

    provider = FakeProvider()
    worker = FakeWorker()
    result = __import__("asyncio").run(
        run_diagnostic_attempt(
            package,
            strategy=CURRENT_CONTRACT,
            model="configured-model",
            attempt_number=1,
            provider=provider,
            worker=worker,
            job_id="diagnostic-job",
        )
    )

    required_keys = {
        "provider_model",
        "strategy",
        "response_validity",
        "schema_or_contract_findings",
        "repair_invocation",
        "repair_result",
        "source_assembled",
        "worker_reached",
        "worker_result",
        "valid_solid_count",
        "step_produced",
        "stl_produced",
        "brep_produced",
        "topology",
        "required_feature_evidence",
        "candidate_quality",
        "provider_latency_ms",
        "prompt_tokens",
        "output_tokens",
        "total_tokens",
        "elapsed_ms",
    }
    assert required_keys <= result.keys()
    assert result["worker_reached"] is True
    assert result["repair_invocation"]["invoked"] is True
    assert result["repair_invocation"]["attempts"] == 1
    assert provider.calls == 2
    assert worker.calls == 2
