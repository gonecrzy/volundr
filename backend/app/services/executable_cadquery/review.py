"""Blind final-package review contracts.

The reviewer is an independent audit/veto.  This module prepares the narrow
input packet and persists a normalized result; it never edits CAD or upgrades
a deterministic Volundr failure into success.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


BLIND_REVIEW_PACKET_VERSION = "executable-cadquery-blind-review-packet-v1"
BLIND_REVIEW_RECORD_VERSION = "executable-cadquery-blind-review-record-v1"
REVIEW_VERDICTS = frozenset({"PASS", "FAIL", "UNCERTAIN"})


def build_blind_review_packet(
    *,
    original_prompt: str,
    clarifications: Sequence[Mapping[str, Any]] = (),
    revisions: Sequence[Mapping[str, Any]] = (),
    final_output_identities: Sequence[str],
    package_manifest: Mapping[str, Any],
    neutral_measurement_report: Mapping[str, Any],
    fixed_views: Sequence[str] = (),
    units: str = "mm",
    producer_history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct the only context a blind final-package reviewer receives."""

    # ``producer_history`` is accepted solely to make the isolation boundary
    # explicit to callers and tests.  It is intentionally never read.
    del producer_history
    return {
        "schema_version": BLIND_REVIEW_PACKET_VERSION,
        "original_prompt": str(original_prompt),
        "clarifications": [deepcopy(dict(item)) for item in clarifications if isinstance(item, Mapping)],
        "revisions": [deepcopy(dict(item)) for item in revisions if isinstance(item, Mapping)],
        "final_output_identities": [str(item) for item in final_output_identities],
        "package_manifest": deepcopy(dict(package_manifest)),
        "neutral_measurement_report": deepcopy(dict(neutral_measurement_report)),
        "fixed_views": [str(item) for item in fixed_views],
        "units": str(units),
    }


def build_blind_review_record(
    *,
    review_cycle: int,
    reviewer_result: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize an independent reviewer response with Volundr veto rules."""

    requirements: list[dict[str, Any]] = []
    for item in reviewer_result.get("requirements", []):
        if not isinstance(item, Mapping) or not item.get("requirement_id"):
            continue
        verdict = _verdict(item.get("verdict"))
        discrepancies = item.get("discrepancies", [])
        if not isinstance(discrepancies, list):
            discrepancies = [str(discrepancies)]
        requirements.append(
            {
                "requirement_id": str(item["requirement_id"]),
                "evidence_type": str(item.get("evidence_type") or "not_stated"),
                "observed": deepcopy(item.get("observed")),
                "verdict": verdict,
                "discrepancies": deepcopy(discrepancies),
            }
        )
    final_verdict = _verdict(reviewer_result.get("final_verdict"))
    state = str(candidate_policy.get("state") or "candidate_blocked")
    deterministic_blockers = [
        str(item) for item in candidate_policy.get("blockers", []) if item
    ]
    if state == "candidate_blocked" or deterministic_blockers:
        disposition = "vetoed_by_deterministic_failure"
        accepted = False
    elif final_verdict == "FAIL":
        disposition = "reviewer_veto"
        accepted = False
    elif final_verdict == "UNCERTAIN":
        disposition = "missing_evidence_or_review"
        accepted = False
    else:
        disposition = "independent_confirmation"
        accepted = True
    return {
        "schema_version": BLIND_REVIEW_RECORD_VERSION,
        "review_cycle": int(review_cycle),
        "requirements": requirements,
        "revision_preservation": deepcopy(reviewer_result.get("revision_preservation", {})),
        "final_verdict": final_verdict,
        "candidate_policy_state": state,
        "deterministic_blockers": deterministic_blockers,
        "disposition": disposition,
        "accepted_for_candidate": accepted,
    }


def _verdict(value: Any) -> str:
    verdict = str(value or "UNCERTAIN").upper()
    return verdict if verdict in REVIEW_VERDICTS else "UNCERTAIN"

