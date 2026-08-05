"""Deterministic repository documentation, test, study, and reference audit.

The audit is repository tooling. It is deliberately not imported by the
runtime workflow and cannot alter provider, worker, or product routing.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


AUDIT_SCHEMA_VERSION = "volundr-repository-audit-v1"

CURRENT_AUTHORITATIVE_PATHS = {
    "docs/CURRENT_TRAJECTORY.md",
    "docs/PROVIDER_CONTRACT.md",
    "docs/INTEGRATION_TEST_LOOP.md",
    "docs/STUDY_INDEX.md",
}

CURRENT_SUPPORTING_PATHS = {
    "README.md",
    "CODEX_KICKOFF_PROMPT.md",
    "docs/DOCUMENTATION_MAP.md",
    "docs/ARCHITECTURE.md",
    "docs/CADQUERY_BACKEND.md",
    "docs/PRODUCT_DIRECTION.md",
    "docs/MVP_SCOPE.md",
    "docs/GEMINI_RULESET.md",
    "docs/MULTI_OUTPUT_GENERATION.md",
    "docs/GEOMETRY_EXECUTION_CONTEXT.md",
    "docs/GEOMETRY_BODY_SYMBOL_CONTRACT.md",
    "docs/GEOMETRY_SLOT_CONTRACT.md",
    "docs/GEOMETRY_SLOT_PRODUCTION_ROLLOUT.md",
    "docs/PLAN_SOURCE_IDENTITY_BOUNDARY.md",
    "docs/PROVIDER_INTEROPERABILITY_CONTRACT.md",
    "docs/WORKER_DIAGNOSTIC_REPAIR.md",
    "docs/REQUIREMENT_SEMANTICS_CONTRACT.md",
    "docs/REQUIREMENT_TRACE_CONTRACT.md",
    "docs/REQUIREMENT_PIPELINE_AUDIT.md",
    "docs/ENVIRONMENT_VARIABLES.md",
    "docs/DEPLOYMENT.md",
    "docs/TEST_STRATEGY.md",
    "docs/AI_CAD_DIRECTION_ALIGNMENT.md",
    "docs/AI_VISUAL_REVIEW_PLAN.md",
    "docs/COMPACT_DETAILED_PIPELINE_DIAGNOSIS.md",
    "docs/COMPACT_PLAN_CONTRACT.md",
    "docs/COMPONENT_TARGETED_REVISIONS.md",
    "docs/DERIVED_DEPENDENCY_CLASSIFICATION.md",
    "docs/DETERMINISTIC_USER_WORKFLOW_GATE.md",
    "docs/EXPORTS.md",
    "docs/FUNCTIONAL_DESIGN_INTENT.md",
    "docs/FUNCTIONAL_GEOMETRY_VERIFICATION.md",
    "docs/GEOMETRY_TOPOLOGY_CONVERGENCE.md",
    "docs/LIVE_DEBUG_BATCH_IMPLEMENTATION.md",
    "docs/MULTI_VIEW_SNAPSHOT_CONTRACT.md",
    "docs/OBSERVED_FRONTEND_TESTING_SCRIPT.md",
    "docs/PARAMETRIC_PRODUCT_MODEL.md",
    "docs/PATTERN_COORDINATE_SPACE_CONTRACT.md",
    "docs/PLANNING_DEPTH_MODEL.md",
    "docs/PRINTABILITY_INSPECTOR.md",
    "docs/PRODUCT_REVIEW_ACTIONS.md",
    "docs/PROJECT_PERSISTENCE.md",
    "docs/PROMPT_CONTEXT_PACK.md",
    "docs/PROVIDER_CONVERGENCE_REGRESSION_FIXTURES.md",
    "docs/PROVIDER_RESPONSE_CONVERGENCE.md",
    "docs/REPEATED_FEATURE_LAYOUTS.md",
    "docs/REQUIREMENT_PROPAGATION_REVIEW.md",
    "docs/REQUIREMENT_TRACE_NORMALIZATION.md",
    "docs/REVISION_EVIDENCE_MODEL.md",
    "docs/GEOMETRY_SLOTS_BLOCKER_REVIEW.md",
    "docs/PRODUCT_VALIDATION_ROUND_1.md",
}

HISTORICAL_IMMUTABLE_PATHS = {
    "docs/CADQUERY_TRANSITION_EVALUATION.md",
    "docs/CURRENT_REPOSITORY_AUDIT.md",
    "docs/GEMINI_PROVIDER_CONTRACT_FOUNDATION.md",
    "docs/GEMINI_PROVIDER_CONTRACT_CORRECTION.md",
    "docs/GEMINI_PROVIDER_CONTRACT_HOLDOUT.md",
    "docs/GEMINI_PROVIDER_CONTRACTS.md",
}

HISTORICAL_SUPERSEDED_PATHS = {
    "docs/MODEL_GENERATION_CONTRACT.md",
}

_HISTORICAL_NAME_MARKERS = (
    "ABLATION",
    "ANALYZER_AUDIT",
    "BASELINE",
    "BENCHMARK",
    "COMPARISON",
    "CORRECTION",
    "EVALUATION",
    "EXPERIMENT",
    "HOLDOUT",
    "LIVE_BATCH",
    "NEXT_ACTIONS",
    "OFFLINE_REPLAY",
    "RESULTS",
    "RECONCILIATION",
    "RUN_RECORD",
    "STABILITY",
    "STUDY",
    "FACTORIAL",
    "MIXED_CAD",
)


def _normalized(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
    except OSError:
        return ""


def _tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _title(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def classify_document(path: str, content: str = "") -> str:
    """Classify a document without treating a missing import as deletion proof."""

    normalized = _normalized(path)
    if normalized in CURRENT_AUTHORITATIVE_PATHS:
        return "current_authoritative"
    if normalized.startswith("docs/archive/"):
        return "historical_superseded"
    if normalized.startswith("docs/mutantpowers/plans/"):
        return "historical_immutable"
    if normalized in HISTORICAL_SUPERSEDED_PATHS:
        return "historical_superseded"
    if normalized in HISTORICAL_IMMUTABLE_PATHS:
        return "historical_immutable"
    if normalized in CURRENT_SUPPORTING_PATHS:
        return "current_supporting"
    if normalized.startswith(("docs/GEMINI_", "docs/OLLAMA_")):
        return "historical_immutable"
    name = PurePosixPath(normalized).name.upper()
    if any(marker in name for marker in _HISTORICAL_NAME_MARKERS):
        return "historical_immutable"
    if re.search(r"\b(open|scad|legacy)\b", content, re.IGNORECASE) and normalized.startswith("docs/"):
        return "historical_superseded"
    return "unknown_requires_review"


_STALE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "obsolete-thinking-profile",
        re.compile(r"(?:\bH0\b.*\bcurrent\b|\bcurrent\b.*\bH0\b)", re.IGNORECASE),
    ),
    (
        "obsolete-geometry-prompt",
        re.compile(r"(?:T0-current.*geometry|geometry.*T0-current)", re.IGNORECASE),
    ),
    (
        "obsolete-seed",
        re.compile(r"(?:seed\s*[:=]?\s*1701.*\bcurrent\b|\bcurrent\b.*seed\s*[:=]?\s*1701)", re.IGNORECASE),
    ),
    (
        "obsolete-repair-gate",
        re.compile(r"(?:repair.*\bcurrent\b.*\bgate\b|\bgate\b.*repair.*\bcurrent\b)", re.IGNORECASE),
    ),
    (
        "obsolete-output-identity",
        re.compile(r"(?:canonical\s+(?:printable\s+)?output\s+id|output\s+id\s+is\s+canonical|id\s+is\s+the\s+canonical\s+output)", re.IGNORECASE),
    ),
    (
        "obsolete-provider-profile",
        re.compile(r"(?:profile[- ]B|S1-profile-b).*(?:current|authoritative)", re.IGNORECASE),
    ),
)


def _is_historical_path(path: str) -> bool:
    normalized = _normalized(path)
    return (
        normalized.startswith("docs/archive/")
        or normalized.startswith("docs/mutantpowers/plans/")
        or normalized in HISTORICAL_IMMUTABLE_PATHS
        or normalized in HISTORICAL_SUPERSEDED_PATHS
        or any(marker in PurePosixPath(normalized).name.upper() for marker in _HISTORICAL_NAME_MARKERS)
    )


def find_stale_reference_violations(documents: Mapping[str, str]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path, content in sorted(documents.items()):
        if _is_historical_path(path):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for rule_id, pattern in _STALE_RULES:
                if pattern.search(line):
                    findings.append({"path": path, "line": line_number, "rule_id": rule_id, "text": line.strip()})
    current_decision_paths = [
        path
        for path, content in sorted(documents.items())
        if not _is_historical_path(path)
        and re.search(r"\bcurrent\b[^\n]*(?:provider|integration)[^\n]*\bdecision\b", content, re.IGNORECASE)
    ]
    if len(current_decision_paths) > 1:
        for path in current_decision_paths:
            findings.append({
                "path": path,
                "line": 1,
                "rule_id": "multiple-current-provider-decisions",
                "text": "multiple active documents claim current provider or integration decision",
                "related_paths": current_decision_paths,
            })
    return findings


_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate_markdown_links(
    documents: Mapping[str, str],
    known_paths: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    known = {_normalized(path) for path in (known_paths or documents)}
    known.update(_normalized(path) for path in documents)
    findings: list[dict[str, object]] = []
    for path, content in sorted(documents.items()):
        if not path.endswith(".md"):
            continue
        base = PurePosixPath(path).parent
        for line_number, line in enumerate(content.splitlines(), start=1):
            for raw_target in _MARKDOWN_LINK.findall(line):
                target = raw_target.strip().split("#", 1)[0].split("?", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                candidate = _normalized(posixpath.normpath(posixpath.join(str(base), target)))
                if candidate not in known:
                    findings.append({"path": path, "target": candidate, "line": line_number, "reason": "target_not_found"})
    return findings


def _extract_markdown_targets(path: str, content: str) -> list[str]:
    base = PurePosixPath(path).parent
    targets: list[str] = []
    for raw_target in _MARKDOWN_LINK.findall(content):
        target = raw_target.strip().split("#", 1)[0].split("?", 1)[0]
        if target and "://" not in target and not target.startswith("mailto:"):
            targets.append(_normalized(posixpath.normpath(posixpath.join(str(base), target))))
    return sorted(set(targets))


def _searchable_sources(root: Path, tracked: list[str]) -> dict[str, str]:
    selected = {
        path
        for path in tracked
        if path == "README.md"
        or path == "CODEX_KICKOFF_PROMPT.md"
        or path.startswith("docs/")
        or path.startswith("backend/scripts/")
        or path.startswith("scripts/")
        or path.startswith("backend/app/services/gemini_")
        or path == "backend/app/services/documentation_audit.py"
        or path.startswith("backend/app/services/ai/")
        or path.startswith("backend/tests/")
        or path.startswith("frontend/") and ("test" in path or path.endswith((".md", ".json")))
    }
    selected.update(
        _normalized(path.relative_to(root))
        for base in (root / "docs", root / "backend/scripts")
        if base.exists()
        for path in base.rglob("*")
        if path.is_file()
        and not _normalized(path.relative_to(root)).startswith("docs/audit/")
        and path.suffix in {".md", ".py", ".sh", ".toml", ".yaml", ".yml", ".json"}
    )
    return {path: _read_text(root / path) for path in sorted(selected)}


def _references_for(path: str, sources: Mapping[str, str]) -> list[str]:
    basename = PurePosixPath(path).name
    stem = PurePosixPath(path).stem
    needles = {path, basename, stem}
    references = [
        source
        for source, content in sources.items()
        if source != path and any(needle and needle in content for needle in needles)
    ]
    return sorted(references)


def build_documentation_inventory(root: Path, tracked: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    tracked = tracked or _tracked_paths(root)
    paths = [
        path
        for path in tracked
        if path.endswith(".md") and not path.startswith("docs/audit/") and (path.startswith("docs/") or path in {"README.md", "CODEX_KICKOFF_PROMPT.md"})
    ]
    paths.extend(
        _normalized(path.relative_to(root))
        for path in (root / "docs").rglob("*.md")
        if path.is_file() and not _normalized(path.relative_to(root)).startswith("docs/audit/")
    )
    paths = sorted(set(paths) | {path for path in ("README.md", "CODEX_KICKOFF_PROMPT.md") if (root / path).is_file()})
    sources = _searchable_sources(root, tracked)
    items: list[dict[str, Any]] = []
    for path in paths:
        file_path = root / path
        content = _read_text(file_path)
        items.append({
            "path": path,
            "title": _title(content),
            "classification": classify_document(path, content),
            "sha256": _sha256(file_path),
            "bytes": file_path.stat().st_size,
            "line_count": len(content.splitlines()),
            "references": _extract_markdown_targets(path, content),
            "referenced_by": _references_for(path, sources),
            "immutable_evidence": classify_document(path, content) in {"historical_immutable", "historical_superseded"},
        })

    embedded: list[dict[str, Any]] = []
    embedded_pattern = re.compile(r"provider contract|prompt version|integration-only|authoritative output_id|study id", re.IGNORECASE)
    for path, content in sources.items():
        if not path.endswith((".py", ".sh", ".toml", ".yaml", ".yml")):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if embedded_pattern.search(line) and ("#" in line or '"""' in line or "'''" in line or path.startswith("backend/scripts/")):
                embedded.append({"path": path, "line": line_number, "text": line.strip()[:240]})

    counts = Counter(item["classification"] for item in items)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "inventory": "repository-documentation",
        "items": items,
        "embedded_documentation_sources": embedded,
        "summary": {"document_count": len(items), "by_classification": dict(sorted(counts.items()))},
    }


