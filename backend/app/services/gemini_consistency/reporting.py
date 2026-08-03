from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.gemini_benchmark import (
    GeminiBenchmarkExperiment,
    GeminiBenchmarkMembership,
    GeminiBenchmarkModel,
    GeminiBenchmarkRun,
)
from app.services.gemini_consistency.comparison import compare_evidence, controlled_comparison, failure_signature
from app.services.workflow.redaction import RedactionService


def _markdown_table(rows: list[tuple[str, str]]) -> str:
    lines = ["| Item | Value |", "| --- | --- |"]
    lines.extend(f"| {name} | {value.replace('|', '\\|')} |" for name, value in rows)
    return "\n".join(lines)


def _identity(experiment: dict[str, Any]) -> dict[str, Any]:
    return {
        "git_head": experiment.get("git_head"),
        "migration_head": experiment.get("migration_head"),
        "provider": experiment.get("provider"),
        "model_policy": experiment.get("model_policy") or experiment.get("model_settings"),
        "prompt_versions": experiment.get("prompt_versions"),
        "configuration_hash": experiment.get("configuration_hash"),
        "build_identities": experiment.get("build_identities"),
    }


def _write_safe(path: Path, value: Any) -> None:
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=path.parent, evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_text_safe(path: Path, value: str) -> None:
    redactor = RedactionService()
    safe, _ = redactor.normalize_evidence_text(value, data_root=path.parent, evidence_root=path.parent)
    redactor.assert_text_redacted(safe)
    path.write_text(safe, encoding="utf-8")


