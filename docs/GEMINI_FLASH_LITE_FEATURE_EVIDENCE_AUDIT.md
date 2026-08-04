# Gemini Flash Lite feature-evidence audit

The historical reports’ single `measured feature evidence` count obscured the
actual state of verification. The corrected analyzer classifies every project
as one of:

- `measured` — preserved measurement records exist;
- `measurement_failed` — verification ran and produced a blocking failure;
- `verification_not_run` — the project did not reach an accepted topology;
- `no_verification_target` — an accepted result had no explicit target;
- `evidence_not_captured` — verification/status was reached but measurements
  were not persisted;
- `artifact_unavailable_for_replay` — the accepted artifact could not support
  offline reconstruction.

## Captured result

| Status | Baseline | Validation |
| --- | ---: | ---: |
| measured | 0 | 0 |
| measurement_failed | 1 | 0 |
| verification_not_run | 28 | 28 |
| no_verification_target | 0 | 0 |
| evidence_not_captured | 1 | 2 |
| artifact_unavailable_for_replay | 0 | 0 |

There were only three accepted topology-valid revisions in the captured
evidence: one baseline revision and two validation revisions. The historical
“five valid topology projects per round” value was an analyzer artifact, not a
count of five accepted topology-valid records. The accepted records preserved
geometry and verification status, but not deterministic feature measurement
records; the analyzer therefore reports `evidence_not_captured` rather than
claiming zero features were present.

The offline replay path can reconstruct measurements when preserved
`feature_measurements`, `feature_evidence`, or revision-level verification
records exist. It does not invent measurements from hashes, paths, or mesh
metadata.

