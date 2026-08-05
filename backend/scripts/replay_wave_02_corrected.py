#!/usr/bin/env python3
"""Replay the frozen Wave-02 provider responses through corrected boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import render_geometry_prompt_parameter_access_v1
from app.services.gemini_integration.real_ports import build_real_boundary_ports
from app.services.gemini_integration.representative_waves import load_wave_manifest
from app.services.gemini_integration.transport import ProviderCallResult
from app.services.gemini_integration.workflow import IntegrationWorkflowRunner


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "data/debug-sessions/representative-workflow-waves/representative-workflow-wave-02"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _provider_text(root: Path, project_id: str, stage: str) -> str | None:
    path = root / "captures" / f"{project_id}_{project_id}_revision-001_provider_{stage}.json"
    if not path.is_file():
        return None
    output = _read_json(path).get("output") or {}
    text = output.get("text")
    return str(text) if text is not None else None


def _raw_hashes(root: Path, projects: list[Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for project in projects:
        values: dict[str, str] = {}
        for stage in ("requirements", "plan", "geometry"):
            text = _provider_text(root, project.project_id, stage)
            if text is not None:
                values[stage] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result[project.project_id] = values
    return result


def _previous_plan(root: Path, project: Any) -> dict[str, Any] | None:
    if not project.revision_of:
        return None
    path = root / "captures" / f"{project.revision_of}_{project.revision_of}_revision-001_plan_adapter.json"
    if not path.is_file():
        return None
    normalized = (_read_json(path).get("output") or {}).get("normalized")
    return normalized if isinstance(normalized, dict) else None


async def _run(root: Path, repository_root: Path) -> dict[str, Any]:
    manifest = load_wave_manifest(root / "wave-manifest.json")
    profile = GeminiFlashLiteContractV1.from_repository(repository_root)
    replay_root = root / "replays" / "corrected-boundary-replay"
    if replay_root.exists():
        shutil.rmtree(replay_root)
    store = IntegrationEvidenceStore(replay_root, study_id="representative-workflow-wave-02-corrected-replay")
    ports = build_real_boundary_ports(
        profile=profile,
        evidence_store=store,
        jobs_root=replay_root / "worker-jobs",
    )

    async def frozen_provider_call(*, stage: str, prompt: str, operation_id: str) -> ProviderCallResult:
        project_id = operation_id.split(":")[1]
        text = _provider_text(root, project_id, stage)
        return ProviderCallResult(
            operation_id=operation_id,
            text=text,
            complete=text is not None,
            attempts=[],
            request_payload={"offline_replay": True, "stage": stage, "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()},
            actual_model=profile.model,
        )

    ports.provider_call = frozen_provider_call
    workflow = IntegrationWorkflowRunner(
        profile=profile,
        study_id="representative-workflow-wave-02",
        wave_id=manifest.wave_id,
        provenance_marker="volundr-representative-workflow-wave",
        evidence_store=store,
        ports=ports,
        geometry_prompt_renderer=render_geometry_prompt_parameter_access_v1,
    )

    outcomes: list[dict[str, Any]] = []
    for project in manifest.projects:
        outcome = await workflow.run_project(project, previous_design_plan=_previous_plan(root, project))
        outcomes.append(outcome.as_dict())

    worker_jobs = store.boundaries()
    worker_records = [
        item["output"]
        for item in worker_jobs
        if item.get("boundary") == "worker" and isinstance(item.get("output"), dict)
    ]
    result = {
        "schema_version": "volundr-wave-02-corrected-boundary-replay-v1",
        "phase": "correction_replay",
        "offline_only": True,
        "synthetic": True,
        "provider_success_eligible": False,
        "provider_calls": 0,
        "provider_attempts": 0,
        "worker_calls": len(worker_records),
        "projects": outcomes,
        "raw_provider_response_hashes": _raw_hashes(root, list(manifest.projects)),
        "raw_provider_responses_preserved": True,
        "baseline_capture_root": str(root / "captures"),
        "replay_capture_root": str(replay_root / "captures"),
        "boundary_count": len(store.boundaries()),
        "worker_results": worker_records,
        "production_routing_changed": False,
        "wave_02_representative_run": True,
    }
    replay_root.mkdir(parents=True, exist_ok=True)
    (replay_root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    result = asyncio.run(_run(args.root.resolve(), REPO_ROOT))
    print(json.dumps({"phase": result["phase"], "provider_calls": result["provider_calls"], "worker_calls": result["worker_calls"], "projects": len(result["projects"])}, sort_keys=True))


if __name__ == "__main__":
    main()
