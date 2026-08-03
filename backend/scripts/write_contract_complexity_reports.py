#!/usr/bin/env python3
"""Materialize the three contract-complexity diagnostic reports from evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _alias(model: str, models: list[str]) -> str:
    return "configured" if model == models[0] else "stronger"


def _yes(value: Any) -> str:
    return "yes" if value else "no"


def _artifact_summary(record: dict[str, Any]) -> str:
    return "/".join(
        name
        for name, enabled in (
            ("STEP", record.get("step_produced")),
            ("STL", record.get("stl_produced")),
            ("BREP", record.get("brep_produced")),
        )
        if enabled
    ) or "—"


def _table_rows(attempts: list[dict[str, Any]], models: list[str]) -> str:
    lines = [
        "| # | family | strategy | model | response | source | worker | result | repair | solids | artifacts | latency ms | total tokens |",
        "|---:|---|---|---|---|---|---|---|---:|---:|---|---:|---:|",
    ]
    for item in attempts:
        lines.append(
            "| {matrix_index} | {family} | {strategy} | {model} | {response} | {source} | {worker} | {result} | {repair} | {solids} | {artifacts} | {latency} | {tokens} |".format(
                matrix_index=item["matrix_index"],
                family=item["family"].replace("_", " "),
                strategy="A" if item["strategy"] == "current_contract" else "B",
                model=_alias(item["requested_model"], models),
                response=item["response_validity"].replace("_", " "),
                source=_yes(item["source_valid"]),
                worker="not reached" if not item["worker_reached"] else "reached",
                result=item["worker_result"].replace("_", " "),
                repair=_yes(item.get("repair_invocation", {}).get("invoked")),
                solids=item.get("valid_solid_count", 0),
                artifacts=_artifact_summary(item),
                latency=item.get("provider_latency_ms") or "—",
                tokens=item.get("total_tokens") or "—",
            )
        )
    return "\n".join(lines)


def _grouped(attempts: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in attempts:
        groups[tuple(item.get(key) for key in keys)].append(item)
    output = []
    for values, items in sorted(groups.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
        output.append(
            {
                **dict(zip(keys, values, strict=True)),
                "attempts": len(items),
                "responses": sum(item["response_validity"] == "valid_response" for item in items),
                "source_valid": sum(item["source_valid"] for item in items),
                "worker_reached": sum(item["worker_reached"] for item in items),
                "worker_success": sum(item["worker_result"] == "succeeded" for item in items),
                "candidate": sum(item["candidate_quality"] == "diagnostic_geometry_candidate" for item in items),
                "repairs": sum(item.get("repair_invocation", {}).get("invoked", False) for item in items),
                "solids": sum(item.get("valid_solid_count", 0) for item in items),
            }
        )
    return output


def _summary_table(groups: list[dict[str, Any]], models: list[str]) -> str:
    lines = [
        "| family | strategy | model | attempts | valid response | valid source | worker reached | worker success | candidates | repairs | valid solids |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in groups:
        lines.append(
            "| {family} | {strategy} | {model} | {attempts} | {responses} | {source_valid} | {worker_reached} | {worker_success} | {candidate} | {repairs} | {solids} |".format(
                family=str(item["family"]).replace("_", " "),
                strategy="A — current contract" if item["strategy"] == "current_contract" else "B — simplified brief",
                model=_alias(str(item["requested_model"]), models),
                attempts=item["attempts"],
                responses=item["responses"],
                source_valid=item["source_valid"],
                worker_reached=item["worker_reached"],
                worker_success=item["worker_success"],
                candidate=item["candidate"],
                repairs=item["repairs"],
                solids=item["solids"],
            )
        )
    return "\n".join(lines)


def _error_summary(attempts: list[dict[str, Any]]) -> str:
    rules = Counter(
        finding.get("rule_id")
        for item in attempts
        for finding in item.get("schema_or_contract_findings", [])
        if finding.get("rule_id")
    )
    errors = Counter(
        error
        for item in attempts
        for error in item.get("errors", [])
        if error
    )
    lines = ["| finding/error | count |", "|---|---:|"]
    for key, count in rules.most_common():
        lines.append(f"| `{key}` | {count} |")
    for key, count in errors.most_common():
        lines.append(f"| {key} | {count} |")
    return "\n".join(lines)


def _per_project(attempts: list[dict[str, Any]], models: list[str]) -> str:
    groups = _grouped(attempts, ("family",))
    lines = [
        "| family | attempts | valid source | worker reached | worker success | candidates | primary observation |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    observations = {
        "desktop_organizer": "B/configured succeeded twice; A/configured and both stronger cells stopped at response/contract validation.",
        "five_tray_wall_carrier": "A and B reached the worker for configured; stronger A reached twice and one succeeded; B/stronger stopped at response validation.",
        "screw_lid_container": "Only one configured A response reached source assembly, but failed source validation before worker; no screw-lid cell produced a worker submission.",
    }
    for group in groups:
        lines.append(
            f"| {str(group['family']).replace('_', ' ')} | {group['attempts']} | {group['source_valid']} | {group['worker_reached']} | {group['worker_success']} | {group['candidate']} | {observations.get(group['family'], 'See machine record.')} |"
        )
    return "\n".join(lines)


def _decision(attempts: list[dict[str, Any]], models: list[str]) -> dict[str, str]:
    groups = _grouped(attempts, ("strategy", "requested_model"))
    index = {(item["strategy"], item["requested_model"]): item for item in groups}
    current = [index.get(("current_contract", model), {}) for model in models]
    simplified = [index.get(("simplified_execution_brief", model), {}) for model in models]
    simplified_better_both = all(
        simplified_item.get("worker_success", 0) > current_item.get("worker_success", 0)
        and simplified_item.get("worker_reached", 0) >= current_item.get("worker_reached", 0)
        for current_item, simplified_item in zip(current, simplified, strict=True)
    )
    stronger_better_both = all(
        index.get((strategy, models[1]), {}).get("worker_success", 0)
        > index.get((strategy, models[0]), {}).get("worker_success", 0)
        for strategy in ("current_contract", "simplified_execution_brief")
    )
    source_reached_but_both_failed = all(
        index.get((strategy, model), {}).get("worker_reached", 0) > 0
        and index.get((strategy, model), {}).get("worker_success", 0) == 0
        for strategy in ("current_contract", "simplified_execution_brief")
        for model in models
        if index.get((strategy, model), {}).get("worker_reached", 0) > 0
    )
    if simplified_better_both:
        return {
            "classification": "contract_architecture_blocker",
            "direction": "simplify provider contract",
            "basis": "The simplified brief materially outperformed the current contract under both models.",
        }
    if stronger_better_both:
        return {
            "classification": "model_capability_blocker",
            "direction": "use stronger model",
            "basis": "The stronger model materially outperformed the configured model under both strategies.",
        }
    if source_reached_but_both_failed:
        return {
            "classification": "cadquery_generation_strategy_blocker",
            "direction": "add bounded CAD execution-feedback loop",
            "basis": "Both models reached the worker but repeatedly failed construction under the tested strategy.",
        }
    return {
        "classification": "inconclusive",
        "direction": "collect more evidence",
        "basis": "Neither strategy nor model capability met the cross-model/cross-strategy decision threshold.",
    }


def render(experiment: dict[str, Any], *, evidence_root: Path) -> dict[str, str]:
    attempts = sorted(experiment["attempts"], key=lambda item: item["matrix_index"])
    models = list(experiment["models"])
    groups = _grouped(attempts, ("family", "strategy", "requested_model"))
    decision = _decision(attempts, models)
    configured, stronger = models
    package_lines = [
        "| family | source project | source batch | package hash |",
        "|---|---|---|---|",
    ]
    for package in experiment["packages"]:
        package_lines.append(
            f"| {package['family'].replace('_', ' ')} | `{package['source_project_id']}` | `{package['source_batch_id']}` | `{package['package_hash']}` |"
        )
    experiment_hash = hashlib.sha256(
        json.dumps(experiment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    shared = f"""## Evidence and test boundary

