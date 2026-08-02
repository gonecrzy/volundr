# User Testing Checkpoint

Checkpoint date: 2026-08-02  
Checkpoint directory: `/tmp/volundr-user-testing-checkpoint-20260802T194000Z`

## Repository and runtime

- Git HEAD at checkpoint creation: `86026f424a4f18bdf0bae4c1e33fa5c5d2bea60f`
- Migration head: `0027_export_records (head)`
- Compose services: `volundr-api`, `volundr-web`, and `volundr-cad-worker`
- API health/readiness: passed
- Configured provider/model: `gemini_api` / `gemini-3.5-flash-lite`
- Project database: 32 projects; 4 active; 0 archived
- Durable artifact references checked: 0 missing
- Checkpoint contents exclude credentials, raw provider responses, and full
  conversation transcripts.

The checkpoint is read-only. It contains project/revision/message-count
summaries and runtime metadata; it does not retry provider calls, regenerate
geometry, create exports, or modify project state. Runtime data and checkpoint
directories are gitignored.

## Product-shell corrections

- Blocked initial attempts now say: “No working version has been created yet.”
- Blocked revisions with an accepted current version say: “Your Current
  working version is unchanged.”
- Persisted legacy blocked messages are rendered against the authoritative
  current revision ID, so an old unconditional sentence cannot mislabel a
  blocked-only project.
- Workflow stages are mapped to Understanding, Planning, Creating, or
  Checking. Unknown or unavailable stages use a neutral “Creating the model…”
  fallback and never mark Planning falsely.
- Reopened workspaces receive the latest persisted workflow stage when a run
  is active.
- Archive hides a project from the active list but preserves records and files
  indefinitely. Explicit Delete remains destructive. Old archive removal is an
  operator-only dry-run/non-dry-run maintenance command.
- Only untouched, evidence-free drafts remain eligible for bounded cleanup;
  user content, workflow evidence, requirements, revisions, and artifacts make
  a draft retainable.

## Read-only browser review

The running frontend was reviewed through the real browser at 1440 × 900,
1024 × 768, and 390 × 844 without submitting messages. The representative
spacer project showed its conversation, Current working version, blocked
history, snapshots, printable parts, comparison/history access, and export
controls. The project drawer showed active projects and current-version state.
The blocked initial wording was accurate after the rebuilt web image was
loaded, including the no-working-version case. The historical-selection banner
also avoids implying that a nonexistent version is current.

Observed console output contained no errors, and all observed API requests
returned successfully. Three.js emitted its PCFSoftShadowMap deprecation
warning while rendering the viewer; this is a facilitator caution, not a
workflow or data-integrity failure. No raw backend error was visible.

The Projects drawer is active-project-only by design. Archived projects remain
reachable through their explicit stable URL/API; a dedicated archived-project
view is not introduced in this checkpoint.

## Deterministic fixture readiness

The existing deterministic suites provide known-good, clarification, revision,
blocked-attempt, reopen/reconnect, comparison, export, and physical-feedback
paths. The observed session should use those fixtures rather than live Gemini
reliability. The facilitator should keep frontend usability evaluation
separate from unresolved live compact/detailed CAD-quality issues.

## Deferred CAD issues

The tackle-tray project remains a safely blocked live design-quality case. Its
backend requirement/trace limitation is not a user-testing blocker for the
frontend fixtures. Do not present that live output as a validated physical
design during the session.

## Readiness result

**Ready with listed facilitator cautions.**

Observed testing has not yet occurred. The facilitator should explain that the
session evaluates chat, clarification, revisions, history, blocked attempts,
reopen, comparison, and export targeting using deterministic fixtures; it does
not establish live CAD quality or physical print compliance.
