# CadQuery Identity Contract Correction - 2026-07-30

## Root Cause

The corrected readiness rerun failed because CadQuery source generation and repair did not receive one non-negotiable authority inventory everywhere source could be produced or repaired.

Findings from `output/live-benchmarks/live-benchmark-20260730T225034Z-consistency-correction-enclosure-rerun`:

- The initial source prompt did not include a terminal authoritative source-identity section. It included protected requirement values, but the source-probe parameter target list omitted `standoff_count` and `standoff_hole`.
- The missing protected parameters were present in the approved Design Plan and requirement inventory, but they were not rendered as exact required `ParameterSpec` declarations in every affected prompt.
- The prompt path did not consistently distinguish stable product IDs from Python symbol names. Function names were flexible, but product IDs were not made mechanically mandatory in repair prompts.
- The source contract already blocked invalid CadQuery syntax and some parameter trace issues, but `ProjectService._persist_source_contract_validation` was not applying Plan-derived source-authority checks to every generated source and repair.
- Repair prompts did not receive the complete authoritative identity inventory. The lid-only repair prompt only had standalone benchmark source-probe targets, so Gemini could invent `lid_component` and `lid_body`.
- Predictable failures that should be caught before execution are now source-contract failures: missing required parameters, unused protected parameters, missing/renamed components, missing/renamed outputs, output ownership drift, protected feature metadata loss, and protected/default value mismatch.

## Canonical Authority Inventory

Implemented `cadquery-source-authority-v1` in `backend/app/services/cad/cadquery_source_authority.py`.

The inventory is built deterministically from the approved Design Plan and passed through `ModelGenerationRequest.source_authority` to:

- initial CadQuery generation,
- source-contract repair,
- execution repair,
- component-targeted revision,
- scope correction.

For the enclosure rerun, the authority inventory required:

- Parameters: `pcb_width`, `pcb_depth`, `pcb_height`, `standoff_count`, `standoff_hole`, `wall_thickness_mm`.
- Components: `base_shell`, `snap_lid`.
- Protected features: `pcb_cavity`, `standoffs`.
- Outputs: `base -> base_shell`, `lid -> snap_lid`, one solid each.

## Prompt Changes

Narrow prompt version bumps:

- `cadquery-generation-v4`
- `cadquery-contract-repair-v2`
- `cadquery-execution-repair-v2`
- `cadquery-component-revision-v2`
- `cadquery-scope-correction-v2`

Each affected prompt now contains an `AUTHORITATIVE SOURCE IDENTITIES` section near the output instructions with structured JSON and readable tables. The prompt states that Python function names may differ, but decorator and metadata product IDs must match exactly.

## Contract Changes

The CadQuery source authority validator now adds hard findings for:

- `cadquery.required_parameter_missing`
- `cadquery.required_parameter_metadata_mismatch`
- `cadquery.required_parameter_unused`
- `cadquery.required_component_missing`
- `cadquery.required_feature_missing`
- `cadquery.required_output_missing`
- `cadquery.component_identity_mismatch`
- `cadquery.output_identity_mismatch`
- `cadquery.output_component_mismatch`
- `cadquery.unapproved_identity_added`
- `cadquery.protected_value_mismatch`

The existing CadQuery contract also now accepts static `@component(id="...")` and `@shared_helper(id="...")` metadata forms, while still allowing the existing positional form.

Execution parameter loading now normalizes integral Design Plan count values to source-declared `int` parameters before worker submission. This fixed the rerun-only issue where `standoff_count` was stored as `4.0` in the Plan but declared as `type="int"` in source.

## Repair Behavior

Contract repair now receives the rejected source, exact hard findings, and the full source-authority inventory. In the final enclosure rerun, the initial generated source was rejected before execution because `standoff_count` was declared but not used. The bounded contract repair corrected that issue while preserving:

- component IDs: `base_shell`, `snap_lid`,
- output IDs: `base`, `lid`,
- protected parameter values,
- protected feature decorators.

## Regression Coverage

Added focused deterministic coverage for:

- missing protected parameters,
- declared but unused protected count parameters,
- invented component/output identities,
- differing Python function names with matching stable IDs,
- keyword `id=` decorator metadata,
- integral Plan count coercion for source-declared integer parameters.

Existing consistency, structured revision, prompt snapshot, benchmark fixture, and frontend tests were rerun.

## Base-Generation Rerun

Final preserved rerun:

`output/component-revision-evaluation/live-component-revision-20260730-identity-contract-correction`

Provider:

- `gemini_api`
- `gemini-3.5-flash-lite`

Recorded final provider usage:

- provider calls: `2`
- estimated prompt tokens: `15,751`
- latency: `21,476.554 ms`

Implementation-session note: an earlier preliminary live attempt consumed 2 additional provider calls before the deterministic integer execution-parameter fix was applied. The final preserved rerun above is the evidence run used for this report.

## Base Consistency Result

The final base rerun improved the failure mode:

- Initial source: rejected before execution by source contract.
- Contract repair: passed source contract.
- Execution: produced STEP/STL/BREP artifacts for both required outputs.
- Pre-execution consistency: passed.
- Post-execution consistency: blocked.

Source metadata after repair:

- Parameters: `pcb_width=70.0`, `pcb_depth=45.0`, `pcb_height=18.0`, `standoff_count=4`, `standoff_hole=2.6`, `wall_thickness_mm=3.0`.
- Components: `base_shell`, `snap_lid`.
- Outputs: `base`, `lid`.
- Output ownership: `base -> base_shell`, `lid -> snap_lid`.

Output manifest:

- `base`: `ready_with_warnings`, component `base_shell`, one solid, dimensions `78 x 53 x 26 mm`.
- `lid`: `blocked`, component `snap_lid`, one solid, dimensions `78 x 53 x 5 mm`.

Blocking reason:

- `lid` extends below the build plate (`z_min=-2.0`), producing `geometry.build_plate_min_z` and `orientation.below_build_plate`.
- Design artifact consistency then blocked because required manifest output `lid` was not ready.

## Lid Revision Result

The lid finger-pull revision was not started. This is correct lifecycle behavior: the regenerated base did not certify as revision-base ready, so Volundr did not create a provider-backed Revision Plan and did not consume revision-planning quota.

## Topology and Printability

Topology succeeded:

- `base`: one solid, valid topology.
- `lid`: one solid, valid topology.

Printability/readiness blocked:

- `lid` has geometry below Z=0.
- Additional nonblocking orientation findings reported overhang/bridge/unsupported-ceiling concerns.

Manual classification:

- Base generation: requires targeted geometry/orientation repair before acceptance.
- Lid revision: not evaluated because the base was not certifiable.

## User-Facing Behavior

Source-contract identity failure messaging now starts with:

`The generated model did not implement the approved design identities.`

The UI continues to show technical details separately and does not ask the user for more dimensions for internal identity failures.

## Remaining Issues

- The identity contract is now preventing and repairing the target ID/parameter defects.
- The current enclosure base still fails for a narrower post-contract geometry/orientation issue: lid placement below the build plate.
- The revision lifecycle correctly refused to use the blocked base.

## Recommended Next Task

Add a narrowly scoped generation/repair correction for output build-plate placement and orientation readiness, then rerun only the electronics enclosure base. Start the lid finger-pull revision only after the base certifies.