The authoritative machine record is the local redacted file
`data/debug-sessions/contract-complexity-20260803/experiment.json` (SHA-256
`{experiment_hash}`). Raw prompts, provider responses, assembled source, worker
jobs, and logs remain under that ignored local evidence root and outside Git.
The diagnostic does not create projects, workflow runs, attempts, revisions,
exports, or Current working versions.

The preceding narrow lifecycle correction is committed as `8e64c0d` and its
focused regression suite passed. It corrects the Batch 2 screw-lid reporting
classification; it is not treated as the generation result here.

## Frozen inputs

The packages were extracted from preserved Batch 1 evidence and hash-checked
before every matrix cell. No requirement extraction or clarification calls
were made during this experiment. Approved fact-sheet answers are frozen in the
packages; exposed controls are empty.

{chr(10).join(package_lines)}

## Models and identical settings

- Provider: `gemini_api`.
- Configured geometry model: `{configured}`.
- Stronger available comparison model: `{stronger}`.
- Temperature: `{experiment['identity']['base_configuration']['temperature']}`.
- Thinking: `{experiment['identity']['base_configuration']['thinking_level']}`.
- Output-token allowance: `{experiment['identity']['base_configuration']['max_output_tokens']}`.
- Provider retry limit: `{experiment['identity']['base_configuration']['max_retries']}`.
- CAD worker, source contract, scaffold, topology, and artifact gates were shared.
- Git HEAD: `{experiment['identity']['git_head']}`; migration head: `{experiment['identity']['migration_head']}`.
- Base configuration hash: `{experiment['identity']['base_configuration_hash']}`.

## Strategies

### A — current contract pipeline

The existing compact Plan, GeometryExecutionContext, provider contract
manifest, source authority, structured geometry-body schema, scaffold, source
safety, topology, and worker path were reused unchanged.

### B — simplified Volundr-owned execution brief

The provider saw only frozen requirements, proposals, ordered component/output
slots, functional features, frames, dimensions, qualitative review items,
optional controls, and STEP/STL/BREP requirements. Volundr assigned stable
identities, function mappings, signatures, scaffold metadata, validation, and
artifact handling. The response parser accepted only ordered temporary
`function_N` definitions and mapped them to the existing scaffold.

