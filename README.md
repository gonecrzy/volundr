# Volundr

Volundr is a self-hosted, single-user application for generating, compiling, previewing, revising, and exporting functional parametric 3D-printing models through OpenSCAD and Gemini CLI.

## Status

Stage 1 and Stage 2 are complete. The manual OpenSCAD workspace can create
projects, compile SCAD into immutable revisions, persist source/STL/log/metadata
assets, show compile diagnostics, restore successful revisions, preview STL
geometry, and download SCAD/STL outputs. Docker Compose is the official V1
deployment method.

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

After pulling implementation changes, rebuild the API image and apply migrations before judging generation quality:

```bash
docker compose build volundr-api volundr-web
cd backend
VOLUNDR_DATA_DIR=../data .venv/bin/alembic upgrade head
```

The API container and local database must be on the current migration head. A stale runtime can continue using the legacy one-step Gemini prompt and bypass the staged Design Specification, Design Plan, source-contract, candidate, and validation gates.

The frontend includes the Stage 2 manual CAD workspace and staged AI generation
path. Development defaults to a local Ollama provider at
`http://10.1.20.25:11434` using `qwen2.5-coder:14b`. Gemini remains available as an
explicit provider switch.

The default generation workflow is intentionally simple while model quality is
being stabilized: chat prompts call AI source generation directly, compile the
result, and present the result as a candidate. The staged Design Specification,
Design Plan, multi-output, structured revision, and strict marker-contract UI
can be rebuilt into the normal path after the simple model loop is reliable.
Set `VOLUNDR_GENERATION_MODE=advanced` and build the frontend with
`VITE_VOLUNDR_GENERATION_MODE=advanced` to expose the advanced workflow again.

If a project has an active revision, the Generate action sends that revision's
OpenSCAD source as context and stores the result as a follow-up AI revision.
Child revisions expose a unified source diff against their parent in the
diagnostics panel.
The workspace parses simple numeric and boolean assignments in the marked
`USER PARAMETERS` section and exposes controls that update the SCAD source for
manual recompilation.
Projects can be renamed or archived from the browser workspace; archived
projects are hidden from the default project list.
Project activity is captured as a per-project message ledger for the original
intent, revision instructions, and system events.

## AI Provider Setup

Volundr selects the AI backend with:

```bash
VOLUNDR_AI_PROVIDER=ollama
```

The development default is local Ollama with `qwen2.5-coder:14b`. Current phase-validation runs show it is the best primary local model for this OpenSCAD path. Keep Gemini as an explicit provider option for later higher-capability endpoint testing.

```bash
VOLUNDR_OLLAMA_BASE_URL=http://10.1.20.25:11434
VOLUNDR_OLLAMA_MODEL=qwen2.5-coder:14b
VOLUNDR_OLLAMA_TIMEOUT_SECONDS=300
# Optional for thinking-capable models:
VOLUNDR_OLLAMA_THINK=false
```

Make sure the model is available on the Ollama host:

```bash
ollama pull qwen2.5-coder:14b
```

Notes from current local model testing:

- `qwen2.5-coder:14b` is the primary local model.
- Thinking-capable Ollama models can be tested with `VOLUNDR_OLLAMA_THINK=false` to suppress reasoning and keep `response` clean.
- `deepseek-coder-v2:16b` remains a slower fallback comparison model.
- `joshuaokolo/C3Dv0:latest` is not compatible with the current OpenSCAD prompt contract without a separate adapter.

Generation attempts record `provider=ollama`, the model, endpoint, timeout, and
`auth_mode=local_ollama`; no API keys are stored.

### Gemini CLI Setup

The API service is the only service that mounts Gemini credentials:

```text
${VOLUNDR_GEMINI_DIR:-./data/gemini}:/home/volundr/.gemini
```

Authenticate Gemini CLI for that profile before using the browser Generate
button, or use the direct Gemini API provider with API-key based auth.

For API-key based auth, set:

```bash
VOLUNDR_AI_PROVIDER=gemini_api
GEMINI_API_KEY=<your key>
VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite
VOLUNDR_GEMINI_API_THINKING_LEVEL=minimal
```

Use an API key from a dedicated Google AI/Gemini project for Volundr, with billing/quota controls appropriate for automated generation runs. Generation attempts record the Gemini model, transport, non-secret auth mode, and configured thinking level so quota or policy issues can be traced without storing credentials. `gemini_cli` remains available for a configured Gemini CLI profile, but API-key operation should use `gemini_api`.

For source generation, use `VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite` as the default Gemini endpoint unless you are deliberately comparing model tiers. In the current CadQuery validation path it avoids the tighter `gemini-3.5-flash` request-limit behavior and still returns useful geometry signals. Keep `VOLUNDR_GEMINI_API_THINKING_LEVEL=minimal` unless you are deliberately testing deeper reasoning; unbounded thinking can consume the response with reasoning text instead of a complete fenced CadQuery source block.

## Manual Compile API

Create a project:

```bash
curl -X POST http://localhost:8000/api/projects \
  -H 'content-type: application/json' \
  -d '{"name":"Mounting bracket","original_intent":"A flat bracket with two holes."}'
```

Compile a manual revision:

```bash
curl -X POST http://localhost:8000/api/projects/<project-id>/revisions \
  -H 'content-type: application/json' \
  -d '{"scad_source":"cube([10, 20, 30]);","user_instruction":"Initial manual model."}'
```

Successful revision assets are stored under:

```text
data/projects/<project-id>/revisions/<revision-id>/
├── model.scad
├── model.stl
├── compile.log
├── ai-output.txt
└── metadata.json
```