def _test_classification(path: str, content: str) -> tuple[str, str]:
    normalized = _normalized(path)
    if "/fixtures/" in normalized or "/snapshots/" in normalized:
        if "gemini" in normalized or "provider" in normalized or "geometry" in normalized:
            return "retain_regression", "named provider or geometry fixture"
        return "retain_current", "deterministic fixture"
    if normalized.endswith("test_documentation_audit.py"):
        return "retain_current", "audit tooling regression"
    if any(token in normalized for token in (
        "test_gemini_flash_lite_",
        "test_gemini_profile_ablation",
        "test_gemini_system_boundary_methods",
        "test_gemini_provider_contract_foundation",
        "test_gemini_provider_contract_correction",
    )):
        return "historical_integrity_only", "preserves an immutable study protocol or historical result"
    if "test_gemini_integration" in normalized or "test_gemini_geometry_prompt_narrow_fix" in normalized:
        return "retain_current", "current integration boundary or replay behavior"
    if "prompt_snapshot" in normalized or normalized.endswith("test_prompt_snapshots.py"):
        return "retain_current", "current production prompt behavior"
    return "retain_current", "current production behavior, safety invariant, or tooling"


def _markers(content: str) -> list[str]:
    patterns = {
        "skip": r"pytest\.skip|@pytest\.mark\.skip|@pytest\.mark\.skipif",
        "xfail": r"pytest\.mark\.xfail|@pytest\.mark\.xfail",
        "warning": r"pytest\.warns|warnings\.warn|filterwarnings|deprecated",
    }
    return sorted(name for name, pattern in patterns.items() if re.search(pattern, content, re.IGNORECASE))


