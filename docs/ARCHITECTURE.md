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
│ - generation orchestration                    │
│ - AI provider interface                       │
│ - CAD runner interface                        │
│ - asset delivery                              │
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

Initial implementation:

```text
OpenScadCliRunner
```

## Job State

Generation jobs should use explicit states:

```text
queued
generating
extracting_source
compiling
inspecting
repairing
succeeded
failed
cancelled
```

The frontend should receive status through polling initially or SSE when practical.

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