def build_experiment_reports(
    experiment: dict[str, Any], records: list[dict[str, Any]], output_root: Path
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_label = "historical_noncontrolled_reference" if experiment.get("mode") != "five_case" else "formal_five_case_candidate"
    grouped: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    integrity_findings: list[dict[str, Any]] = []
    resource_profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identity = _identity(experiment)
    for record in records:
        model = str(record.get("model") or "unknown")
        provider = record.get("provider")
        model_label = f"{provider}/{model}" if provider else model
        case_id = str(record.get("case_id") or "unknown")
        run_index = int(record.get("run_index") or 0)
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            integrity_findings.append({"kind": "missing_evidence", "model": model_label, "case_id": case_id, "run_index": run_index})
            evidence = {"integrity_finding": "missing_evidence", "outcome_category": "missing_artifacts"}
        nested_metrics = evidence.get("metrics") if isinstance(evidence, dict) else None
        if isinstance(nested_metrics, dict):
            for finding in nested_metrics.get("integrity_findings", []):
                if isinstance(finding, dict):
                    integrity_findings.append({
                        **finding,
                        "model": model_label,
                        "case_id": case_id,
                        "run_index": run_index,
                    })
        grouped[(model_label, case_id)][run_index] = {**record, "model": model_label, "evidence": evidence}
        resource_profile = record.get("resource_profile")
        if isinstance(resource_profile, dict):
            resource_profiles[model_label].append(resource_profile)

    pair_comparisons: list[dict[str, Any]] = []
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    controlled: dict[str, dict[str, Any]] = {}
    for (model, case_id), runs in sorted(grouped.items()):
        first = runs.get(1, {"evidence": None})
        second = runs.get(2, {"evidence": None})
        first_evidence = first.get("evidence") or {"outcome_category": "missing_artifacts"}
        second_evidence = second.get("evidence") or {"outcome_category": "missing_artifacts"}
        comparison = compare_evidence(first_evidence, second_evidence)
        item = {"model": model, "case_id": case_id, "comparison": comparison}
        pair_comparisons.append(item)
        by_model[model].append(item)
        first_identity = first.get("identity") or identity
        second_identity = second.get("identity") or identity
        if model not in controlled:
            controlled[model] = controlled_comparison(first_identity or {}, second_identity or {}).__dict__

    for model in by_model:
        if not controlled.get(model):
            controlled[model] = controlled_comparison(identity, identity).__dict__
    signatures: dict[str, int] = defaultdict(int)
    for item in pair_comparisons:
        for signature in (
            item["comparison"]["failure_signatures"].get("first"),
            item["comparison"]["failure_signatures"].get("second"),
        ):
            if signature:
                signatures[signature] += 1

    model_summaries = {
        model: {
            "paired_case_count": len(items),
            "mean_consistency_score": round(
                sum(float(item["comparison"]["overall_score"]) for item in items) / len(items),
                4,
            ) if items else 0.0,
            "failure_signature_count": sum(
                1 for item in items if any(item["comparison"]["failure_signatures"].values())
            ),
            "resource_profiles": resource_profiles.get(model, []),
        }
        for model, items in sorted(by_model.items())
    }

    _write_safe(output_root / "comparison.json", {
        "evidence_label": evidence_label,
        "pairs": pair_comparisons,
        "controlled_comparisons": controlled,
    })
    _write_safe(output_root / "cross-model-comparison.json", {
        "basis": [
            "verified_requirement_satisfaction",
            "valid_geometry",
            "topology",
            "paired_consistency",
            "source_contract_compliance",
            "artifact_completeness",
            "repair_success",
            "candidate_outcome",
        ],
        "models": model_summaries,
    })
    _write_safe(output_root / "resource-profile.json", {"models": resource_profiles})
    _write_safe(output_root / "integrity-report.json", {"schema_version": "gemini-consistency-integrity-v1", "findings": integrity_findings})
    _write_safe(output_root / "failure-signatures.json", dict(signatures))
    _write_text_safe(
        output_root / ("pilot-summary.md" if experiment.get("mode") == "pilot" else "benchmark-summary.md"),
        "# Gemini consistency benchmark\n\n"
        + _markdown_table(
            [
                ("Experiment", str(experiment.get("id"))),
                ("Mode", str(experiment.get("mode"))),
                ("Evidence label", evidence_label),
                ("Paired cases", str(len(pair_comparisons))),
                ("Integrity findings", str(len(integrity_findings))),
            ]
        )
        + "\n",
    )
    _write_text_safe(
        output_root / "model-comparison.md",
        "# Model comparison\n\n" + "\n".join(
            f"- `{model}`: {len(items)} paired case comparisons; mean consistency {model_summaries[model]['mean_consistency_score']:.3f}"
            for model, items in sorted(by_model.items())
        ) + "\n",
    )
    _write_text_safe(
        output_root / "run-consistency.md",
        "# Run consistency\n\n" + "\n".join(
            f"- `{item['model']}` / `{item['case_id']}`: {item['comparison']['overall_score']:.3f}"
            for item in pair_comparisons
        ) + "\n",
    )
    _write_text_safe(
        output_root / "failure-signatures.md",
        "# Failure signatures\n\n" + ("\n".join(f"- `{key}`: {value}" for key, value in sorted(signatures.items())) or "No normalized failure signatures recorded.") + "\n",
    )
    _write_text_safe(
        output_root / "codex-review.md",
        "# Codex review instruction\n\n"
        "Review each generated project individually using the evidence under this experiment. "
        "Do not implement corrections during this review. Record repeated cross-product defects, "
        "same-family defects, provider variability, isolated anomalies, and integrity or misleading-state defects.\n",
    )
    return {
        "experiment_id": experiment.get("id"),
        "evidence_label": evidence_label,
        "pair_count": len(pair_comparisons),
        "controlled_comparisons": controlled,
        "integrity_findings": integrity_findings,
        "failure_signatures": dict(signatures),
        "model_summaries": model_summaries,
        "report_root": str(output_root),
    }


class GeminiConsistencyReportingService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    def generate(self, experiment_id: str) -> dict[str, Any]:
        experiment_row = self.db.get(GeminiBenchmarkExperiment, experiment_id)
        if experiment_row is None:
            raise LookupError("benchmark experiment not found")
        experiment = {
            "id": experiment_row.id,
            "mode": experiment_row.mode,
            "git_head": experiment_row.git_head,
            "migration_head": experiment_row.migration_head,
            "provider": experiment_row.provider,
            "prompt_versions": json.loads(experiment_row.prompt_versions_json),
            "configuration_hash": experiment_row.configuration_hash,
            "build_identities": json.loads(experiment_row.build_identities_json),
            "model_settings": json.loads(experiment_row.model_settings_json),
        }
        records: list[dict[str, Any]] = []
        memberships = self.db.scalars(
            select(GeminiBenchmarkMembership)
            .join(GeminiBenchmarkRun)
            .join(GeminiBenchmarkModel)
            .where(GeminiBenchmarkRun.experiment_id == experiment_id)
            .order_by(GeminiBenchmarkModel.position, GeminiBenchmarkRun.run_index, GeminiBenchmarkMembership.position)
        ).all()
        for membership in memberships:
            run = self.db.get(GeminiBenchmarkRun, membership.run_id)
            model = self.db.get(GeminiBenchmarkModel, run.model_config_id) if run else None
            evidence = None
            if membership.evidence_path:
                evidence_file = self.data_dir / membership.evidence_path
                if evidence_file.is_file():
                    try:
                        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        evidence = None
            records.append({
                "case_id": membership.corpus_case_id,
                "provider": model.provider if model else None,
                "model": model.requested_model if model else "unknown",
                "resource_profile": json.loads(model.resource_profile_json) if model and model.resource_profile_json else {},
                "run_index": run.run_index if run else 0,
                "identity": json.loads(run.identity_json) if run and run.identity_json else None,
                "evidence": evidence,
            })
        return build_experiment_reports(
            experiment,
            records,
            self.data_dir / experiment_row.report_root,
        )
