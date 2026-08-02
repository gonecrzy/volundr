# CadQuery Primary Transition Implementation Plan
> **Execution mode:** Inline Execution

**Goal:** Move Volundr to a CadQuery-primary, Gemini-primary, staged-workflow architecture through bounded, verified, separately committed phases.

**Architecture:** CadQuery Python source becomes the authoritative regeneration source. The API submits structured CAD execution jobs to an isolated worker, the worker owns source validation and artifact export, and the API owns persistence, candidate lifecycle, reviews, provider orchestration, and user-facing state.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite, React/Vite/TypeScript, Playwright, Docker Compose, CadQuery/OpenCascade, Gemini API.

## Phase 0 Report

### Base And Working Tree

- Current branch: `cadquery-v1-backend`.
- Current HEAD: `e5ead43e946d272e325a2cf90cdee21e38803613` (`Tighten CadQuery source prompt guardrails`).
- Audited HEAD is still the checked-out base.
- Commits after the audit: none in the current local checkout.
- Working tree before transition edits: `docs/CURRENT_REPOSITORY_AUDIT.md` was untracked; no tracked file changes were present.
- Current migration head: `0014_design_plan_clarifications`.

### Current Test Baseline

- `cd backend && .venv/bin/python -m pytest -q`: passed, `277 passed, 1 skipped, 2 warnings`.
- `cd frontend && npm test -- --run`: passed, `6 files, 38 tests`.
- `cd frontend && npm run build`: passed.
- `cd frontend && npm run test:e2e`: failed because default simple mode lacks the advanced `Plan revision` button.
- `cd frontend && VITE_VOLUNDR_GENERATION_MODE=advanced npm run test:e2e`: failed because `Generate revision` remains disabled after approving the mocked Revision Plan.

### Docker Compose Behavior

- Services from `docker compose config --services`: `volundr-api`, `volundr-cad-worker`, `volundr-web`.
- `volundr-api` defaults `VOLUNDR_AI_PROVIDER` to `ollama` and `VOLUNDR_GENERATION_MODE` to `simple`.
- `volundr-api` mounts the full data directory at `/app/data` and the Gemini profile at `/home/volundr/.gemini`.
- `volundr-cad-worker` mounts only `${VOLUNDR_DATA_DIR:-./data}/jobs:/work/jobs`, but it is attached to `volundr-internal` and has no `network_mode: none`.
- `cad-worker/Dockerfile` installs OpenSCAD and runs `python -m app.workers.cad_worker`.
- `backend/app/workers/cad_worker.py` only creates the workspace and sleeps; it does not poll, receive, or execute jobs.

### Existing CadQuery Probe Files

- `backend/app/services/cad/cadquery_runner.py`: subprocess-based probe runner; writes `model.py`, internal runner script, STL, optional STEP, logs, and mesh metadata from the caller process.
- `backend/app/services/cad/cadquery_contract.py`: AST validator for the current narrow `build_model()` probe contract.
- `backend/app/services/ai/source_extraction.py`: includes `extract_python_source` for fenced `python` or `cadquery` blocks and raw CadQuery-looking source.
- `backend/app/services/ai/gemini_cli.py`: owns `CADQUERY_SOURCE_PROMPT_VERSION = "cadquery-source-v2"` plus `build_cadquery_prompt`.
- `backend/app/services/ai/gemini_api.py` and `backend/app/services/ai/ollama.py`: delegate CadQuery generation to the shared prompt builder.
- `backend/app/services/generation/live_benchmarks.py`: exposes `--source-language cadquery` for benchmark/probe use and calls `CadQueryCliRunner`.
- `backend/tests/test_cadquery_contract.py`, `backend/tests/test_cad_runner.py`, `backend/tests/test_live_generation_benchmarks.py`, `backend/tests/test_live_generation_benchmark_cli.py`, `backend/tests/test_gemini_api_provider.py`, and `backend/tests/test_prompt_snapshots.py`: probe-level CadQuery coverage.

### Existing OpenSCAD Execution Call Sites

