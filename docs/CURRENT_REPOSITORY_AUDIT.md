# Current Repository Audit

Audit date: 2026-07-30.

Audited checkout: branch `cadquery-v1-backend`, HEAD `e5ead43 Tighten CadQuery source prompt guardrails`.

This audit is based on repository inspection and local non-live verification. No external AI provider was called.

# 1. Executive Summary

Volundr currently works as a self-hosted CAD generation workspace with a FastAPI backend, React frontend, SQLite persistence, OpenSCAD compilation, STL preview/download, candidate review, staged requirements/planning paths, deterministic OpenSCAD parameter configuration, structured revision planning, component-scoped source revision checks, multi-output STL artifacts, and local benchmark tooling. The checked-out branch also contains experimental CadQuery source-probe support with a prompt, Python source extraction, AST contract validation, and a CadQuery runner that can export STL/STEP when CadQuery is installed.

The lifecycle that is actually active by default is the simple chat/generation path: `frontend/src/main.tsx` defaults to `VITE_VOLUNDR_GENERATION_MODE=simple`, backend `app/core/config.py` defaults `generation_mode="simple"`, and `/api/projects/{project_id}/generate` can call AI source generation directly. The advanced staged lifecycle exists and is covered by backend tests, but the default UI hides most of it unless built with `VITE_VOLUNDR_GENERATION_MODE=advanced`.

The repository is partly coherent: the backend service has a single central lifecycle owner in `backend/app/services/projects/service.py`, and tests cover many state transitions. The main incoherence is strategic drift: docs still describe OpenSCAD/Gemini as the V1 kernel, README/config now default to Ollama/simple workflow, and the current branch adds CadQuery probe code without integrating it into the product lifecycle.

Largest risks:

- CAD execution security: generated CAD runs in the API container process boundary today; the `volundr-cad-worker` container is idle and not a real execution boundary.
- Backend coupling: persistent fields, schemas, API names, prompt modes, source validators, output selectors, and parameter configuration all assume OpenSCAD.
- Lifecycle bypasses: simple generation, manual revision, and spec-only generation bypass Design Plan approval and multi-output rules.
- Validation confidence: post-mesh checks are useful but limited; source markers record intent and cannot prove arbitrary geometry semantics.
- Provider drift: the code has a provider interface, but many records and services still store `gemini_ruleset_version`, and runtime defaults are Ollama rather than Gemini.

Readiness for CAD-backend abstraction: partially ready. Design Specifications, Design Plans, Revision Plans, candidate acceptance, generation attempts, findings, and many mesh/printability checks are reusable. Source contracts, artifact fields, runners, parameter override execution, prompt routing, multi-output selection, export packaging, and security boundaries need explicit backend interfaces before CadQuery can be primary for normal projects.

# 2. Repository And Deployment Structure

Major directories:

- `backend/`: FastAPI app, SQLAlchemy models, Alembic migrations, CAD runners, AI providers, generation services, tests, and live benchmark CLI.
- `frontend/`: React/Vite/TypeScript UI, Three.js STL viewer, workflow view helpers, Vitest tests, Playwright e2e test.
- `cad-worker/`: Dockerfile for a CAD worker image.
- `docs/`: product, architecture, data model, prompt, validation, and roadmap documents.
- `data/`: ignored runtime data bind mount; default local SQLite target when `VOLUNDR_DATA_DIR=../data`.
- `output/`: ignored benchmark output.

Backend/frontend/worker boundaries:

- `backend/app/main.py` mounts the API router and CORS.
- `backend/app/api/projects.py` exposes REST endpoints.
- `backend/app/services/projects/service.py` orchestrates project lifecycle, AI calls, source validation, compilation, validation, candidate state, export, and configuration.
- `frontend/src/main.tsx` is the primary UI and API client.
- `backend/app/workers/cad_worker.py` only creates the CAD workspace and sleeps; it does not poll jobs or compile CAD.

Docker services in `docker-compose.yml`:

- `volundr-web`: builds `frontend/`, serves nginx on `${VOLUNDR_WEB_PORT:-8080}:80`, depends on API.
- `volundr-api`: builds `backend/`, runs `alembic upgrade head && uvicorn`, mounts `${VOLUNDR_DATA_DIR:-./data}:/app/data` and `${VOLUNDR_GEMINI_DIR:-./data/gemini}:/home/volundr/.gemini`.
- `volundr-cad-worker`: builds `cad-worker/Dockerfile`, mounts `${VOLUNDR_DATA_DIR:-./data}/jobs:/work/jobs`, but currently runs the idle worker module.

Network:

- Compose network `volundr-internal`.
- No `network_mode: none` is set for CAD execution.
- Docker default outbound network access is not explicitly disabled.

Secrets and credentials:

- `.env.example` defines `GEMINI_API_KEY=`, `VOLUNDR_GEMINI_DIR=./data/gemini`, `VOLUNDR_AI_PROVIDER=ollama`, and model/provider settings.
- `.env` is ignored by git, but `docker compose config` expands secrets into rendered configuration. Do not paste full compose config into logs.
- Gemini profile is mounted only into `volundr-api`; not into `volundr-web` or `volundr-cad-worker`.
- Because CAD compilation happens in `volundr-api`, generated CAD execution currently shares the API container's environment and mounted secrets.

OpenSCAD installation/invocation:

- `backend/Dockerfile` installs Debian `openscad` in the API image.
- `cad-worker/Dockerfile` also installs `openscad`, but the worker is idle.
- `backend/app/services/cad/runner.py` invokes `settings.openscad_binary` with `-D` defines, `-o model.stl`, and source path in a per-job directory under `settings.cad_workspace_dir`.

Generated artifacts are stored under `settings.data_dir`, usually `/app/data` in Docker or `../data` when explicitly set locally:

- `projects/<project_id>/generation-runs/<attempt_id>/request.json`
- `projects/<project_id>/generation-runs/<attempt_id>/prompt.txt`
- `projects/<project_id>/generation-runs/<attempt_id>/raw-output.txt`
- `projects/<project_id>/generation-runs/<attempt_id>/extracted-source.scad`
- `projects/<project_id>/generation-runs/<attempt_id>/source-contract.json`
- `projects/<project_id>/revisions/<revision_id>/model.scad`
- `projects/<project_id>/revisions/<revision_id>/project.scad`
- `projects/<project_id>/revisions/<revision_id>/model.stl`
- `projects/<project_id>/revisions/<revision_id>/stl/<output>.stl`
- `projects/<project_id>/revisions/<revision_id>/logs/<output>.log`
- `projects/<project_id>/revisions/<revision_id>/metadata/<output>.json`
- `projects/<project_id>/revisions/<revision_id>/output-manifest.json`
- `projects/<project_id>/configuration-changes/<change_id>/configuration.json`
- `projects/<project_id>/configuration-changes/<change_id>/parameter-overrides.json`
- `projects/<project_id>/revision-plans/<revision_plan_id>/revision-compliance.json`
- `projects/<project_id>/revision-plans/<revision_plan_id>/component-revision-summary.json`

# 3. Current Runtime Lifecycle

Default simple request path:

```text
browser chat
  -> POST /api/projects/{project_id}/generate
  -> ProjectService.generate_initial_revision
  -> ai_provider.generate_model
  -> extract_scad_source
  -> SourceContractValidator
  -> OpenScadCliRunner.compile
  -> inspect_stl/trimesh
  -> geometric invariants when Design Specification exists
  -> printability findings
  -> candidate revision
  -> explicit accept/reject
```

Advanced staged path:

```text
request
  -> /projects/{id}/requirements
requirements
  -> DesignSpecification row and parsed-design-spec.json
Design Specification
  -> /design-specifications/{id}/design-plan
Design Plan
  -> DesignPlan row and parsed-design-plan.json
approval
  -> /design-plans/{id}/approve
generation
  -> /design-plans/{id}/generate
source validation
  -> source_validation_results + validation_findings
compilation
  -> revision_outputs, STL/log/metadata artifacts
output validation
  -> geometric_analysis_results + validation_findings
candidate
  -> Revision.review_state ready|ready_with_warnings|blocked
acceptance
  -> /candidates/{revision_id}/accept sets Revision.accepted and Project.active_revision_id
```

Stage details:

