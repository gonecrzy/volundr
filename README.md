# Volundr

Volundr is a self-hosted, single-user application for generating, executing, previewing, revising, and exporting functional parametric 3D-printing products. The approved transition target is CadQuery Python as the authoritative CAD source, OpenCascade B-Rep topology validation, STEP as the primary geometry artifact, STL as the derived print/preview artifact, Gemini API as the primary runtime AI provider, and a staged Design Specification and Design Plan workflow.

## Status

The current checkout still contains the working OpenSCAD product path and an
experimental CadQuery probe. That is transitional implementation debt, not the
strategic product architecture. The authoritative direction is defined in:

- `docs/CADQUERY_BACKEND.md`
- `docs/mutantpowers/plans/2026-07-30-cadquery-primary-transition.md`
- `docs/CURRENT_REPOSITORY_AUDIT.md`

Docker Compose remains the supported deployment method, but the current CAD
worker is not yet a real execution boundary. Until Phase 2 lands, generated CAD
execution in the product lifecycle is not isolated from the API container.

## Intended Product Workflow

```text
describe product
  -> extract requirements
  -> review or clarify Design Specification
  -> create Parametric Design Plan
  -> approve plan
  -> generate CadQuery Python through Gemini API
  -> validate source contract
  -> execute in isolated CAD worker
  -> validate B-Rep topology
  -> export STEP and STL
  -> review candidate
  -> explicitly accept or revise
```

## Product Constraints

- self-hosted through Docker Compose
- single-user
- no paid CAD software
- Gemini API is the primary runtime AI provider
- CadQuery Python is the editable regeneration source of truth
- STEP is the primary interoperable geometry artifact
- STL is derived for print preview and printing
- functional parametric parts and manageable multi-part printable products are the focus

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

The frontend includes a manual OpenSCAD workspace and staged AI generation path
from prior development stages. The active transition makes the staged workflow
the normal path and removes the simple raw prompt-to-source bypass as a product
default.

If a project has an active revision, the Generate action sends that revision's
accepted source as context and stores the result as a follow-up AI revision.
Child revisions expose a unified source diff against their parent in the
diagnostics panel.
The workspace parses simple numeric and boolean assignments in the marked
`USER PARAMETERS` section for the current OpenSCAD path. The CadQuery target uses
typed parameter execution without source rewriting.
Projects can be renamed or archived from the browser workspace; archived
projects are hidden from the default project list.
Project activity is captured as a per-project message ledger for the original
intent, revision instructions, and system events.

## AI Provider Setup

Volundr selects the AI backend with:

```bash
VOLUNDR_AI_PROVIDER=gemini_api
```

Gemini API is the primary runtime provider for the CadQuery transition. Ollama
may remain available for local development and provider-adapter comparison, but
it is not the product default.

Optional Ollama comparison settings:

```bash
VOLUNDR_OLLAMA_BASE_URL=http://10.1.20.25:11434
VOLUNDR_OLLAMA_MODEL=qwen2.5-coder:14b
VOLUNDR_OLLAMA_TIMEOUT_SECONDS=300
# Optional for thinking-capable models:
VOLUNDR_OLLAMA_THINK=false
```

For Ollama comparison runs, make sure the model is available on the Ollama host:

```bash
ollama pull qwen2.5-coder:14b
```

Notes from prior local model testing:

- `qwen2.5-coder:14b` was the strongest local model for the transitional OpenSCAD path.
- Thinking-capable Ollama models can be tested with `VOLUNDR_OLLAMA_THINK=false` to suppress reasoning and keep `response` clean.
- `deepseek-coder-v2:16b` remains a slower fallback comparison model.
- `joshuaokolo/C3Dv0:latest` is not compatible with the current OpenSCAD prompt contract without a separate adapter.

Generation attempts record provider, model, non-secret endpoint/auth metadata,
timeouts, prompt versions, and failure state; API keys are not stored.

### Gemini API Setup

Use API-key based auth for the primary Gemini provider:

```bash
VOLUNDR_AI_PROVIDER=gemini_api
GEMINI_API_KEY=<your key>
VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite
VOLUNDR_GEMINI_API_THINKING_LEVEL=minimal
```

The current Compose file still mounts a Gemini CLI profile into `volundr-api`
for the legacy provider path. The CAD worker must never receive Gemini CLI
profile data, Gemini API keys, Ollama credentials, or arbitrary API environment
variables.

Use an API key from a dedicated Google AI/Gemini project for Volundr, with billing/quota controls appropriate for automated generation runs. Generation attempts record the Gemini model, transport, non-secret auth mode, and configured thinking level so quota or policy issues can be traced without storing credentials. `gemini_cli` remains available for a configured Gemini CLI profile, but API-key operation should use `gemini_api`.

For source generation, use `VOLUNDR_GEMINI_MODEL=gemini-3.5-flash-lite` as the default Gemini endpoint unless you are deliberately comparing model tiers. In the current CadQuery validation path it avoids the tighter `gemini-3.5-flash` request-limit behavior and still returns useful geometry signals. Keep `VOLUNDR_GEMINI_API_THINKING_LEVEL=minimal` unless you are deliberately testing deeper reasoning; unbounded thinking can consume the response with reasoning text instead of a complete fenced CadQuery source block.

## Transitional Manual Compile API

The current checkout still supports manual OpenSCAD compilation while the
CadQuery backend is being implemented. This API is transitional and will be
renamed or removed during the CadQuery persistence and OpenSCAD removal phases.

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