- `backend/app/api/dependencies.py`: constructs `OpenScadCliRunner`.
- `backend/app/services/projects/service.py`: stores `OpenScadCliRunner`, compiles per-output planned revisions through `self.cad_runner.compile(...)`, and compiles single/manual revisions through `self.cad_runner.compile(...)`.
- `backend/app/services/generation/live_benchmarks.py`: calls `OpenScadCliRunner(...).compile(...)` for source probes.
- `backend/app/services/cad/runner.py`: owns OpenSCAD subprocess execution, `-D` defines, `selected_output`, STL output, logs, timeout handling, and mesh inspection.
- `backend/Dockerfile` and `cad-worker/Dockerfile`: install OpenSCAD.

### Frontend Simple And Advanced Mode Controls

- `frontend/src/main.tsx` reads `VITE_VOLUNDR_GENERATION_MODE`, defaults to `simple`, and derives `ADVANCED_WORKFLOW_ENABLED`.
- `frontend/src/chatWorkflow.ts` routes follow-up messages to revision planning only when advanced mode is enabled.
- `docker-compose.yml` defaults `VITE_VOLUNDR_GENERATION_MODE` and `VOLUNDR_GENERATION_MODE` to `simple`.
- `backend/app/core/config.py` defaults `generation_mode` to `simple`.
- `frontend/e2e/candidate-workflow.spec.ts` assumes advanced controls such as `Plan revision` and `Generate revision`.

## File-By-File Transition Plan

### Phase 1: Authoritative CadQuery Direction

**Files:** `docs/CADQUERY_BACKEND.md`, `README.md`, `docs/PRODUCT_DIRECTION.md`, `docs/ARCHITECTURE.md`, `docs/CURRENT_STAGE_ROADMAP.md`, `docs/DATA_MODEL.md`, `docs/GEMINI_PROMPT_ARCHITECTURE.md`, `docs/PARAMETRIC_PRODUCT_MODEL.md`, `docs/MULTI_OUTPUT_GENERATION.md`, `docs/PARAMETER_CONFIGURATION.md`, `docs/STRUCTURED_REVISION_PLANNING.md`, `docs/COMPONENT_TARGETED_REVISIONS.md`, `docs/CAD_EXECUTION_SECURITY.md`, `docs/TEST_STRATEGY.md`, `docs/MVP_SCOPE.md`, `docs/DOCUMENTATION_MAP.md`, `docs/CURRENT_REPOSITORY_AUDIT.md`, this plan file.

**Intent:** Define CadQuery, Gemini API, STEP/STL, staged workflow, typed parameter execution, topology validation, worker isolation, and OpenSCAD removal as the authoritative direction while clearly marking current implementation gaps.

**Verification:** `git diff --check`; documentation contradiction scan for primary/default OpenSCAD, Ollama, simple workflow, and already-isolated worker claims; `git status --short`.

**Commit:** `Define CadQuery-primary architecture`.

### Phase 2: Isolated CAD Worker Boundary

**Files:** `cad-worker/Dockerfile`, `docker-compose.yml`, `backend/app/workers/cad_worker.py`, `backend/app/core/config.py`, `backend/app/services/cad/jobs.py`, `backend/app/services/cad/worker_client.py`, `backend/app/services/cad/worker_execution.py`, `backend/app/services/cad/runner.py`, `backend/app/api/dependencies.py`, `backend/app/services/projects/service.py`, `backend/tests/test_cad_worker.py`, `backend/tests/test_cad_worker_security.py`, `backend/tests/test_project_api.py`, `docs/CAD_EXECUTION_SECURITY.md`, `docs/ARCHITECTURE.md`.

**Intent:** Replace the idle worker with a real structured job boundary. Use filesystem-backed atomic job directories unless repository inspection during implementation proves a database queue is safer. Keep OpenSCAD in the API only as a temporary compatibility path if needed to keep intermediate commits testable.

**Verification:** targeted worker unit/integration tests, timeout test, malformed manifest test, path traversal test, duplicate completion test, environment scrub test, `docker compose config --services`, `git diff --check`, backend targeted tests.

**Commit:** `Implement isolated CAD worker execution`.

### Phase 3: CadQuery-Native Persistence

**Files:** `backend/app/models/revision.py`, `backend/app/models/revision_output.py`, `backend/app/models/generation_attempt.py`, `backend/app/models/source_validation_result.py`, `backend/app/models/geometric_analysis_result.py`, `backend/app/schemas/project.py`, `backend/app/services/projects/service.py`, `backend/app/api/projects.py`, `frontend/src/main.tsx`, `frontend/src/candidateView.ts`, `frontend/src/configurationView.ts`, `backend/alembic/versions/*.py`, `docs/DATA_MODEL.md`, `docs/MULTI_OUTPUT_GENERATION.md`.