| Stage | Primary service/function | Input record | Output record/artifacts | State changes/failure behavior | Frontend state |
|---|---|---|---|---|---|
| request/project | `ProjectService.create_project`, `create_draft_project`, `save_project` | `ProjectCreate`/`ProjectSave` | `projects`, `project_messages` | Drafts expire after 14 days; archived after 60 days cleanup | Project drawer/workspace |
| requirements | `extract_requirements`, `_run_requirement_extraction` | `projects`, `RequirementExtractionCreate` | `generation_attempts`, `design_specifications`, clarification rows, `parsed-design-spec.json` | Invalid JSON triggers one schema repair recursion; provider errors become 502 | Advanced requirement review or clarification prompts |
| Design Specification | `_parse_design_specification_payload`, `_persist_design_specification` | raw AI JSON | immutable versioned spec artifact | outcomes: `generation_ready`, `clarification_required`, conflict, unsupported, failed | `RequirementReview` and chat answers |
| Design Plan | `create_design_plan_from_specification`, `_run_design_planning` | ready Design Specification | `design_plans`, plan clarification rows, `parsed-design-plan.json` | invalid JSON one repair; must approve before planned generation | Advanced design plan review |
| generation | `generate_initial_revision` or `generate_from_design_plan` | `GenerationCreate`, optional spec/plan | `generation_attempts` prompt/raw/source artifacts | provider timeout/failure classified on attempt | chat pending/error |
| source validation | `_extract_validate_or_repair_source`, `_persist_source_contract_validation` | extracted SCAD | `source_validation_results`, `validation_findings`, `source-contract.json` | hard rejection blocks compile; one contract repair attempt | source checks panel/error |
| compilation | `_create_revision_from_source` or `_create_revision_from_planned_source` | validated SCAD | `revisions`, optional `revision_outputs`, STL/log/metadata | compile failure creates failed revision and may trigger one compile repair for initial generation | candidate/revision list |
| output validation | `_persist_geometric_analysis`, `_persist_validation_findings`, `_persist_assembly_output_findings` | STL mesh and source metadata | `geometric_analysis_results`, `validation_findings` | blocking findings produce blocked candidate/output | candidate and output panels |
| candidate | `_derive_review_state` | persisted findings | `Revision.review_state` | AI candidates are not auto-accepted | Review controls |
| acceptance | `accept_candidate`, `reject_candidate` | candidate revision | `Project.active_revision_id`, revision timestamps | blocked/rejected candidates cannot be accepted | active design label updates |

Additional flows:

- Requirement clarification: clarification questions are stored on `clarification_questions`; answers go to `clarification_answers`; `_run_requirement_extraction` reruns with previous spec and answers, superseding the previous spec.
- Design Plan approval: `approve_design_plan` changes `review_state` to `approved`; `generate_from_design_plan` refuses unapproved/superseded plans.
- Deterministic parameter configuration: `preview_configuration_change` resolves presets/overrides against Design Plan parameters and OpenSCAD source mappings; `generate_from_configuration_change` recompiles unchanged source with `-D` overrides and stores `configuration.json` and `parameter-overrides.json`.
- Structured AI revision: `create_revision_plan` requires a successful base revision with approved Design Plan; `approve_revision_plan` is required before `generate_from_revision_plan`.
- Component-targeted revision: `generate_from_revision_plan` builds scoped context from source markers/fingerprints and output manifest, uses `openscad-component-revision-v1`, then validates source scope before compile.
- Compile repair: initial generation only gets one bounded compile repair after a failed compile. The repair is also source-contract validated before compile.
- Contract repair: source-contract failure triggers one bounded contract repair in `_extract_validate_or_repair_source`.
- Scope correction: if revision compliance fails, `_attempt_scope_correction` asks AI once to correct source scope and revalidates before compile.
- Output retry: `retry_revision_output` recompiles one failed output from the same source hash and selector, without AI.

Lifecycle bypasses:

- `/api/projects/{project_id}/generate` runs direct AI source generation in simple mode.
- `/api/design-specifications/{specification_id}/generate` generates from a Design Specification without Design Plan approval.
- `/api/projects/{project_id}/revisions` accepts manual SCAD source and compiles without staged AI lifecycle.
- CadQuery source probes exist only in benchmark tooling, not the project lifecycle.

# 4. Persistence Model

Current Alembic head: `0014_design_plan_clarifications`.

Migration chain:

`0001_project_revision_base -> 0002_project_messages -> 0003_printability_profiles -> 0004_generation_attempts -> 0005_candidate_revisions -> 0006_design_specifications -> 0007_source_contract_validation -> 0008_geometric_analysis_results -> 0009_design_plans -> 0010_multi_output_artifacts -> 0011_structured_revision_plans -> 0012_configuration_changes -> 0013_component_revision_summaries -> 0014_design_plan_clarifications`.

Relevant tables:

| Table/model | Purpose | Mutability/versioning | Important FKs | Lifecycle ownership | Active use |
|---|---|---|---|---|---|
| `projects` / `Project` | Design workspace and active revision pointer | mutable name/status/active pointer | `active_revision_id -> revisions.id` | Project API/service | active |
| `project_messages` / `ProjectMessage` | user/system event ledger | append-only | `project_id`, `revision_id` | Project service | active |
| `revisions` / `Revision` | immutable model candidate/accepted state | mostly immutable artifacts; mutable review/accept/reject/count fields | project, parent revision, spec, plan, config change | Project service | active |
| `generation_attempts` / `GenerationAttempt` | AI run observability and failure taxonomy | append/update during attempt | project, base revision, resulting revision | AI orchestration | active |
| `design_specifications` / `DesignSpecification` | immutable structured requirements | versioned by `version_number`; superseded pointer | project, attempt, superseded spec | requirement extraction | active in advanced and optional simple context |
| `clarification_questions` / `ClarificationQuestion` | spec clarification prompts | append-only per spec | project, spec | requirement extraction | active |
| `clarification_answers` / `ClarificationAnswer` | spec clarification answers | append-only | project, question, spec | clarification flow | active |
| `design_plans` / `DesignPlan` | immutable parametric product plan | versioned; mutable review approval/rejection | project, spec, attempt, superseded plan | planning flow | active in advanced/multi-output/config/revisions |
| `design_plan_clarification_questions` | plan clarification prompts | append-only per plan | project, design plan | design planning | active |
| `design_plan_clarification_answers` | plan clarification answers | append-only | project, plan, question | design planning | active |
| `revision_plans` / `RevisionPlan` | immutable scoped revision plan | versioned; mutable review/generated links | project, base revision, base/revised spec/plan, attempt | revision planning | active in advanced |
| `revision_plan_clarification_questions` | revision-plan questions | append-only | project, revision plan | revision planning | active |
| `revision_plan_clarification_answers` | revision-plan answers | append-only | project, plan, question | revision planning | active |
| `revision_compliance_results` | pre-compile scope comparison | append-only | project, revision plan, attempt, revision | revision compliance | active |
| `revision_success_results` | post-generation success criteria | append-only | project, revision plan, revision, attempt | revision validation | active |
| `component_revision_summaries` | scoped revision output/interface summary | append-only | project, revision plan, revision, base revision, attempt | component revisions | active |
| `configuration_changes` / `ConfigurationChange` | deterministic parameter/preset preview and generation record | immutable preview; generated link and approval time added | project, base revision, generated revision, spec, plan | configuration service | active |
| `configuration_presets` / `ConfigurationPreset` | project-local presets | append-only user-created presets | project, design plan | configuration service | active |
| `revision_outputs` / `RevisionOutput` | per-output printable artifacts | output state mutable during compile/retry; artifact evidence otherwise stable | revision, design plan, spec | multi-output compile | active |
| `validation_findings` / `ValidationFinding` | source, geometry, printability, assembly, revision findings | mutable only for nonblocking dismissal | revision, output, attempt, spec, source result | validators | active |
| `source_validation_results` / `SourceValidationResult` | source-contract run result | append-only; `revision_id` attached after candidate creation | project, attempt, spec, revision | source validation | active for OpenSCAD |
| `geometric_analysis_results` / `GeometricAnalysisResult` | post-mesh invariant results | append-only | revision, output, spec | geometry validation | active |
| `printability_profiles` / `SavedPrintabilityProfile` | saved printer profile settings | user mutable | none/projectless | printability profile service | active |

Persistence assumptions that block backend neutrality:

- `Revision.scad_source_path` and `RevisionRead.scad_source_path` are mandatory source fields even for future non-SCAD source.
- `RevisionOutput.module_name`, `compile_command_json`, and output manifests assume selector/module execution.
- `GenerationAttempt.gemini_ruleset_version` is mandatory even for Ollama and future providers.
- `SourceValidationResult` stores `contract_version="source-contract-v1"` and OpenSCAD scanner metadata.

# 5. Current AI Provider Architecture

Provider interface: `backend/app/services/ai/provider.py`.

Implemented adapters:

- `GeminiCliProvider` in `backend/app/services/ai/gemini_cli.py`.
- `GeminiApiProvider` in `backend/app/services/ai/gemini_api.py`.
- `OllamaProvider` in `backend/app/services/ai/ollama.py`.

Authentication:

- Gemini CLI: `gemini` binary with mounted profile under `/home/volundr/.gemini`, command includes `--skip-trust` and policy file `gemini_no_tools_policy.toml`.
- Gemini API: `GEMINI_API_KEY` or `VOLUNDR_GEMINI_API_KEY`, passed as query parameter `key`.
- Ollama: local HTTP endpoint, no key.

