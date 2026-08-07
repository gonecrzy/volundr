# Volundr deployment

The supported product-like local deployment is Docker Compose with three
services:

- `volundr-web`: static React application served by nginx;
- `volundr-api`: FastAPI, SQLite, Gemini provider, migrations, project and
  export APIs;
- `volundr-cad-worker`: isolated non-root CadQuery worker using only the
  shared jobs directory.

Start with:

```bash
cp .env.example .env
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f volundr-api
```

### Minimal production-like configuration

Copy the root `.env.example` and provide only the deployment ports, data root,
provider, default model, and the root `GEMINI_API_KEY` plus optional
`GEMINI_API_KEY_2` for a live Gemini API deployment.
The API workspace is derived from `{VOLUNDR_DATA_DIR}/jobs`; Gemini CLI state
is mounted from `{VOLUNDR_DATA_DIR}/gemini`. Advanced path overrides are not
needed for the standard Compose layout.

Stop or restart without deleting data:

```bash
docker compose down
docker compose up -d
```

`volundr-api` runs `alembic upgrade head` before Uvicorn starts. Its `/health`
endpoint is a process liveness check; `/ready` verifies the SQLite connection
and durable data root. The web service waits for API readiness. The worker
health check verifies that the worker process is alive, and the worker writes
`.worker-health.json` in the shared jobs directory for operational inspection.

## Storage and backup

`VOLUNDR_DATA_DIR` is mounted at `/app/data` in the API and its derived `jobs`
subdirectory is mounted at `/work/jobs` in the worker. This root contains the
SQLite database, project source, registered STEP/STL/BREP artifacts, previews,
workflow bundles, and export packages. Back up the complete directory; do not
back up only temporary worker paths.

Compose maps the root keys into the API-only SecretStr settings
`VOLUNDR_GEMINI_PRIMARY_API_KEY` and `VOLUNDR_GEMINI_FALLBACK_API_KEY`. The
browser gets only intentionally public `VITE_*` build values, and the worker
receives no provider credentials or network access.

For production, use a secret manager for the API key, a private
`VOLUNDR_DATA_DIR` with restricted permissions, an allowlist in
`VOLUNDR_CORS_ORIGINS` when the frontend is hosted separately, and a
backup/restore procedure tested against the SQLite database and artifact
hashes. Docker/Compose commands must be run in an environment with Docker
installed; repository tests do not claim container runtime verification when
it is unavailable.

### Advanced overrides

Operational limits, snapshot controls, provider-specific settings, and the
credential-free Gemini policy file are documented in
`docs/ENVIRONMENT_VARIABLES.md`. Prefer typed defaults and add overrides only
for a proxy, separate origin, resource limit, provider choice, or isolated
test run.

For an isolated developer-assisted live evaluation, an operator may enable
`VOLUNDR_DEVELOPER_TOOLS_ENABLED=true`. This is disabled by default and is not
part of the minimal `.env.example`. It enables only the backend-authorized
debug-batch surface; it does not expose provider credentials to the browser or
permit browser execution of Codex or arbitrary shell commands. See
`docs/LIVE_DEBUG_BATCH_IMPLEMENTATION.md` for the evidence boundary.
