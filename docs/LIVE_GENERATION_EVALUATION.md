# Live Generation Evaluation

This document defines Volundr's controlled live generation-quality evaluation harness. It is for measuring model quality and directing roadmap decisions; it does not promote prompts automatically.

`docs/CADQUERY_BACKEND.md` supersedes older provider and backend assumptions. Dry-run remains the default. Live CadQuery transition benchmarks should use Gemini API only after deterministic execution and fake-provider lifecycle tests are reliable.

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

It complements deterministic benchmark fixtures. Deterministic tests prove the pipeline is wired correctly; live evaluations measure whether the selected provider produces useful functional products.

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

Dry-run mode is the default and never calls a model. Ollama remains available for local provider-adapter comparison:

```bash
PYTHONPATH=. python3 scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/core.json \
  --output-dir ../output/live-benchmarks \
  --run-label ollama-core \
  --provider ollama \
  --max-runs 10
```

Current local comparison model:

```bash
VOLUNDR_OLLAMA_MODEL=qwen2.5-coder:14b
```

For thinking-capable local models, set `VOLUNDR_OLLAMA_THINK=false` when the benchmark should measure final answers only. Ollama separates reasoning into a `thinking` field when thinking is enabled, but long thinking traces can consume the timeout before a useful final response is produced.

For phase checks where reproducibility matters, set it explicitly:

```bash
VOLUNDR_OLLAMA_MODEL=qwen2.5-coder:14b \
PYTHONPATH=. python3 scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/core.json \
  --output-dir ../output/live-benchmarks \
  --run-label ollama-core \
  --provider ollama \
  --max-runs 10
```

Ollama uses the configured `VOLUNDR_OLLAMA_BASE_URL` and `VOLUNDR_OLLAMA_MODEL` and does not require `--allow-live` because it has no external quota cost. Live Gemini runs require `--allow-live` because they can spend external quota. Use `gemini` for the Gemini CLI transport and `gemini-api` for the direct Gemini API-key transport:

```bash
--provider gemini --allow-live
--provider gemini-api --allow-live
```

Direct Gemini API source-generation runs should use `VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite` by default for this phase-validation path. Keep `VOLUNDR_GEMINI_API_THINKING_LEVEL` explicit as `minimal` unless a run is intentionally measuring deeper reasoning; Gemini thinking models can otherwise spend the response budget on reasoning text and fail to return a complete fenced source block.

This explicit opt-in prevents accidental quota spend during routine testing.

## Phase-Validation Runs

Use `--phase-validation` between implementation phases when the goal is a quick before/after signal rather than a full benchmark pass:

```bash
PYTHONPATH=. python3 scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/core.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase-1-baseline \
  --phase-validation \
  --source-brief \
  --source-probe \
  --source-probe-repair \
  --provider ollama \
  --max-runs 3
```

The flag selects exactly three scenarios:

- `creative_fish_shelf_bracket`
- `honeycomb_angle_bracket`
- `threaded_control_knob`

Do not treat the phase run as a complete acceptance test. It is a smoke signal for whether the AI and pipeline are moving in the right direction on functional geometry, requested styling, subtractive CAD patterns, parameterization, and curated-library pressure.

`--source-probe` adds a lightweight direct CAD-source generation probe. The
probe prompt includes the benchmark's expected parameter IDs as top-level
control targets while explicitly keeping creative form open. CadQuery is the
product source language. CadQuery probes extract `source-extracted.py`, validate
it against the restricted `cadquery-v1` AST contract, execute the generated
source, and export STEP/STL artifacts when CadQuery is installed in the
benchmark environment. The analysis reports extracted editable parameter IDs and
exact expected-parameter coverage.

The `cadquery-v1` contract is intentionally narrower than unrestricted Python:
only `import cadquery as cq` and the Volundr runtime import are allowed,
module-level parameter/output metadata must be AST-visible, top-level CadQuery
execution is rejected, and unsafe/dynamic calls such as file access, `eval`,
`exec`, `getattr`, `globals`, and `locals` are rejected before worker execution.
This is defense in depth; real execution still happens in the isolated worker.

The `cadquery-generation-v1` prompt keeps the same `cadquery-v1` execution contract and includes the stronger generation guidance from earlier source-probe failures: do not use `math`, `map()`, or string parsing; expose `thread_spec` as a numeric millimeter diameter; extrude only closed profiles; and prefer fused single-profile creative bracket geometry over loose decorative solids.

