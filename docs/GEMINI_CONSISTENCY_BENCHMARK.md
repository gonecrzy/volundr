# Gemini consistency benchmark

This benchmark evaluates response consistency through the Volundr HTTP API.
The runner never calls Gemini, Codex, the browser, or the CAD worker directly.
It uses the normal project creation and chat workflow, with a backend-gated
benchmark model header for model selection.

The original Gemini corpus remains available for historical tooling, but the
current live comparison is the frozen five-case corpus
`benchmarks/ollama-consistency-v1.json`. Five-case runs execute the Gemini
anchor twice and each explicitly admitted Ollama model twice, with stable
experiment, model, run, case, project, and client-message identifiers. The
runner supports dry-run validation, exact model filters, bounded concurrency,
one product-policy retry, and at most two clarification rounds using only the
case fact sheet. Historical ten- and fifty-case runs must not be mixed into the
revised comparison.

Raw evidence stays local and outside Git under
`data/debug-sessions/model-consistency/<experiment-id>/` for five-case runs
and is durable
evidence, not temporary worker output. Evidence is redacted before it is
written and reports are generated from existing project records, workflow
events, attempts, revisions, artifacts, exports, and local evidence files.

The capability setting is `VOLUNDR_DEVELOPER_TOOLS_ENABLED=false` by default.
It is documented only as an advanced developer deployment setting and is not
part of the minimal `.env.example`. Every benchmark endpoint enforces it on
the server.

## Operator sequence

1. Run the benchmark command with `--dry-run`, discovery, and resource
   preflight.
2. Freeze exactly five cases and the admitted model list.
3. Run the Gemini anchor twice and each admitted Ollama model twice with no
   intervening fixes.
4. Freeze the evidence and verify configuration identities before comparison.
5. Generate reports, follow every `codex-review.md`, and write the correction
   plan without implementing corrections in the same run.

The pilot and full result documents are generated only after their respective
API runs; placeholder status is not evidence of a completed run.