Model/configuration:

- `backend/app/core/config.py` defaults `ai_provider="ollama"`, `ollama_model="qwen2.5-coder:14b"`, `gemini_model="gemini-3.5-flash-lite"`.
- `docker-compose.yml` also defaults `VOLUNDR_AI_PROVIDER=ollama`.
- Gemini API temperature defaults to `0.2`, max output tokens `8192`, thinking level `minimal`, retries `2`, retry sleep cap `60`.

Invocation and output handling:

- All providers return raw text; structured JSON is parsed by `ProjectService` with Pydantic schemas.
- Invalid requirements/design-plan/revision-plan JSON triggers one schema repair by recursively rerunning the same stage with raw output and validation error.
- Gemini API handles HTTP 429/503 retry delays from headers, details, or error text.
- Gemini CLI timeout terminates process group, then kills if needed.
- Provider failure fallback is limited to one repair attempt within the same provider/stage; there is no automatic provider fallback.

Token/cost tracking:

- Product generation attempts persist provider settings and prompt paths, but no actual token usage or cost.
- Live benchmark tooling estimates token/cost preflight and writes metrics, but product runtime does not persist provider token accounting.

Health checks:

- `/health` returns `{"status":"ok"}` only.
- No provider health check endpoint verifies Gemini/Ollama availability.

Prompt-mode routing:

- `GeminiCliProvider.prompt_template_version_for` selects prompt versions based on request diagnostics/current source/design plan/revision plan.
- `ProjectService` records rendered prompt files via provider prompt-builder methods.

Gemini-specific leakage:

- `GenerationAttempt.gemini_ruleset_version`, `DesignSpecification.gemini_ruleset_version`, `DesignPlan.gemini_ruleset_version`, `RevisionPlan.gemini_ruleset_version`.
- `SourceContractValidator` default `ruleset_version="gemini-ruleset-v1"`.
- Docs and prompt files are named Gemini even when `OllamaProvider` is active.
- `_gemini_ruleset_version()` in `ProjectService` reads `ai_provider.gemini_ruleset_version`.

Adding another provider currently requires:

- One adapter: yes, if it can reuse existing prompt text and raw text responses.
- Orchestration changes: probably no for OpenSCAD, yes for provider health/cost or if structured outputs are native tool/function calls.
- Schema changes: not strictly for a provider, but provider-neutral naming should replace `gemini_ruleset_version`.
- Frontend changes: no provider selector currently exposed; environment-only switching.
- Prompt changes: yes if a provider needs different output constraints, tool disabling, or native structured-output mechanisms.

# 6. Prompt Architecture

Active prompt modes:

| Mode/version | Source file | Renderer | Inputs | Expected output | Validation | Persisted metadata | Reachable |
|---|---|---|---|---|---|---|---|
| `requirements-v1` | `backend/app/services/ai/gemini_cli.py` | `_build_requirement_prompt` | user request, previous spec, clarifications, defaults | JSON Design Specification | Pydantic `DesignSpecificationPayload` | attempt prompt/raw/spec path, spec row | yes, advanced route |
| requirement schema repair | same | `_build_requirement_prompt` with `schema_repair_of_raw_output` | invalid raw output + error | repaired JSON | same | new attempt | yes |
| `source-brief-v1` | same | `_build_source_brief_prompt` | benchmark intent, expected params/invariants | JSON source brief | benchmark parser only | benchmark artifacts | benchmark only |
| `design-plan-v1` | same | `_build_design_plan_prompt` | approved spec, previous plan, clarifications | JSON Design Plan | Pydantic `DesignPlanPayload` plus link/dependency checks | attempt prompt/raw/plan path, plan row | yes, advanced route |
| design-plan schema repair | same | `_build_design_plan_prompt` repair branch | invalid raw output + error | repaired JSON | same | new attempt | yes |
| `openscad-generation-v3` | same | `_build_design_spec_openscad_prompt` | approved Design Specification | fenced OpenSCAD | source extraction + OpenSCAD source contract | attempt prompt/source/contract | yes via spec-only generation |
| `openscad-generation-v5` | same | `_build_planned_openscad_prompt` | approved spec + approved Design Plan | fenced OpenSCAD with output selector | source extraction + source contract + compile | attempt/revision/output artifacts | yes via Design Plan generation |
| `contract-repair-v2` | same | `_build_contract_repair_prompt` | rejected source + contract diagnostics | full fenced OpenSCAD | source extraction + source contract | repair attempt | yes |
| `legacy-compile-repair-v1` | same | legacy `_build_prompt` with compiler diagnostics | failed source + compiler diagnostics | full fenced OpenSCAD | source extraction + source contract before compile | repair attempt | yes for initial generation |
| `revision-planning-v1` | same | `_build_revision_plan_prompt` | base revision, spec, plan, manifest, source metadata, findings | JSON Revision Plan | Pydantic `RevisionPlanPayload` | attempt/revision plan row | yes, advanced route |
| revision-plan schema repair | same | `_build_revision_plan_prompt` repair branch | invalid raw output + error | repaired JSON | same | new attempt | yes |
| `openscad-revision-v2` | same | `_build_structured_revision_prompt` | approved Revision Plan + base source | full fenced OpenSCAD | source contract + compliance + compile | attempt/revision | technically reachable when no scoped context |
| `openscad-component-revision-v1` | same | `_build_component_revision_prompt` | approved Revision Plan + scoped context | full fenced OpenSCAD | source contract + compliance + output preservation | attempt/revision/summary | yes for normal structured revisions with scoped context |
| `scope-correction-v1` | same | `_build_scope_correction_prompt` | failed revised source + compliance findings | full fenced OpenSCAD | source contract + compliance | correction attempt | yes, one bounded attempt |
| `legacy-initial-v1` | same | legacy `_build_prompt` | raw project/user instruction | fenced OpenSCAD | source extraction + source contract | attempt/revision | yes in simple mode |
| `legacy-revision-v1` | same | legacy `_build_prompt` with current source | active source + instruction | fenced OpenSCAD | source extraction + source contract | attempt/revision | yes in simple mode with active revision |
| `cadquery-source-v2` | same | `build_cadquery_prompt` | benchmark/probe request, optional diagnostics/source | fenced Python | `extract_python_source` + `validate_cadquery_source` + optional runner | benchmark artifacts | benchmark/probe only |

Stale/dead paths:

- `clarification-v1` is documented in `docs/GEMINI_PROMPT_ARCHITECTURE.md`, but there is no separate implemented prompt mode; clarification is embedded in requirements, Design Plan, and Revision Plan JSON stages.
- Prompt snapshot fixtures only cover legacy OpenSCAD snapshots; current staged prompts are covered by assertions but not full snapshots.
- `openscad-revision-v2` is mostly superseded by component-scoped revision because `generate_from_revision_plan` always builds `scoped_revision_context`.
- Feature flags `enable_design_plans`, `enable_multi_output`, `enable_structured_revisions`, and `enable_strict_marker_contract` exist in settings/compose but are not the main backend gates; frontend build mode is the practical gate.

# 7. OpenSCAD Coupling Map

## Backend-neutral and reusable

| File/module | Responsibility | Inbound callers | Outbound dependencies | Persistence assumptions | Migration difficulty |
|---|---|---|---|---|---|
| `backend/app/models/design_specification.py` | versioned requirements | requirement extraction, planning, revision | JSON artifacts | provider/ruleset naming leak only | low |
| `backend/app/models/design_plan.py` | parametric product plan | planning, generation, config | JSON artifacts | output entries contain `module_name` but schema is extensible | medium |
| `backend/app/models/revision_plan.py` | structured revision and summaries | revision planning/generation | source metadata and output manifests | scope fields generic, fingerprints OpenSCAD-derived | medium |
| `backend/app/models/generation_attempt.py` | AI attempt observability | all AI stages | prompt/rendered files | `gemini_ruleset_version`, `extracted_source_path` | medium |
| `backend/app/models/validation_finding.py` | validation findings | validators and review | none specific | generic categories/rules | low |
| `backend/app/services/mesh/inspect.py` | STL metadata | runners/validators | trimesh | STL only | low for STL, medium for B-Rep |
| `backend/app/services/printability/inspector.py` | mesh printability | project service | trimesh/STL | mesh-based | low |
| candidate acceptance in `ProjectService` | candidate state transitions | API | findings | generic review states | low |

## Requires interface generalization