def build_test_inventory(root: Path, tracked: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    tracked = tracked or _tracked_paths(root)
    paths = [
        path
        for path in tracked
        if path.startswith("backend/tests/") or path.startswith("frontend/") and ("test" in path or "spec" in path)
    ]
    for base in (root / "backend/tests", root / "frontend"):
        if not base.exists():
            continue
        paths.extend(
            _normalized(path.relative_to(root))
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".json", ".ts", ".tsx", ".js", ".mjs"}
            and not any(part in {"node_modules", "test-results", "dist", ".vite", "__pycache__"} for part in path.parts)
            and (base.name == "tests" or "test" in path.name or "spec" in path.name or "fixtures" in path.parts or "snapshots" in path.parts)
        )
    paths = sorted(set(paths))
    items: list[dict[str, Any]] = []
    for path in paths:
        file_path = root / path
        content = _read_text(file_path)
        classification, reason = _test_classification(path, content)
        items.append({
            "path": path,
            "kind": "fixture" if "/fixtures/" in path or "/snapshots/" in path else "test",
            "classification": classification,
            "reason": reason,
            "sha256": _sha256(file_path),
            "markers": _markers(content),
            "historical_contract_terms": sorted(set(re.findall(r"\b(?:H0[^\s,;)]*|T0-current|seed.?1701|S1-profile-b)\b", content, re.IGNORECASE))),
        })
    counts = Counter(item["classification"] for item in items)
    marker_counts = Counter(marker for item in items for marker in item["markers"])
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "inventory": "tests-and-fixtures",
        "items": items,
        "summary": {
            "item_count": len(items),
            "by_classification": dict(sorted(counts.items())),
            "marker_counts": dict(sorted(marker_counts.items())),
        },
    }


