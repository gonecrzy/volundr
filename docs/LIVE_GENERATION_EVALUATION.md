# Live Generation Evaluation

This document defines Volundr's controlled live generation-quality evaluation harness. It is for measuring model quality and directing roadmap decisions; it does not promote prompts automatically.

## Purpose

The harness answers which area most limits successful generated products:

- prompt quality
- Design Plan quality
- component decomposition
- parameter modeling
- geometry generation
- printability
- revision preservation
- UX

It complements deterministic benchmark fixtures. Deterministic tests prove the pipeline is wired correctly; live evaluations measure whether Gemini produces useful functional products.

## Runner

Run from the repository root:

```bash
cd backend
PYTHONPATH=. python3 scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/core.json \
  --output-dir ../output/live-benchmarks \
  --run-label first-controlled-core \
  --provider dry-run \
  --max-runs 10
```

Dry-run mode is the default and never calls Gemini. A live Gemini run requires both:

```bash
--provider gemini --allow-live
```

This explicit opt-in prevents accidental quota spend during routine testing.

## Quota Controls

Every run validates:

- selected benchmark count
- runs per case
- total run cap
- estimated prompt-token cap
- live-provider opt-in
- optional estimated cost cap when the caller supplies a token price

The runner fails before any provider call when a quota limit is exceeded.
Volundr does not hardcode Gemini pricing in the harness. Use `--cost-per-1k-tokens-usd` and `--max-estimated-cost-usd` when a controlled run needs a cost ceiling.

## Run Directory

Each run writes an ignored artifact directory:

```text
output/live-benchmarks/<run-id>/
├── run-manifest.json
├── aggregate-metrics.json
├── prompt-version-comparison.json
├── artifacts/
│   └── <benchmark-id>/run-001/
│       ├── benchmark-input.json
│       ├── requirements-prompt.txt
│       └── requirements-raw-output.txt
├── case-reports/
│   └── <benchmark-id>-run-001.md
└── human-scoring/
    └── <benchmark-id>-run-001.json
```

Provider raw output files exist only for live provider runs. Dry runs still collect benchmark inputs, rendered prompts, manifests, reports, and scoring forms.

## Run Manifest

`run-manifest.json` uses schema `live-benchmark-run-v1` and records:

- harness version
- suite name and path
- selected benchmark IDs
- provider mode and non-secret provider settings
- prompt-template versions
- Gemini ruleset version
- quota controls
- per-case artifact paths
- failure class
- prompt hashes
- `no_automatic_prompt_promotion: true`

The manifest is the primary reproducibility record for a controlled run.

## Prompt-Version Comparison

`prompt-version-comparison.json` compares the current prompt versions with an optional baseline manifest:

```bash
--baseline-manifest output/live-benchmarks/<old-run>/run-manifest.json
```

The comparison is report-only. It records changed, unchanged, new, and removed prompt versions, but promotion remains manual.

## Human Scoring

Each case run gets a JSON scoring form with one score bucket per roadmap decision area:

- prompt quality
- Design Plan quality
- component decomposition
- parameter modeling
- geometry generation
- printability
- revision preservation
- UX

Scores use:

```text
0 = not evaluated
1 = failed or misleading
2 = usable only with major correction
3 = partially successful
4 = good with minor issues
5 = ready quality for this benchmark
```

Reviewers should cite artifact paths in `evidence_paths` and list the recommended next work buckets. Aggregated scoring can then show whether failures cluster around prompting, planning, geometry, validation, or workflow.

## Metrics

`aggregate-metrics.json` currently records:

- total case runs
- status counts
- failure-class counts
- estimated prompt tokens
- live-provider enabled flag
- next-work buckets initialized for human scoring
- no-promotion flag

Future evaluators may aggregate completed human scoring forms into the same next-work buckets, but prompt promotion must still remain a separate manual decision.

## First Controlled Set

The first controlled run should use the core suite, one run per case, and dry-run mode. This verifies benchmark selection, prompt snapshot collection, run manifests, reports, and scoring forms before spending Gemini quota.

After the dry-run artifacts are reviewed, a small live run can be launched with one or two representative core benchmarks. Full-suite repeated live runs should wait until the scoring workflow is exercised on a small set.

## Limits

This harness does not yet execute the complete browser-visible staged workflow end to end. The current live provider mode collects requirement-extraction provider output and the surrounding prompt/version artifacts. Full live product-generation scoring should extend the same manifest format rather than replace it.

The harness is intentionally unable to accept candidates, update active revisions, or promote prompt versions.
