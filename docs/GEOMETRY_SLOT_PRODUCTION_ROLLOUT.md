# Geometry slot production rollout

## Rollout gates

1. Keep `VOLUNDR_GEOMETRY_CONTRACT_MODE=auto` with the detailed-route legacy
   boundary intact.
2. Run deterministic contract, fixture replay, workflow, frontend, build,
   Compose, health, and Playwright checks.
3. Run one unchanged five-project live validation batch through the normal
   frontend, configured provider, and CadQuery worker.
4. Freeze the batch and preserve all attempts and local evidence before any
   review or correction decision.

There is no live prompt/model comparison in this rollout. The five projects
use the existing mixed-CAD prompts and fact-sheet answers, with no more than
two clarification rounds and at most one retry after a first failed attempt.
No source, prompt, provider/model, environment, policy, image, schema, or
retry-policy change is allowed during the batch.

## Safety boundaries

The backend capability and API authorization remain separate from frontend
visibility. Provider credentials and internal configuration never reach the
browser. The browser cannot run Codex, arbitrary shell commands, or a worker.
Raw evidence stays local and outside Git under
`data/debug-sessions/<batch-id>/`; only redacted derived fixtures and dated
summaries may be committed.

If a future paired comparison is run, Batch 2 is controlled only when Git
HEAD, migration head, provider, model policy, prompt versions, configuration
hash, and backend/frontend/worker build identities all match Batch 1. Any
mismatch is recorded and makes the comparison uncontrolled.

## Fallback and rollback

Fallback is a pre-worker compatibility escape hatch, not a provider repair
loop. It is recorded in attempt routing metadata and cannot silently change
the contract. Worker repair is localized to one diagnosed slot and retains
unaffected hashes. A failed batch report can be regenerated from frozen
evidence without changing membership or making provider/worker calls.

Corrections after evaluation are planning-only in
`docs/LIVE_BATCH_CORRECTION_PLAN.md`; they require a separate implementation
and verification run.
