"""Authoritative semantic requirement and candidate qualification policy.

This module only classifies persisted evidence.  It does not inspect source,
invoke a verifier, call a provider, or change workflow state.  The workflow
orchestrator persists its result and the API/harness read that same result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


SEMANTIC_POLICY_VERSION = "executable-cadquery-semantic-policy-v1"
CANDIDATE_POLICY_VERSION = "executable-cadquery-candidate-policy-v1"

REQUIREMENT_POLICIES = frozenset({"machine_required", "review_required", "informational"})
MACHINE_RESULTS = frozenset({"verified", "failed", "unsupported_verifier"})
CANDIDATE_STATES = frozenset(
    {"candidate_blocked", "candidate_ready_for_review", "candidate_fully_verified"}
)

_PASSING_OUTPUT_STATES = frozenset({"completed", "ready", "ready_with_warnings"})
_PASSING_WORKER_STATES = frozenset({"completed", "ready", "ready_with_warnings"})
_PASSING_TOPOLOGY_STATES = frozenset({"valid", "passed", "verified", "ok"})


def evaluate_semantic_policy(
    semantic_result: Mapping[str, Any] | None,
    design_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the product policy to final-geometry verifier evidence.

    A missing finding for a ``machine_required`` requirement is an explicit
    ``unsupported_verifier`` result.  It is never converted into a human
    review obligation merely because the application lacks coverage.
    """

    source = deepcopy(dict(semantic_result or {}))
    requirements = [
        item
        for item in design_contract.get("requirements", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    requirement_ids = {str(item["requirement_id"]) for item in requirements}
    raw_findings = [
        dict(item)
        for item in source.get("findings", [])
        if isinstance(item, Mapping) and item.get("requirement_id")
    ]
    by_id: dict[str, dict[str, Any]] = {}
    extra_findings: list[dict[str, Any]] = []
    for finding in raw_findings:
        requirement_id = str(finding["requirement_id"])
        if requirement_id in requirement_ids and requirement_id not in by_id:
            by_id[requirement_id] = finding
        elif requirement_id not in requirement_ids:
            extra_findings.append(finding)

    evaluated: list[dict[str, Any]] = []
    passed: list[str] = []
    failed: list[str] = []
    unsupported: list[str] = []
    review_required: list[str] = []

    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        finding = by_id.get(requirement_id)
        policy = _requirement_policy(requirement)
        measurement_available = _measurement_available(finding)
        observed_status = _observed_status(finding)
        if policy == "machine_required":
            if not measurement_available:
                result = "unsupported_verifier"
            elif observed_status == "passed":
                result = "verified"
            elif observed_status == "failed":
                result = "failed"
            else:
                result = "unsupported_verifier"
        elif policy == "review_required":
            result = "verified" if observed_status == "passed" else "review_required"
            review_required.append(requirement_id)
        else:
            result = "verified" if observed_status == "passed" else "informational"

        if result == "verified":
            passed.append(requirement_id)
        elif result == "failed":
            failed.append(requirement_id)
        elif result == "unsupported_verifier":
            unsupported.append(requirement_id)

        evaluated.append(
            {
                "requirement_id": requirement_id,
                "policy": policy,
                "verification_policy": requirement.get("verification_policy"),
                "expected_value": deepcopy(requirement.get("expected")),
                "measurement_available": measurement_available,
                "measured_value": _measured_value(finding),
                "tolerance": requirement.get("tolerance"),
                "result": result,
                "evidence_source": _evidence_source(finding, measurement_available),
                "observed_status": observed_status,
            }
        )

    # Preserve topology and other non-contract evidence for diagnostics, but
    # never let it hide a contract requirement or change a missing verifier
    # into success.
    for finding in extra_findings:
        status = str(finding.get("status") or "unverifiable")
        requirement_id = str(finding["requirement_id"])
        if status == "passed":
            passed.append(requirement_id)
        elif status == "failed":
            failed.append(requirement_id)
        elif status in {"unverifiable", "unsupported_verifier"}:
            unsupported.append(requirement_id)

    passed = _unique(passed)
    failed = _unique(failed)
    unsupported = _unique(unsupported)
    review_required = _unique(review_required)
    if failed:
        status = "failed"
    elif unsupported:
        status = "unsupported_verifier"
    elif review_required:
        status = "review_required"
    else:
        status = "passed"

    findings = extra_findings + evaluated
    result = {
        **source,
        "status": status,
        "passed": passed,
        "failed": failed,
        # Keep the legacy field for persisted readers while making the
        # application-coverage defect explicit and machine-actionable.
        "unverifiable": unsupported,
        "unsupported_verifier": unsupported,
        "review_required": review_required,
        "findings": findings,
        "semantic_policy_version": SEMANTIC_POLICY_VERSION,
        "policy_summary": {
            "version": SEMANTIC_POLICY_VERSION,
            "machine_required": sum(item["policy"] == "machine_required" for item in evaluated),
            "review_required": sum(item["policy"] == "review_required" for item in evaluated),
            "informational": sum(item["policy"] == "informational" for item in evaluated),
            "verified": len([item for item in evaluated if item["result"] == "verified"]),
            "failed": len(failed),
            "unsupported_verifier": len(unsupported),
        },
    }
    return result


def derive_candidate_policy(
    *,
    outputs: Iterable[Mapping[str, Any]],
    semantic_verification: Mapping[str, Any] | None,
    artifacts: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
    independent_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the sole candidate state from persisted evidence.

    The independent review is a veto/audit.  A reviewer PASS is considered
    only after deterministic output, topology, artifact, and machine semantic
    evidence has passed.
    """

    output_records = [dict(item) for item in outputs if isinstance(item, Mapping)]
    blockers: list[str] = []
    review_obligations: list[str] = []
    if not output_records:
        blockers.append("required_outputs_missing")

    for output in output_records:
        output_id = str(output.get("output_id") or "unknown_output")
        if output.get("required", True) is not True:
            continue
        state = str(output.get("state") or "")
        if state not in _PASSING_OUTPUT_STATES:
            blockers.append(f"output:{output_id}:state:{state or 'missing'}")
        worker_status = str(output.get("worker_status") or "")
        if worker_status and worker_status not in _PASSING_WORKER_STATES:
            blockers.append(f"output:{output_id}:worker:{worker_status}")
        topology_status = str(output.get("topology_status") or "")
        if topology_status not in _PASSING_TOPOLOGY_STATES:
            blockers.append(f"output:{output_id}:topology:{topology_status or 'missing'}")
        if output.get("artifact_available") is not True:
            blockers.append(f"output:{output_id}:artifact_missing")
        if output.get("artifact_integrity") is False:
            blockers.append(f"output:{output_id}:artifact_integrity")

    semantic = dict(semantic_verification or {})
    semantic_status = str(semantic.get("status") or "")
    if not semantic:
        blockers.append("semantic_verification_missing")
    if semantic_status in {"failed", "unsupported_verifier", "unverifiable"}:
        blockers.extend(
            str(item)
            for item in (
                semantic.get("failed") or []
            )
            if item
        )
        blockers.extend(
            str(item)
            for item in (
                semantic.get("unsupported_verifier")
                or semantic.get("unverifiable")
                or []
            )
            if item
        )
        if not semantic.get("failed") and not semantic.get("unsupported_verifier") and not semantic.get("unverifiable"):
            blockers.append(f"semantic:{semantic_status}")
    elif semantic_status not in {"passed", "review_required"}:
        blockers.append(f"semantic:{semantic_status or 'missing'}")
    review_obligations.extend(str(item) for item in semantic.get("review_required") or [] if item)

    # If callers provide a separate artifact report, its explicit false state
    # is authoritative.  Absence is not a blocker here because output-level
    # artifact evidence above remains mandatory.
    if isinstance(artifacts, Mapping):
        if artifacts.get("integrity") is False or artifacts.get("valid") is False:
            blockers.append("artifact_integrity")
    elif artifacts is not None:
        for artifact in artifacts:
            if isinstance(artifact, Mapping) and artifact.get("available") is False:
                blockers.append(f"artifact:{artifact.get('artifact_id') or 'unknown'}:missing")

    review = dict(independent_review or {})
    verdict = str(review.get("verdict") or "").upper()
    if verdict == "FAIL":
        blockers.append("independent_final_review_failed")
    elif verdict == "UNCERTAIN":
        review_obligations.append("independent_final_review")
    elif verdict != "PASS":
        review_obligations.append("independent_final_review")

    blockers = _unique(blockers)
    review_obligations = _unique(review_obligations)
    if blockers:
        state = "candidate_blocked"
    elif review_obligations:
        state = "candidate_ready_for_review"
    else:
        state = "candidate_fully_verified"
    return {
        "state": state,
        "candidate_state": state,
        "candidate_policy_version": CANDIDATE_POLICY_VERSION,
        "semantic_policy_version": semantic.get("semantic_policy_version", SEMANTIC_POLICY_VERSION),
        "blockers": blockers,
        "review_obligations": review_obligations,
        "eligible_for_review": state == "candidate_ready_for_review",
        "fully_verified": state == "candidate_fully_verified",
        "independent_review_verdict": verdict or None,
    }


def _requirement_policy(requirement: Mapping[str, Any]) -> str:
    policy = requirement.get("policy")
    return policy if isinstance(policy, str) and policy in REQUIREMENT_POLICIES else "machine_required"


def _observed_status(finding: Mapping[str, Any] | None) -> str:
    if finding is None:
        return "missing"
    status = str(finding.get("status") or finding.get("result") or "unverifiable")
    if status in {"passed", "verified"}:
        return "passed"
    if status == "failed":
        return "failed"
    return "unverifiable"


def _measurement_available(finding: Mapping[str, Any] | None) -> bool:
    if finding is None:
        return False
    if isinstance(finding.get("measurement_available"), bool):
        return finding["measurement_available"]
    return _observed_status(finding) in {"passed", "failed"}


def _measured_value(finding: Mapping[str, Any] | None) -> Any:
    if finding is None:
        return None
    if "measured_value" in finding:
        return deepcopy(finding["measured_value"])
    for key in ("measurements", "observed", "measured"):
        if key in finding:
            return deepcopy(finding[key])
    return None


def _evidence_source(finding: Mapping[str, Any] | None, available: bool) -> str:
    if finding is not None and finding.get("evidence_source"):
        return str(finding["evidence_source"])
    return "final_mesh" if available else "none"


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))
