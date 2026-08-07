"""Run the frozen Phase 1A first-blocker survey without repair operations.

This harness uses the ordinary executable-CadQuery Settings/provider/service
path, but passes ``provider_operation_limit=1`` to the existing ladder so an
initial failure becomes survey data instead of triggering L0/L1/L2/L3 repair.
It writes compact sanitized records to the preregistered evidence root; raw
provider responses remain in the controlled temporary data directory owned by
the existing provider-evidence boundary.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.revision import Revision
from app.schemas.validated_cadquery import ValidatedCadQueryStart
from app.api.dependencies import build_executable_ai_provider
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService
from app.services.geometry.snapshots import SnapshotRenderSettings, render_stl_view
from app.services.validated_cadquery_workflow import safe_diagnostic


EVIDENCE_SCHEMA_VERSION = "executable-cadquery-phase-1a-first-pass-v1"


class SurveyIntegrityError(RuntimeError):
    """Raised when the harness detects an operation outside the survey gate."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Mapping[str, Any]) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def model_dump(value: Any) -> dict[str, Any]:
    dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return dumped if isinstance(dumped, dict) else {}


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def first_provider_attempt(history: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for item in history:
        if item.get("attempt_number") == 1 and isinstance(item.get("provider_attempt"), Mapping):
            return item
    return history[0] if history else None


def owner_for(boundary: str | None, failure_class: str | None) -> str | None:
    if boundary in {"provider_response", "source_contract"}:
        return "provider" if boundary == "provider_response" else "source_contract"
    if boundary == "execution":
        return "worker"
    if boundary == "topology":
        return "topology_verifier"
    if boundary == "semantic":
        return "semantic_verifier"
    if boundary == "artifact":
        return "artifact_pipeline"
    if boundary == "package":
        return "package_pipeline"
    if boundary == "preview":
        return "preview_pipeline"
    if failure_class and "clarification" in failure_class:
        return "clarification"
    return None


def highest_stage(initial: Mapping[str, Any] | None, state: str) -> str:
    if initial is None:
        return "candidate_ready" if state in {"candidate_ready", "revision_ready"} else "workflow_initialization"
    boundary = str(initial.get("failure_boundary") or "")
    return {
        "provider_response": "provider_response",
        "source_contract": "source_contract",
        "execution": "execution",
        "topology": "topology",
        "semantic": "semantic_measurement",
        "artifact": "artifact",
        "package": "package",
        "preview": "presentation",
    }.get(boundary, "candidate_ready" if state in {"candidate_ready", "revision_ready"} else "worker")


def artifact_paths(data_dir: Path, revision: Revision | None) -> list[Path]:
    if revision is None:
        return []
    paths: list[Path] = []
    for output in revision.outputs:
        if not output.stl_path:
            continue
        path = Path(output.stl_path)
        paths.append(path if path.is_absolute() else data_dir / path)
    return [path.resolve() for path in paths if path.is_file()]


def render_first_view(
    *,
    data_dir: Path,
    revision: Revision | None,
    output_path: Path,
) -> bool:
    paths = artifact_paths(data_dir, revision)
    if not paths:
        return False
    try:
        render_stl_view(
            paths[0],
            output_path,
            "isometric",
            SnapshotRenderSettings(
                image_width=768,
                image_height=768,
                padding_ratio=0.08,
                background="neutral_light",
                edge_overlay=True,
            ),
        )
    except (OSError, ValueError, RuntimeError):
        return False
    return output_path.is_file() and output_path.stat().st_size > 0


def build_first_pass_record(
    *,
    project: Mapping[str, Any],
    contract: Mapping[str, Any],
    result: Any,
    workflow_error: str | None,
    output_root: Path,
    data_dir: Path,
    db: Any,
) -> dict[str, Any]:
    payload = model_dump(result)
    provenance = json_object(payload.get("provenance"))
    history = [item for item in provenance.get("repair_history", []) if isinstance(item, Mapping)]
    initial = first_provider_attempt(history)
    attempts = [item for item in history if isinstance(item.get("provider_attempt"), Mapping) and item.get("provider_attempt")]
    if len(attempts) > 1:
        raise SurveyIntegrityError(
            f"{project['project_id']} produced {len(attempts)} provider operations during Phase 1A first pass"
        )
    if any(str(item.get("repair_level") or "initial") not in {"initial", "L0"} for item in attempts):
        raise SurveyIntegrityError(f"{project['project_id']} entered a repair level during the first pass")

    state = str(payload.get("state") or "failed")
    diagnostics = json_object(payload.get("diagnostics"))
    initial_boundary = str(initial.get("failure_boundary")) if initial and initial.get("failure_boundary") else None
    initial_failure = str(initial.get("failure_class")) if initial and initial.get("failure_class") else None
    first_blocker = initial_failure or (None if state in {"candidate_ready", "revision_ready"} else str(diagnostics.get("kind") or "workflow_initialization_failure"))
    revision = db.get(Revision, payload.get("revision_id")) if payload.get("revision_id") else None
    render_path = output_root / f"{project['project_id']}-render.png"
    visible_model = render_first_view(data_dir=data_dir, revision=revision, output_path=render_path)
    worker_result = json_object(initial.get("worker_result")) if initial else {}
    topology_result = json_object(initial.get("topology_result")) if initial else {}
    semantic_result = json_object(initial.get("semantic_result")) if initial else {}
    output_records = []
    for output in payload.get("outputs", []):
        if not isinstance(output, Mapping):
            continue
        output_records.append(
            {
                "output_id": output.get("output_id"),
                "required": output.get("required"),
                "state": output.get("state"),
                "generation_status": output.get("generation_status"),
                "worker_status": output.get("worker_status"),
                "topology_status": output.get("topology_status"),
                "artifact_available": output.get("artifact_available"),
                "failure_owner": output.get("failure_owner"),
                "safe_diagnostic": output.get("safe_diagnostic"),
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "project_id": project["project_id"],
        "corpus_order": project["order"],
        "title": project.get("title"),
        "specification_category": project["specification_category"],
        "geometry_families": project.get("geometry_families", []),
        "prompt_sha256": sha256_text(str(project["prompt"])),
        "design_contract_sha256": sha256_json(contract),
        "clarification_count": len(project.get("clarifications", [])),
        "provider_attempt_count": len(attempts),
        "source_extracted": bool(initial and initial.get("extraction_succeeded")),
        "source_contract_valid": bool(initial and initial.get("source_contract_valid")),
        "worker_started": bool(worker_result.get("revision_id") or worker_result.get("phase")),
        "topology": {"observed": bool(initial), "result": topology_result},
        "semantic": {"observed": bool(initial), "result": semantic_result},
        "artifact": {
            "observed": bool(initial),
            "outputs_with_artifacts": sum(bool(item.get("artifact_available")) for item in output_records),
            "required_outputs": sum(bool(item.get("required")) for item in output_records),
        },
        "preview": {"observed": visible_model, "screenshot": str(render_path.relative_to(output_root)) if visible_model else None},
        "workflow_id": payload.get("id"),
        "project_runtime_id": payload.get("project_id"),
        "revision_id": payload.get("revision_id"),
        "state": state,
        "highest_stage_reached": highest_stage(initial, state),
        "first_unresolved_blocker": first_blocker,
        "observed_stage": initial_boundary or ("candidate_ready" if state in {"candidate_ready", "revision_ready"} else None),
        "normalized_failure_class": initial_failure,
        "first_incorrect_owner": owner_for(initial_boundary, initial_failure),
        "visible_model": visible_model,
        "candidate_ready_reached": state in {"candidate_ready", "revision_ready"},
        "outputs": output_records,
        "provider_transport": "gemini_api_rest_x_goog_api_key_via_GeminiApiProvider",
        "provider_repair_operations": 0,
        "workflow_error": safe_diagnostic(workflow_error) if workflow_error else None,
        "initial_attempt": {
            "failure_boundary": initial_boundary,
            "failure_class": initial_failure,
            "raw_response_hash": initial.get("raw_response_hash") if initial else None,
            "extracted_source_hash": initial.get("extracted_source_hash") if initial else None,
            "diagnostic": initial.get("diagnostic") if initial else None,
        },
    }


async def run_survey(manifest_path: Path, output_root: Path) -> None:
    manifest = read_json(manifest_path)
    projects = manifest.get("projects")
    if not isinstance(projects, list) or len(projects) != 16:
        raise ValueError("Phase 1A manifest must contain exactly 16 projects")
    if not settings.executable_cadquery_flow_enabled:
        raise ValueError("executable CadQuery flow must be explicitly enabled for the survey process")
    if settings.executable_cadquery_corpus_manifest_path is None:
        raise ValueError("survey process requires the frozen corpus manifest setting")
    if settings.executable_cadquery_corpus_manifest_path.resolve() != manifest_path.resolve():
        raise ValueError("survey process manifest setting does not match the frozen manifest")

    provider = build_executable_ai_provider(settings)
    runner = FilesystemCadWorkerRunner(jobs_root=settings.cad_workspace_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    for project in sorted(projects, key=lambda item: int(item["order"])):
        if not isinstance(project, Mapping):
            raise ValueError("Phase 1A manifest project must be an object")
        project_id = str(project["project_id"])
        contract = dict(project["contract"])
        started = time.perf_counter()
        workflow_error: str | None = None
        with SessionLocal() as db:
            service = ExecutableCadQueryWorkflowService(
                db=db,
                data_dir=settings.data_dir,
                ai_provider=provider,
                cad_runner=runner,
                owner_id="volundr-single-user",
            )
            original_ladder = service._generate_with_repair_ladder

            async def bounded_ladder(*args: Any, **kwargs: Any) -> Any:
                kwargs["provider_operation_limit"] = 1
                return await original_ladder(*args, **kwargs)

            service._generate_with_repair_ladder = bounded_ladder  # type: ignore[method-assign]
            try:
                result = await service.start_design(
                    ValidatedCadQueryStart(name=str(project["title"]), intent=str(project["prompt"]))
                )
            except Exception as exc:
                result = {"state": "failed", "diagnostics": {"kind": "survey_harness_failure"}}
                workflow_error = str(exc)
            record = build_first_pass_record(
                project=project,
                contract=contract,
                result=result,
                workflow_error=workflow_error,
                output_root=output_root,
                data_dir=settings.data_dir,
                db=db,
            )
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            write_json(output_root / f"project-{int(project['order']):02d}-first-pass.json", record)
        print(
            json.dumps(
                {
                    "project_id": project_id,
                    "state": record["state"],
                    "first_unresolved_blocker": record["first_unresolved_blocker"],
                    "provider_attempts": record["provider_attempt_count"],
                },
                sort_keys=True,
            ),
            flush=True,
        )


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(run_survey(args.manifest.resolve(), args.output_root.resolve()))
    except SurveyIntegrityError:
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
