from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.geometry_slots import (
    GEOMETRY_SLOTS_SCHEMA_VERSION,
    build_geometry_slot_manifest,
    parse_geometry_slots,
)
from app.services.cad.source_scaffold import render_cadquery_scaffold, validate_scaffold_source
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.geometry.feature_measurements import verify_one_connected_output
from app.services.projects.output_outcomes import resolve_output_outcome
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.transport import SecondaryGeminiClient
from app.services.gemini_integration.workflow import IntegrationBoundaryPorts


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def canonicalize_worker_output_manifest(
    printable_outputs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    provenance: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map the Plan output identity to the worker's canonical ``output_id`` once.

    Plans captured by the integration study use ``id`` for printable outputs,
    while the real worker/runtime/artifact boundary is keyed by ``output_id``.
    This is the sole integration mapping between those representations.  The
    returned manifest contains only the canonical worker field; the mapping
    evidence preserves the authoritative source field and value.
    """

    canonical_manifest: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, output in enumerate(printable_outputs or []):
        if not isinstance(output, dict):
            raise ValueError(f"printable output {index} must be an object")

        plan_id = output.get("id")
        worker_id = output.get("output_id")
        if plan_id is not None and not isinstance(plan_id, str):
            raise ValueError(f"printable output {index} has a non-string id")
        if worker_id is not None and not isinstance(worker_id, str):
            raise ValueError(f"printable output {index} has a non-string output_id")
        plan_id = plan_id.strip() if isinstance(plan_id, str) else None
        worker_id = worker_id.strip() if isinstance(worker_id, str) else None
        if not plan_id and not worker_id:
            raise ValueError(f"printable output {index} has no output identity")
        if plan_id and worker_id and plan_id != worker_id:
            raise ValueError(
                f"printable output {index} has conflicting identities: id={plan_id!r}, output_id={worker_id!r}"
            )

        canonical_id = worker_id or plan_id
        assert canonical_id is not None
        if canonical_id in seen:
            raise ValueError(f"duplicate printable output identity: {canonical_id}")
        seen.add(canonical_id)
        source_fields = [field for field, value in (("id", plan_id), ("output_id", worker_id)) if value]
        mapped = {key: value for key, value in output.items() if key not in {"id", "output_id"}}
        mapped["output_id"] = canonical_id
        canonical_manifest.append(mapped)
        mappings.append({
            "manifest_index": index,
            "canonical_field": "output_id",
            "canonical_value": canonical_id,
            "source_fields": source_fields,
            "source_values": {field: output.get(field) for field in source_fields},
            "mapping": "Plan.printable_outputs.id_to_worker.output_id" if source_fields == ["id"] else "identity_preserved",
            "semantic_repair": False,
            "provenance": provenance,
        })
    return canonical_manifest, mappings


def build_real_boundary_ports(
    *,
    profile: GeminiFlashLiteContractV1,
    evidence_store: IntegrationEvidenceStore,
    jobs_root: Path | None = None,
) -> IntegrationBoundaryPorts:
    """Bind the integration runner to existing Volundr boundaries only."""

    provider = SecondaryGeminiClient(
        profile,
    )
    worker = FilesystemCadWorkerRunner(jobs_root=jobs_root)

    async def provider_call(*, stage: str, prompt: str, operation_id: str):
        return await provider.generate(stage=stage, prompt=prompt, operation_id=operation_id)

    async def assemble_source(*, project, plan, geometry, provenance):
        manifest = build_geometry_slot_manifest(plan, planning_depth="detailed_plan")
        payload = {
            "schema_version": GEOMETRY_SLOTS_SCHEMA_VERSION,
            "slots": geometry.get("slots", []) if isinstance(geometry, dict) else [],
        }
        parsed = parse_geometry_slots(json.dumps(payload), manifest)
        rendered = render_cadquery_scaffold(plan, parsed.functions)
        output_manifest, output_identity_mapping = canonicalize_worker_output_manifest(
            plan.get("printable_outputs", []),
            provenance=provenance,
        )
        return {
            "source": rendered.source,
            "output_manifest": output_manifest,
            "output_identity_mapping": output_identity_mapping,
            "scaffold_hash": rendered.scaffold_hash,
            "geometry_function_ids": list(rendered.expected_geometry_functions),
            "provenance": provenance,
        }

    async def static_validate(*, source, provenance):
        findings = list(validate_scaffold_source(source))
        try:
            metadata = validate_cadquery_source(source)
        except CadQueryContractError as exc:
            findings.append({"rule_id": "cadquery.contract", "message": str(exc), "blocking": True})
            metadata = None
        return {
            "valid": not any(item.get("blocking", True) for item in findings),
            "findings": findings,
            "metadata": _json_safe(metadata),
            "provenance": provenance,
        }

    async def worker_submit(*, source, output_manifest, provenance):
        if any(
            not isinstance(item, dict) or not isinstance(item.get("output_id"), str) or not item["output_id"].strip()
            for item in output_manifest
        ):
            raise ValueError("worker output manifest must contain canonical output_id values")
        project_id = str(provenance.get("project_id") or "project")
        revision_id = str(provenance.get("revision_id") or "revision")
        job_id = f"gemini-integration-{project_id}-{revision_id}".replace(":", "-")
        result = await worker.compile(
            source,
            job_id,
            parameter_values={},
            requested_outputs=output_manifest,
        )
        return {
            "success": result.success,
            "job_id": result.job_id,
            "failure_class": "timeout" if result.timed_out else None if result.success else "worker_runtime",
            "error_message": result.error_message,
            "compile_result": result,
            "provenance": provenance,
        }

    async def collect_artifacts(*, worker_result, provenance):
        compile_result = worker_result.get("compile_result")
        outputs = []
        for output in getattr(compile_result, "outputs", []) or []:
            outputs.append({
                "output_id": output.output_id,
                "required": output.required,
                "stl_path": output.stl_path,
                "step_path": output.step_path,
                "brep_path": output.brep_path,
                "metadata_path": output.metadata_path,
                "topology_metadata_path": output.topology_metadata_path,
                "stl_hash": output.stl_hash,
                "step_hash": output.step_hash,
                "brep_hash": output.brep_hash,
                "compile_error": output.compile_error,
                "metadata": _json_safe(output.metadata),
                "topology": _json_safe(output.topology_metadata),
            })
        return {"outputs": outputs, "provenance": provenance}

    async def inspect_topology(*, artifacts, provenance):
        solid_counts: dict[str, int] = {}
        findings: list[dict[str, Any]] = []
        for output in artifacts.get("outputs", []) or []:
            topology = output.get("topology") or {}
            count = topology.get("detected_solid_count") if isinstance(topology, dict) else None
            if count is not None:
                solid_counts[str(output.get("output_id"))] = int(count)
            elif output.get("metadata"):
                metadata = output["metadata"]
                if isinstance(metadata, dict) and metadata.get("connected_components") is not None:
                    solid_counts[str(output.get("output_id"))] = int(metadata["connected_components"])
            if output.get("compile_error"):
                findings.append({"output_id": output.get("output_id"), "reason": output["compile_error"], "blocking": True})
        return {
            "valid": not findings,
            "solid_counts": solid_counts,
            "findings": findings,
            "registered_artifacts": artifacts.get("outputs", []),
            "provenance": provenance,
        }

    async def verify_requirements(*, project, plan, topology, provenance):
        expected = [
            {
                "output_id": item.get("id") or item.get("output_id"),
                "required": item.get("required", True),
                "expected_solid_count": item.get("expected_solid_count", 1),
                "required_artifact_formats": item.get("required_artifact_formats", ["stl", "step", "brep"]),
            }
            for item in plan.get("printable_outputs", []) or []
            if isinstance(item, dict)
        ]
        registered = topology.get("registered_artifacts", [])
        outcome = resolve_output_outcome(
            expected_outputs=expected,
            worker_status="succeeded" if topology.get("registered_artifacts") is not None else "failed",
            registered_artifacts=registered,
            source_valid=True,
            verification_status="measured" if topology.get("valid") else "blocked",
        )
        return {
            "valid": outcome.is_candidate_eligible,
            "state": outcome.state,
            "candidate_eligible": outcome.is_candidate_eligible,
            "output_outcome": _json_safe(outcome),
            "provenance": provenance,
        }

    async def decide_candidate(*, project, verification, provenance):
        return {
            "decision": "candidate" if verification.get("candidate_eligible") else "blocked",
            "state": verification.get("state"),
            "provenance": provenance,
        }

    return IntegrationBoundaryPorts(
        provider_call=provider_call,
        assemble_source=assemble_source,
        static_validate=static_validate,
        worker_submit=worker_submit,
        collect_artifacts=collect_artifacts,
        inspect_topology=inspect_topology,
        verify_requirements=verify_requirements,
        decide_candidate=decide_candidate,
        provider=provider,
    )


__all__ = ["build_real_boundary_ports", "canonicalize_worker_output_manifest"]
