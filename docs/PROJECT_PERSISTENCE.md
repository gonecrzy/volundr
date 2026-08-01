# Project persistence

Volundr treats the backend database and configured data directory as the
authoritative project copy. Every project remains revisionable through chat;
browser storage is limited to harmless UI state and never owns requirements,
messages, revisions, workflow runs, or artifacts.

## Reload and recovery

`GET /api/projects/{project_id}/workspace` returns the project metadata,
complete message ledger, revision lineage, Current working version pointer,
active requirements, active workflow, and an artifact-integrity summary. The
frontend uses this aggregate when reopening a stable `/projects/{project_id}`
URL, so a refresh does not reconstruct state from optimistic browser memory.

The API classifies stale `running` workflow records as `abandoned` using
`VOLUNDR_WORKFLOW_STALE_SECONDS` (900 seconds by default). This prevents a
server or worker restart from leaving a project displaying a false running
state. Abandoned runs remain in history; Volundr does not silently resubmit a
provider request that could duplicate a charge or create a conflicting
revision.

Projects, messages, requirement-ledger entries, deltas, physical-test
observations, plans, revisions, attempts, workflow evidence, and registered
artifact paths are persisted in SQLite and the mounted data directory. A
blocked attempt is retained in the revision history and cannot replace the
Current working version.

The workspace response reports registered output files that are missing from
durable storage. Missing files are not presented as downloadable artifacts.

The chat-first frontend renders the persisted message ledger from this
workspace aggregate. Chat submission writes the user message and semantic
assistant response, while system events remain technical evidence. Reload and
retry therefore use backend records rather than optimistic browser state.

## Deployment expectation

The Compose deployment mounts `VOLUNDR_DATA_DIR` at `/app/data`; this contains
the SQLite database, project files, worker job records, previews, and export
packages. Back up that directory while the stack is stopped or with a
filesystem/database backup procedure that preserves SQLite consistency. The
backend image runs migrations before starting the API.
