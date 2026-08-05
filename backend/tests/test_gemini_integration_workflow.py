from pathlib import Path

import pytest

from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.corpus import build_integration_corpus
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.transport import ProviderCallResult
from app.services.gemini_integration.workflow import (
    IntegrationBoundaryPorts,
    IntegrationWorkflowRunner,
)


class SpyProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, *, stage: str, prompt: str, operation_id: str) -> ProviderCallResult:
        self.calls.append((stage, prompt, operation_id))
        if stage == "requirements":
            text = '{"requirements":[{"id":"req-1","subject":"plate width","value":100,"unit":"mm","operator":"exact"}],"clarification_required":false,"generation_ready":true}'
        elif stage == "plan":
            text = '{"requirements":[{"id":"req-1","description":"plate width"}],"components":[{"id":"base","name":"base"}],"features":[],"printable_outputs":[{"id":"out","component_id":"base"}]}'
        else:
            text = '{"slots":[{"slot_id":0,"statements":["body = body.cut(cutter)"],"result_symbol":"body"}]}'
        return ProviderCallResult(
            operation_id=operation_id,
            text=text,
            complete=True,
            attempts=[{"attempt_id": operation_id + ":attempt-1", "operation_id": operation_id, "status_code": 200}],
            request_payload={"stage": stage},
            actual_model="gemini-3.5-flash-lite",
        )


@pytest.fixture
def ports():
    calls: list[str] = []
    provider = SpyProvider()

    async def assemble_source(*, project, plan, geometry, provenance):
        calls.append("source_assembly")
        return {"source": "source", "output_manifest": plan.get("printable_outputs", [])}

    async def static_validate(*, source, provenance):
        calls.append("static_validation")
        return {"valid": True}

    async def worker_submit(*, source, output_manifest, provenance):
        calls.append("worker")
        return {"success": True, "job_id": "job-001"}

    async def artifacts(*, worker_result, provenance):
        calls.append("artifacts")
        return {"outputs": [{"output_id": "out", "stl": "out.stl"}]}

    async def topology(*, artifacts, provenance):
        calls.append("topology")
        return {"valid": True, "solid_counts": {"out": 1}}

    async def verification(*, project, plan, topology, provenance):
        calls.append("verification")
        return {"valid": True, "obligations": []}

    async def candidate(*, project, verification, provenance):
        calls.append("candidate")
        return {"decision": "candidate"}

    return IntegrationBoundaryPorts(
        provider_call=provider,
        assemble_source=assemble_source,
        static_validate=static_validate,
        worker_submit=worker_submit,
        collect_artifacts=artifacts,
        inspect_topology=topology,
        verify_requirements=verification,
        decide_candidate=candidate,
        calls=calls,
        provider=provider,
    )


@pytest.mark.asyncio
async def test_runner_exercises_real_boundary_sequence_and_isolates_provenance(tmp_path: Path, ports) -> None:
    profile = GeminiFlashLiteContractV1.from_repository(Path(__file__).resolve().parents[2])
    store = IntegrationEvidenceStore(tmp_path, study_id="gemini-provider-contract-integration-01")
    runner = IntegrationWorkflowRunner(
        profile=profile,
        study_id="gemini-provider-contract-integration-01",
        evidence_store=store,
        ports=ports,
    )

    outcome = await runner.run_project(build_integration_corpus()[0])

    assert outcome.candidate_decision == "candidate"
    assert ports.calls == ["source_assembly", "static_validation", "worker", "artifacts", "topology", "verification", "candidate"]
    assert [stage for stage, _, _ in ports.provider.calls] == ["requirements", "plan", "geometry"]
    geometry_prompt = ports.provider.calls[-1][1]
    assert '"slots"' in geometry_prompt
    assert '"active_requirements"' in geometry_prompt
    assert all(item[2].startswith("gemini-provider-contract-integration-01:") for item in ports.provider.calls)
    assert all(boundary["provenance"]["study_id"] == "gemini-provider-contract-integration-01" for boundary in store.boundaries())


@pytest.mark.asyncio
async def test_runner_stops_at_unsafe_adapter_blocker_without_skipping_forensic_capture(tmp_path: Path, ports) -> None:
    profile = GeminiFlashLiteContractV1.from_repository(Path(__file__).resolve().parents[2])

    async def bad_provider(*, stage: str, prompt: str, operation_id: str) -> ProviderCallResult:
        result = await ports.provider(stage=stage, prompt=prompt, operation_id=operation_id)
        if stage == "requirements":
            return ProviderCallResult(
                operation_id=operation_id,
                text='{"requirements":[{"subject":"cable diameter","value":8,"source":"user"}],"clarification_required":true,"generation_ready":true}',
                complete=True,
                attempts=result.attempts,
                request_payload=result.request_payload,
            )
        return result

    ports.provider_call = bad_provider
    store = IntegrationEvidenceStore(tmp_path, study_id="gemini-provider-contract-integration-01")
    runner = IntegrationWorkflowRunner(
        profile=profile,
        study_id="gemini-provider-contract-integration-01",
        evidence_store=store,
        ports=ports,
    )

    outcome = await runner.run_project(build_integration_corpus()[1])

    assert outcome.candidate_decision is None
    assert outcome.earliest_blocker == "requirements_adapter"
    assert not ports.calls
    assert store.boundaries()
    assert any(item["boundary"] == "requirements_adapter" for item in store.boundaries())