_STUDY_PURPOSES = {
    "contract-complexity-20260803": "compare provider contract complexity and worker reach",
    "feature-verification-deterministic": "deterministic feature-verification evidence",
    "gemini-consistency": "Gemini response consistency and integrity evidence",
    "gemini-flash-lite-study": "Gemini Flash Lite baseline and validation study",
    "gemini-profile-ablation": "Gemini settings, thinking, prompt, and buildability ablation",
    "gemini-provider-contract-foundation": "provider contract foundation and intrinsic quality gate",
    "gemini-provider-contract-integration": "integration-only stage and real-boundary evidence",
    "gemini-provider-contract-integration-geometry-fix-validation": "historical geometry fix validation copy",
    "gemini-system-boundary-methods": "system-boundary and processing-method study",
    "geometry-slots-deterministic": "deterministic geometry-slot validation",
    "model-consistency": "historical model consistency evidence",
    "ollama-calibration": "Ollama calibration and holdout evidence",
    "ollama-only": "historical Ollama installation and verification evidence",
}

_STUDY_ORDER = {
    "gemini-flash-lite-study-01": 1,
    "gemini-profile-ablation-01": 2,
    "gemini-system-boundary-methods-01": 3,
    "gemini-provider-contract-foundation-01": 4,
    "provider-contract-correction-01": 5,
    "gemini-provider-contract-integration-01": 6,
    "narrow-fix-01": 7,
    "targeted-provider-validation-01": 8,
    "geometry-prompt-narrow-fix-01": 9,
    "printable-output-identity-correction-01": 10,
}

_SUPERSEDED_BY = {
    "gemini-flash-lite-study-01": "gemini-profile-ablation-01",
    "gemini-profile-ablation-01": "gemini-system-boundary-methods-01",
    "gemini-system-boundary-methods-01": "gemini-provider-contract-foundation-01",
    "gemini-provider-contract-foundation-01": "provider-contract-correction-01",
    "provider-contract-correction-01": "gemini-provider-contract-integration-01",
    "narrow-fix-01": "targeted-provider-validation-01",
    "targeted-provider-validation-01": "geometry-prompt-narrow-fix-01",
    "geometry-prompt-narrow-fix-01": "printable-output-identity-correction-01",
}

_STUDY_COMMITS = {
    "gemini-flash-lite-study-01": ["4f7b24e", "e0330fd"],
    "gemini-profile-ablation-01": ["3b70356", "73fe42b"],
    "gemini-system-boundary-methods-01": ["7047aac", "50df441", "5264fbd"],
    "gemini-provider-contract-foundation-01": ["33c837e", "f06694f", "c3bc0af"],
    "provider-contract-correction-01": ["c3bc0af"],
    "gemini-provider-contract-integration-01": ["bf99090", "b518eda", "a3a03fe", "1a9c583", "6bf76c9", "4f6cc7c"],
    "narrow-fix-01": ["ec2e5f3"],
    "targeted-provider-validation-01": ["9aa1843"],
    "geometry-prompt-narrow-fix-01": ["aa69c88"],
    "printable-output-identity-correction-01": ["5735f2b"],
}


def _decision_summary(record: Path) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for path in sorted(record.rglob("*decision*.json")):
        if not path.is_file():
            continue
        try:
            payload = json.loads(_read_text(path))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        values = {
            key: payload[key]
            for key in ("decision", "final_decision", "integration_status", "validation_id", "provider_calls", "worker_calls")
            if key in payload
        }
        if values:
            decisions.append({"path": _normalized(path.relative_to(record)), "values": values})
    return decisions


