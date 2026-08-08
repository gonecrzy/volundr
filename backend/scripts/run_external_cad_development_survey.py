"""Run the frozen external-cad-50-v1.1 development first-pass survey.

This runner is intentionally a thin benchmark harness around the normal
executable-CadQuery service.  It never materializes a benchmark-authored
executable contract and never loads validation/holdout project details.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select

from app.api.dependencies import build_executable_ai_provider
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.clarification_question import ClarificationQuestion
from app.models.design_specification import DesignSpecification
from app.models.generation_attempt import GenerationAttempt
from app.models.revision import Revision
from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
from app.schemas.validated_cadquery import ValidatedCadQueryStart
from app.services.ai.gemini_cli import (
    CADQUERY_COMPONENT_REVISION_PROMPT_VERSION,
    CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION,
    CADQUERY_SOURCE_PROMPT_VERSION,
    CONTRACT_REPAIR_PROMPT_VERSION,
    DESIGN_PLAN_PROMPT_VERSION,
    GEMINI_RULESET_VERSION,
    REQUIREMENTS_PROMPT_VERSION,
    REVISION_PLAN_PROMPT_VERSION,
    SCOPE_CORRECTION_PROMPT_VERSION,
    SOURCE_BRIEF_PROMPT_VERSION,
)
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.executable_cadquery.repair import AUTOMATIC_PROVIDER_OPERATION_BUDGET
from app.services.external_benchmarks.comparison import compare_reference_geometry
from app.services.external_benchmarks.reference_analysis import analyze_reference, sha256_file
from app.services.external_benchmarks.survey import (
    SURVEY_SCHEMA_VERSION,
    FrozenSurveyProject,
    SurveyCell,
    build_survey_order,
    load_frozen_development_projects,
    reference_similarity_status,
)
from app.services.projects.requirement_ledger import RequirementLedgerStore, active_requirements
from app.services.validated_cadquery_workflow import safe_diagnostic


class SurveyIntegrityError(RuntimeError):
    """Raised when the frozen survey boundary is violated."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v11-manifest",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1.1/manifest.json",
    )
    parser.add_argument(
        "--v1-manifest",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1/manifest.json",
    )
    parser.add_argument(
        "--development-specs",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1.1/comparison-specifications-development.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "data/debug-sessions/external-benchmarks/cad-50-v1.1/development-first-pass",
    )
    return parser.parse_args()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _model_dump(value: Any) -> dict[str, Any]:
    dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return dict(dumped) if isinstance(dumped, Mapping) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_versions() -> dict[str, str]:
    return {
        "requirements": REQUIREMENTS_PROMPT_VERSION,
        "design_plan": DESIGN_PLAN_PROMPT_VERSION,
        "cadquery_source": CADQUERY_SOURCE_PROMPT_VERSION,
        "contract_repair": CONTRACT_REPAIR_PROMPT_VERSION,
        "cadquery_execution_repair": CADQUERY_EXECUTION_REPAIR_PROMPT_VERSION,
        "scope_correction": SCOPE_CORRECTION_PROMPT_VERSION,
        "component_revision": CADQUERY_COMPONENT_REVISION_PROMPT_VERSION,
        "revision_plan": REVISION_PLAN_PROMPT_VERSION,
        "source_brief": SOURCE_BRIEF_PROMPT_VERSION,
        "ruleset": GEMINI_RULESET_VERSION,
    }


def _build_preflight(
    *,
    v11_manifest: Path,
    v1_manifest: Path,
    development_specs: Path,
    projects: tuple[FrozenSurveyProject, ...],
    order: tuple[SurveyCell, ...],
    output_root: Path,
) -> dict[str, Any]:
    corpus_env = os.environ.get("VOLUNDR_EXECUTABLE_CADQUERY_CORPUS_MANIFEST_PATH")
    if corpus_env:
        raise SurveyIntegrityError("corpus-manifest injection is present before survey start")
    if settings.executable_cadquery_corpus_manifest_path is not None:
        raise SurveyIntegrityError("Settings contains a corpus manifest during external survey")
    if not settings.executable_cadquery_flow_enabled:
        raise SurveyIntegrityError("executable CadQuery flow is not enabled")
    if not settings.gemini_primary_api_key:
        raise SurveyIntegrityError("primary Gemini credential is absent before survey start")

    return {
        "schema_version": SURVEY_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "code_commit": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "origin_branch_head": _git("rev-parse", "origin/experiment/gemini-executable-cadquery-v1"),
        "main_head": _git("rev-parse", "main"),
        "worktree_clean": _git("status", "--porcelain") == "",
        "execution_mode": "direct_normal_executable_cadquery_service",
        "provider": {
            "configured_provider": settings.ai_provider,
            "transport": "gemini_api_rest_x_goog_api_key_via_GeminiApiProvider",
            "model": settings.gemini_model,
            "requirements_model": settings.gemini_requirements_model or settings.gemini_model,
            "geometry_model": settings.gemini_geometry_model or settings.gemini_model,
            "primary_slot_present": bool(settings.gemini_primary_api_key),
            "fallback_slot_present": bool(settings.gemini_fallback_api_key),
            "fallback_policy": "fallback only after HTTP 429",
        },
        "repair_limits": {
            "automatic_provider_operation_budget": AUTOMATIC_PROVIDER_OPERATION_BUDGET,
            "workflow_provider_operation_limit_override": None,
            "changed_for_survey": False,
        },
        "prompt_versions": _prompt_versions(),
        "frozen_inputs": {
            "v11_manifest_sha256": _file_hash(v11_manifest),
            "v1_manifest_sha256": _file_hash(v1_manifest),
            "development_specs_sha256": _file_hash(development_specs),
            "development_project_count": len(projects),
            "live_cell_count": len([cell for cell in order if not cell.excluded]),
            "excluded_cell_count": len([cell for cell in order if cell.excluded]),
            "development_ids": [project.benchmark_id for project in projects],
            "comparison_specification_hashes": {
                project.benchmark_id: project.comparison_specification_hash for project in projects
            },
            "reference_set_hashes": {
                project.benchmark_id: project.reference_set_sha256 for project in projects
            },
        },
        "environment_boundary": {
            "corpus_manifest_env_present": bool(corpus_env),
            "settings_corpus_manifest_configured": settings.executable_cadquery_corpus_manifest_path is not None,
            "reference_geometry_loaded_by_runner": False,
            "holdout_details_loaded_by_runner": False,
            "reference_geometry_sent_to_provider": False,
            "historical_pilot_evidence_overwritten": False,
            "output_root": str(output_root),
        },
    }


