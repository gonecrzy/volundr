# CadQuery Output Placement and Lid Revision Evaluation

Date: 2026-07-30

## Placement Root Cause

The regenerated enclosure source built the lid as an independent printable output centered around its local Z origin. That produced model-space bounds below the build plate. In the prior identity-contract rerun, the lid exported with `z_min=-2.0 mm`, so geometry and printability correctly blocked it before acceptance.

Diagnosis:

1. The source intentionally produced a lid body that crossed Z=0. This was ordinary CadQuery centered-box behavior, not a missing user requirement.
2. CadQuery `box(...)` operations are centered by default unless `centered` or a later translation changes that placement.
3. Output placement was source-owned before this pass. The worker exported model-space geometry directly.
4. STEP and STL agreed on negative Z in the failing artifacts because both were exported from the same unnormalized model.
5. The printability rule was correct: printable artifacts below Z=0 should block. The defect was using model-space coordinates as print-space coordinates.
6. Historical output-manifest scan found negative-Z topology in the earlier enclosure `lid_body` revision artifacts; it did not show a broad fixture-wide pattern in current manifests.
7. Automatic Z translation is safe for independently printable outputs because it is a rigid transform that preserves geometry, topology, source hash, parameter hash, and component identity. Assembly/interface reasoning can still read model-space bounds from metadata.
8. The narrow durable correction is worker-side print-space translation per output, not prompt-only source rewriting or user clarification.

## Coordinate-Space Policy

Implemented policy:

`cadquery-output-placement-v1`

For each independently printable CadQuery output:

- Preserve source geometry and model-space meaning.
- Inspect model-space B-Rep bounds after build.
- Derive a print transform that raises negative `z_min` to `0`.
- Do not rotate outputs in this pass.
- Export STL, STEP, and BREP from the print-space model.
- Persist model-space bounds, print transform, and print-space bounds in topology metadata.

Example from the successful enclosure rerun:

- Base: model-space `z_min=0.0`, print transform `[0.0, 0.0, 0.0]`, print-space `z_min=0.0`.
- Lid: model-space `z_min=-1.5`, print transform `[0.0, 0.0, 1.5]`, print-space `z_min=0.0`.

## Worker and Export Changes

The CadQuery CLI runner now applies the print-placement transform at export time:

- Source is unchanged.
- Source hash is unchanged.
- Parameter hash is unchanged.
- Topology solid count is checked before and after translation.
- STL and STEP are exported from the same print-space model.
- BREP export also uses the print-space model for output-level artifacts.
- The execution manifest includes `placement_policy`, `model_space_bounds`, `print_transform`, and `print_space_bounds`.

The output manifest carries the same topology metadata, so downstream review and debug artifacts can distinguish model-space from print-space.

## Certification Changes

No new broad certification architecture was added.

Existing design-artifact consistency now passes when:

- source and output identities match,
- execution/output manifests match,
- required outputs are ready,
- print-space topology is valid,
- print-space artifacts are above the build plate.

Negative model-space Z no longer blocks when the persisted print transform produces valid print-space placement. Negative print-space Z still blocks through the existing geometry and printability rules.

## Frontend

Printable output review now shows a concise placement summary:

- `Placed on build plate`
- `Raised 1.5 mm to build plate`

Raw transform arrays remain in technical topology metadata rather than the default review view.

## Base Rerun Result

Rerun artifact directory:

`output/component-revision-evaluation/live-component-revision-20260730-identity-contract-correction`

Provider:

- `gemini_api`
- `gemini-3.5-flash-lite`

Base generation result:

- Initial source generation: source-contract rejected before execution because `standoff_count` was declared but not used.
- Contract repair: succeeded.
- Source identity contract: passed after repair.
- Stable components: `base_shell`, `snap_lid`.
- Stable outputs: `base`, `lid`.
- Protected parameters preserved: `pcb_width`, `pcb_depth`, `pcb_height`, `standoff_count`, `standoff_hole`.
- Execution: succeeded.
- Output count: two required outputs, both produced.
- Solid counts: one solid for `base`, one solid for `lid`.
- Design consistency: passed.
- Review state: `ready_with_warnings`.
- Base candidate: accepted for the revision proof.

