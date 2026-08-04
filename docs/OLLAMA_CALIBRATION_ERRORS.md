# Ollama calibration errors

Every original and reprocessed issue is machine-readable in
`data/debug-sessions/ollama-calibration/calibration-admission-report/resolution-queue.json`;
aggregate signatures are in the adjacent `resolution-aggregates.json`.
Each entry has one primary owner, stage, error code, evidence path, blocking
flags, and recommended resolution.

The resolution report preserves all 29 original observations. Representation
variants were reprocessed or closed as precise model/contract limitations;
native truncation, ambiguous final objects, unsupported slot helpers, and
worker/topology findings remain separately classified. Transport, timeout,
adapter, and profile issues are not included in CAD-quality scoring.

CAD findings are only eligible for quality scoring when the response passed a
frozen profile and the isolated worker plus topology validation produced
authoritative evidence. No missing CAD operation is repaired by the runner.
