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
