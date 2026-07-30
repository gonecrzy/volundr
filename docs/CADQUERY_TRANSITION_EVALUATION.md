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

Attempted the live Gemini CLI path first with a one-case CadQuery source probe before spending broader quota:

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

Direct Gemini API access later became available and was used for a CadQuery smoke probe:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-gemini-api-smoke-v6 \
  --benchmark-id simple_mounting_plate \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --max-runs 1 \
  --max-estimated-tokens 80000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T144306Z-phase11-gemini-api-smoke-v6
```

Result:

- Case runs: 1.
- Requirements provider status: `provider_output_collected`.
- Source brief status: `source_brief_parsed`.
- Source probe status: `source_parameters_analyzed`.
- Source compile status: `compile_succeeded`.
- Source repair status: `not_attempted`.
- Expected parameter coverage: `1.0`.
- Compile warnings: `0`.
- Disconnected mesh count: `0`.

## Benchmark Gate Status

The required varied live Gemini API set was run:

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

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T144341Z-phase11-required
```

Aggregate result:

- Case runs: 12.
- Requirements provider statuses: `provider_output_collected=11`, `provider_failed=1`.
- Provider failure: `honeycomb_angle_bracket` requirements request timed out after 120 seconds.
- Source brief statuses: `source_brief_parsed=12`.
- Direct source compile statuses: `compile_succeeded=7`, `compile_failed=2`, `not_run=3`.
- Source repair attempts: 5.
- Source repair compile statuses: `compile_succeeded=4`, `compile_failed=1`, `not_run=7`.
- Repair-inclusive source compile success: 11 of 12 cases.
- Remaining source failure: `parametric_multi_part_hinged_box` repaired source failed with `output shape is invalid`.
- Source expected-parameter coverage average: `0.6667`.
- Repair artifacts had full expected-parameter coverage for repaired cases where extraction succeeded.
- Compiled direct-source outputs with nonzero volume: 7.
- Compiled direct-source watertight outputs: 7.
- Compile warnings: `0`.
- Disconnected mesh count: `0`.

Conclusion:

The transition is not declared fully successful from live benchmarks. The direct Gemini API path is usable and the CadQuery backend can execute most live-generated outputs, but the required 12-case gate still has one provider timeout and one unrepaired invalid-shape compile failure. The benchmark remains a human-review gate for requirement understanding, clarification quality, Design Plan usefulness, parameter quality, component decomposition, B-Rep validity, expected solid-count compliance, STEP/STL completeness, printability, revision preservation, configuration regeneration, and human print-worthiness.

Follow-up focused rerun after prompt hardening for hinged boxes:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-required-rerun-failures \
  --benchmark-id parametric_multi_part_hinged_box \
  --benchmark-id honeycomb_angle_bracket \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --max-runs 2 \
  --max-estimated-tokens 120000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T145209Z-phase11-required-rerun-failures
```

Result:

- Case runs: 2.
- Requirements provider statuses: `provider_output_collected=2`.
- Source brief statuses: `source_brief_parsed=2`.
- Source repair compile statuses: `compile_succeeded=2`.
- Both previously failing cases compiled after repair.

Latest full 12-case rerun after adding nonblocking source-brief fallback:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-required-v3 \
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

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T150430Z-phase11-required-v3
```

Latest aggregate result:

- Case runs: 12.
- Requirements provider statuses: `provider_output_collected=12`.
- Source brief statuses: `source_brief_parsed=10`, `source_brief_provider_failed=2`; source generation continued without the failed briefs.
- Direct source compile statuses: `compile_succeeded=6`, `compile_failed=5`, `not_run=1`.
- Source repair attempts: 5.
- Source repair compile statuses: `compile_succeeded=3`, `compile_failed=2`, `not_run=7`.
- Repair-inclusive source compile success: 9 of 12 cases.
- Remaining source failures: `parametric_multi_part_hinged_box` source provider timeout, `parametric_case_carrier` invalid output shape after repair, and `honeycomb_angle_bracket` invalid output shape after repair.
- Source expected-parameter coverage average: `0.9091`.
- Compile warnings: `0`.
- Disconnected mesh count: `0`.

