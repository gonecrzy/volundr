# Volundr Architecture

This document defines Volundr's technical shape: major components, service boundaries, provider interfaces, runtime flow, storage layout, and deployment model.

## Decision Status

`docs/CADQUERY_BACKEND.md` is the current architecture authority for the
CadQuery-primary product path. Historical OpenSCAD-era details in older docs are
superseded where they conflict with the CadQuery backend document.

## System Overview

```text
┌───────────────────────────────────────────────┐
│ Browser                                       │
│ React + TypeScript                            │
│                                               │
│ - persistent chat workspace                   │
│ - conversation, viewer, and inspector         │
│ - prompt and revision input                   │
│ - source editor                               │
│ - Three.js STL viewer                         │
│ - revision history                            │
└──────────────────────┬────────────────────────┘
                       │ HTTPS / JSON / SSE
┌──────────────────────▼────────────────────────┐
│ FastAPI Backend                               │
│                                               │
│ - project API                                 │
│ - revision API                                │
│ - requirement extraction and clarification    │
│ - Design Plan generation and validation       │
│ - requirement-led revision planning           │
│ - generation orchestration                    │
│ - multi-output artifact orchestration         │
│ - candidate revision review and acceptance    │
│ - pre-execution source-contract checks        │
│ - post-compile geometric invariant checks     │
│ - AI provider interface                       │
│ - CAD runner interface                        │
│ - persisted validation findings               │
│ - asset delivery                              │
│ - output manifest and ZIP export              │
│ - workflow observability and debug bundles    │
│ - live benchmark artifact collection          │
│ - SQLite persistence                          │
└───────────────┬───────────────────┬───────────┘
                │                   │
       ┌────────▼────────┐  ┌──────▼───────────┐
       │ Gemini API      │  │ CAD Worker       │
       │ Provider        │  │                  │
       │                 │  │ structured jobs  │
       │ API key auth    │  │ isolated process │
       │ no CAD exec     │  │ timeout/limits   │
       └─────────────────┘  └──────┬───────────┘
                                   │
                            ┌──────▼───────────┐
                            │ Mesh Inspection │
                            │ trimesh          │
                            └──────────────────┘
                                   │
                            ┌──────▼───────────┐
                            │ Geometry Checks  │
                            │ invariant analyzers │
                            └──────────────────┘
```

The requirement ledger is the authority for active product requirements and
revision deltas. Source parameters are implementation details unless a user
explicitly exposes a reusable control. The same project lifecycle handles
ordinary chat revisions, optional controls, blocked attempts, and start-over
lineages.

The normal flagged browser presentation is one responsive workspace: a fixed
conversation column, flexible viewer, and compact inspector on desktop; a
Details drawer at intermediate widths; and Conversation/Model/Details tabs on
narrow screens. The browser submits one authoritative chat operation and
renders persisted messages and backend state. It does not decide validation,
promotion, revision lineage, or export eligibility.

## Docker Deployment

Docker Compose is the official V1 deployment method. Volundr uses three fixed service and container names:

```text
volundr-web
volundr-api
volundr-cad-worker
```

### `volundr-web`

Responsibilities:

- serve the compiled React application
- proxy or route browser API requests to `volundr-api`
- contain no Gemini credentials
- contain no CAD execution tooling
- expose only the web entrypoint required by Traefik

### `volundr-api`

Responsibilities:

- FastAPI application
- SQLite access
- project and revision orchestration
- candidate state transitions
- Design Plan output manifest resolution
- structured revision-plan persistence and compliance validation
- per-output compile/retry orchestration
- project export packaging
- controlled live generation benchmark evaluation
- validation finding persistence and blocking/advisory enforcement
- Gemini API provider and optional development providers
- generation job state
- controlled asset delivery
- communication with `volundr-cad-worker`

This service may hold provider credentials. It must not execute generated
CadQuery Python directly.

Workflow tracing is part of backend orchestration. `docs/WORKFLOW_OBSERVABILITY.md`
defines workflow runs, structured events, artifact registry records,
first-failure diagnosis, frontend correlation, redaction, debug bundles, and
run comparison. Console logs are not the authoritative lifecycle record.

### `volundr-cad-worker`

Responsibilities:

- CadQuery execution
- source-contract validation inside the worker
- STEP/STL export
- B-Rep topology validation
- trimesh inspection
- temporary job workspace
- CAD-specific limits and cleanup
- no Gemini credentials
- no Docker socket
- no access to unrelated project files
- no outbound network access when the selected job transport permits it

SQLite, projects, generated assets, and provider credentials remain outside the containers in persistent bind mounts. Provider credentials must not be mounted into the CAD worker.

## Canonical Docker Compose Names