def _record_candidate(path: Path, collection: Path, direct_files: list[Path]) -> bool:
    relative_depth = len(path.relative_to(collection).parts)
    names = {item.name for item in direct_files}
    name = path.name
    return (
        relative_depth <= 1
        or "study.json" in names
        or "reports" in {item.name for item in path.iterdir() if item.is_dir()}
        or any(token in name for token in ("-01", "narrow-fix", "targeted-provider-validation", "geometry-prompt"))
    )


def build_study_inventory(root: Path, tracked: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    studies_root = root / "data/debug-sessions"
    tracked = tracked or _tracked_paths(root)
    source_text = _searchable_sources(root, tracked)
    if not studies_root.is_dir():
        return {"schema_version": AUDIT_SCHEMA_VERSION, "inventory": "studies", "directories": [], "records": [], "summary": {}}

    directories: list[dict[str, Any]] = [{
        "path": _normalized(studies_root.relative_to(root)),
        "collection": None,
        "depth": 0,
        "direct_file_count": 0,
        "direct_directory_count": sum(item.is_dir() for item in studies_root.iterdir()),
    }]
    records: list[dict[str, Any]] = []
    for collection in sorted(path for path in studies_root.iterdir() if path.is_dir()):
        collection_name = collection.name
        purpose = _STUDY_PURPOSES.get(collection_name, "unclassified debug-session collection")
        collection_children = list(collection.iterdir())
        directories.append({
            "path": _normalized(collection.relative_to(root)),
            "collection": collection_name,
            "depth": 1,
            "direct_file_count": sum(item.is_file() for item in collection_children),
            "direct_directory_count": sum(item.is_dir() for item in collection_children),
        })
        for path in sorted(item for item in collection.rglob("*") if item.is_dir()):
            direct_files = [item for item in path.iterdir() if item.is_file()]
            relative = _normalized(path.relative_to(root))
            directory_item = {
                "path": relative,
                "collection": collection_name,
                "depth": len(path.relative_to(studies_root).parts),
                "direct_file_count": len(direct_files),
                "direct_directory_count": sum(item.is_dir() for item in path.iterdir()),
            }
            directories.append(directory_item)
            if not _record_candidate(path, collection, direct_files):
                continue
            study_id = path.name
            file_names = [item.name.lower() for item in direct_files]
            all_files = list(path.rglob("*"))
            raw_capture_count = sum(
                1
                for item in all_files
                if item.is_file() and any(token in item.name.lower() for token in ("request", "response", "attempt", "prompt"))
            )
            record_is_derived = any(part in {"reports", "results", "analysis"} for part in path.relative_to(studies_root).parts)
            derived_report_count = sum(
                1
                for item in all_files
                if item.is_file() and (record_is_derived or any(part in {"reports", "results", "analysis"} for part in item.relative_to(path).parts))
            )
            possible_sensitive_names = [
                _normalized(item.relative_to(path))
                for item in all_files
                if item.is_file() and re.search(r"(?:\.env|secret|credential|api.?key|token)", item.name, re.IGNORECASE)
            ]
            referenced_by = _references_for(study_id, source_text)
            record = {
                "study_id": study_id,
                "path": relative,
                "collection": collection_name,
                "purpose": purpose,
                "chronological_position": _STUDY_ORDER.get(study_id),
                "status": "current_supporting" if (
                    (collection_name == "gemini-provider-contract-integration" and study_id in {"gemini-provider-contract-integration-01", "geometry-prompt-narrow-fix-01"})
                    or study_id == "printable-output-identity-correction-01"
                ) else "historical_immutable",
                "superseded_by": _SUPERSEDED_BY.get(study_id),
                "raw_capture_count": raw_capture_count,
                "derived_report_count": derived_report_count,
                "referenced_by": referenced_by,
                "commit_association": list(_STUDY_COMMITS.get(study_id, [])),
                "reproducible": any("runner" in source or "run_" in source or "geometry_prompt_narrow_fix.py" in source for source in referenced_by),
                "unique_evidence": raw_capture_count > 0 or derived_report_count > 0 or bool(file_names),
                "sensitive_filename_signals": possible_sensitive_names,
                "secret_scan": "filename-only; values were not loaded into the audit report",
                "final_decisions": _decision_summary(path),
            }
            records.append(record)

    if not any(item["study_id"] == "printable-output-identity-correction-01" for item in records):
        identity_report = studies_root / "gemini-provider-contract-integration/gemini-provider-contract-integration-01/reports/geometry-prompt-narrow-fix-01"
        if identity_report.is_dir():
            report_files = [item for item in identity_report.rglob("*") if item.is_file()]
            records.append({
                "study_id": "printable-output-identity-correction-01",
                "path": _normalized(identity_report.relative_to(root)),
                "collection": "gemini-provider-contract-integration",
                "purpose": "offline correction of the Plan-to-worker printable output identity boundary",
                "chronological_position": _STUDY_ORDER["printable-output-identity-correction-01"],
                "status": "current_supporting",
                "superseded_by": None,
                "raw_capture_count": 0,
                "derived_report_count": len(report_files),
                "referenced_by": _references_for("printable-output-identity-correction-01", source_text),
                "commit_association": ["5735f2b"],
                "reproducible": True,
                "unique_evidence": True,
                "sensitive_filename_signals": [],
                "secret_scan": "filename-only; values were not loaded into the audit report",
                "final_decisions": _decision_summary(identity_report),
            })

    records.sort(key=lambda item: (item["chronological_position"] is None, item["chronological_position"] or 999, item["path"]))
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "inventory": "studies",
        "preservation": "All data/debug-sessions files and directories are retained; this report only indexes them.",
        "directories": directories,
        "records": records,
        "summary": {
            "collection_count": len(list(studies_root.iterdir())),
            "directory_count": len(directories),
            "record_count": len(records),
            "raw_capture_count": sum(int(item["raw_capture_count"]) for item in records),
            "derived_report_count": sum(int(item["derived_report_count"]) for item in records),
            "records_with_sensitive_filename_signals": sum(bool(item["sensitive_filename_signals"]) for item in records),
        },
    }


