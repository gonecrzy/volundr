# Geometry slots live evaluation

Status: deterministic production gate complete; the historical diagnostic
batch and one post-implementation focused real-provider validation batch were
completed and frozen on 2026-08-03. Raw evidence for both batches remains
local and outside Git.

## Post-implementation focused validation

The required focused batch completed successfully with Playwright test status
`1 passed` in 2.8 minutes. Its batch ID is
`8a81e929-9f8b-410d-9239-393bcaba9b2f`; the raw evidence is preserved at
`/tmp/volundr-live-e2e.tUuRBW/data/debug-sessions/8a81e929-9f8b-410d-9239-393bcaba9b2f/`
and is intentionally not committed.

The batch used Git HEAD
`476254b204c5585eb717863719d6a8816d86f6ab`, migration head
`0032_provider_response_lifecycle`, provider `gemini_api`, configured model
`gemini-3.5-flash-lite`, and the captured production prompt versions and build
identities. Redaction completed with status `confirmed`. There was no Batch 2
and no controlled comparison.

| Project | Canonical outcome | Worker | Geometry/artifacts | Blocking evidence |
| --- | --- | --- | --- | --- |
| wall carrier | `source_blocked` | no | not reached | compact-plan normalization |
| portable holder | `candidate_blocked` | succeeded | one solid; STEP/STL/BREP present | critical handle, drainage, and strap-slot requirement findings |
| desktop organizer | `source_blocked` | no | not reached | pre-worker requirement-trace ambiguity |
| monitor wall mount | `source_blocked` | no | not reached | geometry source extraction defect; physical engineering review remains required |
| screw-lid container | `worker_failed` | failed | no valid output | CadQuery selector syntax failure |

The portable result confirms the generic one-part topology obligation helped
the generated output converge to one solid with complete artifacts; candidate
promotion still stopped at actual requirement gates. The regenerated copied
report also confirms that the pre-worker desktop artifact finding now resolves
to `source_blocked`, matching its lifecycle label rather than `interrupted`.

Screenshots for this batch are local under
`/tmp/volundr-live-e2e.tUuRBW/data/debug-sessions/8a81e929-9f8b-410d-9239-393bcaba9b2f/screenshots/`.

## Required batch

The live batch is `geometry-slots-live-01` and uses the five existing mixed-CAD
projects: wall carrier, portable holder, desktop organizer, monitor wall
mount, and screw-lid container. It must use the same prompts and approved fact
sheets throughout, preserve every attempt, and keep raw evidence local under
`data/debug-sessions/geometry-slots-live-01/` outside Git.

The monitor-wall-mount result is not a load-bearing safety determination.
Reports must retain its physical engineering/test-review warning even when
geometry and workflow checks pass.

## Deterministic gate

- Backend: 711 tests passed.
- Geometry-slot contract and frozen fixture replay: 19 contract/fixture tests
  passed within the targeted 39-test integration slice.
- Frontend: 93 unit tests passed; production build passed.
- Playwright: direct and compact chat-first scenarios passed at 1440×900.
- Screenshots: local ignored evidence under
  `data/debug-sessions/geometry-slots-deterministic/`.

The browser scenarios confirmed that the selected contract is visible only in
technical details, direct and compact paths use `volundr-geometry-slots-v1`,
and internal contract work does not create duplicate user-facing progress.

## Frozen live batch result

The authoritative local evidence is the frozen batch at
`/tmp/volundr-live-e2e.VMFoAm/data/debug-sessions/8ea3488d-940b-44de-9ed1-772efef6597f/`.
It is intentionally not committed to Git. The batch was `geometry-slots-live-01`
with ID `8ea3488d-940b-44de-9ed1-772efef6597f`; membership was five projects,
the state was frozen, and the report recorded zero integrity findings.

The captured identities were Git HEAD
`bf8281fb476a5114fe4c395e986edd056400ef99`, migration head
`0032_provider_response_lifecycle`, provider `gemini_api`, configured model
`gemini-3.5-flash-lite`, configuration hash
`76d0ab528fa8eba60a8cb272c80ab3ad1afcd5fa54862bea020f0d788fae55d3`, and
clean backend, frontend, and worker build identities at that same Git SHA.
The production prompt versions remained `requirements-v4`,
`compact-cad-plan-v3`, `design-plan-v8`, `cadquery-geometry-body-v10`,
`cadquery-geometry-body-repair-v10`, and `revision-planning-v1`.

