from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PILOT_CASE_IDS = tuple(f"case-{index:03d}" for index in range(1, 11))
FLASH_LITE_STUDY_CASE_IDS = PILOT_CASE_IDS
FLASH_LITE_STUDY_VERSION = "gemini-flash-lite-study-v1"
OLLAMA_CASE_IDS = tuple(f"ollama-case-{index:03d}" for index in range(1, 6))
SPECIFICITY_LEVELS = {"vague", "moderate", "high", "constrained"}
REQUIRED_CASE_FIELDS = {
    "case_id",
    "title",
    "family",
    "initial_prompt",
    "specificity",
    "fact_sheet",
    "allowed_proposal_categories",
    "prohibited_assumptions",
    "expected_output_count",
    "expected_route_category",
    "safety_notes",
    "evaluation_tags",
    "dimension_scale",
}


@dataclass(frozen=True)
class ConsistencyCase:
    case_id: str
    title: str
    family: str
    initial_prompt: str
    specificity: str
    fact_sheet: dict[str, Any]
    allowed_proposal_categories: list[str]
    prohibited_assumptions: list[str]
    expected_output_count: int
    expected_route_category: str | None
    safety_notes: list[str]
    evaluation_tags: list[str]
    dimension_scale: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class ConsistencyCorpus:
    version: str
    cases: tuple[ConsistencyCase, ...]
    content_hash: str
    raw: dict[str, Any]

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)

    @property
    def specificity_counts(self) -> dict[str, int]:
        return {
            level: sum(case.specificity == level for case in self.cases)
            for level in ("vague", "moderate", "high", "constrained")
        }

    @property
    def family_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.family] = counts.get(case.family, 0) + 1
        return counts

    def case(self, case_id: str) -> ConsistencyCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)

    def to_document(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.raw))


def _content_hash(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_consistency_corpus(
    document: dict[str, Any],
    *,
    id_prefix: str = "case",
    exact_count: int | None = None,
) -> None:
    if not isinstance(document, dict):
        raise ValueError("corpus document must be an object")
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("corpus version is required")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus cases are required")
    if exact_count is not None and len(cases) != exact_count:
        raise ValueError(f"corpus must contain exactly {exact_count} cases")
    expected_ids = [f"{id_prefix}-{index:03d}" for index in range(1, len(cases) + 1)]
    actual_ids = [case.get("case_id") if isinstance(case, dict) else None for case in cases]
    if actual_ids != expected_ids or len(set(actual_ids)) != len(actual_ids):
        raise ValueError(f"stable case IDs must be {expected_ids[0]} through {expected_ids[-1]} with no duplicates")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each corpus case must be an object")
        missing = sorted(REQUIRED_CASE_FIELDS - set(case))
        if missing:
            raise ValueError(f"{case.get('case_id', 'unknown')} missing fields: {', '.join(missing)}")
        if case["specificity"] not in SPECIFICITY_LEVELS:
            raise ValueError(f"{case['case_id']} has unsupported specificity")
        for field in ("title", "family", "initial_prompt", "dimension_scale"):
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError(f"{case['case_id']} requires non-empty {field}")
        if not isinstance(case["fact_sheet"], dict) or not case["fact_sheet"]:
            raise ValueError(f"{case['case_id']} requires a fact sheet")
        if not isinstance(case["expected_output_count"], int) or case["expected_output_count"] < 1:
            raise ValueError(f"{case['case_id']} requires a positive expected output count")
        for field in ("allowed_proposal_categories", "prohibited_assumptions", "safety_notes", "evaluation_tags"):
            if not isinstance(case[field], list) or not all(isinstance(item, str) and item.strip() for item in case[field]):
                raise ValueError(f"{case['case_id']} requires a non-empty string list for {field}")
    family_counts: dict[str, int] = {}
    for case in cases:
        family_counts[case["family"]] = family_counts.get(case["family"], 0) + 1
    if max(family_counts.values()) > 5:
        raise ValueError("no design family may contain more than five cases")


def load_consistency_corpus(path: Path) -> ConsistencyCorpus:
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_consistency_corpus(document)
    return _load_corpus(document)


def validate_flash_lite_study_corpus(document: dict[str, Any]) -> None:
    """Validate the immutable ten-case corpus used by the Flash Lite study."""

    validate_consistency_corpus(document, exact_count=10)
    if document.get("version") != FLASH_LITE_STUDY_VERSION:
        raise ValueError(f"Flash Lite study corpus version must be {FLASH_LITE_STUDY_VERSION}")
    if document.get("study_kind") != "before-and-after product correction study":
        raise ValueError("Flash Lite study corpus must declare the before-and-after study kind")
    policy = document.get("clarification_policy")
    if not isinstance(policy, dict) or policy.get("max_rounds") != 2:
        raise ValueError("Flash Lite study corpus must freeze the two-round clarification policy")
    actual_ids = tuple(case.get("case_id") for case in document["cases"])
    if actual_ids != FLASH_LITE_STUDY_CASE_IDS:
        raise ValueError("Flash Lite study corpus must use case-001 through case-010 in order")


def load_flash_lite_study_corpus(path: Path) -> ConsistencyCorpus:
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_flash_lite_study_corpus(document)
    return _load_corpus(document)


def validate_ollama_consistency_corpus(document: dict[str, Any]) -> None:
    validate_consistency_corpus(document, id_prefix="ollama-case", exact_count=5)


def load_ollama_consistency_corpus(path: Path) -> ConsistencyCorpus:
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_ollama_consistency_corpus(document)
    return _load_corpus(document)


def _load_corpus(document: dict[str, Any]) -> ConsistencyCorpus:
    cases = tuple(
        ConsistencyCase(
            case_id=case["case_id"],
            title=case["title"],
            family=case["family"],
            initial_prompt=case["initial_prompt"],
            specificity=case["specificity"],
            fact_sheet=dict(case["fact_sheet"]),
            allowed_proposal_categories=list(case["allowed_proposal_categories"]),
            prohibited_assumptions=list(case["prohibited_assumptions"]),
            expected_output_count=case["expected_output_count"],
            expected_route_category=case["expected_route_category"],
            safety_notes=list(case["safety_notes"]),
            evaluation_tags=list(case["evaluation_tags"]),
            dimension_scale=case["dimension_scale"],
            raw=dict(case),
        )
        for case in document["cases"]
    )
    return ConsistencyCorpus(
        version=document["version"],
        cases=cases,
        content_hash=_content_hash(document),
        raw=document,
    )
