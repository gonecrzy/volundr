import pytest

from app.services.ai.provider import ModelGenerationResult
from scripts.run_live_geometry_model_comparison import compare, frozen_request


def _frozen_report() -> dict:
    return {
        "request": "Create a holder.",
        "requirements": {"specification": {"object_type": "holder"}},
        "design_plan": {
            "plan": {
                "schema_version": "1.0",
                "parameters": [],
                "derived_parameters": [],
                "components": [{"id": "body", "label": "Body", "features": []}],
                "features": [],
                "printable_outputs": [{"id": "body", "component_id": "body", "required": True}],
                "functional_contract": {},
            }
        },
    }


def test_frozen_request_does_not_require_upstream_provider_artifacts() -> None:
    request = frozen_request(_frozen_report())

    assert request.design_specification == {"object_type": "holder"}
    assert request.design_plan["components"][0]["id"] == "body"
    assert request.generation_contract_version == "cadquery-scaffold-v1"


@pytest.mark.asyncio
async def test_comparison_runs_each_geometry_model_twice_without_upstream_calls() -> None:
    class FakeProvider:
        async def generate_cadquery_model(self, request):
            return ModelGenerationResult(
                raw_output="{}",
                provider="fake",
                provider_model="fake-model",
                routing_metadata={"selected_model": "fake-model", "actual_model": "fake-model"},
                provider_latency_ms=1,
            )

    result = await compare(
        report=_frozen_report(),
        models=[("fast", "fast-model"), ("geometry", "strong-model")],
        runs_per_model=2,
        worker=None,
        provider_factory=lambda _model: FakeProvider(),
    )

    assert result["upstream_provider_calls"] == 0
    assert result["prompt_drift"] is False
    assert len(result["attempts"]) == 4
    assert {item["model_label"] for item in result["attempts"]} == {"fast", "geometry"}
    assert all(item["final_candidate_state"] == "blocked" for item in result["attempts"])