def _survey_order_payload(order: tuple[SurveyCell, ...]) -> dict[str, Any]:
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-order",
        "sequential": True,
        "passes": ["premise_only", "comparison_specification"],
        "cells": [
            {
                "order": cell.order,
                "benchmark_id": cell.benchmark_id,
                "category": cell.category,
                "mode": cell.mode,
                "prompt_sha256": _sha256_text(cell.prompt),
                "excluded": cell.excluded,
                "exclusion_reason": cell.exclusion_reason,
                "comparison_ready": cell.comparison_ready,
                "reference_similarity_status": cell.reference_similarity_status,
                "comparison_specification_hash": cell.comparison_specification_hash,
                "reference_set_sha256": cell.reference_set_sha256,
            }
            for cell in order
        ],
    }


def _safe_transport_record(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "logical_operation_id",
        "attempt_id",
        "attempt_index",
        "credential_slot",
        "credential_present",
        "request_hash",
        "status_code",
        "failure_class",
        "retry_delay_seconds",
        "request_started_at",
        "response_received",
        "response_length",
        "raw_response_hash",
        "exception_type",
        "normalized_transport_error",
        "transport_retry_classification",
        "rate_limit_429_classification",
        "provider_request_id",
    )
    return {key: record.get(key) for key in keys}


def _safe_history(history: Any) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        provider_attempt = item.get("provider_attempt")
        provider_attempt = provider_attempt if isinstance(provider_attempt, Mapping) else {}
        transport_attempts = provider_attempt.get("transport_attempts")
        transport_attempts = transport_attempts if isinstance(transport_attempts, list) else []
        safe.append(
            {
                "operation_id": item.get("operation_id"),
                "attempt_number": item.get("attempt_number"),
                "repair_level": item.get("repair_level"),
                "observed_stage": item.get("observed_stage"),
                "failure_boundary": item.get("failure_boundary"),
                "failure_class": item.get("failure_class"),
                "first_incorrect_owner": item.get("first_incorrect_owner"),
                "source_hash": item.get("source_hash"),
                "extracted_source_hash": item.get("extracted_source_hash"),
                "raw_response_hash": item.get("raw_response_hash"),
                "extraction_succeeded": item.get("extraction_succeeded"),
                "syntax_valid": item.get("syntax_valid"),
                "source_contract_valid": item.get("source_contract_valid"),
                "result_hash": item.get("result_hash"),
                "normalized_error": safe_diagnostic(str(item.get("normalized_error"))) if item.get("normalized_error") else None,
                "progress": item.get("progress"),
                "revision_id": item.get("revision_id"),
                "provider_attempt": {
                    "attempt_number": provider_attempt.get("attempt_number"),
                    "level": provider_attempt.get("level"),
                    "status": provider_attempt.get("status"),
                    "failure_class": provider_attempt.get("failure_class"),
                    "logical_operation_id": provider_attempt.get("logical_operation_id"),
                    "attempt_id": provider_attempt.get("attempt_id"),
                    "transport_attempts": [
                        _safe_transport_record(attempt)
                        for attempt in transport_attempts
                        if isinstance(attempt, Mapping)
                    ],
                },
                "worker_result": _safe_worker_result(item.get("worker_result")),
                "topology_result": _safe_topology_result(item.get("topology_result")),
                "semantic_result": _safe_semantic_result(item.get("semantic_result")),
            }
        )
    return safe


def _safe_worker_result(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, Mapping) else {}
    return {
        key: value.get(key)
        for key in (
            "job_id",
            "phase",
            "success",
            "failure_class",
            "output_ids",
            "result_hash",
            "execution_manifest_path",
        )
    }


def _safe_topology_result(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, Mapping) else {}
    return {
        key: value.get(key)
        for key in (
            "valid",
            "outcome",
            "detected_solid_count",
            "expected_solid_count",
            "schema_version",
            "failure_class",
        )
    }


def _safe_semantic_result(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, Mapping) else {}
    safe: dict[str, Any] = {}
    for key in ("status", "passed", "failed", "unverifiable", "review_required", "informational", "unsupported"):
        current = value.get(key)
        if isinstance(current, list):
            safe[key] = current
        elif current is not None:
            safe[key] = current
    return safe