Service names and `container_name` values should match:

```yaml
services:
  volundr-web:
    container_name: volundr-web

  volundr-api:
    container_name: volundr-api

  volundr-cad-worker:
    container_name: volundr-cad-worker
```

Use a dedicated Compose network named:

```text
volundr-internal
```

Recommended persistent host layout:

```text
/opt/volundr/
├── data/
│   ├── app.db
│   ├── projects/
│   ├── jobs/
│   └── thumbnails/
└── gemini/
```

Recommended named or bind-mounted paths:

```text
volundr-api:
  /opt/volundr/data -> /app/data
  /opt/volundr/gemini -> /home/volundr/.gemini

volundr-cad-worker:
  /opt/volundr/data/jobs -> /work/jobs
```

Do not mount the Gemini directory into `volundr-web` or `volundr-cad-worker`.

## Backend Modules

Suggested structure:

```text
backend/app/
├── api/
├── core/
├── db/
├── models/
├── schemas/
├── services/
│   ├── ai/
│   ├── cad/
│   ├── mesh/
│   ├── projects/
│   └── revisions/
├── workers/
└── main.py
```

## Provider Interfaces

### AI provider

```python
class AiProvider(Protocol):
    async def generate_model(
        self,
        request: ModelGenerationRequest,
    ) -> ModelGenerationResult:
        ...
```

The request should include:

- original project intent
- current source, when revising
- new user instruction
- compiler diagnostics, when repairing
- source-contract diagnostics, when contract-repairing
- Design Specification, when available
- approved Design Plan, when available
- approved Revision Plan, when making a scoped AI revision
- output manifest, source metadata, and selected findings, when revision-planning
- mesh metadata, when available
- generation contract version

Implemented providers:

```text
GeminiCliProvider
GeminiApiProvider
OllamaProvider
```

Potential later implementations:

```text
OpenAIProvider
AnthropicProvider
```

The CadQuery transition default is `GeminiApiProvider` via `VOLUNDR_AI_PROVIDER=gemini_api`. `GeminiCliProvider` and `OllamaProvider` may remain available as optional adapters, but neither is the product default.

### CAD runner

```python
class CadRunner(Protocol):
    async def compile(
        self,
        source: str,
        job_id: str,
    ) -> CadCompileResult:
        ...
```

### CAD worker job transport

Phase 2 uses a filesystem-backed job transport under the CAD jobs directory. The API writes an atomic job directory containing `job.json` and `input/model.py`; the worker validates the manifest, executes one job, and writes `result.json` atomically.

This choice fits the current self-hosted single-user deployment because it needs no broker service, survives worker restarts, is easy to inspect during failures, and can be mounted narrowly into the worker. The tradeoff is that it is not a distributed queue and does not provide high-throughput scheduling, priority, or multi-worker locking beyond atomic file operations. Those are not required for the current product shape.

## Candidate Acceptance Flow

```text
AI or post-active manual source
  -> source extraction / source screening
  -> source-contract validation
  -> if hard violation: failed generation attempt, optional one contract repair, no candidate
  -> if quality findings only: continue and persist findings
  -> CadQuery worker execution
  -> if execution failure: optional one bounded repair after source-contract validation passes
  -> mesh inspection
  -> geometric invariant analysis for supported protected values
  -> deterministic validation findings
  -> revision review_state: ready | ready_with_warnings | blocked
  -> explicit accept or reject action
```

Only explicit acceptance updates `projects.active_revision_id` for generated candidates. Restore is limited to accepted revisions. Blocking findings are enforced in the backend service layer.

Initial implementation:

```text
CadQuery worker job
```

## Job State

Generation jobs should use explicit states:

```text
requirements_queued
requirements_extracting
clarification_required
requirements_ready
planning
plan_clarification_required
plan_ready
plan_approved
generation_queued
generating_cadquery
extracting_python
contract_validating
compiling
inspecting
validating
candidate_ready
candidate_blocked
unsupported
requirements_conflict
repairing
failed
cancelled
```

The frontend should receive status through polling initially or SSE when practical.

Generation stabilization should split generation runs from revision records. A generation run records the provider/prompt/request lifecycle; a revision records a model state. A successful compile may create a candidate revision before it becomes the active accepted revision.

Design Plan clarification is a normal planning state, not a failed generation. Persisted answers create a superseding immutable Design Plan version before CadQuery generation can be approved.

The normal chat-first AI flow is:

```text
request
  -> requirements-v1
  -> persist Design Specification
  -> clarification/conflict/unsupported or automatic plan creation
  -> design-plan-v1
  -> persist immutable Design Plan
  -> plan clarification or automatic first-draft generation
  -> CadQuery generation from validated Design Plan
  -> source validation
  -> isolated CadQuery execution
  -> mesh inspection
  -> geometric invariant validation
  -> printability validation
  -> repair, Current working version, or preserved blocked attempt
```