**Intent:** Replace SCAD-specific canonical fields with backend/source-language/artifact fields, add STEP/topology persistence, and document destructive development database recreation.

**Verification:** Alembic fresh upgrade, backend model/API tests, frontend type tests, export ZIP tests, `git diff --check`.

**Commit:** `Replace CAD persistence with CadQuery-native artifacts`.

### Phase 4: Production CadQuery Source Contract

**Files:** `backend/volundr_cad/__init__.py`, `backend/volundr_cad/runtime.py`, `backend/app/services/cad/cadquery_contract.py`, `backend/app/services/ai/source_extraction.py`, `backend/app/services/ai/gemini_cli.py`, `backend/app/services/ai/provider.py`, `backend/app/services/projects/service.py`, `backend/tests/test_cadquery_contract.py`, `backend/tests/test_source_extraction.py`, `backend/tests/test_source_contract_pipeline.py`, `backend/tests/test_prompt_snapshots.py`, `docs/CADQUERY_BACKEND.md`, `docs/GEMINI_PROMPT_ARCHITECTURE.md`.

**Intent:** Promote the probe contract into `cadquery-v1` with typed parameters, `build(params)`, `Product`, `PrintableOutput`, output IDs, component IDs, expected solid counts, and bounded contract repair.

**Verification:** malicious source rejection tests, source extraction tests, contract repair tests, prompt snapshot tests, backend targeted tests.

**Commit:** `Implement production CadQuery source contract`.

### Phase 5: CadQuery Single And Multi-Output Execution

**Files:** `backend/app/services/cad/cadquery_runner.py`, `backend/app/services/cad/worker_execution.py`, `backend/volundr_cad/runtime.py`, `backend/app/services/projects/service.py`, `backend/app/services/mesh/inspect.py`, `backend/app/services/printability/inspector.py`, `backend/app/models/revision_output.py`, `backend/app/schemas/project.py`, `backend/tests/test_cadquery_execution.py`, `backend/tests/test_multi_output_generation.py`, `backend/tests/test_project_api.py`, `backend/tests/test_printability_inspector.py`, `docs/MULTI_OUTPUT_GENERATION.md`, `docs/TEST_STRATEGY.md`.

**Intent:** Execute the CadQuery `Product` contract in the worker, validate B-Rep/topology before meshing, export STEP/STL, emit manifests, and handle required/optional partial failures.

**Verification:** single-output fixture, multi-output fixture, required failure blocks candidate, optional failure warns, retry without provider call, STEP/STL hash assertions, backend targeted tests.

**Commit:** `Implement CadQuery multi-output execution`.

### Phase 6: Gemini CadQuery Staged Generation

**Files:** `backend/app/core/config.py`, `docker-compose.yml`, `frontend/vite.config.ts`, `frontend/src/main.tsx`, `backend/app/services/ai/gemini_cli.py`, `backend/app/services/ai/gemini_api.py`, `backend/app/services/ai/provider.py`, `backend/app/services/projects/service.py`, `backend/tests/test_ai_provider_selection.py`, `backend/tests/test_generation_api.py`, `backend/tests/test_design_plans.py`, `backend/tests/test_prompt_snapshots.py`, `docs/GEMINI_PROMPT_ARCHITECTURE.md`, `docs/PRODUCT_DIRECTION.md`.

**Intent:** Make Gemini API and staged generation the defaults, replace OpenSCAD generation/repair prompt modes with CadQuery modes, and remove simple raw prompt-to-source as the normal product path.

**Verification:** fake-provider staged generation tests, prompt version assertions, config tests, no live provider calls, frontend mode tests, `git diff --check`.

**Commit:** `Integrate Gemini CadQuery generation`.

### Phase 7: CadQuery Parameter Regeneration

**Files:** `backend/volundr_cad/runtime.py`, `backend/app/services/projects/service.py`, `backend/app/models/configuration_change.py`, `backend/app/schemas/project.py`, `backend/app/api/projects.py`, `frontend/src/configurationView.ts`, `frontend/src/main.tsx`, `backend/tests/test_parameter_configuration.py`, `frontend/src/configurationView.test.ts`, `docs/PARAMETER_CONFIGURATION.md`.