Latest conclusion:

The required live gate is still not a release-quality pass. The system now handles Gemini API access, contract-level runtime mistakes, v1 parameter coverage, and source-brief provider failures more robustly, but the live model still produces invalid topology or times out on a minority of complex cases. The transition remains short of the requested live benchmark success criterion.

Final automated live source-gate rerun after carrier topology prompt hardening and brief-guided source fallback:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-required-v4 \
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

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T152753Z-phase11-required-v4
```

Final automated aggregate result:

- Case runs: 12.
- Requirements provider statuses: `provider_output_collected=12`.
- Source brief statuses: `source_brief_parsed=12`.
- Direct source compile statuses: `compile_succeeded=11`, `compile_failed=1`.
- Source repair attempts: 1.
- Source repair compile statuses: `compile_succeeded=1`, `not_run=11`.
- Repair-inclusive source compile success: 12 of 12 cases.
- Remaining source failures after repair: none.
- Source expected-parameter coverage average: `0.9167`; all non-clarification cases had full expected-parameter coverage.
- Compiled direct-source outputs with nonzero volume: 11.
- Compiled direct-source watertight outputs: 11.
- Compile warnings: `0`.
- Disconnected mesh count: `0`.

Final automated conclusion:

The automated live Gemini API source gate passes for the required 12-case set when repair-inclusive source compilation is counted. Prompt promotion remains disabled and the harness still requires human scoring for requirement understanding, Design Plan usefulness, printability, revision preservation, configuration regeneration, and print-worthiness before declaring product-quality release readiness.

## Final Current-HEAD Verification

Current HEAD verification after live-gate stabilization:

```bash
rtk .venv/bin/python -m pytest -q
rtk npm test -- --run
rtk npm run build
rtk npm run test:e2e
rtk .venv/bin/alembic heads
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-final-migration .venv/bin/alembic upgrade head
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-final-migration .venv/bin/alembic current
rtk git diff --check
```

Results:

- Backend tests: 198 passed, 1 existing Starlette/httpx deprecation warning.
- Frontend unit tests: 38 passed across 6 files.
- Frontend production build: succeeded.
- Playwright staged workflow: 1 passed.
- Alembic has a single head: `0015_cadquery_native_persistence`.
- Fresh SQLite database migration upgraded through all migrations to `0015_cadquery_native_persistence (head)`.
- Diff whitespace check: clean.

Final Docker worker verification:

```bash
rtk docker compose ps
rtk docker inspect volundr-cad-worker --format '{{.Config.User}} {{.HostConfig.NetworkMode}} {{.HostConfig.ReadonlyRootfs}} {{json .HostConfig.SecurityOpt}} {{json .HostConfig.PidsLimit}} {{json .HostConfig.Memory}} {{json .HostConfig.NanoCpus}}'
rtk docker exec volundr-cad-worker python -c "import os, cadquery, volundr_cad.runtime; print(os.getuid(), os.getgid(), cadquery.__version__)"
rtk docker exec volundr-cad-worker python -c "import os; print(sorted(k for k in os.environ if 'GEMINI' in k or 'OLLAMA' in k or k == 'VOLUNDR_AI_PROVIDER'))"
rtk docker exec volundr-cad-worker python -c "import socket; s=socket.socket(); s.settimeout(2); print(s.connect_ex(('1.1.1.1', 443))); s.close()"
```

Results:

- Compose services running: `volundr-api`, `volundr-cad-worker`, and `volundr-web`.
- Worker policy: user `volundr-cad`, network mode `none`, read-only root filesystem, `no-new-privileges:true`, PID limit 128, memory limit 1 GiB, CPU limit 1.0.
- Worker runtime import check: UID/GID `100/101`, CadQuery `2.8.0`, `volundr_cad.runtime` import succeeds.
- Worker provider environment check returned an empty list.
- Worker network probe returned `101` (`ENETUNREACH`).
- Deterministic queue job `docker-smoke-cadquery-final-v4` succeeded with `failure_class=null`, STEP/STL/BREP artifacts, valid topology metadata, output hashes, and structured diagnostics.
