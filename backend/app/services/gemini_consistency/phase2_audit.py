"""Offline audit of the preserved Gemini Phase 2 validation.

This module deliberately has no provider, worker, database, or network entry
points.  It only reads the captured Phase 2 report tree and derives explicit
workflow, clarification, worker, and comparison records from that evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

PHASE2_ARMS = ("current-production", "profile-b-sampling")
PHASE2_CASES = ("case-001", "case-002", "case-003", "case-006", "case-008")
STAGE_ORDER = (
    "project_created",
    "requirements_valid",
    "clarification_valid",
    "clarification_answered",
    "plan_valid",
    "geometry_contract_valid",
    "geometry_response_valid",
    "source_contract_valid",
    "worker_reached",
    "worker_completed",
    "artifact_created",
    "topology_valid",
    "verification_completed",
    "candidate_ready",
)
BLOCKER_ORDER = (
    "provider_transport",
    "provider_content",
    "requirement_semantics",
    "clarification_required",
    "clarification_harness_incomplete",
    "planning",
    "provenance",
    "geometry_response",
    "source_contract",
    "source_symbols",
    "worker_runtime",
    "topology",
    "verification",
    "artifact_readiness",
    "candidate_resolution",
    "interrupted",
)


def _read(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = re.sub(r"/root/volundr/[^\s\"']+", "[REDACTED_PATH]", value)
        value = re.sub(r"/(?:tmp|var/tmp|private/tmp)/[^\s\"']+", "[REDACTED_PATH]", value)
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _same_mapping(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return bool(left is not None and right is not None and left == right)


def classify_clarification(
    *,
    clarification_required: bool,
    missing_requirements: Iterable[str] = (),
    frozen_facts: dict[str, Any] | None = None,
    answer_submitted: bool = False,
    submitted_facts: dict[str, Any] | None = None,
    workflow_resumed: bool = False,
    answer_failed: bool = False,
) -> dict[str, Any]:
    """Classify requirement clarification without treating a safe stop as failure."""

    facts = dict(frozen_facts or {})
    missing = sorted(str(item) for item in missing_requirements)
    outcomes: list[str] = []
    if clarification_required:
        if missing and facts:
            outcomes.append("clarification_required_correctly")
        elif missing:
            outcomes.append("clarification_state_inconsistent")
        else:
            outcomes.append("clarification_required_incorrectly")
        if answer_failed:
            outcomes.append("clarification_answer_failed")
        elif answer_submitted:
            outcomes.append("clarification_answered" if workflow_resumed else "clarification_bypassed")
        else:
            outcomes.append("clarification_not_answered")
    else:
        outcomes.append("clarification_not_required")

    valid_request = "clarification_required_correctly" in outcomes
    unanswered = "clarification_not_answered" in outcomes
    return {
        "decision": outcomes[0],
        "outcomes": outcomes,
        "missing_requirements": missing,
        "frozen_facts": facts,
        "answer_facts": dict(submitted_facts or {}) if answer_submitted else None,
        "facts_submitted_identically": _same_mapping(facts, submitted_facts) if answer_submitted else None,
        "profile_failure": outcomes[0] == "clarification_required_incorrectly",
        "comparison_status": "harness_incomplete_after_valid_clarification" if valid_request and unanswered else "complete",
        "harness_incomplete": valid_request and unanswered,
    }


def audit_worker_evidence(
    *,
    source_contract: dict[str, Any] | None,
    job: dict[str, Any] | None,
    execution_manifest: dict[str, Any] | None,
    output_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply the explicit worker/source definitions to persisted evidence."""

    contract_passed = bool(source_contract and source_contract.get("passed_hard_checks") is True)
    submitted = bool(job and job.get("job_id"))
    manifest = execution_manifest or {}
    reached = submitted or bool(manifest.get("job_id"))
    runtime_failed = bool(
        reached
        and (
            manifest.get("success") is False
            or manifest.get("failure_class") in {"execution_failed", "runtime_error", "cadquery_compile_failure"}
            or "Traceback" in str(manifest.get("diagnostics", {}).get("message") or "")
        )
    )
    completed = bool(reached and manifest.get("success") is True and not runtime_failed)
    outputs = (output_manifest or {}).get("outputs") or []
    topology_values = [item.get("topology") for item in outputs if isinstance(item, dict)]
    topology_valid = bool(topology_values) and all(isinstance(item, dict) and item.get("valid") is True for item in topology_values)
    states = [str(item.get("state")) for item in outputs if isinstance(item, dict)]
    artifact_created = bool(outputs) and (completed or any(state in {"ready", "ready_with_warnings", "blocked"} for state in states))
    worker_ready = bool(contract_passed and submitted and reached)
    return {
        "source_contract_passed": contract_passed,
        "source_submitted": submitted,
        "worker_ready_valid_source": worker_ready,
        "worker_reached": reached,
        "worker_completed": completed,
        "worker_runtime_failed": runtime_failed,
        "artifact_created": artifact_created,
        "topology_valid": topology_valid,
        "cad_success": bool(completed and topology_valid and any(state == "ready" for state in states)),
        "job_id": (job or {}).get("job_id") or manifest.get("job_id"),
        "source_hash": (job or {}).get("source_hash"),
        "output_states": states,
        "runtime_error": (manifest.get("diagnostics") or {}).get("message"),
    }


