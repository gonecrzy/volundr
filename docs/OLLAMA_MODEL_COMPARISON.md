# Ollama model comparison

The comparison is controlled only when both batches match on Git HEAD,
migration head, provider, model policy, prompt versions, configuration hash,
and backend/frontend/worker build identities. Any mismatch is persisted,
marked `uncontrolled`, and stops the planned controlled live comparison until
the configuration is restored.

The comparison consumes existing project evidence and materializes report
copies only. It does not introduce a second event system and does not rerun
providers, workers, geometry, retries, candidates, revisions, or exports.

The correction plan distinguishes repeated cross-product defects, repeated
same-family defects, provider variability, isolated anomalies, and integrity or
misleading-state defects. It is planning output only.

