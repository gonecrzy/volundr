# Feature verification live evaluation

Status: frozen evaluation; no same-run corrections were implemented.

The focused live batch reused the existing five mixed-CAD prompts and approved
fact sheets without changing source, prompts, provider/model, environment,
policy, images, schema, or retry policy:

- label: `feature-verification-live-01`;
- batch ID: `5532f214-7fa4-4ba3-b36a-28be39300618`;
- raw evidence: `/tmp/volundr-live-e2e.KTYBmD/data/debug-sessions/5532f214-7fa4-4ba3-b36a-28be39300618/`;
- raw evidence remains local and outside Git.

## Batch result

Five projects were created and all five completed requirements. Three reached
the worker, one produced valid geometry, one produced snapshots, and none was
promoted or exported:

| Project | Worker | Final outcome | Classification |
|---|---:|---|---|
| wall-mounted carrier | yes | Blocked after worker | post-worker verification block |
| portable two-tray holder | yes | Blocked after worker | worker runtime/topology failure |
| desktop organizer | yes | Blocked after worker | worker runtime failure |
| fixed monitor wall mount | no | Blocked before worker | provider/source content failure |
| screw-lid container | no | Blocked before worker | provider/source content failure |

Provider behavior was 21 calls across 5 projects, 21 generation attempts, 64
workflow-stage attempts, one content repair, and zero provider retries. The
report recorded zero duplicate messages, zero missing assistant outcomes, and
zero frontend errors.

## Individual review and classification

The wall carrier reached valid geometry and preserved STEP/STL/BREP and
snapshots, but remained blocked by the authoritative verification/candidate
gate. This is evidence that valid topology is not incorrectly presented as
feature compliance.

The portable holder reached the worker but failed with an invalid output shape
and disconnected-solid topology evidence. The desktop organizer reached the
worker but failed during CAD execution. The monitor mount and screw-lid
projects stopped before the worker on provider/source content. The monitor
mount remains a geometry/workflow evaluation only; no result implies
load-bearing safety, and physical engineering/test review is still required.

- Repeated cross-product defect: candidate classification/verification remains
  a blocking frontier after worker evidence (three projects).
- Repeated same-family defect: worker geometry reliability produces invalid or
  disconnected output in the holder/organizer family (two worker-reaching
  failures).
- Provider variability: the two pre-worker source/content stops cannot be
  separated into provider variance versus prompt-family behavior from one
  batch.
- Isolated anomalies: the wall carrier’s valid geometry with a blocked final
  candidate and the portable holder’s disconnected output are useful frozen
  regressions.
- Integrity/misleading-state defects: none in the frozen report; redaction
  removed absolute host paths and the frontend had no recorded errors.

## Comparison and correction boundary

No Batch 2 was run, so no controlled-comparison claim is made. A future Batch
2 must match all identity fields before comparison and must stop if any differs.

Exactly one next priority is selected for planning: **generic final geometry
verification convergence for traced features**. The repair should make the
feature-to-requirement measurement contract observable and actionable for
worker-successful outputs, using the wall carrier and frozen holder/organizer
evidence as regressions. It must not relax candidate gates, accept
disconnected solids, or add product-family bypasses.

The correction plan is planning only in
`docs/LIVE_BATCH_CORRECTION_PLAN.md`; no correction was implemented in this
evaluation.

## Screenshots

Deterministic candidate-review screenshot:
`frontend/output/playwright/feature-evidence-candidate-review.png`.

Frozen live screenshots remain in the local batch folder under `screenshots/`
and are intentionally not committed.
