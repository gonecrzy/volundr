from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.executable_cadquery.recovery import FailureObservation, RecoveryRouter
from app.services.executable_cadquery.recovery_executor import RecoveryActionExecutor


ROOT = Path("data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus")


@pytest.mark.asyncio
async def test_application_owned_verifier_recovery_reuses_existing_artifacts_without_provider() -> None:
    contract = {
        "outputs": [{"output_id": "body", "expected_solid_count": 1}],
        "requirements": [],
    }
    revision = SimpleNamespace(
        outputs=[
            SimpleNamespace(
                output_id="body",
                stl_path="data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-05/revision/stl/mating_insert.stl",
                step_path="present.step",
            )
        ]
    )
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="semantic_measurement",
            failure_class="semantic_requirement_unverifiable",
            evidence={"policy": "machine_required", "measurement_available": False},
            attempt_ordinal=1,
        )
    )

    result = await RecoveryActionExecutor(data_dir=Path(".")).execute(
        decision,
        revision=revision,
        contract=contract,
    )

    assert result.executed is True
    assert result.provider_calls == 0
    assert result.worker_calls == 0
    assert result.action == "application_owned_fix"


@pytest.mark.asyncio
async def test_export_retry_uses_existing_worker_retry_authority() -> None:
    class FakeProjectService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def retry_revision_output(self, output_id: str):
            self.calls.append(output_id)
            return {"output_id": output_id, "execution_state": "ready"}

    output = SimpleNamespace(id="output-row", output_id="body", execution_state="failed")
    revision = SimpleNamespace(outputs=[output])
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="artifact_export",
            failure_class="stl_export_failure",
            evidence={"valid_shape": True},
            attempt_ordinal=1,
        )
    )
    project_service = FakeProjectService()

    result = await RecoveryActionExecutor(data_dir=Path(".")).execute(
        decision,
        revision=revision,
        contract={},
        project_service=project_service,
    )

    assert result.executed is True
    assert result.provider_calls == 0
    assert result.worker_calls == 1
    assert project_service.calls == ["output-row"]


@pytest.mark.asyncio
async def test_worker_timeout_retry_uses_existing_worker_retry_authority() -> None:
    class FakeProjectService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def retry_revision_output(self, output_id: str):
            self.calls.append(output_id)
            return {"output_id": output_id, "execution_state": "failed"}

    output = SimpleNamespace(id="timeout-output", output_id="body", execution_state="failed")
    revision = SimpleNamespace(outputs=[output])
    decision = RecoveryRouter().route(
        FailureObservation(
            observed_stage="build_execution",
            failure_class="worker_timeout",
            evidence={"timed_out": True},
            attempt_ordinal=1,
        )
    )
    project_service = FakeProjectService()

    result = await RecoveryActionExecutor(data_dir=Path(".")).execute(
        decision,
        revision=revision,
        contract={},
        project_service=project_service,
    )

    assert result.executed is True
    assert result.provider_calls == 0
    assert result.worker_calls == 1
    assert project_service.calls == ["timeout-output"]
