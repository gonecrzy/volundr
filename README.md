# Volundr

Volundr is a self-hosted, single-user application for generating, compiling, previewing, revising, and exporting functional parametric 3D-printing models through OpenSCAD and Gemini CLI.

## Status

Milestone 1 implementation is in progress. The repository now has a FastAPI
backend skeleton, SQLite model foundation, secure OpenSCAD runner tests, and
Docker Compose service definitions. Docker Compose is the official V1 deployment
method.

Implementation should begin with the secure OpenSCAD execution foundation described in:

- `CODEX_KICKOFF_PROMPT.md`
- `docs/CURRENT_STAGE_ROADMAP.md`

## Intended V1 Workflow

```text
describe part
  -> generate parameterized OpenSCAD through Gemini CLI
  -> compile through OpenSCAD CLI
  -> inspect STL in browser
  -> revise conversationally or edit source
  -> preserve revision history
  -> download SCAD and STL
```

## Product Constraints

- self-hosted through Docker Compose
- single-user
- no API requirement for V1
- no paid CAD software
- Gemini CLI authentication performed once on the host
- OpenSCAD source is the editable source of truth
- STL is an export
- functional FDM parts are the initial focus

## Documentation

Start with `docs/DOCUMENTATION_MAP.md`, then read every file in `docs/` before implementation.


## V1 Containers

Volundr uses these fixed Docker Compose service and container names:

```text
volundr-web
volundr-api
volundr-cad-worker
```

Runtime data is stored outside the containers in persistent bind mounts.

## Milestone 1 Setup

Backend tests require Python 3.12+ and OpenSCAD on the host.

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Apply SQLite migrations with:

```bash
cd backend
VOLUNDR_DATA_DIR=../data .venv/bin/alembic upgrade head
```

Validate Compose configuration with:

```bash
docker compose config
```

Run the V1 service skeleton with:

```bash
docker compose up --build
```

The frontend is only a Milestone 1 placeholder. Gemini integration, the CAD
workspace UI, project APIs, revision workflows, and STL preview are intentionally
not implemented yet.
