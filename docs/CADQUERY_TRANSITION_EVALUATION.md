# CadQuery Transition Evaluation

Date: 2026-07-30

## Phase 10 Verification

The CadQuery-only product path is committed in `a9cdc13 Remove OpenSCAD product paths`.

Verified commands:

```bash
rtk .venv/bin/python -m pytest -q
rtk npm test -- --run
rtk npm run build
rtk npm run test:e2e
rtk git diff --check
```

Results from the original Phase 10 commit:

- Backend: 177 passed, 1 existing Starlette/httpx deprecation warning.
- Frontend unit tests: 38 passed.
- Frontend production build: succeeded.
- Playwright staged workflow: 1 passed.
- Diff whitespace check: clean.

Additional local security verification added after the Phase 11 audit:

```bash
rtk .venv/bin/python -m pytest tests/test_cadquery_contract.py tests/test_cad_worker.py -q
rtk .venv/bin/python -m pytest -q
```

Results:

- CadQuery contract and worker security slice: 36 passed.
- Full backend after artifact-boundary hardening: 183 passed, 1 existing Starlette/httpx deprecation warning.
- Added explicit coverage for network-library import rejection, environment-inspection attempts, malformed STEP rejection, and worker result rejection of artifact paths outside the job directory.

Additional frontend workflow verification:

```bash
rtk npm run test:e2e
```

Result:

- Playwright staged revision workflow: 1 passed.

Additional migration verification:

```bash
rtk .venv/bin/alembic heads
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-migration-fresh.AIqMt2 .venv/bin/alembic upgrade head
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-migration-fresh.AIqMt2 .venv/bin/alembic current
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-migration-0014.Bae6bA .venv/bin/alembic upgrade 0014_design_plan_clarifications
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-migration-0014.Bae6bA .venv/bin/alembic upgrade head
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-migration-0014.Bae6bA .venv/bin/alembic current
```

Results:

- Alembic has a single head: `0015_cadquery_native_persistence`.
- Fresh SQLite database creation upgraded through all migrations to `0015_cadquery_native_persistence (head)`.
- Selected pre-CadQuery baseline upgrade from `0014_design_plan_clarifications` to `0015_cadquery_native_persistence` completed.
- Resulting schema includes CadQuery-native `revisions` fields (`source_path`, `cad_backend`, `source_language`, `source_hash`, `source_contract_version`, `execution_manifest_path`) and `revision_outputs` STEP/BREP/topology/execution manifest fields.

Additional Docker worker verification:

```bash
rtk docker compose up --build -d
rtk docker compose ps
rtk docker inspect volundr-cad-worker --format '{{.Config.User}} {{.HostConfig.NetworkMode}} {{.HostConfig.ReadonlyRootfs}} {{json .HostConfig.SecurityOpt}} {{json .HostConfig.PidsLimit}} {{json .HostConfig.Memory}} {{json .HostConfig.NanoCpus}}'
rtk docker exec volundr-cad-worker python -c "import os, cadquery, volundr_cad.runtime; print(os.getuid(), os.getgid(), cadquery.__version__)"
rtk docker exec volundr-cad-worker python -c "import os; print(sorted(k for k in os.environ if 'GEMINI' in k or 'OLLAMA' in k or k == 'VOLUNDR_AI_PROVIDER'))"
rtk docker exec volundr-cad-worker python -c "import socket; s=socket.socket(); s.settimeout(2); print(s.connect_ex(('1.1.1.1', 443))); s.close()"
```

Results:

- Compose rebuilt and started `volundr-web`, `volundr-api`, and `volundr-cad-worker`.
- CAD worker runtime policy: user `volundr-cad`, `network_mode=none`, read-only root filesystem, `no-new-privileges:true`, PID limit 128, memory limit 1 GiB, CPU limit 1.0.
- CAD worker environment has no Gemini/Ollama/provider credential variables.
- CAD worker imports `cadquery` 2.8.0 and `volundr_cad.runtime` successfully.
- Worker network probe to `1.1.1.1:443` returned `101` (`ENETUNREACH`).
- Deterministic queue job `docker-smoke-cadquery-e28ca1d3` succeeded with `failure_class=null`, STEP/STL/BREP artifacts, valid topology metadata, and artifact files visible under the shared jobs directory for API/host access.
- Failure diagnostics were verified with job `docker-smoke-cadquery-5eefd24f`, which returned `success=false`, `failure_class=execution_failed`, command args, exit code, and traceback diagnostics.
- Full backend regression after Docker fixes: `rtk .venv/bin/python -m pytest -q` -> 186 passed, 1 existing Starlette/httpx deprecation warning.

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