| Project | Route | Contract | Initial slot response | Completion | Fallback | Worker | Final outcome | Integrity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| wall carrier | compact | —; plan blocked first | — | 0 | — | no | blocked before worker | 0 |
| portable holder | compact | slots | 1 completed, 5 invalid of 6 | 1 call for 5 slots | no | yes | blocked after worker: execution/topology | 0 |
| desktop organizer | compact | slots | 1 completed, 5 invalid of 6 | 1 call for 5 slots | no | yes | blocked after worker: candidate verification | 0 |
| monitor wall mount | detailed | legacy | — | 0 | — | no | blocked before worker: artifact consistency | 0 |
| screw-lid container | compact | slots | 0 completed, 9 invalid of 9 | 1 call for 9 slots | no | no | blocked before worker: artifact consistency | 0 |

Across the batch, 19 provider calls produced 19 generation attempts, two
content repairs, zero provider retries, two worker reaches, two generated
geometry results, one snapshot set, and zero valid geometry results. The
funnel retained all five requirement completions and all attempts. The report
also recorded zero duplicate messages, zero frontend errors, and zero missing
assistant outcomes.

The slot-route initial geometry prompts used 5,892–9,607 provider prompt
tokens, compared with the prior current-contract evidence of approximately
39,000–46,000 tokens. Focused completion prompts were 13,245–20,971 tokens.
The detailed monitor route remained on the documented legacy boundary and used
55,475 prompt tokens. This confirms material reduction for direct/compact slot
generation, but not successful geometry production in this batch.

## Individual project review

- The wall carrier reached compact planning but failed plan normalization on
  two attempts after the initial requirements call. It never reached source
  assembly or the worker.
- The portable holder supplied one valid slot and five invalid slots. The
  focused call was bounded to those five slots. Source passed, but the worker
  reported an invalid output shape and topology found separate solids that
  were expected to be connected.
- The desktop organizer followed the same one-valid/five-invalid convergence
  pattern. It produced a revision and snapshots, but final candidate
  classification remained blocked by verification. A preliminary live-manifest
  heuristic called it `candidate` while the authoritative frozen report called
  it `Blocked after worker`; this is recorded as a misleading-state repair
  candidate even though the integrity scanner returned zero findings.
- The monitor wall mount correctly stayed on the detailed/legacy boundary. It
  was blocked by design-artifact inconsistency before the worker. It remains a
  geometry/workflow evaluation only: the evidence does not establish wall,
  fastener, material, or load-bearing safety, and physical engineering/test
  review is still required.
- The screw-lid container returned nine invalid slots, received one bounded
  completion call, and remained blocked by design-artifact consistency. This
  does not justify adding a screw-thread helper in this pass.

Repeated signatures were `plan_validation:plan.validation.blocked` in two
projects and `candidate_classification:candidate.classified` in two projects.
The worker/topology failures were same-family geometry defects in the
portable-holder path. Provider variability is present in the different
completion and post-worker outcomes, but no second live batch was run to make
a controlled variability claim. The monitor artifact inconsistency and the
preliminary-versus-authoritative desktop outcome are isolated/integrity-state
review items.

## Comparison and decision

There is no Batch 2 in this rollout: `baseline_batch_id` is null and the
comparison status is `not_applicable`. Therefore this run may be compared with
the earlier diagnostic evidence for reach and token direction, but it must not
be presented as a controlled improvement claim. Relative to the objective's
prior evidence, the slot route reduced the geometry prompt size substantially
and kept the direct/compact contract boundary intact; it did not yet produce a
valid live geometry result.

The initial post-batch planning note named deterministic feature verification,
but the subsequent blocker review tested that counterfactual against every
worker-reaching project and rejected it. Exactly one actual next CAD priority
is selected:

**Generic geometry/topology convergence.**

Both worker-reaching projects failed to become valid candidates: one failed
worker output/topology convergence and one failed required-output readiness
despite valid topology. The narrow manifest/report integrity correction is
implemented separately; no selected CAD correction or follow-up live run is
part of this review.

The complete evidence review and rejection of the other priorities is in
`docs/GEOMETRY_SLOTS_BLOCKER_REVIEW.md`.