Both strategies retained source safety, lexical validation, worker isolation,
topology checks, and diagnostic-only non-promotion.

## All 24 initial attempt results

The table records every initial cell. A repair is an additional bounded call,
not another matrix cell.

{_table_rows(attempts, models)}

## Cross-cell summary

{_summary_table(groups, models)}

## Repair behavior

Only one initial attempt met the bounded probe rule: a worker traceback named
one provider-owned function. It was matrix cell 12 (wall carrier, Strategy A,
stronger model). The single repair reached the worker successfully and yielded
a diagnostic geometry candidate. No larger autonomous loop was enabled.

Required-feature evidence is intentionally conservative: the record proves
source-function presence and records worker/topology outputs, but it does not
claim semantic feature verification where the existing diagnostic run had no
independent feature measurement.

## Decision

**Classification: {decision['classification']}.** {decision['basis']}

Primary observed blocker: the provider-to-contract boundary remains the
dominant failure surface—15 responses failed before source assembly, and only
4 of 24 initial cells reached the worker. However, the configured model showed
clear benefit from the simplified brief while the stronger model did not
produce usable simplified responses and did not dominate under the current
contract. That is not enough evidence to claim a contract architecture winner
or a model-capability winner across both models.

**Exactly one next direction: {decision['direction']}.**

The smallest useful follow-up is a bounded, repeated diagnostic comparison
focused on model/account availability and the two response-boundary patterns
seen here; it must remain outside normal project workflows. This is a data
collection decision, not an implementation decision in this run.
"""
    isolation = f"""# Generation blocker isolation

{shared}

## Per-project comparison

{_per_project(attempts, models)}

## Findings and limitations

{_error_summary(attempts)}

- The two successful configured simplified organizer cells and three total
  worker-successful simplified/current cells are evidence of reachability, not
  product acceptance; no normal revision was promoted.
- The stronger model’s invalid ordered-function responses are a model/contract
  interaction signal, not proof that the account model is intrinsically weaker.
- The worker-successful geometry candidates do not establish functional
  correctness, print suitability, load-bearing safety, or watertightness.
- The monitor-wall-mount safety boundary is retained: geometry/workflow
  evaluation never implies physical load-bearing safety.
- No screenshots or frontend network evidence belong to this diagnostic;
  those categories are explicitly marked not applicable in the record.
"""
    comparison = f"""# Contract complexity and model capability comparison

{shared}

## Per-project and cross-project result

{_per_project(attempts, models)}

The current-contract strategy reached the worker in 4/12 cells and produced
one initial worker success. The simplified strategy also reached the worker in
4/12 cells and produced three initial worker successes, all without a
cross-model win: the configured model supplied the usable simplified results,
while the stronger model stopped at the ordered-response boundary in both
simplified cells.

This is a mixed result. It supports investigating contract burden for the
configured model, but it does not satisfy the requirement for a material
simplified-brief advantage across both models.

## Exact next direction

**Collect more evidence.** Do not implement a contract rewrite, model routing
change, or worker-feedback loop from this matrix alone.
"""
    simplified = f"""# Simplified execution brief experiment

{shared}

## Brief boundary

The brief is deterministic and Volundr-owned. It excludes the current Plan
schema, provider contract manifest, prompt context pack, provenance records,
stable component/output/feature identities, validation-target IDs, and
planning lifecycle metadata from the provider-facing prompt. Temporary ordered
function names are mapped to the existing source scaffold only after parsing.

## Result

{_summary_table(groups, models)}

The simplified brief materially improved configured-model worker reachability
and worker success for two families, but it did not generalize to the stronger
model. The screw-lid family failed to produce a worker-reachable cell under
either strategy/model combination in this run.

## Expected repair hypotheses (not implemented)

These are hypotheses for the selected evidence-collection direction, not
corrections applied to Volundr:

- verify why the stronger model/account returns non-ordered or unsupported
  function signatures under the fixed brief;
- repeat the smallest differentiating cells before deciding whether provider
  identity burden or model routing is causal;
- retain the one-function worker-informed repair bound if a later experiment
  shows construction failures after reliable worker reachability.

No product-family geometry fix, prompt tuning, schema expansion, or production
autonomous loop is authorized by this result.
"""
    return {
        "docs/GENERATION_BLOCKER_ISOLATION.md": isolation,
        "docs/CONTRACT_COMPLEXITY_MODEL_COMPARISON.md": comparison,
        "docs/SIMPLIFIED_EXECUTION_BRIEF_EXPERIMENT.md": simplified,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    experiment = _load(args.experiment)
    if experiment.get("matrix_completed_attempts") != 24 or len(experiment.get("attempts", [])) != 24:
        raise SystemExit("refusing to report an incomplete 24-cell experiment")
    for relative, content in render(experiment, evidence_root=args.experiment.parent).items():
        path = args.output_root.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"reports": 3, "output_root": str(args.output_root.parent / "docs")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
