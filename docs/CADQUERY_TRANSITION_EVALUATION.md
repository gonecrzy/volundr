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

Initial-run conclusion:

This first full-suite run did not prove a successful live gate. The direct Gemini API path was usable and the CadQuery backend executed most live-generated outputs, but this run still had one provider timeout and one unrepaired invalid-shape compile failure. Later reruns and follow-up probes below supersede those specific execution failures; the benchmark remains a human-review gate for requirement understanding, clarification quality, Design Plan usefulness, parameter quality, component decomposition, B-Rep validity, expected solid-count compliance, STEP/STL completeness, printability, revision preservation, configuration regeneration, and human print-worthiness.

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

The automated live Gemini API source gate passes for the required 12-case set when repair-inclusive source compilation is counted. Follow-up probes added live Design Plan coverage, deterministic configuration validation, and solid-count negative-control evidence. Prompt promotion remains disabled because the harness still requires human/product review for requirement fidelity, Design Plan usefulness beyond coverage counts, printability, revision preservation, configuration workflow quality, and print-worthiness before declaring product-quality release readiness.

## Phase 11 Scoring Addendum

Scoring basis:

- Live Gemini API run: `live-benchmark-20260730T152753Z-phase11-required-v4`.
- Automated evidence: run manifest, aggregate metrics, source parameter analyses, source compile workspaces, worker execution results, topology metadata, STEP/STL/BREP export presence, and case reports.
- Manual artifact review: generated source for clarification behavior, multipart outputs, honeycomb bracket, carrier handle, adapter repair, electronics enclosure, repeated rack, and organizer.
- Large generated artifacts remain under ignored `output/live-benchmarks/`; this document records the committed evidence.

Dimension score:

| Dimension | Score | Evidence |
| --- | --- | --- |
| Requirement understanding | Partial pass | Requirements output was collected for all 12 cases. The vague shelf-bracket request correctly returned `clarification_required=true` and `generation_ready=false`; the honeycomb bracket understood dimensions but did not implement real hexagonal honeycomb geometry. |
| Clarification quality | Pass for covered live case | `vague_clarification` asked for shelf dimensions, hole dimensions/spacing, load capacity, and shelf thickness, and did not mark the request generation-ready. |
| Design Plan usefulness | Partial live score plus deterministic workflow coverage | Follow-up live Design Plan probes scored expected component, feature, output, and dependency coverage. Component/output coverage was strong in focused runs. The recorded dependency coverage needs a fresh rerun because the harness later fixed analysis to read schema-correct `dependency_edges`; Design Plan approval/usefulness as a user workflow is verified by backend and Playwright staged workflow tests. |
| Parameter quality | Pass with caveats | All 11 concrete source cases had full expected-parameter coverage. The clarification case correctly had no generation-ready parameters at requirements time, while the forced source probe later exposed synthetic parameters that should not be accepted as product output before clarification. |
| Component decomposition | Partial pass | Multi-output cases exported separate body/lid outputs, and product cases exposed component/output IDs. The honeycomb bracket collapsed the honeycomb feature into rectangular pockets, so feature decomposition was not requirement-faithful there. |
| Valid source rate | Pass after bounded repair | 11 of 12 direct source probes compiled; 12 of 12 compiled after one bounded repair. `parametric_adapter` required repair. |
| Worker execution success | Pass | Every final source probe execution produced successful worker results for all required outputs. |
| B-Rep validity | Pass | Every final output had valid topology metadata and nonzero volume. |
| Expected solid-count compliance | Pass | Every final normal output reported `detected_solid_count=1` with disconnected bodies disallowed. A focused negative-control live run also generated loose bosses as separate solids and was blocked with `detected_solid_count=3` against `expected_solid_count=1`. |
| STEP/STL output completeness | Pass | Every final output produced STEP, STL, BREP, and topology metadata. |
| Printability | Partial pass | The live artifacts avoid disconnected bodies and export watertight solids, but the live harness did not run the full printability inspector per case. `honeycomb_angle_bracket` is not requirement-faithful enough to count as print-worthy honeycomb. |
| Revision preservation | Covered by deterministic workflow tests, partial live evidence | `component_revision_lid_only` generated a valid revised lid, and deterministic backend/Playwright tests cover structured revision preservation. The v4 live harness did not execute a full accepted-source-to-revised-candidate preservation comparison. |
| Configuration regeneration | Pass for focused build-volume probe, broader workflow deterministic | Deterministic configuration tests verify provider-free parameter regeneration. A focused live configuration probe reran generated CadQuery source with `rail_length=360` and observed the expected `profile.build_volume` Critical blocking rule; full browser-visible configuration workflow quality remains deterministic/Playwright evidence rather than a live provider score. |
| Human print-worthiness | Not a release pass | Automated validity is good, but human artifact review found at least one functional-fidelity miss (`honeycomb_angle_bracket`). The old repaired `parametric_adapter` live source exposed a pre-hardening metadata defect (`parameters=params`), but current contract/runtime checks reject Product parameter metadata that does not reference module-level `PARAMETERS`. External/user acceptance is still required before prompt promotion. |