`--source-brief` requires `--source-probe`. It adds a JSON-only `source-brief-v1` stage before CAD source generation. The brief captures intended object type, functional goal, style goal, planned outputs, expected connected body count, functional features, style attachment rules, hard requirements, and open questions. The parsed brief is then injected into the source prompt as compact structured context.

When extraction succeeds, the probe compiles the source with the selected source-language runner and records STL/mesh validation artifacts. This is a syntax and mesh smoke check, not candidate acceptance and not a substitute for human visual review.

`--source-probe-repair` requires `--source-probe`. When the first source-probe
extraction or execution fails, the harness sends one repair prompt using the raw
or extracted failed source plus extraction/runtime diagnostics. The CadQuery
repair path returns `.py`. When `--source-brief` is also enabled and the source
executes but mesh metadata reports more connected components than the parsed
brief expects, the same bounded repair path runs with disconnected-mesh
diagnostics. The harness stores separate `source-repair-*` prompt, raw output,
extracted source, parameter analysis, execution logs, STEP/STL, and mesh
metadata artifacts. Repair metrics are separate from first-pass source-probe
metrics so raw model quality and repair recovery can be compared directly.

`--design-plan-probe` adds a staged Design Plan provider call after requirements
collection. It stores `design-plan-prompt.txt`, `design-plan-raw-output.txt`,
`design-plan-parsed.json`, and `design-plan-analysis.json`. The analysis compares
the parsed plan with fixture expectations for components, features, printable
outputs, and dependency edges. This scores planning quality separately from
source validity; it does not approve a plan, accept a candidate, or exercise the
browser workflow.

`--configuration-probe` requires `--source-probe`. After a source probe succeeds
or repair succeeds, the harness reruns the generated CadQuery source with the
fixture's `expected_configuration.requested_overrides`, then runs the existing
printability inspector against the configured output STL. The probe records
`configuration-printability-report.json`, blocking `Critical` rule IDs, and
whether the expected blocking rule, such as `profile.build_volume`, was observed.
This measures deterministic provider-free configuration validation; it does not
call the provider again.

## Quota Controls

Every run validates:

- selected benchmark count
- runs per case
- total run cap
- estimated prompt-token cap
- live-provider opt-in for Gemini
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
│       ├── requirements-raw-output.txt
│       ├── source-prompt.txt
│       ├── source-raw-output.txt
│       ├── source-extracted.py
│       ├── source-parameter-analysis.json
│       ├── design-plan-prompt.txt
│       ├── design-plan-raw-output.txt
│       ├── design-plan-parsed.json
│       ├── design-plan-analysis.json
│       ├── configuration-printability-report.json
│       └── source-compile-workspace/
│           └── source-probe/
│               ├── source.py
│               ├── model.step
│               ├── model.stl
│               ├── metadata.json
│               ├── stdout.log
│               └── stderr.log
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
- ruleset version
- quota controls
- whether the run used the phase-validation scenario set
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
- source-probe extraction and compile status counts
- average expected-parameter coverage from extracted source
- count of compiled source probes with watertight and nonzero-volume meshes
- count of compiled source probes with disconnected meshes and the maximum connected-component count
- total runtime warning/deprecation lines from source-probe execution logs
- Design Plan probe status counts
- average expected Design Plan component, feature, output, and dependency coverage
- configuration-probe status counts
- count of configuration probes where the expected blocking rule was observed
- no-promotion flag

Future evaluators may aggregate completed human scoring forms into the same next-work buckets, but prompt promotion must still remain a separate manual decision.

## First Controlled Set

The first controlled run should use the core suite, one run per case, and dry-run mode. This verifies benchmark selection, prompt snapshot collection, run manifests, reports, and scoring forms before spending Gemini quota.

After the dry-run artifacts are reviewed, a small live run can be launched with one or two representative core benchmarks. Full-suite repeated live runs should wait until the scoring workflow is exercised on a small set.

## Limits

This harness does not yet execute the complete browser-visible staged workflow end to end. The current live provider mode collects requirement-extraction provider output, optional Design Plan output, optional source-brief output, optional direct CadQuery source output, optional deterministic configuration probe output, and the surrounding prompt/version artifacts. Full live product-generation scoring should extend the same manifest format rather than replace it.

The harness is intentionally unable to accept candidates, update active revisions, or promote prompt versions.