def _code_classification(path: str) -> tuple[str, str]:
    normalized = _normalized(path)
    if normalized == "backend/scripts/audit_repository.py":
        return "current_supporting", "active deterministic repository audit command"
    if any(token in normalized for token in (
        "run_gemini_study",
        "profile_ablation",
        "system_boundary",
        "provider_contract_foundation",
        "provider_contract_correction",
        "provider_contract_narrow_fix",
        "provider_contract_targeted_validation",
        "geometry_prompt_narrow_fix",
        "buildability_phase2",
        "buildability_reanalysis",
        "audit_gemini_phase2",
    )):
        return "historical_immutable", "retained reproducibility runner for an immutable study"
    if normalized.startswith("backend/app/services/gemini_integration/"):
        return "current_supporting", "integration-only boundary or replay implementation"
    if normalized.startswith("backend/app/services/gemini_consistency/"):
        return "historical_immutable", "historical consistency and provider-study implementation"
    if normalized == "backend/app/services/documentation_audit.py":
        return "current_supporting", "offline audit library; not imported by runtime workflow"
    if normalized.startswith("backend/app/services/ai/"):
        return "current_supporting", "current provider interface or adapter implementation"
    if normalized.startswith("backend/scripts/") or normalized.startswith("scripts/"):
        return "current_supporting", "operator or reproducibility script; no deletion inferred from import absence"
    return "unknown_requires_review", "included because it is provider, study, or integration-adjacent code"


def build_script_code_inventory(root: Path, tracked: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    tracked = tracked or _tracked_paths(root)
    paths = [
        path
        for path in tracked
        if path.startswith("backend/scripts/")
        or path.startswith("scripts/")
        or path.startswith("backend/app/services/gemini_integration/")
        or path.startswith("backend/app/services/gemini_consistency/")
        or path == "backend/app/services/documentation_audit.py"
        or path.startswith("backend/app/services/ai/")
    ]
    for base in (
        root / "backend/scripts",
        root / "scripts",
        root / "backend/app/services/gemini_integration",
        root / "backend/app/services/gemini_consistency",
        root / "backend/app/services/ai",
    ):
        if not base.exists():
            continue
        paths.extend(
            _normalized(path.relative_to(root))
            for path in base.rglob("*")
            if path.is_file() and path.suffix in {".py", ".sh"}
        )
    paths = sorted(set(paths))
    sources = _searchable_sources(root, tracked)
    items: list[dict[str, Any]] = []
    for path in paths:
        file_path = root / path
        classification, reason = _code_classification(path)
        items.append({
            "path": path,
            "kind": "script" if path.startswith(("backend/scripts/", "scripts/")) else "provider_or_integration_code",
            "classification": classification,
            "reason": reason,
            "sha256": _sha256(file_path),
            "referenced_by": _references_for(path, sources),
            "safe_to_delete": False,
            "safe_to_archive": False,
            "decision": "retain",
        })
    counts = Counter(item["classification"] for item in items)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "inventory": "scripts-and-provider-integration-code",
        "items": items,
        "summary": {"item_count": len(items), "by_classification": dict(sorted(counts.items()))},
    }


def build_reference_graph(
    root: Path,
    documentation: Mapping[str, Any],
    tests: Mapping[str, Any],
    studies: Mapping[str, Any],
    scripts: Mapping[str, Any],
    tracked: list[str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    tracked = tracked or _tracked_paths(root)
    sources = _searchable_sources(root, tracked)
    candidates: list[dict[str, Any]] = []
    for item in documentation.get("items", []):
        candidates.append({"path": item["path"], "classification": item["classification"], "kind": "documentation"})
    for item in tests.get("items", []):
        candidates.append({"path": item["path"], "classification": item["classification"], "kind": item["kind"]})
    for item in scripts.get("items", []):
        candidates.append({"path": item["path"], "classification": item["classification"], "kind": item["kind"]})
    for item in studies.get("records", []):
        candidates.append({"path": item["path"], "classification": item["status"], "kind": "study_record"})

    graph: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["path"]):
        path = candidate["path"]
        refs = _references_for(PurePosixPath(path).name, sources)
        if path.startswith("docs/"):
            content = _read_text(root / path)
            refs = sorted(set(refs) | set(_extract_markdown_targets(path, content)))
        graph.append({
            **candidate,
            "referenced_by": refs,
            "references": _extract_markdown_targets(path, _read_text(root / path)) if (root / path).is_file() and path.endswith(".md") else [],
            "safe_to_delete": False,
            "safe_to_archive": candidate["classification"] == "historical_superseded" and not refs,
            "reason": "No deletion or move is authorized by absence of an import; preserve evidence and operator discoverability.",
        })
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "inventory": "reference-graph",
        "nodes": graph,
        "summary": {
            "node_count": len(graph),
            "unreferenced_nodes": sum(not item["referenced_by"] for item in graph),
            "safe_to_delete_nodes": 0,
            "safe_to_archive_nodes": sum(bool(item["safe_to_archive"]) for item in graph),
        },
    }