**Intent:** Validate JSON parameter values and regenerate via worker execution without source rewriting, command-line defines, or provider calls.

**Verification:** preview tests, preset tests, protected/editability tests, invalid structural change tests, parameter hash reproducibility tests, frontend tests.

**Commit:** `Implement CadQuery parameter regeneration`.

### Phase 8: Structured CadQuery Revisions

**Files:** `backend/volundr_cad/runtime.py`, `backend/app/services/cad/cadquery_contract.py`, `backend/app/services/projects/service.py`, `backend/app/models/revision_plan.py`, `backend/app/schemas/project.py`, `backend/app/services/ai/gemini_cli.py`, `backend/tests/test_structured_revision_planning.py`, `frontend/src/revisionPlanView.ts`, `frontend/src/main.tsx`, `docs/STRUCTURED_REVISION_PLANNING.md`, `docs/COMPONENT_TARGETED_REVISIONS.md`.

**Intent:** Keep complete-source revision behavior, replace SCAD markers with AST-visible CadQuery ownership metadata, validate protected fingerprints, and use topology/STEP/STL evidence for preservation checks.

**Verification:** component-targeted revision tests, unauthorized protected change blocks before execution, allowed scoped change executes, scope correction runs once, configured values remain executable.

**Commit:** `Implement structured CadQuery revisions`.

### Phase 9: Frontend Workflow And Playwright

**Files:** `frontend/src/main.tsx`, `frontend/src/chatWorkflow.ts`, `frontend/src/candidateView.ts`, `frontend/src/configurationView.ts`, `frontend/src/designSpecificationView.ts`, `frontend/src/designPlanView.ts`, `frontend/src/revisionPlanView.ts`, `frontend/e2e/candidate-workflow.spec.ts`, `backend/tests` fixture providers as needed, `docs/TEST_STRATEGY.md`.

**Intent:** Make the staged lifecycle the primary visible workflow and display CadQuery source, STEP/STL artifacts, topology validation, named outputs, configuration, and structured revisions.

**Verification:** frontend unit tests, production build, Playwright default and staged workflow passing.

**Commit:** `Align staged CadQuery frontend workflow`.

### Phase 10: Remove OpenSCAD Product Paths

**Files:** `backend/app/services/openscad/*`, `backend/app/services/cad/runner.py`, `backend/app/services/ai/source_extraction.py`, `backend/app/services/ai/gemini_cli.py`, `backend/app/services/generation/live_benchmarks.py`, `backend/app/models/*`, `backend/app/schemas/project.py`, `backend/app/services/projects/service.py`, `backend/app/api/projects.py`, `backend/Dockerfile`, `cad-worker/Dockerfile`, `docker-compose.yml`, `frontend/src/*`, `backend/tests/*`, `frontend/e2e/*`, `docs/*`.

**Intent:** Delete obsolete OpenSCAD runners, scanners, prompts, parameters, selectors, fields, UI labels, Docker packages, fixtures, and feature flags after CadQuery equivalents pass.

**Verification:** full backend tests, frontend tests, build, Playwright, Alembic fresh upgrade, no `OpenScad|openscad|scad_source|selected_output|module_name` product-path references except historical docs where explicitly retained.

**Commit:** `Remove OpenSCAD product paths`.

### Phase 11: Functional Benchmark Gate

**Files:** `backend/tests/fixtures/generation_benchmarks/*.json`, `backend/scripts/run_live_generation_benchmarks.py`, `backend/app/services/generation/live_benchmarks.py`, `docs/CADQUERY_TRANSITION_EVALUATION.md`, `docs/GENERATION_BENCHMARKS.md`.

**Intent:** Run controlled Gemini API benchmark cases only after deterministic and mocked tests pass, persist evaluation documentation, and avoid committing secrets or large generated binaries.

**Verification:** dry-run benchmark, then small live benchmark set with explicit user notice before any quota-consuming call, final benchmark report.

**Commit:** `Evaluate CadQuery transition benchmarks`.

## Phase Gates

After every implementation phase:

1. Run targeted tests for the changed subsystem.
2. Run migration verification when persistence changes.
3. Run `git diff --check`.
4. Confirm `git status --short`.
5. Commit a clear rollback point.
6. Record the commit hash for the final transition report.