Case-level score:

| Case | Automated status | Artifact review score | Notes |
| --- | --- | --- | --- |
| `simple_mounting_plate` | Pass | Pass | Full parameter coverage; valid single output. |
| `spacer_bushing` | Pass | Pass | Full parameter coverage; valid single output. |
| `box_with_lid` | Pass | Pass | Separate `box_body` and `lid` outputs; both valid. |
| `parametric_repeated_slot_rack` | Pass | Pass | Slot count drives repeated cuts and rack length; valid single output. |
| `parametric_multi_part_hinged_box` | Pass | Partial pass | Separate base/lid outputs and hinge holes are present. Hinge knuckle fidelity remains a visual/mechanical review item. |
| `parametric_case_carrier` | Pass | Partial pass | Tray count, rails, retention lip, reinforcement, and handle are modeled in one valid output. Build-volume and split-output decisions remain advisory and were not live-regenerated. |
| `parametric_configurable_organizer` | Pass | Pass | Row/column/cell parameters drive divider layout; valid organizer output. |
| `component_revision_lid_only` | Pass | Partial pass | Valid revised lid output. Full protected-body preservation is covered by deterministic revision tests, not by this live source probe. |
| `vague_clarification` | Requirements pass, forced source probe not acceptable | Pass for clarification; source probe is non-acceptance evidence | Requirements stage correctly blocked generation pending clarification. The later source probe generated a generic bracket and must not be treated as an accepted candidate. |
| `parametric_electronics_enclosure` | Pass | Pass | Separate base/lid outputs, standoffs, cable opening, and lid geometry present; both outputs valid. |
| `honeycomb_angle_bracket` | Topology pass | Fail for feature fidelity | Valid bracket with holes/rib, but generated rectangular pockets instead of hexagonal honeycomb cutouts. |
| `parametric_adapter` | Pass after repair | Partial pass | Repaired source produced a valid hollow loft adapter with full expected parameters. The archived live source returned `parameters=params`, but current `cadquery-v1` contract/runtime validation now rejects non-`PARAMETERS` Product metadata; this case needs a fresh live rerun under the hardened contract rather than remaining an unguarded acceptance defect. |

Phase 11 coverage limits:

- The controlled v4 source gate covered 12 varied prompts. Follow-up live runs added dedicated prompts for configuration build-volume risk and accidental multiple-solid risk. The configuration probe now executes the oversized override through the printability inspector and observed `profile.build_volume`; the accidental-multiple-solid negative-control run produced disconnected loose bosses and was rejected by topology validation.
- The v4 live harness is a requirements/source/worker gate, not a full staged Design Specification -> Design Plan -> approval -> generation -> acceptance benchmark.
- Prompt promotion remains disabled because the master prompt explicitly requires more than executable source, and artifact review found requirement-fidelity gaps.

## Additional Phase 11 Missing-Cases Run