def build_documentation_decisions(inventory: Mapping[str, Any]) -> dict[str, Any]:
    items = list(inventory.get("items", []))
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "decisions": [
            {
                "path": item["path"],
                "classification": item["classification"],
                "action": "retain" if item["classification"] in {"current_authoritative", "current_supporting", "historical_immutable", "historical_superseded"} else "review",
                "reason": "Current documents are linked from the new entry point; historical documents remain discoverable and non-authoritative.",
            }
            for item in items
        ],
        "current_authoritative_documents": sorted(CURRENT_AUTHORITATIVE_PATHS),
        "unresolved_review_items": [item["path"] for item in items if item["classification"] == "unknown_requires_review"],
    }


def build_test_decisions(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "decisions": [
            {
                "path": item["path"],
                "classification": item["classification"],
                "old_invariant": "See the test source and historical contract terms recorded in the inventory.",
                "reason": item["reason"],
                "replacement_invariant": "Current production behavior, integration boundary, safety invariant, regression, or historical evidence integrity.",
                "replacement_test_path": item["path"],
            }
            for item in inventory.get("items", [])
        ],
        "unresolved_review_items": [],
    }


def build_result_decisions(root: Path, studies: Mapping[str, Any]) -> dict[str, Any]:
    evidence_root = root / "data/debug-sessions"
    derived: list[dict[str, Any]] = []
    if evidence_root.is_dir():
        for path in sorted(evidence_root.rglob("*")):
            if not path.is_file() or not any(part in {"reports", "results", "analysis"} for part in path.relative_to(evidence_root).parts):
                continue
            derived.append({
                "path": _normalized(path.relative_to(root)),
                "classification": "generated_reproducible",
                "sha256": _sha256(path),
                "action": "retain",
                "source_capture": "same study directory; immutable raw captures remain in place",
                "generation_command": "study-specific runner recorded in docs/STUDY_INDEX.md or the associated plan",
                "reason": "Derived evidence remains discoverable until an exact hash-equivalent replacement is documented.",
            })
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "policy": "Raw captures, attempts, hashes, provenance, and historical decisions are immutable and retained.",
        "derived_results": derived,
        "removed_derived_results": [],
        "disposable_files_removed": [],
        "unresolved_review_items": [],
        "study_record_count": len(studies.get("records", [])),
    }


def build_warning_audit(inventory: Mapping[str, Any]) -> dict[str, Any]:
    warning_items = [item for item in inventory.get("items", []) if "warning" in item.get("markers", [])]
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "observed_command": "cd backend && .venv/bin/python -m pytest -q",
        "observed_warning": {
            "category": "StarletteDeprecationWarning",
            "source": "backend/.venv/lib/python3.13/site-packages/fastapi/testclient.py:1",
            "message": "Using httpx with starlette.testclient is deprecated; install httpx2 instead.",
            "owner": "FastAPI/Starlette/httpx dependency compatibility",
            "affects_product_correctness": "not established; emitted during test-client import",
            "resolution": "Retain and monitor; revisit when the supported FastAPI/Starlette/httpx dependency set changes or httpx2 is an approved compatible dependency.",
        },
        "migration_head_check": {
            "command": "VOLUNDR_DATA_DIR=../data .venv/bin/alembic heads; .venv/bin/alembic current",
            "head": "0036_benchmark_model_metadata",
            "current": "0036_benchmark_model_metadata (head)",
            "schema_check_command": "VOLUNDR_DATA_DIR=../data .venv/bin/alembic check",
            "schema_check": "pre_existing_drift_reported",
            "owner": "migration/schema maintenance; outside this documentation audit",
            "details": "Alembic check reports nullable/index differences on existing tables; no migration was created or applied.",
        },
        "static_warning_sources": [
            {"path": item["path"], "markers": item["markers"]}
            for item in warning_items
        ],
        "owner": "dependency compatibility; pytest.warns markers are expected test assertions",
        "resolution": "Not suppressed globally. The external warning and migration-head drift are recorded with their owners and follow-up conditions above.",
    }


