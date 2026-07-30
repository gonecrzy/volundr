# CadQuery Transition Evaluation

Date: 2026-07-30

## Phase 10 Verification

The CadQuery-only product path is committed in `a9cdc13 Remove OpenSCAD product paths`.

Verified commands:

```bash
rtk .venv/bin/python -m pytest -q
rtk npm test -- --run
rtk npm run build
rtk git diff --check
```

Results:

- Backend: 177 passed, 1 existing Starlette/httpx deprecation warning.
- Frontend unit tests: 38 passed.
- Frontend production build: succeeded.
- Diff whitespace check: clean.

## Live Benchmark Smoke

Attempted the required live Gemini benchmark gate with a one-case CadQuery source probe before spending broader quota:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-smoke \
  --benchmark-id simple_mounting_plate \
  --provider gemini \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --max-runs 1 \
  --max-estimated-tokens 80000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T134714Z-phase11-smoke
```

Result:

- Case runs: 1.
- Requirements provider status: `provider_failed`.
- Source brief status: `source_brief_provider_failed`.
- Source compile status: `not_run`.
- Provider mode: `gemini`.
- Auth mode selected by provider: `gemini_profile`.

Blocker:

The local Gemini CLI profile failed before model output with `IneligibleTierError` because the configured Gemini Code Assist individual tier is no longer supported by the installed CLI. No `GEMINI_API_KEY` or `GOOGLE_API_KEY` was present, so the direct Gemini API path could not be used.

## Benchmark Gate Status

The transition is not declared successful from live benchmarks. Deterministic and mocked verification passes, but the real functional Gemini gate is blocked on credentials/provider access.

When Gemini access is available, run the required varied set:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-required \
  --benchmark-id simple_mounting_plate \
  --benchmark-id spacer_bushing \
  --benchmark-id box_with_lid \
  --benchmark-id parametric_repeated_slot_rack \
  --benchmark-id parametric_multi_part_hinged_box \
  --benchmark-id parametric_case_carrier \
  --benchmark-id parametric_configurable_organizer \
  --benchmark-id component_revision_lid_only \
  --benchmark-id vague_clarification \
  --benchmark-id parametric_electronics_enclosure \
  --benchmark-id honeycomb_angle_bracket \
  --benchmark-id parametric_adapter \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --max-runs 12 \
  --max-estimated-tokens 500000
```

Score the run against requirement understanding, clarification quality, Design Plan usefulness, parameter quality, component decomposition, valid source rate, worker execution success, B-Rep validity, expected solid-count compliance, STEP/STL completeness, printability, revision preservation, configuration regeneration, and human print-worthiness.