After adding explicit full-suite fixtures for the two missing live categories, a focused Gemini API run was executed:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-design-plan-missing-cases \
  --benchmark-id accidental_multiple_solids \
  --benchmark-id configuration_exceeds_build_volume \
  --provider gemini-api \
  --allow-live \
  --design-plan-probe \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --max-runs 2 \
  --max-estimated-tokens 160000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T155117Z-phase11-design-plan-missing-cases
```

Aggregate result:

- Case runs: 2.
- Requirements provider statuses: `provider_output_collected=2`.
- Source brief statuses: `source_brief_parsed=2`.
- Design Plan probe statuses: `design_plan_analyzed=2`.
- Design Plan expected component coverage average: `1.0`.
- Design Plan expected feature coverage average: `0.4166`.
- Design Plan expected output coverage average: `1.0`.
- Design Plan expected dependency coverage average: `0.0`.
- Source probe statuses: `source_parameters_analyzed=2`.
- Direct source compile statuses: `compile_succeeded=2`.
- Source expected-parameter coverage average: `1.0`.
- Compile warnings: `0`.
- Disconnected mesh count: `0`.
- Estimated tokens: `11959`; dollar cost was not recorded.

Case findings:

- `accidental_multiple_solids`: this first missing-cases run produced one valid fused solid with STEP/STL/BREP artifacts. It proved the prompt still needed a stricter negative-control source request; the later focused run below exercised the actual rejection mechanic. Design Plan matched components and output, but missed mounting-hole feature coverage and all expected dependency edges.
- `configuration_exceeds_build_volume`: source output compiled to one valid solid with STEP/STL/BREP artifacts. Design Plan matched components and output, but missed explicit build-volume-check feature coverage and all expected dependency edges. The live run did not execute the oversized `rail_length=360` configuration override, so the `profile.build_volume` blocking behavior remains deterministic-test evidence rather than live-run evidence.

## Additional Solid-Count Negative-Control Run

After changing the accidental-multiple-solid fixture and source request into an explicit negative-control case, a focused Gemini API run was executed:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-solid-count-negative-live \
  --benchmark-id accidental_multiple_solids \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --design-plan-probe \
  --max-runs 1 \
  --max-estimated-tokens 90000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T161230Z-phase11-solid-count-negative-live
```

Aggregate result:

- Case runs: 1.
- Requirements provider statuses: `provider_output_collected=1`.
- Source brief statuses: `source_brief_parsed=1`.
- Design Plan probe statuses: `design_plan_analyzed=1`.
- Source probe statuses: `source_compile_failed=1`.
- Direct source compile statuses: `compile_failed=1`.
- Source expected-parameter coverage average: `1.0`.
- Source topology rejection count: `1`.
- Source solid-count rejection count: `1`.
- Estimated tokens: `4739`; dollar cost was not recorded.

Case findings:

- The generated source kept one declared printable output with `expected_solid_count=1` and `allow_disconnected_solids=False`.
- The generated source intentionally constructed a compound from the base and two alignment bosses left 1 mm above the base, producing three disconnected solids.
- The CadQuery runner rejected the output as `output shape is invalid` and preserved topology metadata showing `detected_solid_count=3`, `expected_solid_count=1`, `allow_disconnected_solids=false`, and `valid=false`.

## Additional Configuration Probe Run

After adding configuration-probe support and feeding fixture override targets into the source prompt, a focused Gemini API run was executed:

```bash
rtk .venv/bin/python scripts/run_live_generation_benchmarks.py \
  --suite tests/fixtures/generation_benchmarks/full.json \
  --output-dir ../output/live-benchmarks \
  --run-label phase11-configuration-probe-live-v2 \
  --benchmark-id configuration_exceeds_build_volume \
  --provider gemini-api \
  --allow-live \
  --source-probe \
  --source-brief \
  --source-probe-repair \
  --design-plan-probe \
  --configuration-probe \
  --max-runs 1 \
  --max-estimated-tokens 110000
```

Artifact directory:

```text
output/live-benchmarks/live-benchmark-20260730T160200Z-phase11-configuration-probe-live-v2
```

Aggregate result:

- Case runs: 1.
- Requirements provider statuses: `provider_output_collected=1`.
- Source brief statuses: `source_brief_parsed=1`.
- Design Plan probe statuses: `design_plan_analyzed=1`.
- Design Plan expected component coverage average: `1.0`.
- Design Plan expected feature coverage average: `0.3333`.
- Design Plan expected output coverage average: `1.0`.
- Design Plan expected dependency coverage average: `0.0`.
- Direct source compile statuses: `compile_failed=1`.
- Source repair statuses: `source_repair_succeeded=1`.
- Source repair compile statuses: `compile_succeeded=1`.
- Source expected-parameter coverage average: `1.0`.
- Configuration probe statuses: `configuration_blocked_build_volume=1`.
- Configuration expected block observed count: `1`.
- Estimated tokens: `6190`; dollar cost was not recorded.

Case findings:

- The repaired source raised `rail_length` maximum to `400.0`, so the requested `rail_length=360` deterministic override could execute.
- The configuration printability report observed `profile.build_volume` as a Critical rule for a 360 mm rail against the fixture's 220 x 220 x 250 mm build volume.
- The same report also observed `orientation.below_build_plate` as Critical, so generated orientation remains a source-quality issue even though the build-volume blocking evidence is now present.

## Final Current-HEAD Verification

Current HEAD verification after live-gate stabilization:

```bash
rtk .venv/bin/python -m pytest -q
rtk npm test -- --run
rtk npm run build
rtk npm run test:e2e
rtk .venv/bin/alembic heads
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-final-migration-solid-count .venv/bin/alembic upgrade head
rtk env VOLUNDR_DATA_DIR=/tmp/volundr-final-migration-solid-count .venv/bin/alembic current
rtk git diff --check
```

Results:

- Backend tests: 207 passed, 1 existing Starlette/httpx deprecation warning.
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

## Final Completion Evidence Map

1. Starting repository state: branch `cadquery-v1-backend`, audited base `e5ead43`, migration head at audit `0014_design_plan_clarifications`, with CadQuery probe-only and OpenSCAD still product-shaped.
2. Final architecture: Gemini API primary, CadQuery Python authoritative source, isolated CadQuery worker execution, STEP primary interoperable artifact, STL derived preview/print artifact, optional BREP persistence, staged lifecycle primary.
3. Commits created in order:
   - `543efa7` Document CadQuery transition baseline
   - `a55164f` Define CadQuery-primary architecture
   - `aaaaf46` Implement isolated CAD worker execution
   - `b0409b3` Replace CAD persistence with CadQuery-native artifacts
   - `0ed91cd` Implement production CadQuery source contract
   - `a5a2993` Implement CadQuery multi-output execution
   - `8ef8a85` Integrate Gemini CadQuery generation
   - `8556418` Implement CadQuery parameter regeneration
   - `c4fbf2f` Implement structured CadQuery revisions
   - `48763b9` Align staged CadQuery frontend workflow
   - `a9cdc13` Remove OpenSCAD product paths
   - `f68232b` Document CadQuery benchmark gate
   - `298f922` Harden CadQuery artifact validation
   - `dd692f1` Record Playwright transition verification
   - `28ffe15` Record CadQuery migration verification
   - `ed8e19c` Verify Docker CadQuery worker execution
   - `d55b407` Reconcile CadQuery transition documentation
   - `6382f37` Harden CadQuery live benchmark contract
   - `70fd04e` Improve live benchmark source fallback
   - `37a1a36` Stabilize CadQuery live source gate
   - `75d0e04` Record final CadQuery transition verification