def build_stale_reference_report(root: Path, documentation: Mapping[str, Any], tracked: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    tracked = tracked or _tracked_paths(root)
    documents = {
        item["path"]: _read_text(root / item["path"])
        for item in documentation.get("items", [])
    }
    known_paths = [path for path in tracked if (root / path).exists()]
    known_paths.extend(_normalized(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and "data/debug-sessions" not in _normalized(path.relative_to(root)))
    known_paths.extend(documents)
    stale = find_stale_reference_violations(documents)
    broken = validate_markdown_links(documents, known_paths=known_paths)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "rules": [rule_id for rule_id, _ in _STALE_RULES] + ["multiple-current-provider-decisions"],
        "historical_exemption": "Only explicitly classified historical paths receive exemptions; no global term ignore is used.",
        "stale_reference_findings": stale,
        "broken_links": broken,
        "passed": not stale and not broken,
        "current_authoritative_documents": sorted(CURRENT_AUTHORITATIVE_PATHS),
    }


def build_summary(
    documentation: Mapping[str, Any],
    tests: Mapping[str, Any],
    studies: Mapping[str, Any],
    scripts: Mapping[str, Any],
    graph: Mapping[str, Any],
    stale: Mapping[str, Any],
) -> str:
    doc_counts = documentation.get("summary", {}).get("by_classification", {})
    test_counts = tests.get("summary", {}).get("by_classification", {})
    current = "\n".join(f"- `{path}`" for path in sorted(CURRENT_AUTHORITATIVE_PATHS))
    unresolved = [
        item["path"]
        for item in documentation.get("items", [])
        if item.get("classification") == "unknown_requires_review"
    ]
    unresolved.append("existing migration schema drift reported by alembic check")
    unresolved_items = "\n".join(f"- `{path}`" for path in unresolved) if unresolved else "- None recorded by the deterministic classifier."
    return f"""# Documentation and Evidence Audit Summary

Schema: `{AUDIT_SCHEMA_VERSION}`. The audit was designed to run offline and
does not call a provider or CAD worker.

## Current authoritative documents

{current}

## Inventory totals

- Documentation files: {documentation.get('summary', {}).get('document_count', 0)} ({json.dumps(doc_counts, sort_keys=True)})
- Test and fixture items: {tests.get('summary', {}).get('item_count', 0)} ({json.dumps(test_counts, sort_keys=True)})
- Study directories indexed: {studies.get('summary', {}).get('directory_count', 0)}
- Study records indexed: {studies.get('summary', {}).get('record_count', 0)}
- Script/provider-code items: {scripts.get('summary', {}).get('item_count', 0)}
- Reference-graph nodes: {graph.get('summary', {}).get('node_count', 0)}

## Retention and cleanup decisions

- Files retained: all inventoried documentation, tests, scripts, provider code,
  raw captures, attempts, hashes, provenance, artifacts, topology, verification,
  and historical decisions.
- Files updated: the new authoritative documents, the root README entry point,
  and links/redirect notices recorded in the audit decisions.
- Files archived: none unless a separate manifest records the path and hash.
- Files removed: none; immutable evidence and ambiguous historical items are not
  deletion candidates.
- Tests retained: all current, regression, tooling, and historical-integrity
  tests pending explicit evidence of safe consolidation.
- Tests rewritten or consolidated: none inferred from pass/fail alone.
- Unresolved review items:
{unresolved_items}

## Automated checks

- Stale-reference check passed: `{bool(stale.get('passed'))}`
- Broken documentation links: {len(stale.get('broken_links', []))}
- Stale active-document findings: {len(stale.get('stale_reference_findings', []))}
- Migration head/current: 0036_benchmark_model_metadata; the read-only schema
  check reports pre-existing nullable/index drift owned by migration maintenance.

The next development phase is representative complete workflows. Historical
provider winners and repair experiments are indexed as evidence; they do not
override the integration foundation or production routing.
"""


def build_audit_bundle(root: Path) -> dict[str, Any]:
    root = root.resolve()
    tracked = _tracked_paths(root)
    documentation = build_documentation_inventory(root, tracked)
    tests = build_test_inventory(root, tracked)
    studies = build_study_inventory(root, tracked)
    scripts = build_script_code_inventory(root, tracked)
    graph = build_reference_graph(root, documentation, tests, studies, scripts, tracked)
    documentation_decisions = build_documentation_decisions(documentation)
    test_decisions = build_test_decisions(tests)
    result_decisions = build_result_decisions(root, studies)
    warning_audit = build_warning_audit(tests)
    stale = build_stale_reference_report(root, documentation, tracked)
    return {
        "repository-documentation-inventory.json": documentation,
        "test-inventory.json": tests,
        "study-inventory.json": studies,
        "script-and-code-inventory.json": scripts,
        "reference-graph.json": graph,
        "documentation-decisions.json": documentation_decisions,
        "test-decisions.json": test_decisions,
        "result-decisions.json": result_decisions,
        "removed-files-manifest.json": {"schema_version": AUDIT_SCHEMA_VERSION, "removed_files": [], "reason": "No deletion is justified by this audit."},
        "archived-files-manifest.json": {"schema_version": AUDIT_SCHEMA_VERSION, "archived_files": [], "reason": "No move is justified without a migration manifest and hash verification."},
        "warning-audit.json": warning_audit,
        "stale-reference-check.json": stale,
        "documentation-audit-summary.md": build_summary(documentation, tests, studies, scripts, graph, stale),
    }


def write_audit_bundle(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "docs/audit").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_audit_bundle(root)
    for filename, payload in bundle.items():
        target = output_dir / filename
        if filename.endswith(".md"):
            target.write_text(str(payload), encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "CURRENT_AUTHORITATIVE_PATHS",
    "HISTORICAL_IMMUTABLE_PATHS",
    "build_audit_bundle",
    "build_documentation_inventory",
    "build_script_code_inventory",
    "build_study_inventory",
    "build_test_inventory",
    "classify_document",
    "find_stale_reference_violations",
    "validate_markdown_links",
    "write_audit_bundle",
]
