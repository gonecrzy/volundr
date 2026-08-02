# Multi-view Snapshot Live Evaluation

Status: Evaluated 2026-08-01 with the opt-in real-provider harness

This report records the opt-in real-provider evaluation of the exact direct
brief and its revision. It must be read separately from deterministic
Playwright fixture results and from any future AI visual-review evaluation.

## Cases

Initial request:

> Create a rectangular spacer plate that is 80 mm wide, 45 mm tall, and 6 mm
> thick. Add two through-holes, each 5 mm in diameter. Place the first hole
> center 12 mm from the left edge and centered vertically. Place the second
> hole center 18 mm from the right edge and centered vertically. Round the four
> outside corners with a 2 mm radius. Produce one printable part.

Revision:

> Increase the plate thickness from 6 mm to 8 mm and move the left hole 3 mm
> to the right. Preserve the plate width, height, right-hole position, hole
> diameters, and corner fillets.

## Required evidence

The live run records the selected direct-brief route, provider attempts,
worker reachability, candidate state, explicit export result, snapshot packet
hash, image hashes, render timings, revision comparison, and browser-quality
signals. It does not claim geometry or physical success when the worker,
artifact, topology, or functional evidence is incomplete.

## Observed result

The exact live request reached the new proportional planning workflow but was
blocked before worker execution by the existing geometry-body dependency gate.
The run was retained temporarily under an isolated live data directory and
then removed by the harness.

- project: `9b651088-a7bd-43c7-b5ae-b22cb495ec9f`;
- initial revision: `425873f9-8a6e-4b2d-b00c-da5fdf580705`;
- requirements: passed after one failed extraction attempt and one successful
  `requirements-v3` attempt;
- selected route: `compact_plan` (`compact-cad-plan-v1`), not direct brief;
  the provider-extracted functional feature inventory caused the router to
  classify the case as interacting features. This is recorded evidence, not a
  router change in this pass;
- planning provider call: one successful `compact-cad-plan-v1` call, using
  `gemini-3.5-flash-lite`, 5,069 ms;
- geometry calls: one `cadquery-geometry-body-v6` call (1,750 ms) and one
  bounded `cadquery-geometry-body-repair-v6` call (2,606 ms);
- blocking finding: `geometry_body.derived_dependency_broken` for an
  incomplete approved dependency path for `hole_y_position`;
- worker: not reached; no STL, STEP, BREP, topology, or functional output;
- snapshot packet/images: not applicable before worker, with no fabricated
  packet or image hashes;
- revision comparison: not generated because there was no worker-produced
  parent/new geometry pair;
- export: not attempted because the candidate was blocked;
- candidate state: blocked, with Current working version unchanged;
- physical checks: not run because worker execution was correctly gated.

The deterministic fixture run passed the standard-view and revision
comparison UI/API coverage, including durable packet/image registration and
stable packet hashes. The real-provider result above remains a genuine
pre-worker source failure, not evidence that snapshot rendering failed.

Deterministic fixture coverage is already present in
`frontend/e2e/snapshot-evidence.spec.ts`; it does not substitute for the
real-provider result above.

## Follow-up classification correction

The earlier `hole_y_position` rejection exposed an unconditional dependency
gate: malformed derived metadata was treated as a critical geometry failure
even when the ordinary plan had no exposed controls and the generated source
did not reference the value. The corrected contract retains that record as
`planning.derived_dependency_unused_or_incomplete` warning evidence. Only an
execution-relevant dependency remains `geometry_body.derived_dependency_broken`.
The rerun outcome is recorded separately in the derived-dependency live
evaluation evidence.

## Corrected rerun — 2026-08-02

The exact request was rerun once through the repaired live harness with the
real Gemini API, FastAPI services, and CadQuery worker. The run completed
without a binding failure and preserved isolated evidence at
`/tmp/volundr-live-e2e.4037sv`.

- route: `direct_brief`; no planning-provider call;
- requirements: passed, `requirements-v3`, Gemini latency 2,788 ms;
- structured geometry: assembled successfully under
  `cadquery-geometry-body-v6`; no derived-dependency findings were emitted by
  this provider response;
- source contract: passed and the worker job was submitted;
- worker: reached, but the generated source failed during execution with a
  genuine `NameError` (`plate_width` was referenced without a local or
  `params[...]` binding);
- worker timing: the generation attempt recorded 1,160 ms provider latency;
  the worker result recorded a 4,142.273 ms compile/worker phase before the
  failure;
- topology, functional mounting/hole, floor, removal, and retention checks:
  not run because no worker geometry was produced;
- snapshots: correctly marked not applicable before worker geometry;
- STL/STEP/BREP readiness: failed with the worker output, with no fabricated
  artifacts;
- candidate: blocked; no Current working version was promoted;
- revision: not attempted because there was no accepted parent version.

This rerun demonstrates that the former unconditional dependency gate no
longer blocks ordinary source assembly. It exposed a separate provider source
execution defect, which remains correctly blocking. The classification-specific
unused-metadata behavior is covered by the deterministic regression and
scaffold-manifest evidence tests; this particular provider response did not
repeat the malformed derived record.

## Symbol-contract correction — 2026-08-02

The preserved `NameError: name 'plate_width' is not defined` was traced to
provider-owned statements in `_ai_component_primary_part(params)`. The
scaffold supplied `params`; it did not create bare Python locals for Plan IDs.
The structured-body validator previously checked syntax and safety but not
lexical name resolution, so the worker was the first evaluator.

The correction adds generic lexical and conservative definite-assignment
analysis, exact per-function symbol inventories in the geometry prompt, and a
bounded repair path for one safely identified provider function. The source
contract still allows ordinary literals and local expressions; it only requires
valid Python scope. See `GEOMETRY_BODY_SYMBOL_CONTRACT.md`.

## Exact spacer rerun — 2026-08-02

The exact spacer request was run through the opt-in live browser harness with
the real Gemini API, FastAPI service, and CadQuery worker. The single selected
scenario passed in 18.3 seconds. Preserved live data: `/tmp/volundr-live-e2e.qfNNKf`.

- route: `direct_brief`; no planning-provider call;
- geometry body: assembled and source-symbol validation passed;
- bounded repair: not invoked because the live provider response used the
  approved `params[...]` bindings; targeted repair remains available for a
  pre-worker rejection or safely identified runtime name failure;
- worker: reached and completed successfully in 3,566.152 ms;
- topology: one valid solid, matching the required one-solid output;
- artifacts: STL, STEP, and BREP produced with persisted hashes;
- snapshots: packet and whole-design/component views generated;
- candidate: `accepted`, Current working version promoted; API-facing review
  state was `ready_with_warnings` because available requirement metadata did not
  provide definitive geometric invariant evidence for every requested feature;
- warnings: deterministic geometric/requirement findings remained nonblocking;
- export: not exercised by this one-scenario routing test;
- revision: not attempted because the live case was an initial request.

No NameError, fake snapshot, fake topology result, or false blocked state was
observed in this rerun. The result demonstrates that the source-scope defect is
resolved for the covered case; it does not claim physical fit, print quality,
or one-handed behavior beyond available deterministic evidence.

Remaining blocker/evidence limitation: the worker and topology gates passed,
but the current live direct brief did not provide enough deterministic
geometric-invariant metadata to turn every requested hole position, corner
radius, or fit statement into a definitive requirement-compliance pass. Those
findings remain warnings and require review of the produced artifact; this pass
does not add another requirement-validation layer.