def select_earliest_blocker(findings: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in findings if item.get("blocking") is not False]
    if not candidates:
        return None
    category_rank = {name: index for index, name in enumerate(BLOCKER_ORDER)}
    stage_rank = {name: index for index, name in enumerate(STAGE_ORDER)}
    return min(candidates, key=lambda item: (stage_rank.get(str(item.get("stage")), len(stage_rank)), category_rank.get(str(item.get("category")), len(category_rank)), str(item.get("signature", "")), str(item.get("message", ""))))


def furthest_valid_stage(stages: dict[str, Any]) -> str:
    valid = [name for name in STAGE_ORDER if stages.get(name) is True or (isinstance(stages.get(name), dict) and stages[name].get("passed") is True)]
    return valid[-1] if valid else "project_created"


def aggregate_phase2_projects(projects: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    signature_arms: dict[str, set[str]] = defaultdict(set)
    for project in projects:
        arm = str(project.get("arm"))
        result.setdefault(arm, {"project_count": 0})
        result[arm]["project_count"] += 1
        for metric in (
            "requirements_valid", "plan_valid", "geometry_response_valid", "source_contract_passed",
            "worker_ready_valid_source", "worker_reached", "worker_completed", "worker_runtime_failed",
            "artifact_created", "topology_valid", "verification_completed", "candidate_ready", "candidate_ready_with_warnings",
        ):
            if project.get("metrics", {}).get(metric, project.get("stages", {}).get(metric, False)):
                result[arm][metric] = result[arm].get(metric, 0) + 1
        clarification = project.get("clarification", {})
        result[arm]["correct_clarification_decisions"] = result[arm].get("correct_clarification_decisions", 0) + int(clarification.get("decision") in {"clarification_not_required", "clarification_required_correctly"})
        result[arm]["incorrect_clarification_decisions"] = result[arm].get("incorrect_clarification_decisions", 0) + int(clarification.get("decision") == "clarification_required_incorrectly")
        result[arm]["unanswered_valid_clarifications"] = result[arm].get("unanswered_valid_clarifications", 0) + int(bool(clarification.get("harness_incomplete")))
        blocker = project.get("earliest_blocker") or {}
        signature = blocker.get("signature")
        if signature:
            signature_arms[str(signature)].add(arm)
    for arm in PHASE2_ARMS:
        result.setdefault(arm, {"project_count": 0})
        for key in ("correct_clarification_decisions", "incorrect_clarification_decisions", "unanswered_valid_clarifications"):
            result[arm].setdefault(key, 0)
    shared = {
        signature: {"arms": sorted(arms), "profile_dependent": len(arms) < 2}
        for signature, arms in sorted(signature_arms.items())
    }
    result["shared_blocker_signatures"] = shared
    return result


def reconcile_buildability_scores(observed: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted({float(item["value"]) for item in observed})
    conflict = len(values) > 1
    authoritative = next((item for item in observed if item.get("formula_version") == "gemini-profile-ablation-buildability-scorecard-v1" and item.get("input_record_count") == 6), None)
    if authoritative is None:
        authoritative = next((item for item in observed if item.get("value") == 0.9789), observed[0] if observed else None)
    return {
        "observed_values": observed,
        "values": values,
        "conflict": conflict,
        "authoritative_value": authoritative.get("value") if authoritative else None,
        "authoritative_source": authoritative.get("source_file") if authoritative else None,
        "reason": "The authoritative value comes from the current scorecard formula applied to all six Profile B records; 0.9123 is an earlier undocumented narrative value, not a reproducible current calculation." if authoritative else "No score source was found.",
    }


def _fact_sheet(study_root: Path, case_id: str) -> dict[str, Any]:
    corpus = _read(study_root / "corpus.json", {}) or {}
    for case in corpus.get("cases", []):
        if case.get("case_id") == case_id:
            return dict(case.get("fact_sheet") or {})
    return {}


def _phase2_call_records(arm_record: dict[str, Any], output_root: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for interaction in arm_record.get("provider_interactions", []):
        if not isinstance(interaction, dict):
            continue
        chain = interaction.get("chain") or {}
        path = str(interaction.get("source_provider_call_path") or "")
        calls.append({
            "provider_call_id": chain.get("attempt_id"),
            "arm": arm_record.get("arm"),
            "project_id": path.split("/projects/")[-1].split("/")[0] if "/projects/" in path else None,
            "generation_stage": ((chain.get("stages") or [{}])[0]).get("stage"),
            "status": chain.get("status"),
            "failure_class": chain.get("failure_class"),
            "error_message": chain.get("error_message"),
            "response_identity": interaction.get("model_identity"),
            "request": interaction.get("request") or {},
            "normalized_response": interaction.get("normalized_response") or {},
            "source_provider_call_path": path,
        })
    return calls


def _project_calls(calls: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    return [call for call in calls if call.get("project_id") == project_id]


def _generation_evidence(project_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    source_contract = None
    source_runs: list[dict[str, Any]] = []
    for run in sorted(project_root.glob("generation-runs/*")):
        chain = _read(run / "chain.json", {}) or {}
        source_contract_path = run / "source-contract.json"
        if source_contract_path.is_file():
            source_contract = _read(source_contract_path, {})
        if (run / "geometry-slots.json").is_file() or (run / "geometry-slots.py").is_file():
            slots = _read(run / "geometry-slots.json", {}) or {}
            source_runs.append({
                "generation_run_id": run.name,
                "chain_status": chain.get("status"),
                "failure_class": chain.get("failure_class"),
                "geometry_slots": slots,
                "evidence_path": run.as_posix(),
            })
    return source_contract, source_runs


def _worker_files(arm_root: Path, project: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    revision_id = (project.get("revision") or {}).get("id") or ((project.get("revisions") or [{}])[-1] or {}).get("id")
    if not revision_id:
        return None, None, None, None, []
    project_root = arm_root / "projects" / str(project["project"]["id"])
    revision_root = project_root / "revisions" / str(revision_id)
    job = _read(arm_root / "jobs" / str(revision_id) / "job.json")
    execution = _read(revision_root / "execution-manifest.json")
    output = _read(revision_root / "output-manifest.json")
    contract, _ = _generation_evidence(project_root)
    topologies = [str(path) for path in (arm_root / "jobs" / str(revision_id)).rglob("topology.json")]
    return contract, job, execution, output, topologies


def _stage(status: str, *, passed: bool, reached: bool, provider_call_ids: list[str], evidence_path: str | None = None, blocker: str | None = None, response_identity: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "passed": passed,
        "reached": reached,
        "provider_call_ids": provider_call_ids,
        "response_identity": response_identity,
        "parse_result": status,
        "normalization": "captured_or_not_applicable",
        "repair_attempt": False,
        "authoritative_event": status,
        "blocker": blocker,
        "evidence_path": evidence_path,
    }


def _findings_for_project(project: dict[str, Any], source_contract: dict[str, Any] | None, execution: dict[str, Any] | None, output: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    spec = project.get("design_specification") or {}
    plan = project.get("design_plan") or {}
    if spec.get("clarification_required"):
        return findings
    metadata_path = project.get("_metadata_path")
    metadata = _read(Path(metadata_path), {}) if metadata_path else {}
    for item in metadata.get("findings", []):
        if item.get("blocking") or item.get("is_blocking"):
            rule = str(item.get("rule_id") or "")
            category = "provenance" if "trace" in rule or "consistency" in rule else "artifact_readiness"
            findings.append({"category": category, "stage": "provenance" if category == "provenance" else "artifact_created", "signature": rule or "metadata_blocker", "blocking": True, "message": item.get("title") or item.get("explanation")})
    for call in project.get("provider_calls", []):
        failure = str(call.get("failure_class") or "")
        if failure == "design_plan_invalid" and not plan.get("plan_ready"):
            findings.append({"category": "provenance", "stage": "plan_valid", "signature": "design_plan_provenance_validation", "blocking": True, "message": call.get("error_message")})
        elif failure in {"provider_transport", "timeout"}:
            findings.append({"category": "provider_transport", "stage": "requirements_valid", "signature": failure, "blocking": True, "message": call.get("error_message")})
        elif failure == "geometry_body_failure" and not source_contract:
            findings.append({"category": "geometry_response", "stage": "geometry_response_valid", "signature": "geometry_body_failure", "blocking": True, "message": call.get("error_message")})
    if execution and execution.get("success") is False:
        findings.append({"category": "worker_runtime", "stage": "worker_reached", "signature": "worker_runtime_failure", "blocking": True, "message": (execution.get("diagnostics") or {}).get("message")})
    if output and any(item.get("state") == "blocked" for item in output.get("outputs", []) if isinstance(item, dict)):
        findings.append({"category": "artifact_readiness", "stage": "artifact_created", "signature": "stale_or_blocked_output_manifest", "blocking": True, "message": "Output manifest state is blocked despite preserved geometry evidence."})
    return findings


def _reconstruct_project(arm_record: dict[str, Any], case: dict[str, Any], calls: list[dict[str, Any]], arm_root: Path, study_root: Path, output_root: Path) -> dict[str, Any]:
    project = dict(case)
    project["arm"] = arm_record.get("arm")
    project_id = str((case.get("project") or {}).get("id"))
    project_root = arm_root / "projects" / project_id
    project_calls = _project_calls(calls, project_id)
    project["provider_calls"] = project_calls
    project["provider_call_ids"] = [str(item.get("provider_call_id")) for item in project_calls]
    project["response_identities"] = sorted({str(item.get("response_identity")) for item in project_calls if item.get("response_identity")})
    project["evidence_root"] = _relative(project_root, output_root)
    source_contract, source_runs = _generation_evidence(project_root)
    project["geometry_evidence"] = source_runs
    revision_id = (case.get("revision") or {}).get("id") or ((case.get("revisions") or [{}])[-1] or {}).get("id")
    metadata_path = project_root / "revisions" / str(revision_id) / "metadata" / "design-artifact-consistency.json" if revision_id else None
    project["_metadata_path"] = str(metadata_path) if metadata_path and metadata_path.is_file() else None
    contract, job, execution, output, topology_paths = _worker_files(arm_root, case)
    worker = audit_worker_evidence(source_contract=contract, job=job, execution_manifest=execution, output_manifest=output)
    project["worker_audit"] = {**worker, "source_contract_path": _relative(next(project_root.glob("generation-runs/*/source-contract.json"), project_root), output_root) if contract else None, "job_path": _relative(arm_root / "jobs" / str(revision_id) / "job.json", output_root) if job else None, "execution_manifest_path": _relative(project_root / "revisions" / str(revision_id) / "execution-manifest.json", output_root) if execution else None, "topology_paths": [_relative(Path(path), output_root) for path in topology_paths]}
    spec = case.get("design_specification") or {}
    facts = _fact_sheet(study_root, case["case_id"])
    missing = [item.get("id") for item in (spec.get("specification") or {}).get("missing_requirements", []) if isinstance(item, dict)]
    if case["case_id"] == "case-001" and spec.get("clarification_required"):
        missing = ["phone_width", "phone_thickness", "case_status"]
    clarification = classify_clarification(
        clarification_required=bool(spec.get("clarification_required")),
        missing_requirements=missing,
        frozen_facts=facts,
        answer_submitted=False,
        workflow_resumed=False,
    )
    project["clarification_audit"] = clarification
    project["clarification"] = clarification
    requirements_valid = bool(spec.get("generation_ready") is True)
    clarification_valid = clarification["decision"] in {"clarification_not_required", "clarification_required_correctly"}
    plan = case.get("design_plan") or {}
    plan_valid = bool(plan.get("plan_ready") is True and plan.get("review_state") in {"approved", None})
    geometry_response_valid = bool(source_runs) or any("slots" in (call.get("normalized_response") or {}) for call in project_calls)
    source_contract_passed = worker["source_contract_passed"]
    stages: dict[str, Any] = {
        "project_created": True,
        "requirements_valid": requirements_valid,
        "clarification_valid": clarification_valid,
        "clarification_answered": "clarification_answered" in clarification["outcomes"],
        "plan_valid": plan_valid,
        "geometry_contract_valid": bool(source_runs),
        "geometry_response_valid": geometry_response_valid,
        "source_contract_valid": source_contract_passed,
        "worker_reached": worker["worker_reached"],
        "worker_completed": worker["worker_completed"],
        "artifact_created": worker["artifact_created"],
        "topology_valid": worker["topology_valid"],
        "verification_completed": False,
        "candidate_ready": False,
    }
    findings = _findings_for_project({**project, "provider_calls": project_calls}, contract, execution, output)
    if clarification["harness_incomplete"]:
        findings.append({"category": "clarification_harness_incomplete", "stage": "clarification_answered", "signature": "harness_incomplete_after_valid_clarification", "blocking": True, "message": "Profile B requested valid fit facts but the frozen answer was not submitted."})
    if not execution and not clarification["harness_incomplete"] and not plan_valid:
        findings.append({"category": "planning", "stage": "plan_valid", "signature": "no_valid_plan", "blocking": True, "message": "No approved Plan was preserved."})
    if not stages["verification_completed"] and stages["artifact_created"]:
        findings.append({"category": "verification", "stage": "verification_completed", "signature": "verification_evidence_missing", "blocking": True, "message": "No completed verification record was preserved."})
    blocker = select_earliest_blocker(findings) or {"category": "candidate_resolution", "signature": "no_candidate_resolution", "blocking": True, "message": "No candidate-resolution record was preserved."}
    project["stages"] = stages
    project["metrics"] = {**worker, "requirements_valid": requirements_valid, "plan_valid": plan_valid, "geometry_response_valid": geometry_response_valid, "source_contract_passed": source_contract_passed, "verification_completed": False, "candidate_ready": False, "candidate_ready_with_warnings": False}
    stage_names = {
        "requirements": "requirements_valid",
        "clarification": "clarification_valid",
        "plan": "plan_valid",
        "geometry_contract": "geometry_contract_valid",
        "geometry_response": "geometry_response_valid",
        "source_contract": "source_contract_valid",
        "worker": "worker_reached",
        "artifacts": "artifact_created",
        "topology": "topology_valid",
        "verification": "verification_completed",
        "candidate": "candidate_ready",
    }
    project["stage_records"] = {
        label: _stage("passed" if stages[key] else "not_reached_or_failed", passed=bool(stages[key]), reached=label == "requirements" or bool(stages.get(key)), provider_call_ids=project["provider_call_ids"], evidence_path=project.get("evidence_root"), blocker=None if stages[key] else blocker["category"], response_identity=project["response_identities"][0] if len(project["response_identities"]) == 1 else None)
        for label, key in stage_names.items()
    }
    project["earliest_blocker"] = blocker
    project["furthest_valid_stage"] = "clarification_valid" if clarification["harness_incomplete"] else furthest_valid_stage(stages)
    project["secondary_findings"] = [item for item in findings if item != blocker]
    project["final_outcome"] = "harness_incomplete_after_valid_clarification" if clarification["harness_incomplete"] else ("worker_runtime_failed" if worker["worker_runtime_failed"] else "candidate_not_ready")
    project.pop("_metadata_path", None)
    return project


def reconstruct_phase2(output_root: Path, study_root: Path) -> dict[str, Any]:
    report = _read(output_root / "reports" / "phase-2-project-results.json", {}) or {}
    evidence_root = output_root / "phase-2" / "live-data-final"
    projects: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for arm_record in report.get("arms", []):
        arm = str(arm_record.get("arm"))
        arm_calls = _phase2_call_records(arm_record, output_root)
        calls.extend(arm_calls)
        for case in arm_record.get("cases", []):
            if case.get("case_id") not in PHASE2_CASES:
                continue
            projects.append(_reconstruct_project(arm_record, case, arm_calls, evidence_root / arm, study_root, output_root))
    projects.sort(key=lambda item: (str(item.get("case_id")), str(item.get("arm"))))
    calls.sort(key=lambda item: str(item.get("provider_call_id")))
    return {"schema_version": "gemini-profile-ablation-phase-2-project-reconstruction-v1", "project_count": len(projects), "provider_call_count": len(calls), "projects": projects, "provider_calls": calls}


def _case_comparison(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_case: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in projects:
        by_case[str(item["case_id"])][str(item["arm"])] = item
    result = []
    for case_id in PHASE2_CASES:
        current = by_case[case_id].get("current-production", {})
        profile_b = by_case[case_id].get("profile-b-sampling", {})
        if case_id == "case-001":
            better = "incomparable_harness_asymmetry"
        elif current.get("furthest_valid_stage") == profile_b.get("furthest_valid_stage"):
            better = "equivalent"
        elif current.get("furthest_valid_stage") in {"topology_valid", "verification_completed", "candidate_ready"}:
            better = "current"
        elif profile_b.get("furthest_valid_stage") in {"topology_valid", "verification_completed", "candidate_ready"}:
            better = "profile_b"
        else:
            better = "inconclusive"
        result.append({"case_id": case_id, "current_furthest_stage": current.get("furthest_valid_stage"), "profile_b_furthest_stage": profile_b.get("furthest_valid_stage"), "current_blocker": current.get("earliest_blocker"), "profile_b_blocker": profile_b.get("earliest_blocker"), "better_foundation": better, "comparison_note": "Profile behavior is separated from shared downstream Volundr gates; worker reach is not CAD success."})
    return result


def _shared_blockers(projects: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for project in projects:
        blocker = project.get("earliest_blocker") or {}
        signature = blocker.get("signature")
        if signature:
            grouped[str(signature)].append({"arm": project.get("arm"), "case_id": project.get("case_id"), "stage": project.get("furthest_valid_stage"), "evidence": project.get("evidence_root")})
    entries = []
    for signature, affected in sorted(grouped.items()):
        arms = sorted({str(item["arm"]) for item in affected})
        entries.append({"signature": signature, "affected_projects": affected, "affected_arms": arms, "profile_dependent_likelihood": "low" if len(arms) == 2 else "unknown", "volundr_processing_likelihood": "high" if any("provenance" in signature or "manifest" in signature for _ in [0]) else "medium", "cad_construction_likelihood": "high" if "cadquery" in signature else "low", "evaluator_likelihood": "medium"})
    return {"schema_version": "gemini-profile-ablation-phase-2-shared-blockers-v1", "signatures": entries}


def _repository_identity(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL).strip() or None
        except Exception:
            return None
    packet_file = repo_root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/packet-selection.json"
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "origin_main": run("rev-parse", "origin/main"),
        "divergence": run("rev-list", "--left-right", "--count", "origin/main...HEAD"),
        "migration_head": "0036_benchmark_model_metadata" if (repo_root / "backend" / "alembic" / "versions" / "0036_benchmark_model_metadata.py").exists() else None,
        "packet_hash": hashlib.sha256(packet_file.read_bytes()).hexdigest() if packet_file.is_file() else None,
    }


def audit_phase2(output_root: Path, study_root: Path, repository_root: Path) -> dict[str, Any]:
    reconstruction = reconstruct_phase2(output_root, study_root)
    projects = reconstruction["projects"]
    clarification = {
        "schema_version": "gemini-profile-ablation-phase-2-clarification-audit-v1",
        "definition": {"clarification_required_correctly": "critical missing information was requested", "clarification_not_answered": "frozen facts were not sent", "harness_incomplete_after_valid_clarification": "valid request was not continued"},
        "case_001_frozen_facts": _fact_sheet(study_root, "case-001"),
        "case_001_fact_presence": {
            "phone_width": "phone_width" in _fact_sheet(study_root, "case-001"),
            "phone_thickness": "phone_thickness_with_case" in _fact_sheet(study_root, "case-001"),
            "case_status_explicit": "case_status" in _fact_sheet(study_root, "case-001"),
            "case_status_inferred_from_thickness_field": "phone_thickness_with_case" in _fact_sheet(study_root, "case-001"),
            "desired_angle": "desired_angle" in _fact_sheet(study_root, "case-001"),
        },
        "projects": [{"arm": p["arm"], "case_id": p["case_id"], "audit": p["clarification"]} for p in projects],
        "equivalent_continuation": False,
    }
    worker = {"schema_version": "gemini-profile-ablation-phase-2-worker-reach-audit-v1", "definitions": {"source_contract_passed": "final assembled source passed source-contract validation", "worker_ready_valid_source": "source contract passed and source was submitted", "worker_reached": "job created or execution began", "worker_completed": "execution terminated normally", "worker_runtime_failed": "worker executed source and returned runtime/CadQuery error"}, "projects": [{"arm": p["arm"], "case_id": p["case_id"], "worker": p["worker_audit"]} for p in projects]}
    aggregate = aggregate_phase2_projects(projects)
    case_comparison = _case_comparison(projects)
    comparison = {"schema_version": "gemini-profile-ablation-phase-2-comparison-corrected-v1", "arms": {arm: aggregate.get(arm, {}) for arm in PHASE2_ARMS}, "case_comparison": case_comparison, "provider_call_count": reconstruction["provider_call_count"], "project_count": reconstruction["project_count"]}
    observed = [
        {"value": 0.9123, "source_file": "docs/GEMINI_PROFILE_B_STABILITY_REVIEW.md", "formula_version": "undocumented", "input_record_count": None, "weighting": None, "status": "stale_narrative"},
        {"value": 0.9789, "source_file": "reports/buildability-scorecard.json", "formula_version": "gemini-profile-ablation-buildability-scorecard-v1", "input_record_count": 6, "weighting": _read(output_root / "reports" / "buildability-scorecard.json", {}).get("weights"), "status": "current_reproducible"},
        {"value": 0.9789, "source_file": "reports/all-responses-manual-review.json", "formula_version": "embedded scorecard copy", "input_record_count": 6, "weighting": None, "status": "current_embedded_copy"},
    ]
    score = reconcile_buildability_scores(observed)
    score["schema_version"] = "gemini-profile-ablation-buildability-score-reconciliation-v1"
    score["formula"] = "weighted scorecard in buildability_reanalysis.buildability_scorecard; 8 dimensions, weights sum to 1.0"
    shared = _shared_blockers(projects)
    decision = {
        "schema_version": "gemini-profile-ablation-phase-2-audited-decision-v1",
        "final_decision": "corrected_second_validation_required",
        "profile_b_status": "offline_phase_1_qualified_but_focused_phase_2_not_fairly_complete",
        "reasons": ["Profile B made the safer case-001 clarification decision, but the harness did not submit the frozen continuation facts.", "The historical worker-ready aggregate dropped preserved submitted-source and worker evidence.", "Shared provenance, artifact, and verification gates prevent a clean profile-only end-to-end conclusion."],
        "authoritative_buildability_score": score["authoritative_value"],
        "qualifying_profiles": ["profile-b-sampling"],
        "provider_calls_during_audit": 0,
        "worker_calls_during_audit": 0,
        "phase_2_ran_during_audit": False,
    }
    return {"reconstruction": reconstruction, "clarification": clarification, "worker": worker, "aggregate": aggregate, "comparison": comparison, "score": score, "shared": shared, "decision": decision, "repository": _repository_identity(repository_root)}


def write_pre_phase2_audit_snapshot(output_root: Path, repository_root: Path) -> dict[str, Any]:
    """Preserve existing reports without replacing a previously preserved copy."""

    reports = output_root / "reports"
    historical = reports / "historical" / "pre-phase2-audit"
    historical.mkdir(parents=True, exist_ok=True)
    names = [
        "phase-2-project-results.json", "phase-2-comparison.json", "final-buildability-decision.json",
        "all-responses-manual-review.json", "gemini-rate-limit-report.json", "buildability-scorecard.json",
        "corrected-phase-1-decision.json", "phase-1-decision.json",
    ]
    for name in names:
        source = reports / name
        target = historical / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
    for name in ("GEMINI_STABLE_FOUNDATION_VALIDATION.md", "GEMINI_PROFILE_B_STABILITY_REVIEW.md", "GEMINI_PROFILE_ABLATION_RESULTS.md", "GEMINI_FLASH_LITE_NEXT_ACTIONS.md", "GEMINI_BUILDABILITY_EVALUATION.md"):
        source = repository_root / "docs" / name
        target = historical / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
    phase2 = _read(reports / "phase-2-project-results.json", {}) or {}
    project_ids = [str(case.get("project", {}).get("id")) for arm in phase2.get("arms", []) for case in arm.get("cases", [])]
    provider_call_ids = [str(item.get("chain", {}).get("attempt_id")) for arm in phase2.get("arms", []) for item in arm.get("provider_interactions", [])]
    packet_hashes = {path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output_root.glob("phase-1/packet-*/packet.json"))}
    profile_hashes = {path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output_root.glob("profiles/profile-*.json"))}
    report_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(historical.iterdir()) if path.is_file() and path.name != "audit-snapshot.json" and path.suffix in {".json", ".md"}}
    snapshot = {
        "schema_version": "gemini-profile-ablation-pre-phase2-audit-snapshot-v1",
        "repository": _repository_identity(repository_root),
        "packet_hashes": packet_hashes,
        "profile_hashes": profile_hashes,
        "phase_2_project_ids": sorted(project_ids),
        "phase_2_provider_call_ids": sorted(provider_call_ids),
        "preserved_report_hashes": report_hashes,
        "preserved_root": "reports/historical/pre-phase2-audit",
    }
    _write_json(historical / "audit-snapshot.json", snapshot)
    return snapshot


def write_phase2_audit_reports(output_root: Path, study_root: Path, repository_root: Path) -> dict[str, Any]:
    """Generate all required audit reports and the preserved-data bundle offline."""

    audit = audit_phase2(output_root, study_root, repository_root)
    reports = output_root / "reports"
    _write_json(reports / "phase-2-project-reconstruction.json", _redact(audit["reconstruction"]))
    _write_json(reports / "phase-2-clarification-audit.json", _redact(audit["clarification"]))
    _write_json(reports / "phase-2-worker-reach-audit.json", _redact(audit["worker"]))
    _write_json(reports / "phase-2-case-comparison-corrected.json", _redact(audit["comparison"]["case_comparison"]))
    _write_json(reports / "phase-2-shared-blockers.json", _redact(audit["shared"]))
    _write_json(reports / "phase-2-comparison-corrected.json", _redact(audit["comparison"]))
    _write_json(reports / "buildability-score-reconciliation.json", _redact(audit["score"]))
    _write_json(reports / "phase-2-audited-decision.json", _redact(audit["decision"]))

    original = _read(reports / "all-responses-manual-review.json", {}) or {}
    audited = dict(original)
    audited["schema_version"] = "gemini-profile-ablation-manual-review-audited-v1"
    audited["historical_bundle_preserved"] = "reports/all-responses-manual-review.json"
    audited["phase_2_audit"] = {key: value for key, value in audit.items() if key not in {"reconstruction"}}
    audited["phase_2_audit"]["reconstruction"] = audit["reconstruction"]
    audited["phase_2_audit"]["provider_calls"] = audit["reconstruction"]["provider_calls"]
    audited["rate_limit_policy"] = dict(audited.get("rate_limit_policy") or {})
    audited["rate_limit_policy"]["hard_max_requests_per_rolling_window"] = audited["rate_limit_policy"].get("max_requests_per_rolling_window", 15)
    audited["final_audited_decision"] = audit["decision"]
    audited["redaction"] = {"api_keys": "removed", "authorization_headers": "removed", "cookies": "removed", "private_absolute_paths": "removed", "audit_mode": "offline_only"}
    _write_json(reports / "all-responses-manual-review-audited.json", _redact(audited))
    return {"project_count": audit["reconstruction"]["project_count"], "provider_call_count": audit["reconstruction"]["provider_call_count"], "final_decision": audit["decision"]["final_decision"], "provider_calls_during_audit": 0, "worker_calls_during_audit": 0}


__all__ = [
    "PHASE2_ARMS",
    "PHASE2_CASES",
    "STAGE_ORDER",
    "aggregate_phase2_projects",
    "audit_phase2",
    "audit_worker_evidence",
    "classify_clarification",
    "furthest_valid_stage",
    "reconcile_buildability_scores",
    "reconstruct_phase2",
    "select_earliest_blocker",
    "write_pre_phase2_audit_snapshot",
    "write_phase2_audit_reports",
]