def _resolve_data_path(data_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = data_dir / path
    return path.resolve()


def _compact_geometry_analysis(value: Mapping[str, Any]) -> dict[str, Any]:
    geometry = value.get("geometry") if isinstance(value.get("geometry"), Mapping) else {}
    mesh = value.get("mesh") if isinstance(value.get("mesh"), Mapping) else {}
    topology = value.get("topology") if isinstance(value.get("topology"), Mapping) else {}
    return {
        "schema_version": value.get("schema_version"),
        "file_type": value.get("file_type"),
        "authority": value.get("authority"),
        "quality_classification": value.get("quality_classification"),
        "units": value.get("units"),
        "geometry": {
            key: geometry.get(key)
            for key in (
                "bounding_box_mm",
                "volume_mm3",
                "surface_area_mm2",
                "center_of_mass_mm",
                "solid_count",
                "component_count",
            )
        },
        "mesh": {
            key: mesh.get(key)
            for key in ("vertex_count", "face_count", "component_count", "watertight", "winding_consistent")
            if key in mesh
        },
        "topology": {
            key: topology.get(key)
            for key in ("schema_version", "valid", "solid_count", "face_count", "shell_count", "volume")
            if key in topology
        },
    }


def _analyze_generated_output(data_dir: Path, output: Any) -> dict[str, Any]:
    values = {
        "output_id": output.output_id,
        "required": output.required,
        "generation_status": output.generation_status,
        "worker_status": output.worker_status,
        "state": output.state,
        "solid_count": output.solid_count,
        "topology_status": output.topology_status,
        "semantic_verification": output.semantic_verification,
        "artifact_available": output.artifact_available,
        "failure_owner": output.failure_owner,
        "safe_diagnostic": output.safe_diagnostic,
        "artifact_hashes": {},
        "geometry": None,
    }
    for kind in ("step", "brep", "stl"):
        relative = getattr(output, f"{kind}_path", None)
        digest = getattr(output, f"{kind}_hash", None)
        path = _resolve_data_path(data_dir, relative)
        if not path or not digest or not path.is_file():
            continue
        values["artifact_hashes"][kind] = digest
        if values["geometry"] is None and kind in {"step", "brep", "stl"}:
            try:
                values["geometry"] = _compact_geometry_analysis(analyze_reference(path, file_type=kind))
            except Exception as exc:
                values["geometry"] = {"analysis_error": type(exc).__name__}
    return values


def _reference_payload(project: FrozenSurveyProject) -> tuple[dict[str, Any], dict[str, Any]]:
    if not project.reference_files:
        raise SurveyIntegrityError(f"reference files absent for {project.benchmark_id}")
    derived_path = ROOT / str(project.reference_files[0]["relative_path"])
    derived_path = derived_path.parent.parent / "derived-reference.json"
    if not derived_path.is_file():
        raise SurveyIntegrityError(f"derived reference evidence is absent for {project.benchmark_id}")
    payload = json.loads(derived_path.read_text(encoding="utf-8"))
    if payload.get("reference_set_sha256") != project.reference_set_sha256:
        raise SurveyIntegrityError(f"reference set hash mismatch for {project.benchmark_id}")
    parts = payload.get("canonical_parts")
    if not isinstance(parts, list):
        parts = []
    reference_parts = [
        {
            "part_id": item.get("part_id"),
            "derived": item.get("derived", {}),
        }
        for item in parts
        if isinstance(item, Mapping) and item.get("part_id")
    ]
    return payload, {
        "derived_reference_path": str(derived_path.relative_to(ROOT)),
        "canonical_part_count": project.canonical_part_count,
        "canonical_parts": [_compact_geometry_analysis(item["derived"]) for item in reference_parts],
        "canonical_part_ids": [item["part_id"] for item in reference_parts],
        "authority": payload.get("authority"),
        "quality_classification": payload.get("quality_classification"),
    }


def _comparison_record(
    *,
    project: FrozenSurveyProject,
    mode: str,
    generated_outputs: list[dict[str, Any]],
    requirement_compliance: Mapping[str, Any],
) -> dict[str, Any]:
    if project.excluded:
        return {
            "status": "replacement_required",
            "metrics": {},
            "raw_reference": None,
            "raw_generated": None,
            "mapping_status": "excluded_replacement_required",
        }
    reference_payload, reference_summary = _reference_payload(project)
    generated_parts = {
        str(output["output_id"]): output["geometry"]
        for output in generated_outputs
        if output.get("output_id") and isinstance(output.get("geometry"), Mapping)
    }
    if mode == "comparison_specification":
        status = reference_similarity_status(project.comparison_specification_status, generated=bool(generated_parts))
    else:
        status = "specification_underconstrained" if generated_parts else "unavailable"

    if len(reference_summary["canonical_part_ids"]) <= 1:
        reference_part = (
            reference_payload.get("canonical_parts", [{}])[0].get("derived", {})
            if reference_payload.get("canonical_parts")
            else reference_payload
        )
        generated_geometry = next(iter(generated_parts.values()), {})
        comparison = compare_reference_geometry(
            reference={"geometry": reference_part.get("geometry", {})},
            generated=generated_geometry if isinstance(generated_geometry, Mapping) else {},
            requirement_compliance=requirement_compliance,
        )
        raw_generated = generated_geometry
    else:
        comparison = compare_reference_geometry(
            reference={
                "canonical_parts": reference_payload.get("canonical_parts", []),
                "aggregate_geometry": reference_payload.get("aggregate_geometry", {}),
            },
            generated={"parts": generated_parts, "aggregate_geometry": {}},
            requirement_compliance=requirement_compliance,
            reference_output_mapping=project.reference_output_mapping,
        )
        raw_generated = generated_parts
    similarity = comparison.get("reference_similarity", {})
    return {
        "status": status,
        "metrics": similarity.get("metrics", {}),
        "raw_reference": reference_summary,
        "raw_generated": raw_generated,
        "mapping_status": similarity.get("metrics", {}).get("mapping_status"),
        "eligible_interpretation": status == "eligible",
        "comparison_engine_status": similarity.get("status"),
    }


def _semantic_counts(verification: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    semantic = verification.get("semantic_verification")
    if not isinstance(semantic, Mapping):
        semantic = verification.get("semantic_result")
    if not isinstance(semantic, Mapping):
        semantic = verification

    def count(*keys: str) -> int:
        for key in keys:
            value = semantic.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return 0

    active = active_requirements(dict(ledger))
    return {
        "total_authoritative_requirements": len(active),
        "machine_pass": count("machine_pass", "passed", "pass"),
        "machine_fail": count("machine_fail", "failed", "fail"),
        "unverifiable": count("unverifiable", "unknown"),
        "review_required": count("review_required", "review"),
        "informational": count("informational", "info"),
        "unsupported_verifier": count("unsupported", "unsupported_verifier"),
        "overall_status": semantic.get("status") or verification.get("status"),
        "candidate_state": verification.get("candidate_state"),
    }


def _requirement_anomalies(specification: Mapping[str, Any]) -> dict[str, Any]:
    requirements = specification.get("requirements")
    if not isinstance(requirements, list):
        requirements = specification.get("authoritative_requirements")
    if not isinstance(requirements, list):
        return {
            "missing_or_clarification_labeled_user": [],
            "model_assumption_labeled_user_required": [],
            "user_explicit_lost_authority": [],
        }
    anomalies = {
        "missing_or_clarification_labeled_user": [],
        "model_assumption_labeled_user_required": [],
        "user_explicit_lost_authority": [],
    }
    for item in requirements:
        if not isinstance(item, Mapping):
            continue
        requirement_id = str(item.get("requirement_id") or item.get("id") or "<unknown>")
        source = str(item.get("source") or item.get("origin") or "")
        explicit = item.get("explicit") is True
        classification = str(item.get("classification") or item.get("policy") or "")
        missing = bool(item.get("missing")) or item.get("value") is None and bool(item.get("required"))
        if missing and source in {"user", "initial_user"}:
            anomalies["missing_or_clarification_labeled_user"].append(requirement_id)
        if not explicit and source in {"user", "initial_user"} and classification in {"required", "machine_required"}:
            anomalies["model_assumption_labeled_user_required"].append(requirement_id)
        if explicit and source not in {"user", "initial_user", "clarification_user"}:
            anomalies["user_explicit_lost_authority"].append(requirement_id)
    return anomalies


def _map_first_blocker(item: Mapping[str, Any] | None, state: str, diagnostics: Mapping[str, Any]) -> str:
    if item is None:
        if state in {"candidate_ready", "revision_ready"}:
            return "candidate_ready"
        if state == "awaiting_clarification":
            return "clarification_required"
        return "executable_contract"
    boundary = str(item.get("failure_boundary") or item.get("observed_stage") or "").lower()
    failure = str(item.get("failure_class") or "").lower()
    provider_attempt = item.get("provider_attempt")
    provider_attempt = provider_attempt if isinstance(provider_attempt, Mapping) else {}
    transport = provider_attempt.get("transport_attempts")
    transport = transport if isinstance(transport, list) else []
    if ("provider" in failure or boundary in {"provider_response", "provider_transport"}) and transport:
        final = transport[-1] if isinstance(transport[-1], Mapping) else {}
        if final.get("response_received") is False or final.get("status_code") in {None, 408, 429, 500, 502, 503, 504, 599}:
            return "cad_provider_transport"
    if boundary in {"provider_response", "provider_source_extraction"}:
        return "cad_provider_response_contract"
    if boundary in {"source_contract", "contract"}:
        return "source_contract"
    if boundary in {"execution", "worker", "source_execution"}:
        return "source_execution"
    if boundary == "topology":
        return "topology"
    if boundary in {"semantic", "semantic_measurement", "semantic_verification"}:
        return "semantic_verification"
    if boundary in {"artifact", "package", "preview"}:
        return "artifact_packaging"
    if state in {"candidate_ready", "revision_ready"}:
        return "candidate_ready"
    return str(diagnostics.get("kind") or "executable_contract")


def _terminal_stage(state: str) -> str:
    return {
        "awaiting_clarification": "clarification_required",
        "candidate_ready": "candidate_ready",
        "revision_ready": "candidate_ready",
        "verification_failed": "semantic_verification",
        "failed": "executable_contract",
    }.get(state, state or "executable_contract")


def _count_requirement_attempts(attempts: list[GenerationAttempt]) -> tuple[int, int, int]:
    requirement_attempts = [item for item in attempts if item.provider_response_stage == "requirements"]
    calls = sum(max(1, int(item.provider_call_count or 0)) for item in requirement_attempts)
    schema_retries = sum(
        1
        for item in requirement_attempts
        if item.content_repair_count > 0 or item.provider_response_classification == "schema_invalid"
    )
    invalid_responses = sum(
        1
        for item in requirement_attempts
        if item.provider_response_classification == "schema_invalid"
    )
    return calls, schema_retries, invalid_responses


def _build_cell_record(
    *,
    project: FrozenSurveyProject,
    cell: SurveyCell,
    result: Any,
    db: Any,
    data_dir: Path,
    observed_transport: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    payload = _model_dump(result)
    workflow_id = payload.get("id")
    if not workflow_id:
        raise SurveyIntegrityError(f"workflow did not return an ID for {cell.benchmark_id}/{cell.mode}")
    workflow = db.get(ValidatedCadQueryWorkflow, workflow_id)
    if workflow is None:
        raise SurveyIntegrityError(f"workflow persistence missing for {cell.benchmark_id}/{cell.mode}")
    state = str(workflow.state)
    provenance = _json_object(workflow.provenance_json)
    history = _json_object(workflow.provenance_json).get("repair_history", [])
    safe_history = _safe_history(history)
    initial = safe_history[0] if safe_history else None
    specification = db.get(DesignSpecification, workflow.design_specification_id) if workflow.design_specification_id else None
    specification_payload = _json_object(workflow.requirements_json)
    questions = []
    if specification is not None:
        questions = [
            {
                "question_id": question.id,
                "requirement_id": question.requirement_id,
                "question": question.question,
                "reason": question.reason,
                "display_order": question.display_order,
            }
            for question in db.scalars(
                select(ClarificationQuestion)
                .where(ClarificationQuestion.design_specification_id == specification.id)
                .order_by(ClarificationQuestion.display_order.asc(), ClarificationQuestion.id.asc())
            )
        ]
    ledger = RequirementLedgerStore(db).load(workflow.project_id)
    attempts = list(
        db.scalars(
            select(GenerationAttempt)
            .where(GenerationAttempt.project_id == workflow.project_id)
            .order_by(GenerationAttempt.attempt_number.asc(), GenerationAttempt.id.asc())
        )
    )
    requirement_calls, schema_retries, invalid_responses = _count_requirement_attempts(attempts)
    revision = db.get(Revision, workflow.revision_id) if workflow.revision_id else None
    generated_outputs = []
    artifact_hashes: dict[str, str] = {}
    worker_ids: set[str] = set()
    if revision is not None:
        for output in revision.outputs:
            generated = _analyze_generated_output(data_dir, output)
            generated_outputs.append(generated)
            for kind, digest in generated["artifact_hashes"].items():
                artifact_hashes[f"{output.output_id}:{kind}"] = digest
    if workflow.package_path:
        package_path = _resolve_data_path(data_dir, workflow.package_path)
        if package_path and package_path.is_file():
            artifact_hashes["design_package"] = sha256_file(package_path)
    for item in safe_history:
        worker = item.get("worker_result") or {}
        if worker.get("job_id"):
            worker_ids.add(str(worker["job_id"]))

    verification = _json_object(workflow.verification_json)
    semantic_counts = _semantic_counts(verification, ledger)
    contract = provenance.get("executable_design_contract")
    contract = dict(contract) if isinstance(contract, Mapping) else None
    contract_source = provenance.get("contract_source") or (contract or {}).get("contract_source")
    if contract is not None and contract_source != "production_requirement_ledger":
        raise SurveyIntegrityError(
            f"invalid contract source for {cell.benchmark_id}/{cell.mode}: {contract_source}"
        )
    if contract is not None and _contains_reference_identifiers(contract, project):
        raise SurveyIntegrityError(f"reference metadata entered executable contract for {cell.benchmark_id}/{cell.mode}")

    generated = state in {"candidate_ready", "revision_ready"} or bool(generated_outputs)
    comparison = _comparison_record(
        project=project,
        mode=cell.mode,
        generated_outputs=generated_outputs,
        requirement_compliance=semantic_counts,
    ) if generated else {
        "status": "replacement_required" if project.excluded else "unavailable",
        "metrics": {},
        "raw_reference": None,
        "raw_generated": None,
        "mapping_status": "not_generated",
        "eligible_interpretation": False,
    }
    source_specification = specification_payload.get("specification", specification_payload)
    if not isinstance(source_specification, Mapping):
        source_specification = {}
    first_blocker = "clarification_required" if state == "awaiting_clarification" else _map_first_blocker(initial, state, _json_object(workflow.diagnostics_json))
    normal_recovery_resolved = bool(initial and len(safe_history) > 1 and state in {"candidate_ready", "revision_ready"})
    cad_generation_calls = sum(1 for item in safe_history if str(item.get("repair_level") or "initial") in {"initial", "initial_generation"})
    cad_repair_calls = sum(1 for item in safe_history if str(item.get("repair_level") or "initial") not in {"initial", "initial_generation"})
    fallback_calls = sum(1 for item in observed_transport if item.get("credential_slot") == "fallback")
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-cell",
        "benchmark_project_id": project.benchmark_id,
        "category": project.category,
        "mode": cell.mode,
        "prompt": cell.prompt,
        "prompt_sha256": _sha256_text(cell.prompt),
        "comparison_specification_hash": project.comparison_specification_hash,
        "reference_set_sha256": project.reference_set_sha256,
        "workflow_id": workflow.id,
        "project_runtime_id": workflow.project_id,
        "revision_id": workflow.revision_id,
        "state": state,
        "terminal_stage": _terminal_stage(state),
        "first_blocker_stage": first_blocker,
        "failure_class": initial.get("failure_class") if initial else None,
        "first_incorrect_owner": initial.get("first_incorrect_owner") if initial else None,
        "observed_stage": initial.get("observed_stage") if initial else None,
        "normal_recovery_resolved": normal_recovery_resolved,
        "timing_seconds": elapsed_seconds,
        "requirement_extraction": {
            "design_specification_id": specification.id if specification else None,
            "provider_calls": requirement_calls,
            "schema_retries": schema_retries,
            "schema_invalid_responses": invalid_responses,
            "requirements": source_specification.get("requirements", source_specification.get("authoritative_requirements", [])),
            "requirement_ids": [
                item.get("requirement_id") or item.get("id")
                for item in source_specification.get("requirements", [])
                if isinstance(item, Mapping)
            ] if isinstance(source_specification.get("requirements", []), list) else [],
            "assumptions": source_specification.get("assumptions", []),
            "missing_requirements": source_specification.get("missing_requirements", []),
            "clarification_required": state == "awaiting_clarification",
            "clarification_questions": questions,
            "clarification_question_count": len(questions),
            "generation_ready": bool(specification and specification.generation_ready),
            "source_label_anomalies": _requirement_anomalies(source_specification),
        },
        "requirement_ledger": ledger,
        "executable_contract": {
            "created": contract is not None,
            "contract_source": contract_source,
            "contract": contract,
            "contract_hash": _sha256_json(contract) if contract is not None else None,
        },
        "provider_attempt_forensics": observed_transport,
        "cad_calls": {
            "initial_generation_calls": cad_generation_calls,
            "repair_calls": cad_repair_calls,
            "fallback_calls": fallback_calls,
            "total_transport_attempts": len(observed_transport),
            "repair_history": safe_history,
        },
        "worker": {
            "execution_count": len(worker_ids),
            "job_ids": sorted(worker_ids),
            "outputs": generated_outputs,
        },
        "topology": {
            "valid": all(
                output.get("geometry", {}).get("topology", {}).get("valid") is not False
                for output in generated_outputs
                if isinstance(output.get("geometry"), Mapping)
            ) if generated_outputs else None,
            "outputs": [
                {
                    "output_id": output.get("output_id"),
                    "solid_count": output.get("solid_count"),
                    "topology_status": output.get("topology_status"),
                    "geometry_topology": (output.get("geometry") or {}).get("topology"),
                }
                for output in generated_outputs
            ],
        },
        "semantic": semantic_counts,
        "artifacts": {
            "hashes": artifact_hashes,
            "package_available": bool(workflow.package_path),
        },
        "reference_comparison": comparison,
        "reference_only_isolation": {
            "reference_geometry_sent_to_provider": False,
            "forbidden_reference_identifiers_in_prompt": _reference_identifiers_in_prompt(cell.prompt, project),
            "hidden_reference_facts_used_for_premise_only": False,
        },
        "provider_transport": "gemini_api_rest_x_goog_api_key_via_GeminiApiProvider",
    }


def _reference_identifiers_in_prompt(prompt: str, project: FrozenSurveyProject) -> list[str]:
    # These are development-only provenance identifiers used for the audit;
    # they are never sent to the provider by this harness.
    forbidden: list[str] = []
    for reference_file in project.reference_files:
        for key in ("original_filename", "relative_path", "sha256"):
            value = reference_file.get(key)
            if isinstance(value, str) and value and value in prompt:
                forbidden.append(value)
    return forbidden


def _contains_reference_identifiers(value: Any, project: FrozenSurveyProject) -> bool:
    rendered = json.dumps(value, sort_keys=True, default=str)
    candidates = [project.reference_set_sha256]
    for reference_file in project.reference_files:
        candidates.extend(
            str(reference_file.get(key))
            for key in ("original_filename", "relative_path", "sha256")
            if reference_file.get(key)
        )
    return any(candidate in rendered for candidate in candidates)


def _replacement_records(order: tuple[SurveyCell, ...]) -> list[dict[str, Any]]:
    return [
        {
            "order": cell.order,
            "benchmark_id": cell.benchmark_id,
            "category": cell.category,
            "mode": cell.mode,
            "status": "excluded_replacement_required",
            "provider_calls": 0,
            "worker_executions": 0,
        }
        for cell in order
        if cell.excluded
    ]


def _cell_path(output_root: Path, cell: SurveyCell) -> Path:
    folder = "premise-only" if cell.mode == "premise_only" else "comparison-specification"
    return output_root / folder / cell.benchmark_id / "run.json"


def _safe_error_record(project: FrozenSurveyProject, cell: SurveyCell, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-cell",
        "benchmark_project_id": project.benchmark_id,
        "category": project.category,
        "mode": cell.mode,
        "prompt_sha256": _sha256_text(cell.prompt),
        "state": "survey_harness_error",
        "terminal_stage": "survey_harness",
        "first_blocker_stage": "survey_harness",
        "failure_class": type(exc).__name__,
        "first_incorrect_owner": "survey_harness",
        "error": safe_diagnostic(str(exc)),
        "provider_calls": 0,
        "worker_executions": 0,
    }


def _excluded_record(cell: SurveyCell) -> dict[str, Any]:
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-cell",
        "benchmark_project_id": cell.benchmark_id,
        "category": cell.category,
        "mode": cell.mode,
        "prompt_sha256": _sha256_text(cell.prompt),
        "state": "excluded_replacement_required",
        "terminal_stage": "replacement_excluded",
        "first_blocker_stage": "replacement_excluded",
        "failure_class": None,
        "first_incorrect_owner": None,
        "provider_calls": 0,
        "worker_executions": 0,
        "reference_comparison": {
            "status": "replacement_required",
            "eligible_interpretation": False,
        },
    }


def _rate_limit_audit(provider: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    all_transport = [
        item
        for record in records
        for item in record.get("provider_attempt_forensics", [])
        if isinstance(item, Mapping)
    ]
    starts = [
        float(item["started_monotonic"])
        for item in all_transport
        if item.get("started_monotonic") is not None
    ]
    starts.sort()
    gaps = [right - left for left, right in zip(starts, starts[1:])]
    rolling_max = 0
    for start in starts:
        rolling_max = max(rolling_max, sum(1 for candidate in starts if start - 60.0 < candidate <= start))
    primary_limiter = getattr(provider, "_validated_primary_limiter", None)
    fallback_limiter = getattr(provider, "_validated_fallback_limiter", None)
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-rate-limit-audit",
        "concurrency": 1,
        "minimum_start_gap_seconds": min(gaps) if gaps else None,
        "rolling_window_maximum": rolling_max,
        "policy_unchanged": True,
        "fallback_policy": "fallback only after HTTP 429",
        "transport_attempt_count": len(all_transport),
        "fallback_attempt_count": sum(1 for item in all_transport if item.get("credential_slot") == "fallback"),
        "429_attempt_count": sum(1 for item in all_transport if item.get("status_code") == 429),
        "request_start_timestamps": [item.get("request_started_at") for item in all_transport],
        "limiters": {
            "primary": {
                "requests_per_minute": getattr(primary_limiter, "requests_per_minute", None),
                "hard_max_requests_per_window": getattr(primary_limiter, "hard_max_requests_per_window", None),
                "minimum_gap_seconds": getattr(primary_limiter, "minimum_gap_seconds", None),
                "window_seconds": getattr(primary_limiter, "window_seconds", None),
            },
            "fallback": {
                "requests_per_minute": getattr(fallback_limiter, "requests_per_minute", None),
                "hard_max_requests_per_window": getattr(fallback_limiter, "hard_max_requests_per_window", None),
                "minimum_gap_seconds": getattr(fallback_limiter, "minimum_gap_seconds", None),
                "window_seconds": getattr(fallback_limiter, "window_seconds", None),
            },
        },
    }


def _aggregate(records: list[dict[str, Any]], projects: tuple[FrozenSurveyProject, ...]) -> dict[str, Any]:
    live_records = [record for record in records if record.get("state") != "excluded_replacement_required"]
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in live_records:
        by_mode[str(record.get("mode"))].append(record)

    def mode_summary(mode: str) -> dict[str, Any]:
        mode_records = by_mode.get(mode, [])
        requirement = [record.get("requirement_extraction", {}) for record in mode_records]
        cad = [record.get("cad_calls", {}) for record in mode_records]
        return {
            "projects_attempted": len(mode_records),
            "requirement_extraction_calls": sum(int(item.get("provider_calls") or 0) for item in requirement),
            "schema_retry_count": sum(int(item.get("schema_retries") or 0) for item in requirement),
            "generation_ready_count": sum(bool(item.get("generation_ready")) for item in requirement),
            "clarification_required_count": sum(bool(item.get("clarification_required")) for item in requirement),
            "mean_clarification_question_count": (
                sum(int(item.get("clarification_question_count") or 0) for item in requirement) / len(requirement)
                if requirement else 0
            ),
            "cad_generation_calls": sum(int(item.get("initial_generation_calls") or 0) for item in cad),
            "cad_repair_calls": sum(int(item.get("repair_calls") or 0) for item in cad),
            "fallback_calls": sum(int(item.get("fallback_calls") or 0) for item in cad),
            "worker_executions": sum(int((record.get("worker") or {}).get("execution_count") or 0) for record in mode_records),
            "first_blocker_distribution": dict(Counter(str(record.get("first_blocker_stage")) for record in mode_records)),
            "candidate_ready_count": sum(record.get("state") in {"candidate_ready", "revision_ready"} for record in mode_records),
            "terminal_states": dict(Counter(str(record.get("state")) for record in mode_records)),
            "source_label_anomaly_counts": {
                key: sum(
                    len((item.get("source_label_anomalies") or {}).get(key, []))
                    for item in requirement
                )
                for key in (
                    "missing_or_clarification_labeled_user",
                    "model_assumption_labeled_user_required",
                    "user_explicit_lost_authority",
                )
            },
        }

    category_data: dict[str, dict[str, Any]] = {}
    for project in projects:
        category_records = [record for record in records if record.get("benchmark_project_id") == project.benchmark_id]
        category_data.setdefault(project.category, {"development_records": 0, "exclusion_count": 0, "clarification_count": 0, "generation_count": 0, "candidate_ready_count": 0, "first_blocker_distribution": {}})
        summary = category_data[project.category]
        summary["development_records"] += 1
        for record in category_records:
            if record.get("state") == "excluded_replacement_required":
                summary["exclusion_count"] += 1
                continue
            if (record.get("requirement_extraction") or {}).get("clarification_required"):
                summary["clarification_count"] += 1
            if (record.get("cad_calls") or {}).get("initial_generation_calls"):
                summary["generation_count"] += 1
            if record.get("state") in {"candidate_ready", "revision_ready"}:
                summary["candidate_ready_count"] += 1
            blocker = str(record.get("first_blocker_stage"))
            summary["first_blocker_distribution"][blocker] = summary["first_blocker_distribution"].get(blocker, 0) + 1

    clusters = Counter(
        (
            str(record.get("first_blocker_stage")),
            str(record.get("failure_class")),
            str(record.get("first_incorrect_owner")),
        )
        for record in live_records
    )
    return {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-summary",
        "survey_status": "complete" if len(records) == 60 else "incomplete",
        "cell_count": len(records),
        "live_workflow_count": len(live_records),
        "replacement_exclusion_count": len(records) - len(live_records),
        "provider_calls": sum(
            len(record.get("provider_attempt_forensics", []))
            for record in live_records
        ),
        "worker_executions": sum(int((record.get("worker") or {}).get("execution_count") or 0) for record in live_records),
        "by_mode": {mode: mode_summary(mode) for mode in ("premise_only", "comparison_specification")},
        "comparison": {
            "comparison_ready_project_count": sum(project.comparison_ready for project in projects if not project.excluded),
            "specification_underconstrained_project_count": sum(
                project.comparison_specification_status == "needs_spec_enrichment"
                for project in projects
                if not project.excluded
            ),
            "replacement_required_project_count": sum(project.excluded for project in projects),
            "eligible_interpreted_cells": sum(
                record.get("reference_comparison", {}).get("status") == "eligible"
                for record in live_records
            ),
            "raw_only_cells": sum(
                record.get("reference_comparison", {}).get("status") == "specification_underconstrained"
                for record in live_records
            ),
            "unavailable_cells": sum(
                record.get("reference_comparison", {}).get("status") == "unavailable"
                for record in live_records
            ),
        },
        "category_breakdown": category_data,
        "first_blocker_clusters": [
            {
                "observed_stage": key[0],
                "failure_class": key[1],
                "first_incorrect_owner": key[2],
                "count": count,
            }
            for key, count in clusters.most_common()
        ],
        "source_label_anomalies": {
            key: sum(
                len(((record.get("requirement_extraction") or {}).get("source_label_anomalies") or {}).get(key, []))
                for record in live_records
            )
            for key in (
                "missing_or_clarification_labeled_user",
                "model_assumption_labeled_user_required",
                "user_explicit_lost_authority",
            )
        },
        "no_product_changes_during_survey": True,
        "holdout_runs": 0,
        "validation_runs": 0,
    }


async def _run() -> None:
    args = _parse_args()
    projects = load_frozen_development_projects(args.v11_manifest, args.v1_manifest, args.development_specs)
    order = build_survey_order(projects)
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise SurveyIntegrityError(f"survey output root is non-empty: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)

    preflight = _build_preflight(
        v11_manifest=args.v11_manifest,
        v1_manifest=args.v1_manifest,
        development_specs=args.development_specs,
        projects=projects,
        order=order,
        output_root=args.output_root,
    )
    _write_json(args.output_root / "preflight.json", preflight)
    _write_json(args.output_root / "survey-order.json", _survey_order_payload(order))
    _write_json(args.output_root / "replacement-exclusions.json", _replacement_records(order))

    project_by_id = {project.benchmark_id: project for project in projects}
    provider = build_executable_ai_provider(settings)
    cad_runner = FilesystemCadWorkerRunner(jobs_root=settings.cad_workspace_dir)
    records: list[dict[str, Any]] = []
    progress_path = args.output_root / "survey-progress.json"

    for cell in order:
        project = project_by_id[cell.benchmark_id]
        if cell.excluded:
            record = _excluded_record(cell)
            records.append(record)
            _write_json(_cell_path(args.output_root, cell), record)
            _write_json(progress_path, {"completed_cells": len(records), "total_cells": len(order), "last_cell": record})
            continue

        started = time.monotonic()
        observed_transport: list[dict[str, Any]] = []
        try:
            with SessionLocal() as db:
                service = __import__(
                    "app.services.executable_cadquery.workflow",
                    fromlist=["ExecutableCadQueryWorkflowService"],
                ).ExecutableCadQueryWorkflowService(
                    db=db,
                    data_dir=settings.data_dir,
                    ai_provider=provider,
                    cad_runner=cad_runner,
                    owner_id="volundr-single-user",
                )
                original_recorder = service._persist_provider_attempt

                def recorder(record: dict[str, Any]) -> None:
                    observed_transport.append(_safe_transport_record(record))
                    original_recorder(record)

                provider.set_validated_attempt_recorder(recorder)
                result = await service.start_design(
                    ValidatedCadQueryStart(name=project.benchmark_id, intent=cell.prompt),
                    idempotency_key=f"external-cad-50-v1.1-development-{cell.mode}-{project.benchmark_id}",
                )
                record = _build_cell_record(
                    project=project,
                    cell=cell,
                    result=result,
                    db=db,
                    data_dir=settings.data_dir,
                    observed_transport=observed_transport,
                    elapsed_seconds=time.monotonic() - started,
                )
        except SurveyIntegrityError:
            raise
        except Exception as exc:
            # Unexpected harness errors invalidate subsequent evidence.  The
            # partial cell is persisted, then the survey stops at the boundary.
            error_record = _safe_error_record(project, cell, exc)
            error_record["timing_seconds"] = time.monotonic() - started
            error_record["provider_attempt_forensics"] = observed_transport
            records.append(error_record)
            _write_json(_cell_path(args.output_root, cell), error_record)
            _write_json(progress_path, {"completed_cells": len(records), "total_cells": len(order), "last_cell": error_record, "survey_stopped": True})
            raise SurveyIntegrityError(
                f"unexpected survey harness error at {project.benchmark_id}/{cell.mode}; survey stopped"
            ) from exc
        records.append(record)
        _write_json(_cell_path(args.output_root, cell), record)
        _write_json(progress_path, {"completed_cells": len(records), "total_cells": len(order), "last_cell": record})

    _write_json(args.output_root / "first-blocker-matrix.json", {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-first-blocker-matrix",
        "cells": [
            {
                key: record.get(key)
                for key in (
                    "benchmark_project_id",
                    "category",
                    "mode",
                    "state",
                    "terminal_stage",
                    "first_blocker_stage",
                    "failure_class",
                    "first_incorrect_owner",
                    "normal_recovery_resolved",
                )
            }
            for record in records
        ],
    })
    _write_json(args.output_root / "provider-call-audit.json", {
        "schema_version": f"{SURVEY_SCHEMA_VERSION}-provider-call-audit",
        "cells": [
            {
                "benchmark_project_id": record.get("benchmark_project_id"),
                "mode": record.get("mode"),
                "requirement_extraction_calls": (record.get("requirement_extraction") or {}).get("provider_calls", 0),
                "requirement_schema_retries": (record.get("requirement_extraction") or {}).get("schema_retries", 0),
                "cad_generation_calls": (record.get("cad_calls") or {}).get("initial_generation_calls", 0),
                "cad_repair_calls": (record.get("cad_calls") or {}).get("repair_calls", 0),
                "fallback_calls": (record.get("cad_calls") or {}).get("fallback_calls", 0),
                "total_transport_attempts": len(record.get("provider_attempt_forensics", [])),
                "excluded": record.get("state") == "excluded_replacement_required",
            }
            for record in records
        ],
        "totals": {
            "requirement_extraction_calls": sum((record.get("requirement_extraction") or {}).get("provider_calls", 0) for record in records),
            "requirement_schema_retries": sum((record.get("requirement_extraction") or {}).get("schema_retries", 0) for record in records),
            "cad_generation_calls": sum((record.get("cad_calls") or {}).get("initial_generation_calls", 0) for record in records),
            "cad_repair_calls": sum((record.get("cad_calls") or {}).get("repair_calls", 0) for record in records),
            "fallback_calls": sum((record.get("cad_calls") or {}).get("fallback_calls", 0) for record in records),
            "total_transport_attempts": sum(len(record.get("provider_attempt_forensics", [])) for record in records),
        },
    })
    _write_json(args.output_root / "rate-limit-audit.json", _rate_limit_audit(provider, records))
    for project in projects:
        cells = [record for record in records if record.get("benchmark_project_id") == project.benchmark_id]
        if len(cells) != 2:
            continue
        _write_json(
            args.output_root / "ab-comparisons" / f"{project.benchmark_id}.json",
            {
                "schema_version": f"{SURVEY_SCHEMA_VERSION}-ab",
                "benchmark_project_id": project.benchmark_id,
                "premise_only": cells[0] if cells[0].get("mode") == "premise_only" else cells[1],
                "comparison_specification": cells[0] if cells[0].get("mode") == "comparison_specification" else cells[1],
                "interpreted_similarity_allowed_only_for_comparison_ready": project.comparison_ready,
            },
        )
    _write_json(args.output_root / "survey-summary.json", _aggregate(records, projects))
    _write_json(progress_path, {"completed_cells": len(records), "total_cells": len(order), "survey_stopped": False})


if __name__ == "__main__":
    asyncio.run(_run())