| File/module | Responsibility | Inbound callers | Outbound dependencies | Persistence assumptions | Migration difficulty |
|---|---|---|---|---|---|
| `backend/app/services/projects/service.py` | lifecycle orchestration | all API routes | AI providers, OpenSCAD runner, source validators | `scad_source_path`, `project.scad`, OpenSCAD source contract | high |
| `backend/app/schemas/project.py` | API contracts | FastAPI/frontend | Pydantic | `ManualRevisionCreate.scad_source`, `OpenScadParameterRead`, `RevisionRead.scad_source_path` | high |
| `backend/app/api/projects.py` | REST endpoints | frontend | `OpenScadCliRunner` dependency | SCAD filenames/media naming | medium |
| `backend/app/services/cad/runner.py` | compile result shape | service/tests | OpenSCAD CLI | returns STL only | medium |
| `backend/app/services/geometry/invariants.py` | geometry invariants | service/tests | source metadata markers + trimesh | OpenSCAD marker metadata | medium |
| `backend/app/services/generation/live_benchmarks.py` | benchmark probe loop | CLI/tests | OpenSCAD/CadQuery runners/providers | explicit source language switch | medium |
| `frontend/src/main.tsx` | UI/API client | browser | REST routes | labels mention Gemini/SCAD/source paths | high |
| `frontend/src/candidateView.ts` | candidate/output UI logic | frontend | API schemas | mostly generic but source checks infer source categories | low |
| `frontend/src/configurationView.ts` | configuration UI logic | frontend | API schemas | `source_mapped` and deterministic source controls | medium |

## OpenSCAD-specific and likely retained only for legacy projects

| File/module | Responsibility | Inbound callers | Outbound dependencies | Persistence assumptions | Migration difficulty |
|---|---|---|---|---|---|
| `backend/app/services/openscad/source_contract.py` | scanner, markers, source contract, module fingerprints | service, tests | regex/token scanner | OpenSCAD comments/modules/assignments | high |
| `backend/app/services/openscad/parameters.py` | extract editable OpenSCAD constants | API/service/frontend | regex parser | top-level SCAD assignments | medium |
| `backend/app/services/ai/source_extraction.py` | SCAD fenced extraction and top-level call checks | generation service | OpenSCAD scanner | fenced `scad`/`openscad` | medium |
| `backend/app/services/cad/runner.py` | OpenSCAD subprocess compile | service/output retry | `openscad` binary | `-D selected_output` | medium |
| OpenSCAD prompt builders in `gemini_cli.py` | source generation/repair/revision prompts | all providers | OpenSCAD syntax/markers | prompt versions persisted | high |
| `Revision.scad_source_path` | authoritative source path | all revision APIs | filesystem | mandatory SCAD name | high |
| `RevisionOutput.module_name` and `selected_output` | multi-output selector | compile loop/export | OpenSCAD `-D` | output module names | medium |
| `build_revision_export` | ZIP export | API | source path and STL paths | writes `project.scad` | medium |
| `cad-worker/Dockerfile` | OpenSCAD worker image | Compose | OpenSCAD package | idle, SCAD-only | low |

# 8. CAD Execution And Security Boundary

Process executing generated CAD source:

- OpenSCAD: `OpenScadCliRunner.compile` starts `openscad` as a subprocess from the API process.
- CadQuery probe: `CadQueryCliRunner.compile` writes generated `model.py` and a runner script, then starts the Python interpreter as a subprocess from the caller process.
- `volundr-cad-worker` does not execute jobs.

Container/user identity:

- `backend/Dockerfile` and `cad-worker/Dockerfile` do not set `USER`; Docker default is root.
- Local test execution uses the current host user.

Network/filesystem:

- API container has `/app/data` and `/home/volundr/.gemini` mounted.
- API container is on `volundr-internal`; outbound network is not disabled.
- Generated OpenSCAD source is written under `/app/data/jobs/<job_id>/model.scad`.
- CadQuery source and runner are written under the same workspace root.
- No Linux sandbox, seccomp profile, AppArmor profile, chroot, read-only root filesystem, or per-job container isolation is implemented in code.

Limits/timeouts:

- `VOLUNDR_CAD_TIMEOUT_SECONDS` default `60`.
- `max_source_bytes` default `500 KiB`.
- `max_stl_bytes` default `100 MiB`.
- subprocesses run in a new process group and are terminated on timeout.

Source screening:

- OpenSCAD runner blocks empty/oversize source and simple patterns for `import(`, `surface(`, `..`, and absolute path-like strings after comment stripping.
- OpenSCAD source-contract blocks `include`, `use`, suspicious paths, missing top-level model/selector calls, and structure issues.
- CadQuery runner validates Python AST: only `import cadquery as cq`, literal top-level assignments, function/class declarations, no unsafe direct calls, no dynamic calls, no imports inside functions, no try/with/global/nonlocal/dunder attributes.

Can generated code access arbitrary files or commands?

- OpenSCAD is screened for known file access constructs, but this is not a complete sandbox.
- CadQuery generated Python is AST-screened, but then imported/executed by Python. The current AST guard is not a security boundary equivalent to process/container isolation.
- The API environment may contain Gemini credentials; generated CAD subprocesses inherit the process environment unless explicitly scrubbed, which is not implemented.

Restricted CadQuery execution assessment:

- The current worker boundary could become suitable only after modification: make the worker real, run as a non-root user, mount only per-job input/output directories, remove Gemini credentials and API secrets, disable network or enforce egress policy, set CPU/memory/process limits, scrub environment, and use a narrow source contract.
- Source validation alone is not a sandbox.

# 9. Multi-Output And Artifact Model

Output declarations:

- Design Plan `printable_outputs` entries are parsed by `_planned_printable_outputs`.
- Supported `output_type`: `printable_component`, `repeated_printable_component`, `optional_printable_component`.
- Source contract requires `@volundr-output <id> module=<module_name> required=<true|false> filename=<...> components=<...>`.

Source-to-output mapping:

- One authoritative `project.scad`.
- `selected_output` plus `render_selected_output()` dispatch.
- Compile loop passes `-D selected_output="<output_id>"`.

Compilation loop:

- `_create_revision_from_planned_source` creates `RevisionOutput` rows, then `_compile_revision_output` compiles each output sequentially.
- Each output gets STL, log, metadata, command args, validation summary, and state.

Persistence:

- Assembly revision stores `expected_output_count`, `required_output_count`, `successful_output_count`, `blocked_output_count`, `failed_output_count`.
- Per-output records store `stl_path`, `stl_hash`, `compile_log_path`, `metadata_json`, `validation_summary_json`.
- `revision.stl_path` points to the first successful output for compatibility.

States:

- Output states include `queued`, `compiling`, `validating`, `ready`, `ready_with_warnings`, `blocked`, `failed`. `compiled` and `skipped` are documented/schema/UI concepts but not normal emitted service states.
- Revision review state derives from all findings: blocking -> `blocked`, any finding -> `ready_with_warnings`, none -> `ready`.

Retries:

- `retry_revision_output` only retries `failed` outputs and requires source hash match.
- It reuses active configuration `openscad_defines` when present.

Manifest/export:

- `_write_output_manifest` writes `output-manifest.json`.
- `/api/revisions/{revision_id}/export.zip` packages README, design spec, design plan, configuration/overrides when present, `project.scad`, manifest, assembly notes, and STLs.
- Single-output compatibility exists through `_legacy_revision_output_read` for revisions with `stl_path` and no `RevisionOutput` rows.

Generic vs SCAD-specific:

- Generic: output records, required/optional classification, artifact states, assembly blocking, STL metadata, ZIP concept.
- SCAD-specific: `module_name`, selector contract, `-D selected_output`, `project.scad` source name, source marker validation.

# 10. Geometry And Validation Architecture

Validation occurs both before meshing and after meshing:

- Before meshing: source extraction and OpenSCAD source-contract validation.
- After meshing: `inspect_stl`, geometric invariant analysis, printability checks, assembly output checks, revision success/output preservation checks.

Mesh inspection:

- `backend/app/services/mesh/inspect.py` uses `trimesh.load(..., force="mesh")`, concatenates scene meshes, records extents, absolute volume, triangle count, connected component count, watertight/winding state, center of mass.

Connected components:

- `_connected_component_count` unions face adjacency and counts connected face groups.
- `inspect_printability` emits `mesh.disconnected_components` warning when count > 1.
- `_is_blocking_printability_result` makes this blocking only when attached to a `RevisionOutput` that is required and has `len(component_ids) <= 1`.
- Multi-component output with multiple component IDs can therefore allow disconnected bodies as warning unless other findings block it.

Solid/body assumptions:

- STL mesh is the common validation artifact.
- There is no B-Rep/topological body validation.
- `CadQueryCliRunner` exports STEP opportunistically, but no STEP/BREP validation model exists.

Geometric invariants:

- `GeometryAnalyzerRegistry.default()` runs bounding box, build-plate, cylindrical-hole, hole-group, and wall-thickness analyzers.
- Supported source markers: `@volundr-geometry type=bounds|hole|hole_group|wall_thickness`.
- Bounding box uses protected requirement mappings and tolerances.
- Hole detection is axis-aligned and confidence-based.
- Wall thickness is a coarse smallest bounding-box extent heuristic.
- Missing geometry markers for protected invariants create warning/unverifiable findings, not blocking.

Printability:

- Rules include empty/zero volume, watertightness, disconnected components, above/below build plate, contact area, minimum thickness, small features/gaps/holes, overhangs, bridge spans, unsupported ceilings/cavities, build volume.
- Blocking rule IDs: `mesh.empty_or_zero_volume`, `orientation.below_build_plate`, `orientation.above_build_plate`, `profile.build_volume`.
- Critical feature rules block only for configured IDs: `feature.minimum_thickness`, `feature.small_features_gaps_holes`.
- Many risks are advisory because orientation/profile/user choice matters.

Output/assembly scoping:

- Per-output findings attach to both `revision_id` and `revision_output_id`.
- Assembly findings attach to revision only.
- Revision success criteria and output preservation add blocking findings when criteria fail.

# 11. Parameter And Configuration Architecture

Parameter sources:

- Design Specification parameters/dimensions have IDs, labels, values, units, source, importance, protected/editable flags.
- Design Plan parameters have IDs, labels, values, type inferred or explicit, editability, protection, component ownership, and optional `source_requirement_id`.
- Design Plan derived parameters have expressions and dependencies.

Source marker mapping:

- OpenSCAD source contract parses top-level assignments and markers:
  - `@volundr-requirement`
  - `@volundr-parameter`
  - `@volundr-dependency`
  - `@volundr-component`
  - `@volundr-feature`
  - `@volundr-output`
- `extract_editable_parameters` separately parses simple top-level constants for read-only revision parameter display.

Command-line overrides:

- Deterministic configuration uses `OpenScadCliRunner._define_args` to pass `-D key=value`.
- `_resolve_configuration` only allows directly editable, source-mapped, OpenSCAD-identifier parameter IDs.
- Derived parameters are not directly editable.
- Unsupported types return `requires_design_revision`.

Dependency expansion:

- `_affected_parameters` expands Design Plan `dependency_edges` transitively.
- `_configuration_impacts` maps affected parameters to components/features/outputs.

Preset behavior:

- Design Plan embedded presets and user-created `configuration_presets` are both supported.
- Preview writes `configuration.json` and `parameter-overrides.json`.
- Generate from configuration recompiles unchanged source and persists a candidate linked to `configuration_change_id`.

Reproducibility:

- Configuration generation checks `base_source_hash`.
- Output retry checks source hash.
- Generated configuration revisions record override manifests and updated configured design specification payloads.

CadQuery mapping:

- Directly reusable: typed parameter concepts, editable/protected flags, dependency graph, preset resolution, configuration change records.
- Needs interface: parameter-to-source mapping, deterministic regeneration, and source hash checks.
- OpenSCAD-specific: `-D` defines, OpenSCAD identifier validation, SCAD assignment scanner, Customizer comment parser.

# 12. Revision Architecture

Revision Plan creation:

- `create_revision_plan` requires a successful base revision with an approved Design Plan.
- It collects Design Specification JSON, Design Plan JSON, output manifest, selected findings, base source, and OpenSCAD source metadata.
- It calls `ai_provider.create_revision_plan`.

Clarification/approval:

- Revision Plans can be `clarification_required`, `pending_review`, `approved`, or `rejected`.
- Clarification answers create a superseding plan.
- Generation requires approved, non-superseded plan.

Design Specification/Plan versioning:

- Revision Plan payload can request revised spec/plan snapshots.
- `_persist_revision_specification_snapshot` and `_persist_revision_design_plan_snapshot` copy JSON and apply simple parameter/requested value updates.
- These snapshots are implementation-simple and not a full product-structure recomputation.

Complete-source revision:

- Gemini returns full SCAD source, not patches/fragments.
- Source extraction requires a full valid SCAD source block.

Component targeting:

- Source ownership comes from OpenSCAD markers and normalized module fingerprints.
- Protected modules/features/outputs/interfaces are validated in `_revision_compliance_findings`.
- Output preservation compares STL hash, dimensions, volume, and connected component count with tolerances.
- Configuration preservation requires configured parameters to remain exposed.

Success criteria:

- Implemented checks: `parameter_value`, `parameter_unchanged`, `output_exists`.
- Other criterion types become `success_unverifiable`, nonblocking.

Boundedness assessment:

- Revisions are bounded by a mix of prompt instructions and deterministic source validation.
- Deterministic checks cover marker preservation, top-level parameter changes, module fingerprint drift, output mappings, configured parameter presence, selected output existence, and coarse output equivalence.
- They do not prove arbitrary feature semantics, assembly fit, load performance, or precise localized geometry changes.

# 13. API And Frontend State

Active backend endpoints include:

- Project: `POST /api/projects`, `POST /api/projects/draft`, `GET /api/projects`, `GET/PATCH /api/projects/{project_id}`, `POST /api/projects/{project_id}/save`, `POST /api/projects/{project_id}/archive`, `DELETE /api/projects/{project_id}`, `GET /api/projects/{project_id}/messages`.
- Requirements/specs: `POST /api/projects/{project_id}/requirements`, `GET /api/projects/{project_id}/design-specification`, `GET /api/design-specifications/{specification_id}`, clarification question/answer routes, `POST /api/design-specifications/{specification_id}/generate`.
- Design Plans: `GET /api/projects/{project_id}/design-plan`, `GET /api/design-plans/{design_plan_id}`, create, approve, reject, clarification answer, generate.
- Revisions/candidates: `POST /api/projects/{project_id}/revisions`, `POST /api/projects/{project_id}/generate`, `GET /api/projects/{project_id}/revisions`, `GET /api/projects/{project_id}/candidates`, `GET /api/candidates/{revision_id}`, accept/reject, restore.
- Outputs/artifacts: source, parameters, compile log, AI output, diff, STL, output list, output STL/log/findings/geometric analysis/retry, output manifest, export ZIP.
- Revision Plans: current/get/create/approve/reject/clarifications/generate/compliance/scope/module comparison/component summary/success results.
- Configuration: parameters, presets, preview, change read, override manifest, generate.
- Printability profiles and one-off revision printability inspection.

Legacy/duplicate paths:

- `/projects/{id}/generate` direct generation vs staged `/requirements` + `/design-plan` + `/generate`.
- `/design-specifications/{id}/generate` spec-only OpenSCAD vs Design Plan generation.
- Manual revision compile accepts SCAD directly.
- `get_revision_parameters` exposes OpenSCAD-scanned parameters separately from structured configuration parameters.

Feature flags:

- Backend settings include advanced feature flags, but service code mainly relies on `generation_mode`.
- Frontend `ADVANCED_WORKFLOW_ENABLED` from `VITE_VOLUNDR_GENERATION_MODE` controls visibility of advanced staged UI.

Frontend screens/components:

- `frontend/src/main.tsx`: workspace, chat, project drawer, editor, STL viewer, diagnostics, revisions, candidate review, advanced panels.
- `frontend/src/designSpecificationView.ts`: requirement state helpers.
- `frontend/src/designPlanView.ts`: Design Plan state helpers.
- `frontend/src/revisionPlanView.ts`: Revision Plan/compliance/success/summary helpers.
- `frontend/src/configurationView.ts`: configuration controls and state labels.
- `frontend/src/candidateView.ts`: candidate/output/finding helpers.
- `frontend/e2e/candidate-workflow.spec.ts`: mocked advanced candidate/revision flow.

Backend functionality not exposed in default UI:

- Staged requirements, Design Plans, structured revisions, and configuration are hidden in simple frontend mode.
- CadQuery source probe is benchmark CLI only.
- Provider selection is environment-only.

UI assumptions not enforced by backend:

- Frontend says “Message Gemini” even when backend default provider is Ollama.
- Playwright e2e assumes advanced mode and specific button enablement not satisfied in current run.
- Frontend state is request/response based; no polling/events for long-running generation beyond pending button state.

# 14. Tests And Verification Quality

Backend tests:

- 277 passed, 1 skipped locally with `.venv/bin/python -m pytest -q`.
- Covers providers, runner behavior, source extraction, source contract, generation API, candidate revisions, Design Specifications, Design Plans, multi-output, geometric pipeline, parameter configuration, structured revisions, CadQuery contract, and live benchmark dry-run logic.
- Many lifecycle tests use fake AI providers and fake runners; they prove orchestration/persistence, not live provider quality.
- OpenSCAD is installed; backend runner tests include actual OpenSCAD execution for small fixtures.
- CadQuery runner tests mostly validate contract rejection and missing dependency behavior; CadQuery is not installed in the test environment.

Frontend tests:

- Vitest passed: 6 files, 38 tests.
- Production build passed.
- Playwright e2e failed in default simple mode because the test waits for advanced `Plan revision`.
- Playwright e2e also failed with `VITE_VOLUNDR_GENERATION_MODE=advanced` because `Generate revision` remained disabled after plan approval in the mocked workflow.

Migration tests:

- Alembic head exists: `0014_design_plan_clarifications`.
- `alembic current` with default `/app/data` failed locally because `/app/data` did not exist outside Docker.
- Fresh temporary database upgrade with `VOLUNDR_DATA_DIR=/tmp/...` passed through head.

Benchmark fixtures:

- Dry-run benchmark command passed for one case and wrote ignored output artifacts.
- Live-provider benchmark coverage exists but was not run to avoid provider/quota usage.

Verification commands run:

| Command | Result |
|---|---|
| `cd backend && .venv/bin/python -m pytest -q` | passed: 277 passed, 1 skipped, 2 warnings |
| `cd frontend && npm test -- --run` | passed: 6 files, 38 tests |
| `cd frontend && npm run build` | passed |
| `cd frontend && npm run test:e2e` | failed: default simple frontend lacks `Plan revision` button |
| `cd frontend && VITE_VOLUNDR_GENERATION_MODE=advanced npm run test:e2e` | failed: `Generate revision` button stayed disabled after approval |
| `cd backend && .venv/bin/alembic heads` | `0014_design_plan_clarifications (head)` |
| `cd backend && .venv/bin/alembic current` | failed locally: default `/app/data` database path unavailable |
| `cd backend && VOLUNDR_DATA_DIR=/tmp/... .venv/bin/alembic upgrade head && ... current` | passed; current head `0014_design_plan_clarifications` |
| `cd backend && .venv/bin/python scripts/run_live_generation_benchmarks.py --provider dry-run --max-cases 1 --max-runs 1 --run-label audit-dry-run` | passed; one dry-run case, no provider calls |
| `docker compose config` | passed; rendered config includes environment values from `.env` |
| `git diff --check` | passed after writing this document |
| `git status --short --untracked-files=all` | only `docs/CURRENT_REPOSITORY_AUDIT.md` is untracked after writing this document |

# 15. Documentation Accuracy

Accurate or mostly accurate:

- `docs/DATA_MODEL.md`: close to implemented tables and fields.
- `docs/MULTI_OUTPUT_GENERATION.md`: matches implemented multi-output records, selector compilation, retry, and ZIP export with minor state vocabulary drift.
- `docs/PARAMETER_CONFIGURATION.md`: aligns with OpenSCAD `-D` deterministic configuration.
- `docs/STRUCTURED_REVISION_PLANNING.md`: aligns with Revision Plan lifecycle and compliance checks.
- `docs/COMPONENT_TARGETED_REVISIONS.md`: aligns with full-source component revision and source-scope validation approach.
- `docs/GEOMETRIC_INVARIANT_VALIDATION.md`: aligns with current supported markers/analyzers and confidence limitations.
- `docs/LIVE_GENERATION_EVALUATION.md`: accurately documents benchmark/probe purpose and CadQuery probe limits.
- `docs/CAD_EXECUTION_SECURITY.md`: accurate as a target/concern document, but stronger than current worker implementation.

Stale or contradictory claims:

- `README.md` and `PRODUCT_DIRECTION.md` still describe OpenSCAD and Gemini CLI as core V1 defaults, while config/compose default to Ollama/simple workflow and current branch contains CadQuery probes.
- `docs/ARCHITECTURE.md` says the backend communicates with `volundr-cad-worker`; implementation compiles inside API and worker is idle.
- `docs/GEMINI_PROMPT_ARCHITECTURE.md` names `clarification-v1` as a distinct stage, but implementation embeds clarification in JSON stage outputs.
- `docs/CURRENT_STAGE_ROADMAP.md` is append-heavy and mixes completed, next, deferred, and branch-specific CadQuery probe status; it is not a crisp current-state document.
- `docs/DOCKER_BASELINE.md` describes CAD worker isolation as intended; Compose does not disable network and worker does not process jobs.

Missing authoritative documents:

- No CAD backend abstraction design.
- No CadQuery product lifecycle contract equivalent to OpenSCAD `MODEL_GENERATION_CONTRACT`.
- No provider-neutral prompt/ruleset naming plan.
- No security design for executing restricted generated Python in production.
- No current branch status document distinguishing `main` from `cadquery-v1-backend`.

Duplicate/contradictory rules:

- Gemini as primary vs Ollama default.
- OpenSCAD as deterministic kernel vs CadQuery probe branch.
- Worker as execution boundary vs API subprocess execution.
- Simple generation default vs staged lifecycle as strategic product direction.

# 16. Reported Commit Verification

All reported commits are present in current ancestry.

