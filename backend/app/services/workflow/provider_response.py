"""Shared, bounded provider-response convergence primitives.

This module deliberately does not validate a particular Volundr contract.  It
records the representations that a stage sees and provides conservative
helpers which stage-specific validators can use without losing the provider's
original response.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


class ProviderResponseOutcome(str, Enum):
    TRANSPORT_FAILURE = "transport_failure"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    EMPTY_RESPONSE = "empty_response"
    TRUNCATED_RESPONSE = "truncated_response"
    INVALID_JSON = "invalid_json"
    SYNTACTICALLY_REPAIRABLE_JSON = "syntactically_repairable_json"
    SCHEMA_INVALID = "schema_invalid"
    PROVENANCE_INVALID = "provenance_invalid"
    SEMANTIC_INCOMPLETE = "semantic_incomplete"
    SEMANTIC_CONTRADICTION = "semantic_contradiction"
    PROTECTED_IDENTITY_VIOLATION = "protected_identity_violation"
    VALID = "valid"
    VALID_AFTER_NORMALIZATION = "valid_after_normalization"
    VALID_AFTER_REPAIR = "valid_after_repair"
    UNCHANGED_REPAIR = "unchanged_repair"
    REGRESSIVE_REPAIR = "regressive_repair"


class RepairOutcome(str, Enum):
    VALID_AFTER_REPAIR = "valid_after_repair"
    UNCHANGED_REPAIR = "unchanged_repair"
    PARTIAL_REPAIR = "partial_repair"
    REGRESSIVE_REPAIR = "regressive_repair"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(value: Any) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _strip_approved_wrapper(raw: str) -> str:
    stripped = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    # Providers sometimes add one short sentence around an otherwise complete
    # JSON object.  Only accept the unique outermost object/array candidate;
    # prose is never converted into fields.
    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if starts:
        start = min(starts)
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if start > 0 and end > start:
            candidate = stripped[start : end + 1]
            if candidate.count("{") == candidate.count("}") and candidate.count("[") == candidate.count("]"):
                return candidate.strip()
    return stripped


def _remove_trailing_commas(value: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", value)


@dataclass(frozen=True)
class ProviderResponseAnalysis:
    stage: str
    raw_text: str
    normalized_text: str | None
    parsed: Any | None
    normalized: Any | None
    classification: ProviderResponseOutcome
    syntax_status: str
    raw_hash: str
    normalized_hash: str | None
    findings_before_normalization: tuple[str, ...] = ()
    findings_after_normalization: tuple[str, ...] = ()
    repaired: Any | None = None
    repaired_hash: str | None = None
    final: Any | None = None
    final_hash: str | None = None
    findings_after_repair: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    identities_changed: bool = False
    provenance_changed: bool = False
    final_stage: str | None = None

    @property
    def original_response(self) -> str:
        return self.raw_text


@dataclass(frozen=True)
class ProvenanceCompletion:
    value: dict[str, Any]
    findings: tuple[str, ...]
    changed: bool = False


@dataclass(frozen=True)
class RepairComparison:
    outcome: RepairOutcome
    original_hash: str
    repaired_hash: str
    changed_paths: tuple[str, ...]
    resolved_findings: tuple[str, ...]
    introduced_findings: tuple[str, ...]
    identities_changed: bool
    provenance_changed: bool
    blocked: bool

    @property
    def classification(self) -> ProviderResponseOutcome:
        if self.outcome is RepairOutcome.UNCHANGED_REPAIR:
            return ProviderResponseOutcome.UNCHANGED_REPAIR
        if self.outcome is RepairOutcome.REGRESSIVE_REPAIR:
            return ProviderResponseOutcome.REGRESSIVE_REPAIR
        if self.outcome is RepairOutcome.VALID_AFTER_REPAIR:
            return ProviderResponseOutcome.VALID_AFTER_REPAIR
        return ProviderResponseOutcome.SEMANTIC_INCOMPLETE


def analyze_provider_response(
    raw_text: str | None,
    *,
    stage: str,
    findings: Iterable[str] = (),
    normalizer: Callable[[Any], tuple[Any, Iterable[str]]] | None = None,
) -> ProviderResponseAnalysis:
    """Parse one response while retaining every representation.

    ``findings`` are supplied by the stage validator.  The parser itself only
    performs approved JSON-envelope normalization and trailing-comma removal.
    """

    raw = "" if raw_text is None else str(raw_text)
    raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if not raw.strip():
        return ProviderResponseAnalysis(
            stage=stage,
            raw_text=raw,
            normalized_text=None,
            parsed=None,
            normalized=None,
            classification=ProviderResponseOutcome.EMPTY_RESPONSE,
            syntax_status="syntax_repair_failed",
            raw_hash=raw_hash,
            normalized_hash=None,
        )

    candidate = _strip_approved_wrapper(raw)
    candidates = [candidate]
    comma_free = _remove_trailing_commas(candidate)
    if comma_free != candidate:
        candidates.append(comma_free)

    parsed: Any | None = None
    normalized_text: str | None = None
    for candidate_text in candidates:
        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError:
            continue
        normalized_text = candidate_text
        break

    if parsed is None:
        return ProviderResponseAnalysis(
            stage=stage,
            raw_text=raw,
            normalized_text=None,
            parsed=None,
            normalized=None,
            classification=ProviderResponseOutcome.INVALID_JSON,
            syntax_status="syntax_repair_failed",
            raw_hash=raw_hash,
            normalized_hash=None,
        )

    normalized = copy.deepcopy(parsed)
    normalization_findings: list[str] = []
    if normalizer is not None:
        normalized, supplied_findings = normalizer(copy.deepcopy(normalized))
        normalization_findings.extend(str(item) for item in supplied_findings)
    supplied_findings = tuple(str(item) for item in findings)
    all_findings = tuple(dict.fromkeys((*supplied_findings, *normalization_findings)))
    changed = normalized_text != raw.strip() or normalized != parsed
    classification = (
        ProviderResponseOutcome.SCHEMA_INVALID
        if supplied_findings
        else ProviderResponseOutcome.VALID_AFTER_NORMALIZATION
        if changed
        else ProviderResponseOutcome.VALID
    )
    return ProviderResponseAnalysis(
        stage=stage,
        raw_text=raw,
        normalized_text=normalized_text,
        parsed=parsed,
        normalized=normalized,
        classification=classification,
        syntax_status="syntax_repair_succeeded" if changed else "not_needed",
        raw_hash=raw_hash,
        normalized_hash=_hash(normalized),
        findings_before_normalization=supplied_findings,
        findings_after_normalization=all_findings,
        final=normalized if not supplied_findings else None,
        final_hash=_hash(normalized) if not supplied_findings else None,
        final_stage=stage if not supplied_findings else None,
    )


def complete_authoritative_provenance(
    record: dict[str, Any],
    authoritative_sources: dict[str, dict[str, Any]],
    *,
    requirement_id: str | None = None,
) -> ProvenanceCompletion:
    """Complete only a uniquely matching provenance source.

    Existing source labels are never silently rewritten.  This is intentional:
    a source mismatch is evidence that must remain visible to the stage
    validator or focused repair.
    """

    value = copy.deepcopy(record)
    provenance = value.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        value["provenance"] = provenance

    matches = [
        (source_id, source)
        for source_id, source in authoritative_sources.items()
        if source.get("value") == value.get("value") and source.get("unit") == value.get("unit")
    ]
    if requirement_id is not None:
        matches = [(requirement_id, authoritative_sources[requirement_id])] if requirement_id in authoritative_sources else []

    existing_source = provenance.get("source")
    if existing_source:
        if matches and matches[0][1].get("source") != existing_source:
            finding = (
                "provenance.proposal_misclassified"
                if existing_source == "volundr_proposal"
                else "provenance.user_input_misclassified"
            )
            return ProvenanceCompletion(value=value, findings=(finding,))
        return ProvenanceCompletion(value=value, findings=())

    if len(matches) != 1:
        finding = "provenance.source_conflict" if len(matches) > 1 else "provenance.derived_source_missing"
        return ProvenanceCompletion(value=value, findings=(finding,))

    source_id, source = matches[0]
    provenance["source"] = source["source"]
    provenance["source_id"] = source_id
    return ProvenanceCompletion(value=value, findings=("provenance.source_completed",), changed=True)


def build_focused_repair_context(
    *,
    record: dict[str, Any],
    findings: Iterable[str],
    protected_ids: Iterable[str],
    allowed_alternatives: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "record": copy.deepcopy(record),
        "findings": [str(item) for item in findings],
        "protected_ids": [str(item) for item in protected_ids],
        "allowed_alternatives": [str(item) for item in allowed_alternatives],
        "prohibited_changes": ["protected_ids", "unrelated_records"],
    }


def _paths(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_paths(child, path))
        return result or {prefix: value}
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value):
            result.update(_paths(child, f"{prefix}[{index}]"))
        return result or {prefix: value}
    return {prefix: value}


def _path_matches(path: str, allowed: str) -> bool:
    return path == allowed or path.startswith(f"{allowed}.") or path.startswith(f"{allowed}[")


def compare_focused_repair(
    original: Any,
    repaired: Any,
    *,
    findings_before: Iterable[str],
    findings_after: Iterable[str],
    affected_paths: Iterable[str],
    protected_paths: Iterable[str] = (),
) -> RepairComparison:
    before_findings = tuple(dict.fromkeys(str(item) for item in findings_before))
    after_findings = tuple(dict.fromkeys(str(item) for item in findings_after))
    original_paths = _paths(original)
    repaired_paths = _paths(repaired)
    changed_paths = tuple(sorted(
        path
        for path in set(original_paths) | set(repaired_paths)
        if original_paths.get(path) != repaired_paths.get(path)
    ))
    protected = tuple(protected_paths)
    affected = tuple(affected_paths)
    identities_changed = any(path == "id" or path.endswith(".id") or path.endswith("]id") for path in changed_paths)
    provenance_changed = any("provenance" in path or path.endswith(".source") for path in changed_paths)
    resolved = tuple(item for item in before_findings if item not in after_findings)
    introduced = tuple(item for item in after_findings if item not in before_findings)
    protected_changed = any(_path_matches(path, item) for path in changed_paths for item in protected)
    unrelated_changed = any(not any(_path_matches(path, item) for item in affected) for path in changed_paths)
    same_hash = _hash(original) == _hash(repaired)

    if protected_changed or unrelated_changed or introduced:
        outcome = RepairOutcome.REGRESSIVE_REPAIR
    elif same_hash or after_findings == before_findings:
        outcome = RepairOutcome.UNCHANGED_REPAIR
    elif after_findings:
        outcome = RepairOutcome.PARTIAL_REPAIR
    else:
        outcome = RepairOutcome.VALID_AFTER_REPAIR

    return RepairComparison(
        outcome=outcome,
        original_hash=_hash(original) or "",
        repaired_hash=_hash(repaired) or "",
        changed_paths=changed_paths,
        resolved_findings=resolved,
        introduced_findings=introduced,
        identities_changed=identities_changed,
        provenance_changed=provenance_changed,
        blocked=outcome is not RepairOutcome.VALID_AFTER_REPAIR,
    )
