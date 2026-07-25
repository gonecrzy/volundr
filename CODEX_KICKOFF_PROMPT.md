# Codex Kickoff Prompt — Volundr

This file is the executable kickoff instruction for Codex. It defines what Codex should build first, which documents control the project, and which V1 constraints must not drift.

You are working in the Volundr repository: a self-hosted, single-user, AI-assisted parametric CAD application for functional 3D-printing models.

## Mission

Build a local-first web application that lets one authenticated user:

1. Describe a functional 3D-printable part in plain English.
2. Generate parameterized OpenSCAD source using Gemini CLI.
3. Compile the source into a valid STL using OpenSCAD CLI.
4. Preview the STL interactively in the browser.
5. Request conversational revisions while preserving working geometry.
6. Edit OpenSCAD directly when desired.
7. View and restore prior revisions.
8. Download SCAD and STL outputs.
9. See meaningful compiler and generation errors.
10. Keep all projects and assets on the self-hosted server.

The editable source of truth is OpenSCAD code. STL is an export artifact, never the primary editable representation.

## V1 Product Constraints

V1 is intentionally:

- Single-user
- Self-hosted
- Local-first
- Intended for functional FDM-printable parts
- Based on OpenSCAD
- Powered initially by Gemini CLI authenticated once on the host
- Designed so other AI providers can be added later
- Protected externally by an existing reverse proxy and optional Authentik forward-auth
- Free of subscriptions, billing, credits, marketplaces, or public sharing

Do not add multi-user architecture, SaaS infrastructure, payment handling, public galleries, collaboration, or complex organization concepts.

## Required Stack

Preferred stack:

- Frontend: React, TypeScript, Vite
- 3D viewer: Three.js, optionally through React Three Fiber if it reduces complexity
- Code editor: Monaco Editor
- Backend API: Python 3.12+ with FastAPI
- Database: SQLite for V1
- ORM/migrations: SQLAlchemy 2.x and Alembic
- CAD engine: OpenSCAD CLI
- AI provider: Gemini CLI subprocess adapter
- Mesh inspection: trimesh
- Job execution: simple in-process or database-backed single-worker queue
- Deployment: Docker Compose only for V1
- Reverse proxy compatibility: Traefik
- Testing: pytest for backend, Vitest for frontend, Playwright for critical workflows

Avoid Redis, Kubernetes, Celery, S3, Kafka, microservices, and other infrastructure that does not serve the V1 use case.

## Repository Expectations

Use these canonical Docker Compose service and container names:

```text
volundr-web
volundr-api
volundr-cad-worker
```

Do not rename them without a concrete technical blocker.

Create or preserve this structure:

```text
/
├── frontend/
├── backend/
├── cad-worker/              # may begin as backend module if separation is premature
├── docs/
├── data/                    # gitignored runtime data
├── docker-compose.yml
├── .env.example
├── README.md
└── Makefile
```

Use the supporting documents in `docs/` as product and technical authority.

## Core Workflow

The expected request path is:

```text
User prompt
  -> backend creates project/generation job
  -> GeminiCliProvider generates OpenSCAD
  -> generated source is validated against the generation contract
  -> OpenSCAD runs in a restricted process/container
  -> STL and compiler logs are produced
  -> trimesh extracts metadata and checks mesh validity
  -> successful revision is stored
  -> frontend displays source, preview, metadata, and revision history
```

For revision requests:

```text
User revision instruction
  + original project intent
  + current accepted OpenSCAD source
  + compiler/mesh information
  -> Gemini CLI
  -> minimal source modification
  -> compile and validate
  -> store as child revision
```

## Mandatory Engineering Principles

1. Preserve working source whenever possible. Revision prompts must request the smallest necessary modification.
2. Never execute arbitrary shell text produced by the AI.
3. Pass generated SCAD to OpenSCAD through controlled files and fixed command arguments.
4. Enforce time, memory, output-size, and file-count limits.
5. Do not let generated code access host paths or arbitrary external files.
6. Store every generation attempt and its status, including failed attempts.
7. Do not overwrite accepted revisions.
8. Keep provider-specific Gemini CLI logic behind an interface.
9. Keep V1 deployment understandable by one technical owner and support Docker Compose as the only V1 installation path.
10. Prefer reliable, testable workflows over visually impressive but fragile features.

## Initial Milestone

Begin with Milestone 1 only:

### Milestone 1 — Secure CAD Execution Foundation

Implement:

- FastAPI application skeleton
- Health endpoint
- SQLite configuration
- Project and revision base models
- A CAD runner service that:
  - accepts OpenSCAD source
  - writes it to a per-job temporary directory
  - invokes OpenSCAD with fixed arguments
  - enforces a timeout
  - captures stdout/stderr
  - returns structured success/failure information
  - produces an STL on success
- Basic trimesh metadata:
  - bounding box
  - volume
  - triangle count
  - connected component count
  - watertight boolean
- Unit tests for successful and failed SCAD execution
- Docker Compose services named `volundr-web`, `volundr-api`, and `volundr-cad-worker`
- `.env.example`
- Setup instructions in README

Do not implement Gemini integration or the full React interface until the CAD execution foundation is proven.

## Deliverables for Each Work Session

At the end of each substantial task:

1. Run relevant tests.
2. Summarize files changed.
3. State what now works.
4. State remaining limitations.
5. Update `docs/CURRENT_STAGE_ROADMAP.md` if milestone status changed.
6. Avoid silently expanding scope.

## First Action

Read `docs/DOCUMENTATION_MAP.md`, then all remaining documents in `docs/`. Inspect the repository and produce:

1. A short repository assessment.
2. A concrete implementation plan for Milestone 1.
3. Any conflicts or missing prerequisites.
4. Then begin implementation unless a blocker makes implementation impossible.