| Commit | Commit subject | Present in ancestry | Primary files changed | Reported feature | Verified implementation status | Discrepancies |
|---|---|---|---|---|---|---|
| `f7cadb2` | Implement generation reliability priority zero | yes | `generation_attempt.py`, `failure_taxonomy.py`, `benchmarks.py`, provider/service tests/docs | generation reliability Priority 0 | Generation attempts, failure taxonomy, benchmark fixtures, prompt snapshots are present and tested | Later defaults/simple workflow mean not all reliability stages are default UI path |
| `2a92f8f` | Implement candidate revision validation gates | yes | `revision.py`, `validation_finding.py`, API/service/frontend candidate files/tests | candidate revision validation gates | Candidate states, accept/reject, blocking finding checks, validation findings are implemented | Manual first revision can auto-accept; candidate lifecycle does not cover all legacy/manual cases equally |
| `0b5bace` | Implement staged requirement extraction | yes | `design_specification.py`, clarification models, provider/service/API/frontend/tests/docs | staged requirement extraction | Requirements extraction, clarification, immutable spec versions, schema repair are implemented | Default simple mode bypasses this stage |
| `9f2969f` | Implement pre-compile source contract validation | yes | `source_validation_result.py`, `source_contract.py`, source extraction/provider/service/tests/docs | pre-compile source contract validation | OpenSCAD source contract validation persists results and blocks hard failures | Manual source compile uses runner screening but not the full AI source-contract pipeline |
| `2e2a937` | Implement geometric invariant validation | yes | `geometric_analysis_result.py`, `geometry/invariants.py`, service/tests/docs | geometric invariant validation | Post-compile analyzers and persisted findings are implemented | Coverage limited to marked/simple geometry; unverifiable cases warn |
| `b71cbf5` | Realign next generation reliability task | yes | roadmap/product/prompt docs | roadmap realignment | Documentation updated | Documentation-only; later docs drift remains |
| `57d3030` | Implement design plan foundation | yes | `design_plan.py`, provider/service/API/frontend/tests/docs | Design Plan foundation | Design Plan schema, creation, approval, clarification, prompt version are implemented | Hidden by default simple frontend mode |
| `2530217` | Implement multi-output generation and export | yes | `revision_output.py`, runner/service/API/frontend/tests/docs | multi-output generation and export | Per-output compile, manifest, ZIP export, retry, legacy compatibility are implemented | SCAD selector-specific; no CadQuery multi-output integration |
| `f8e6ae9` | Implement structured revision planning | yes | `revision_plan.py`, provider/service/API/frontend/tests/docs | structured revision planning | Revision Plan persistence, approval, compliance/success results are implemented | Boundedness depends partly on OpenSCAD source markers and prompt compliance |
| `434214f` | Implement deterministic parameter configuration | yes | `configuration_change.py`, service/API/frontend/tests/docs | deterministic parameter configuration | Preview, presets, override manifest, deterministic recompilation from same source hash are implemented | OpenSCAD `-D` only; no CadQuery parameter execution path |
| `383efe6` | Implement component-targeted full-source revisions | yes | `revision_plan.py`, source_contract.py`, service/API/frontend/tests/docs | component-targeted full-source revisions | Scoped context, module fingerprints, protected output/interface checks, summaries are implemented | Source edits still generated by prompt; geometric/component equivalence is coarse |

# 17. Current Technical Debt And Risks

Critical:

- Generated CAD currently runs in the API process/container boundary with mounted data and Gemini credentials; `volundr-cad-worker` is not a real sandbox.
- CadQuery generated Python would execute with Python interpreter privileges; AST validation reduces obvious misuse but is not sufficient for hostile code.

High:

- OpenSCAD coupling is pervasive in persistence (`scad_source_path`), APIs, prompts, output selection, parameter configuration, source markers, export packaging, and validation.
- Default simple workflow bypasses newer staged Design Specification/Design Plan/Revision Plan lifecycle.
- Provider defaults conflict with stated Gemini-primary direction; runtime defaults use Ollama.
- Playwright e2e is currently failing, indicating frontend advanced workflow drift.
- The CAD worker Docker image references a job worker but only idles, creating a misleading deployment boundary.

Medium:

- `gemini_ruleset_version` naming leaks into provider-neutral tables and records.
- Source markers can be missing, stale, or semantically false; validation may warn rather than block when geometry is unverifiable.
- Output preservation uses mesh hashes/dimensions/volume/component count, not assembly or B-Rep semantics.
- `alembic current` fails locally unless `VOLUNDR_DATA_DIR` is explicitly set.
- Compose config can expose `.env` secrets when rendered in logs.
- Feature flags exist but are not consistently enforced as backend gates.

Low:

- Prompt snapshots are limited mostly to legacy prompt fixtures.
- Some documented output states are not currently emitted.
- README is behind current branch reality.

# 18. CadQuery Migration Readiness

Reusable unchanged:

- Projects, messages, Design Specifications, much of Design Plan/Revision Plan schema, generation attempts concept, candidate acceptance, validation findings, STL mesh inspection, printability inspector, basic geometric analyzers on STL, configuration/preset data concepts.

Needs backend interface:

- CAD source artifact model.
- Source extraction and source contract.
- CAD runner compile result abstraction.
- Output declaration/selection model.
- Deterministic parameter override/regeneration.
- Export packaging.
- Prompt routing/versioning.
- Source metadata and revision compliance fingerprints.

Must be newly implemented:

- CadQuery product lifecycle path from Design Plan to candidate revision.
- CadQuery multi-output contract.
- CadQuery parameter mapping and deterministic regeneration.
- Restricted Python execution sandbox.
- STEP/BREP artifact persistence and validation.
- B-Rep/topological body validation.
- CadQuery structured revision/compliance model.

Should remain legacy:

- OpenSCAD scanner, markers, `selected_output` dispatcher, `-D` overrides, SCAD repair prompts, OpenSCAD process runner, SCAD parameter extraction.

Likely database changes:

- Add source language/backend fields to revision, generation attempt, source validation, output manifest, and export metadata.
- Replace or supplement `scad_source_path` with backend-neutral `source_path`/`source_language`.
- Add STEP/BREP paths/hashes on outputs or artifact table.
- Add provider-neutral ruleset/contract version columns or aliases.

Readiness matrix:

| Capability | Readiness | Evidence |
|---|---|---|
| backend-neutral CAD abstraction | partially ready | runner concept exists, but service/API/persistence are SCAD-specific |
| CadQuery source contract | partially ready | `cadquery_contract.py` and prompt exist for probes only |
| restricted Python execution | not ready | subprocess execution lacks real sandbox/no-network/no-secrets/non-root boundary |
| B-Rep validation | not ready | only STL/trimesh validation is persisted |
| STEP/BREP/STL artifacts | partially ready | CadQuery runner exports STEP opportunistically; DB/API/export only understand STL broadly |
| deterministic parameter regeneration | partially ready | concept exists; implementation is OpenSCAD `-D` only |
| multi-output generation | partially ready | generic records exist; selection is SCAD selector-specific |
| structured revisions | partially ready | lifecycle exists; compliance depends on SCAD markers/fingerprints |
| component-targeted revisions | partially ready | architecture exists; source ownership is SCAD scanner-specific |

# 19. Smallest Safe Migration Sequence

1. Add backend/source-language metadata without behavior change.
   - Objective: make current OpenSCAD artifacts explicitly typed.
   - Affected: models/migrations/schemas/service/export/API responses/frontend types.
   - Prerequisites: passing current backend/frontend tests.
   - Compatibility: backfill existing revisions as `openscad`.
   - Verification: migration upgrade, API regression tests, export tests.
   - Rollback boundary: remove metadata columns before dependent behavior lands.
   - Deferred: CadQuery generation.

2. Introduce a CAD backend interface around current OpenSCAD runner.
   - Objective: isolate compile request/result, source extension, artifact types, and parameter override semantics.
   - Affected: `services/cad`, `ProjectService`, tests.
   - Prerequisites: source-language metadata.
   - Compatibility: OpenSCAD adapter is the only product adapter.
   - Verification: existing OpenSCAD lifecycle tests unchanged.
   - Rollback: keep direct `OpenScadCliRunner` path behind adapter.
   - Deferred: CadQuery product routes.

3. Move CAD execution into a real worker/sandbox boundary for OpenSCAD first.
   - Objective: prove job execution isolation before Python.
   - Affected: `cad-worker`, Docker Compose, CAD adapter transport, tests/docs.
   - Prerequisites: CAD backend interface.
   - Compatibility: API behavior unchanged.
   - Verification: integration compile, timeout, secret absence, network/user checks.
   - Rollback: API local runner remains fallback during pass.
   - Deferred: CadQuery defaulting.

4. Define CadQuery v1 product source contract and artifact schema.
   - Objective: promote probe contract into product-ready backend contract.
   - Affected: docs, schemas, contract validator, prompts, tests.
   - Prerequisites: security boundary design accepted.
   - Compatibility: OpenSCAD remains default.
   - Verification: contract unit tests, malicious-source tests, prompt snapshot tests.
   - Rollback: keep as disabled backend.
   - Deferred: revisions/configuration.

5. Add CadQuery single-output generation behind an explicit backend flag.
   - Objective: generate one candidate from existing Design Specification/Design Plan to STL/STEP.
   - Affected: provider prompt routing, source extraction, runner adapter, artifact persistence, API/frontend minimal display.
   - Prerequisites: CadQuery dependency in worker image and sandbox.
   - Compatibility: OpenSCAD default and legacy projects unaffected.
   - Verification: fake provider, real local CadQuery fixture if installed, export includes source/STL/STEP.
   - Rollback: disable backend flag.
   - Deferred: deterministic config and structured revisions.

6. Add CadQuery multi-output contract.
   - Objective: produce multiple declared artifacts without SCAD selectors.
   - Affected: Design Plan output contract, runner, manifest, export.
   - Prerequisites: single-output CadQuery path.
   - Compatibility: OpenSCAD selector retained for OpenSCAD revisions.
   - Verification: multi-output fixture, partial failure, retry semantics.
   - Rollback: single-output CadQuery remains.
   - Deferred: B-Rep analysis.

7. Add CadQuery deterministic parameter regeneration.
   - Objective: map typed Design Plan parameters to safe Python constants.
   - Affected: configuration service, source contract metadata, runner input.
   - Prerequisites: stable CadQuery source parameter contract.
   - Compatibility: OpenSCAD `-D` unchanged.
   - Verification: hash reproducibility, invalid parameter tests, preset tests.
   - Rollback: route configuration to revision planning for CadQuery.
   - Deferred: arbitrary source edits.

8. Add CadQuery structured revisions and component targeting.
   - Objective: reimplement revision compliance using CadQuery source metadata/B-Rep artifacts.
   - Affected: revision prompts, source metadata, compliance validators, output preservation.
   - Prerequisites: multi-output and parameter contracts.
   - Compatibility: OpenSCAD legacy revisions keep existing path.
   - Verification: scoped revision fixture tests and e2e recovery.
   - Rollback: disable CadQuery revision generation while keeping initial generation.
   - Deferred: advanced assembly/B-Rep proof.

# 20. Recommended Immediate Next Task

Recommended next implementation pass: add source-language/backend metadata and a CAD backend abstraction around the existing OpenSCAD path, with no CadQuery product behavior enabled.

Why it comes next:

- It preserves current behavior while removing the biggest architectural ambiguity: whether a revision/source/output is OpenSCAD or something else.
- It gives CadQuery a place to plug in without copying the whole lifecycle or corrupting existing OpenSCAD assumptions.
- It can be verified entirely with current non-live tests.

Exact scope:

- Add backend-neutral source/artifact fields or aliases.
- Backfill existing revisions as OpenSCAD.
- Introduce an interface/adapter for OpenSCAD compile requests/results.
- Update API schemas/frontend types only as needed to display existing OpenSCAD behavior unchanged.
- Keep all existing routes working.

Explicit exclusions:

- No CadQuery default.
- No generated Python execution in product workflow.
- No prompt migration.
- No B-Rep validation.
- No UI redesign.
- No provider default change.

Completion criteria:

- Existing backend tests pass.
- Frontend tests/build pass.
- Alembic fresh upgrade passes.
- Existing manual/simple/OpenSCAD generation behavior remains API-compatible.
- Reported artifact paths still resolve.
- No live AI calls are required.

Major risks:

- Migration naming churn can break frontend/API compatibility.
- If abstraction is too broad, it may obscure real OpenSCAD behavior; keep the first pass thin and evidence-driven.

# 21. Open Questions Requiring Product Decisions

- Should new projects default to CadQuery immediately after a backend exists, or should CadQuery be opt-in until benchmark evidence beats OpenSCAD?
- Should OpenSCAD remain user-selectable for new projects, or only for legacy revisions?
- Is STEP, BREP, or STL the authoritative generated geometry artifact for CadQuery projects?
- Is arbitrary CadQuery syntax allowed within a sandbox, or must generated source use a constrained Volundr wrapper/SDK?
- Should Gemini API be restored as the default primary runtime provider, or is Ollama the current intended default with Gemini as an explicit option?
- Should the simple chat workflow remain the default, or should the staged lifecycle become the default product workflow again?
- Should user-visible manual source editing support CadQuery, or stay OpenSCAD-only during migration?

# 22. Appendix

Important file paths:

- Backend app: `backend/app/`
- API router: `backend/app/api/projects.py`
- Main orchestration service: `backend/app/services/projects/service.py`
- Settings: `backend/app/core/config.py`
- AI provider protocol: `backend/app/services/ai/provider.py`
- Gemini CLI/API providers: `backend/app/services/ai/gemini_cli.py`, `backend/app/services/ai/gemini_api.py`
- Ollama provider: `backend/app/services/ai/ollama.py`
- Source extraction: `backend/app/services/ai/source_extraction.py`
- OpenSCAD runner: `backend/app/services/cad/runner.py`
- CadQuery runner/contract: `backend/app/services/cad/cadquery_runner.py`, `backend/app/services/cad/cadquery_contract.py`
- OpenSCAD contract/parameters: `backend/app/services/openscad/source_contract.py`, `backend/app/services/openscad/parameters.py`
- Mesh/geometry/printability: `backend/app/services/mesh/inspect.py`, `backend/app/services/geometry/invariants.py`, `backend/app/services/printability/inspector.py`
- Frontend app: `frontend/src/main.tsx`
- Frontend helpers: `frontend/src/candidateView.ts`, `designSpecificationView.ts`, `designPlanView.ts`, `configurationView.ts`, `revisionPlanView.ts`
- Docker: `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `cad-worker/Dockerfile`