4. Database/schema strategy: development migration `0015_cadquery_native_persistence` replaces OpenSCAD-shaped canonical fields with CadQuery-native source, execution, output, topology, STEP/STL/BREP, and manifest fields. Old development databases should be recreated.
5. Worker execution and security model: filesystem-backed job queue; worker runs as non-root `volundr-cad`, with no network, no provider credentials, read-only root filesystem, bounded PID/memory/CPU, structured job/result manifests, timeout handling, artifact hashes, and diagnostics.
6. CadQuery source contract: `cadquery-v1` Python contract with approved imports, typed `ParameterSpec`, `build(params)`, structured `Product`, named `PrintableOutput` records, source extraction, AST validation, contract repair, and worker-owned exports.
7. Parameter model: typed editable/protected parameters with validation, ranges, enums, presets, dependency summaries, and provider-free resolved value execution.
8. Single/multi-output behavior: one Product contract handles single and multiple named outputs; required output failures block candidate readiness, optional failures warn.
9. STEP/BREP/STL artifact behavior: successful CadQuery outputs produce STEP and STL plus BREP where available, metadata JSON, topology summaries, hashes, and execution manifests.
10. Topology and solid-count validation: each output validates supported shape, nonzero volume, B-Rep validity, expected/detected solid count, disconnected-solid policy, bounding box, and output identity before candidate acceptance.
11. Gemini prompt modes: Gemini API is the default provider path; active CadQuery modes cover requirements, Design Plan, generation, contract repair, execution repair, revision planning, component revision, and scope correction.
12. Configuration behavior: deterministic parameter changes reuse accepted source and call the isolated worker without provider calls; configuration records source/parameter hashes, overrides, affected parameters/components/outputs, and validation state.
13. Structured revision behavior: approved Revision Plans drive complete-source CadQuery revisions with preservation checks, bounded repair/correction, and candidate review.
14. Component-targeted revision behavior: targeted components/outputs and protected components/outputs are represented in plans and checked against generated outputs and topology/preservation evidence.
15. Frontend lifecycle: the primary UI path is staged Describe -> Requirements -> Design Plan -> Approve -> Generate -> CadQuery execution/topology validation -> Candidate -> Accept or revise, with CadQuery source, named outputs, topology, configuration, and revision controls.
16. OpenSCAD code removed: OpenSCAD product paths, prompt modes, parser/runner assumptions, schema aliases, UI labels, Docker package usage, and simple bypass defaults were removed or superseded by CadQuery-only paths.
17. Tests and exact results: final current-HEAD backend tests `207 passed`; frontend unit tests `38 passed`; production build succeeded; staged Playwright workflow `3 passed`; `git diff --check` clean.
18. Docker verification: web/API/worker running; worker non-root, no provider env, no network; deterministic CadQuery job succeeded and artifacts were visible through the jobs directory; structured failure diagnostics were previously verified.
19. Live Gemini calls made and quota usage: Gemini CLI smoke failed before output due local tier eligibility; Gemini API smoke and required live reruns were then run with quota caps. Final v4 live run estimated `55751` tokens and did not record dollar cost.
20. Benchmark results: final v4 automated source gate collected 12/12 requirements outputs, parsed 12/12 source briefs, compiled 11/12 direct sources, repaired 1/1 failed source, and produced valid STEP/STL/BREP artifacts for every final output. Focused follow-up live runs added Design Plan probes, build-volume configuration probing, and accidental-multiple-solid prompting; the v2 configuration probe observed `profile.build_volume` for `rail_length=360`, and the solid-count negative-control live run observed `source_probe_solid_count_rejection_count=1`.
21. Remaining limitations: live benchmark scoring is not a full product-quality pass; full revision preservation and human print-worthiness still need richer live or human acceptance gates. Honeycomb bracket feature fidelity, a fresh adapter live rerun under hardened Product metadata validation, generated orientation for the build-volume case, and refreshed Design Plan dependency coverage need follow-up live scoring and prompt/repair hardening where failures remain.
22. Recommended next product task: implement a stricter staged live benchmark that exercises Design Plan approval, deterministic configuration including build-volume failure, protected-output revision preservation, accidental multi-solid rejection, printability inspection, and human scoring aggregation before prompt promotion.
23. Final repository status: expected to be clean after committing current transition evidence updates.
