# Ollama calibration errors

Every unresolved issue is machine-readable in
`data/debug-sessions/ollama-calibration/calibration-final-pass/resolution-queue.json`.
Each entry has one primary owner, stage, error code, evidence path, blocking
flags, and recommended resolution.

The final pass contained model-contract and representation issues, including
native response-mode mismatches, ambiguous final objects, unknown production
slot IDs, Markdown/prose variants, and worker/topology findings where the
worker was reached. Transport, timeout, adapter, and profile issues are not
included in CAD-quality scoring.

CAD findings are only eligible for quality scoring when the response passed a
frozen profile and the isolated worker plus topology validation produced
authoritative evidence. No missing CAD operation is repaired by the runner.
