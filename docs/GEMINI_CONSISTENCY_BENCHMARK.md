# Gemini consistency benchmark

This benchmark evaluates response consistency through the Volundr HTTP API.
The runner never calls Gemini, Codex, the browser, or the CAD worker directly.
It uses the normal project creation and chat workflow, with a backend-gated
benchmark model header for model selection.

The frozen corpus is `benchmarks/gemini-consistency-v1.json`. Pilot runs use
the first ten stable cases; full runs use all fifty. Each selected model is run
twice with stable experiment, model, run, case, project, and client-message
identifiers. The runner supports dry-run validation, filters, resumability,
bounded concurrency, one product-policy retry, and at most two clarification
rounds using only the case fact sheet.

Raw evidence stays local and outside Git under
`data/debug-sessions/gemini-consistency/<experiment-id>/`. It is durable
evidence, not temporary worker output. Evidence is redacted before it is
written and reports are generated from existing project records, workflow
events, attempts, revisions, artifacts, exports, and local evidence files.

The capability setting is `VOLUNDR_DEVELOPER_TOOLS_ENABLED=false` by default.
It is documented only as an advanced developer deployment setting and is not
part of the minimal `.env.example`. Every benchmark endpoint enforces it on
the server.

## Operator sequence

1. Run the benchmark command with `--dry-run` and the discovered model IDs.
2. Run the ten-case pilot twice per model and inspect the pilot gate.
3. Freeze the pilot evidence and verify identities before any full run.
4. Run the fifty-case corpus twice per model with no intervening fixes.
5. Generate reports, follow every `codex-review.md`, and write the correction
   plan without implementing corrections in the same run.

The pilot and full result documents are generated only after their respective
API runs; placeholder status is not evidence of a completed run.