Structured AI revision flow:

```text
accepted revision
  -> revision-planning-v1 from Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
  -> clarification/conflict/unsupported or automatic internal plan progression
  -> cadquery-component-revision-v1 full-source revision
  -> source-contract validation
  -> source scope compliance against approved plan
  -> multi-output worker execution and validation
  -> protected output preservation and interface checks
  -> candidate review
```

The initial frontend flow uses a validated Design Plan. Initial generation,
Design Plan creation, structured revision planning, component-targeted source
revision, source-contract repair, and execution repair use separate prompt
stages and persisted prompt versions.

## File Layout

```text
data/
├── app.db
├── gemini/
├── projects/
│   └── <project-id>/
│       ├── revisions/
│       │   └── <revision-id>/
│       │       ├── source.py
│       │       ├── execution-manifest.json
│       │       ├── output-manifest.json
│       │       ├── step/
│       │       ├── stl/
│       │       ├── ai-output.txt
│       │       └── metadata.json
│       ├── configuration-changes/
│       │   └── <configuration-change-id>/
│       │       ├── configuration.json
│       │       └── parameter-overrides.json
│       ├── generation-runs/
│       │   └── <run-id>/
│       │       ├── request.json
│       │       ├── prompt.txt
│       │       ├── raw-output.txt
│       │       ├── parsed-design-spec.json
│       │       ├── parsed-design-plan.json
│       │       ├── parsed-revision-plan.json
│       │       ├── design-spec.json
│       │       ├── design-plan.json
│       │       ├── extracted-source.py
│       │       └── chain.json
│       └── thumbnails/
└── jobs/
```

## Frontend Layout

Desktop-first V1:

```text
┌────────────────────────────────────────────────────────────┐
│ Volundr project title | status | compile | download                │
├──────────────────┬─────────────────────────────────────────┤
│ conversation     │ 3D preview                              │
│ and revisions    │                                         │
│                  │                                         │
├──────────────────┼─────────────────────────────────────────┤
│ parameters       │ source editor                           │
└──────────────────┴─────────────────────────────────────────┘
```

The exact visual design may evolve, but Volundr should prioritize:

- preview visibility
- source transparency
- revision confidence
- clear generation status
- minimal modal workflows

## Deterministic Configuration Regeneration

Accepted revisions with approved Design Plans expose a configuration workflow.
The backend validates editable Design Plan parameters, persists a
`configuration-change-v1` record, and regenerates candidates from the unchanged
accepted CadQuery source using a typed parameter manifest in the isolated
worker.

This path does not call Gemini. If a requested change adds structure or touches a non-editable/derived parameter, the API returns `requires_design_revision` so the user can use structured revision planning instead.

If a component-targeted AI revision is created from a configured revision, the backend preserves the parameter manifest, verifies configured parameters still exist in source, and executes all outputs with the same resolved values.

Detailed rules are in `docs/PARAMETER_CONFIGURATION.md`.

## Future Architecture Options

Do not implement these prematurely:

- PostgreSQL
- distributed workers
- object storage
- browser-side OpenSCAD WASM
- separate rendering service
- GPU-based visual analysis
- multiple concurrent users

## Frontend Workflow Boundary

The primary frontend renders a chat-first assistant journey. One chat operation routes deterministic intent through the existing authoritative services; only essential clarification interrupts automatic requirements, Design Plan, generation, validation, and working-version promotion. Source editing, manifests, diagnostics, workflow IDs, and debug-bundle download are secondary Technical details. Staged controls remain behind the disabled flag during transition. The implementation audit is in `docs/FRONTEND_WORKFLOW_AUDIT.md` and `docs/CHAT_FIRST_WORKFLOW.md`.

The pipeline separately evaluates source contract, execution, topology, printability, and physical-function compliance through the generic functional verifier registry.

## Durable Workspace And Export Boundary

The database is authoritative for project identity, requirement and revision
history, workflow state, current working revision, and `ExportRecord` metadata.
The data directory is authoritative for source and generated artifacts. The
frontend reopens `/projects/{project_id}` through
`GET /api/projects/{project_id}/workspace`; it does not reconstruct a project
from browser state. Stale running workflows are classified as abandoned while
their evidence is retained.

Export is an explicit backend operation against a selected successful revision.
The API persists deterministic filenames, hashes, warnings, and download paths
for STL, STEP, assembly STEP where unambiguous, printable-parts ZIP, and
complete project-package ZIP exports. Blocked or incomplete revisions cannot
be exported. The browser never receives provider credentials.