Base output manifest:

- `base`: `ready_with_warnings`, component `base_shell`, print-space `z_min=0.0`.
- `lid`: `ready_with_warnings`, component `snap_lid`, model-space `z_min=-1.5`, print-space `z_min=0.0`.

## Lid Revision Result

Revision request:

`Revise only the enclosure lid to add a recessed finger-pull feature that is printable without supports. Preserve the enclosure body, PCB cavity, mounting standoffs, lid fit, outer width and depth, wall thickness, all protected parameters, and all existing component and output identities.`

Revision Plan:

- Outcome: `revision_ready`.
- Targeted component: `snap_lid`.
- Targeted output: `lid`.
- Protected component: `base_shell`.
- Protected output: `base`.

Revision generation:

- Component revision source generation: succeeded.
- Source identities remained exact: `base_shell`, `snap_lid`, `base`, `lid`.
- Source compliance: passed.
- Design consistency: passed.
- Candidate status: `succeeded`.
- Review state: `ready_with_warnings`.

Revision output preservation:

- Protected `base` output: verified unchanged.
- Targeted `lid` output: changed as expected.
- Base output hash: unchanged.
- Lid output hash: changed.
- Lid solid count: one.
- Lid topology: valid.
- Lid print placement: model-space `z_min=-1.5`, print transform `[0.0, 0.0, 1.5]`, print-space `z_min=0.0`.

The revised source contains a recessed finger-pull cut in `snap_lid`.

## Provider Calls and Tokens

Final rerun provider usage:

- Calls: `4`
- Estimated prompt tokens: `31,146`
- Total latency: `19,581.084 ms`

Stages:

- `cadquery`: `7,634` estimated prompt tokens
- `contract_repair`: `8,074` estimated prompt tokens
- `revision_plan`: `7,502` estimated prompt tokens
- `component_revision`: `7,936` estimated prompt tokens

## Printability Result

Both base and revised candidates reached `ready_with_warnings`.

Blocking placement findings from the previous run were eliminated:

- No `geometry.build_plate_min_z` blocker.
- No `orientation.below_build_plate` blocker.

Remaining findings are nonblocking review warnings:

- missing parseable protected geometry metadata for invariant checks,
- overhang/bridge/unsupported-ceiling orientation warnings.

## Manual Classification

- Regenerated enclosure base: printable after orientation/support review.
- Lid finger-pull revision: printable after orientation/support review.

The lifecycle proof succeeded: a certified base was accepted, a component-targeted Revision Plan was created, the lid-only source revision preserved protected output identity and geometry, and the revised candidate reached review.

## Verification

Deterministic verification run before the live rerun:

- Full backend suite: `278 passed`.
- Targeted execution/topology tests: placement runner tests passed.
- Frontend unit tests: `43 passed`.
- Frontend build: passed.
- Staged Playwright suite: `4 passed`.
- Benchmark fixture validation: `32 passed`.

No migration was run because this pass did not add or change database schema.

## Remaining Issues

- Orientation optimization is still intentionally out of scope. The system reports overhang/bridge warnings but does not yet choose alternate rotations.
- Geometry invariant checks still need better source/Plan metadata for protected feature measurement.
- The initial base source still needed one bounded contract repair for `standoff_count` use.

## Recommended Next Task

Stop backend rule expansion for now. Move to workflow tracing and frontend user-workflow audit:

1. Add workflow run IDs, NDJSON lifecycle events, first-failure diagnosis, prompt/source snapshots, parameter/identity traces, and secret-redacted debug bundles.
2. Audit the real frontend journey from request through requirements, proposed design, generation, inspection, configuration/revision, acceptance, and export.
