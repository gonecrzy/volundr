# Volundr Architecture

This document defines the approved V1 technical shape of Volundr: major components, service boundaries, provider interfaces, runtime flow, storage layout, and deployment model.

## Decision Status

The technologies and boundaries in this document are approved V1 defaults. They may be revisited after the core generate, compile, preview, revise, and export workflow is proven, but Codex should not replace them without a concrete blocker.

## System Overview

```text
┌───────────────────────────────────────────────┐
│ Browser                                       │
│ React + TypeScript                            │
│                                               │
│ - project list                                │
│ - prompt and revision input                   │
│ - Monaco OpenSCAD editor                      │
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
│ - parametric Design Plan generation/review    │
│ - structured revision planning/review         │
│ - generation orchestration                    │
│ - multi-output artifact orchestration         │
│ - candidate revision review and acceptance    │
│ - pre-compile OpenSCAD source-contract checks │
│ - post-compile geometric invariant checks     │
│ - AI provider interface                       │
│ - CAD runner interface                        │
│ - persisted validation findings               │
│ - asset delivery                              │
│ - output manifest and ZIP export              │
│ - SQLite persistence                          │
└───────────────┬───────────────────┬───────────┘
                │                   │
       ┌────────▼────────┐  ┌──────▼───────────┐
       │ Gemini CLI      │  │ OpenSCAD Runner  │
       │ Provider        │  │                  │
       │                 │  │ fixed CLI args   │
       │ local OAuth     │  │ temp workspace   │
       │ subprocess      │  │ timeout/limits   │
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
- contain no OpenSCAD execution tooling
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
- validation finding persistence and blocking/advisory enforcement
- Gemini CLI provider
- generation job state
- controlled asset delivery
- communication with `volundr-cad-worker`

This is the only service allowed to mount the persistent Gemini CLI profile.

### `volundr-cad-worker`

Responsibilities:

- OpenSCAD CLI execution
- trimesh inspection
- temporary job workspace
- CAD-specific limits and cleanup
- no Gemini credentials
- no Docker socket
- no access to unrelated project files
- no outbound network access when the selected job transport permits it

SQLite, projects, generated assets, and the Gemini profile remain outside the containers in persistent bind mounts.

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

Initial implementation:

```text
GeminiCliProvider
```

Potential later implementations:

```text
OllamaProvider
GeminiApiProvider
OpenAIProvider
AnthropicProvider
```

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

## Candidate Acceptance Flow

```text
AI or post-active manual source
  -> source extraction / source screening
  -> source-contract validation
  -> if hard violation: failed generation attempt, optional one contract repair, no candidate
  -> if quality findings only: continue and persist findings
  -> OpenSCAD compile
  -> if compile failure: optional one compile repair after source-contract validation passes
  -> mesh inspection
  -> geometric invariant analysis for supported protected values
  -> deterministic validation findings
  -> revision review_state: ready | ready_with_warnings | blocked
  -> explicit accept or reject action
```

Only explicit acceptance updates `projects.active_revision_id` for generated candidates. Restore is limited to accepted revisions. Blocking findings are enforced in the backend service layer.

Initial implementation:

```text
OpenScadCliRunner
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
generating_scad
extracting_scad
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

Recommended staged AI flow:

```text
request
  -> requirements-v1
  -> persist Design Specification
  -> clarification/conflict/unsupported or explicit plan creation
  -> design-plan-v1
  -> persist immutable Design Plan
  -> plan clarification or explicit plan approval
  -> OpenSCAD generation from approved Design Plan
  -> source validation
  -> compile
  -> mesh inspection
  -> geometric invariant validation
  -> printability validation
  -> repair, candidate review, or acceptance
```

Structured AI revision flow:

```text
accepted revision
  -> revision-planning-v1 from Design Specification, approved Design Plan, output manifest, source metadata, and selected findings
  -> clarification/conflict/unsupported or explicit revision-plan approval
  -> openscad-revision-v2
  -> source-contract validation
  -> revision compliance validation against approved plan
  -> multi-output compile and validation
  -> candidate review
```

The legacy endpoint may still generate from a ready Design Specification for compatibility. The new initial frontend flow uses an approved Design Plan. Initial generation, Design Plan creation, structured revision planning, bounded revision generation, source-contract repair, and compiler repair use separate prompt stages and persisted prompt versions.

## File Layout

```text
data/
├── app.db
├── gemini/
├── projects/
│   └── <project-id>/
│       ├── revisions/
│       │   └── <revision-id>/
│       │       ├── model.scad
│       │       ├── model.stl
│       │       ├── compile.log
│       │       ├── ai-output.txt
│       │       └── metadata.json
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
│       │       ├── extracted-source.scad
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
│ parameters       │ OpenSCAD editor                         │
└──────────────────┴─────────────────────────────────────────┘
```

The exact visual design may evolve, but Volundr should prioritize:

- preview visibility
- source transparency
- revision confidence
- clear generation status
- minimal modal workflows

## Future Architecture Options

Do not implement these prematurely:

- PostgreSQL
- distributed workers
- object storage
- browser-side OpenSCAD WASM
- separate rendering service
- GPU-based visual analysis
- multiple concurrent users