Active prompt versions:

- `requirements-v1`
- `source-brief-v1`
- `design-plan-v1`
- `openscad-generation-v3`
- `openscad-generation-v5`
- `revision-planning-v1`
- `openscad-revision-v2`
- `openscad-component-revision-v1`
- `scope-correction-v1`
- `legacy-initial-v1`
- `legacy-revision-v1`
- `contract-repair-v2`
- `legacy-compile-repair-v1`
- `cadquery-source-v2`

Current migration head:

- `0014_design_plan_clarifications`.

Artifact directory layout:

```text
data/
├── app.db
├── jobs/
└── projects/
    └── <project_id>/
        ├── generation-runs/<attempt_id>/
        ├── revisions/<revision_id>/
        │   ├── model.scad
        │   ├── project.scad
        │   ├── model.stl
        │   ├── compile.log
        │   ├── output-manifest.json
        │   ├── stl/
        │   ├── logs/
        │   ├── metadata/
        │   └── geometry/
        ├── revision-plans/<revision_plan_id>/
        └── configuration-changes/<configuration_change_id>/
```

Environment variables:

- `VOLUNDR_DATA_DIR`
- `VOLUNDR_CAD_WORKSPACE_DIR`
- `VOLUNDR_OPENSCAD_BINARY`
- `VOLUNDR_CAD_TIMEOUT_SECONDS`
- `VOLUNDR_AI_PROVIDER`
- `VOLUNDR_OLLAMA_BASE_URL`
- `VOLUNDR_OLLAMA_MODEL`
- `VOLUNDR_OLLAMA_TIMEOUT_SECONDS`
- `VOLUNDR_OLLAMA_THINK`
- `VOLUNDR_GEMINI_BINARY`
- `VOLUNDR_GEMINI_MODEL`
- `VOLUNDR_GEMINI_TIMEOUT_SECONDS`
- `VOLUNDR_GEMINI_POLICY_PATH`
- `GEMINI_API_KEY`
- `VOLUNDR_GEMINI_API_KEY`
- `VOLUNDR_GEMINI_API_BASE_URL`
- `VOLUNDR_GEMINI_API_TEMPERATURE`
- `VOLUNDR_GEMINI_API_MAX_OUTPUT_TOKENS`
- `VOLUNDR_GEMINI_API_THINKING_LEVEL`
- `VOLUNDR_GEMINI_API_MAX_RETRIES`
- `VOLUNDR_GEMINI_API_MAX_RETRY_SLEEP_SECONDS`
- `VOLUNDR_GENERATION_MODE`
- `VOLUNDR_ENABLE_DESIGN_PLANS`
- `VOLUNDR_ENABLE_MULTI_OUTPUT`
- `VOLUNDR_ENABLE_STRUCTURED_REVISIONS`
- `VOLUNDR_ENABLE_STRICT_MARKER_CONTRACT`
- `VITE_VOLUNDR_GENERATION_MODE`
- `VOLUNDR_WEB_PORT`
- `VOLUNDR_GEMINI_DIR`

Docker services:

- `volundr-web`
- `volundr-api`
- `volundr-cad-worker`

Active API route inventory:

- `/health`
- `/api/projects`
- `/api/projects/draft`
- `/api/projects/{project_id}`
- `/api/projects/{project_id}/save`
- `/api/projects/{project_id}/archive`
- `/api/projects/{project_id}/messages`
- `/api/projects/{project_id}/active-revision`
- `/api/projects/{project_id}/requirements`
- `/api/projects/{project_id}/design-specification`
- `/api/design-specifications/{specification_id}`
- `/api/design-specifications/{specification_id}/design-plan`
- `/api/design-specifications/{specification_id}/clarification-questions`
- `/api/design-specifications/{specification_id}/clarification-answers`
- `/api/design-specifications/{specification_id}/generate`
- `/api/projects/{project_id}/design-plan`
- `/api/design-plans/{design_plan_id}`
- `/api/design-plans/{design_plan_id}/approve`
- `/api/design-plans/{design_plan_id}/reject`
- `/api/design-plans/{design_plan_id}/clarification-questions`
- `/api/design-plans/{design_plan_id}/clarification-answers`
- `/api/design-plans/{design_plan_id}/generate`
- `/api/projects/{project_id}/revision-plan`
- `/api/projects/{project_id}/revision-plans`
- `/api/revision-plans/{revision_plan_id}`
- `/api/revision-plans/{revision_plan_id}/approve`
- `/api/revision-plans/{revision_plan_id}/reject`
- `/api/revision-plans/{revision_plan_id}/clarification-questions`
- `/api/revision-plans/{revision_plan_id}/clarification-answers`
- `/api/revision-plans/{revision_plan_id}/generate`
- `/api/revision-plans/{revision_plan_id}/compliance-result`
- `/api/revision-plans/{revision_plan_id}/component-scope`
- `/api/revision-plans/{revision_plan_id}/module-ownership-comparison`
- `/api/revision-plans/{revision_plan_id}/component-revision-summary`
- `/api/revision-plans/{revision_plan_id}/success-results`
- `/api/projects/{project_id}/configuration/parameters`
- `/api/projects/{project_id}/configuration/presets`
- `/api/projects/{project_id}/configuration/preview`
- `/api/configuration-changes/{configuration_change_id}`
- `/api/configuration-changes/{configuration_change_id}/override-manifest`
- `/api/configuration-changes/{configuration_change_id}/generate`
- `/api/projects/{project_id}/revisions`
- `/api/projects/{project_id}/generate`
- `/api/projects/{project_id}/candidates`
- `/api/candidates/{revision_id}`
- `/api/candidates/{revision_id}/findings`
- `/api/candidates/{revision_id}/geometric-analysis`
- `/api/candidates/{revision_id}/accept`
- `/api/candidates/{revision_id}/reject`
- `/api/revisions/{revision_id}/outputs`
- `/api/revision-outputs/{output_artifact_id}`
- `/api/revision-outputs/{output_artifact_id}/findings`
- `/api/revision-outputs/{output_artifact_id}/geometric-analysis`
- `/api/revision-outputs/{output_artifact_id}/retry`
- `/api/revision-outputs/{output_artifact_id}/stl`
- `/api/revision-outputs/{output_artifact_id}/compile-log`
- `/api/revisions/{revision_id}/source`
- `/api/revisions/{revision_id}/parameters`
- `/api/revisions/{revision_id}/compile-log`
- `/api/revisions/{revision_id}/ai-output`
- `/api/revisions/{revision_id}/diff`
- `/api/revisions/{revision_id}/stl`
- `/api/revisions/{revision_id}/output-manifest`
- `/api/revisions/{revision_id}/export.zip`
- `/api/revisions/{revision_id}/printability`
- `/api/revisions/{revision_id}/restore`
- `/api/validation-findings/{finding_id}/dismiss`
- `/api/generation-attempts/{attempt_id}/findings`
- `/api/printability-profiles`
- `/api/printability-profiles/{profile_id}`
