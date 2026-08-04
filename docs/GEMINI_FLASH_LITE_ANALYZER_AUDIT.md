# Gemini Flash Lite analyzer audit

This audit covers `gemini-flash-lite-study-01` using only the captured
baseline and validation evidence under:

`data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01/`

The analyzer was regenerated with `offline_required: true` and
`provider_calls: 0`. No Gemini, Ollama, or project operation was used.

## Defects found

The previous aggregate analyzer had five material defects:

1. `projects_reaching_valid_source` counted any succeeded generation attempt,
   including attempts that never passed source-contract validation or reached
   the worker.
2. Topology success was inferred from the presence of any event containing
   the word `topology`, so `topology.failed` could count as success.
3. Requirements, response structure, execution, and outcome comparisons used
   raw evidence containing generated IDs, paths, hashes, timestamps, wording,
   and provider-operation metadata.
4. Blockers were not reconciled into one earliest authoritative blocker per
   project, and the failure-signature total could not be checked against the
   terminal-project total.
5. Feature verification was reduced to a single measured/not-measured count,
   hiding measurement failures, verification-not-run projects, and accepted
   revisions whose verification evidence was not persisted.

## Corrected definitions

The corrected analyzer creates one canonical record per project with the full
funnel:

`requirements → clarification → planning → geometry_contract → slots_source → source_validation → worker → artifacts → topology → feature_verification → candidate_resolution`

Valid source now means that the final source passed source-contract validation
and was submitted to the worker. Worker reach is reported separately from
worker completion. Topology requires an accepted revision with one connected,
watertight result or an explicit topology-pass event.

Semantic comparisons retain meaning-bearing fields only: requirement meaning,
clarification intent and supplied fact, plan structure, response class,
execution state, topology state, verification state, and final outcome.
Generated IDs, ordering, wording, paths, hashes, timestamps, token counts,
latency, and provider-operation IDs are ignored.

Historical reports were preserved under
`reports/historical/pre-correction/` before corrected reports were written.

