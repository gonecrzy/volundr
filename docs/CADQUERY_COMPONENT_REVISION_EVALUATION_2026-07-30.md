# CadQuery Component Revision Evaluation

Date: 2026-07-30

Base smoke run: `output/live-benchmarks/live-benchmark-20260730T214755Z-live-smoke-correction-targeted-v5`

Authoritative evaluation artifact: `output/component-revision-evaluation/live-component-revision-20260730-enclosure-lid-v2`

Discarded procedural replay: `output/component-revision-evaluation/live-component-revision-20260730-enclosure-lid-v1`

## Scope

This evaluation exercised the first real component-targeted CadQuery revision path against the live-generated electronics enclosure from the targeted correction run. No general prompts, schemas, source contracts, or revision architecture were changed before the run.

The requested revision was:

> Revise only the enclosure lid to add a recessed finger-pull feature that is printable without supports. Preserve the enclosure body, PCB cavity, mounting standoffs, lid fit, outer width and depth, wall thickness, and all existing output identities.

The full lifecycle was attempted:

```text
accepted base revision
-> Revision Plan
-> Revision Plan approval
-> Gemini component-targeted full-source CadQuery revision
-> source contract
-> source ownership comparison
-> scope correction
-> revised candidate
```

The lifecycle stopped before CadQuery execution of the revised source because deterministic Revision Plan compliance rejected the generated and scope-corrected source.

## Base Enclosure State

The base source exists and compiles into two valid outputs:

| Source artifact | Value |
| --- | --- |
| Source file | `source-extracted.py` from the preserved enclosure run |
| Source components | `enclosure_base`, `enclosure_lid` |
| Source outputs | `base_body`, `lid_body` |
| Base output topology | both outputs valid, one solid each |
| Base source `wall_thickness` default | `2.5 mm` |
| Base execution parameters in preserved run | `pcb_width=70`, `pcb_depth=45`, `pcb_height=18`, `standoff_count=4`, `standoff_hole=2.6` |

The preserved Design Plan does not use the same IDs or all the same parameter values:

| Design Plan artifact | Value |
| --- | --- |
| Components | `base_shell`, `snap_lid` |
| Printable outputs | `base`, `lid` |
| Plan `wall_thickness` | `3.0 mm` |

This mismatch is material for component-targeted revision because the revision prompt includes both Design Plan IDs and source/output-manifest IDs, while the preservation checker compares revised source against both the approved Revision Plan and the base source.

## Revision Plan

The corrected replay produced a Revision Plan without clarification.

Key scope:

- Targeted component: `enclosure_lid`
- Targeted feature: `finger_pull`
- Targeted output: `lid_body`
- Protected output: `base_body`
- Protected parameters: `pcb_width=70.0 mm`, `pcb_depth=45.0 mm`, `pcb_height=18.0 mm`, `wall_thickness=3.0 mm`
- Allowed parameter additions/changes: `finger_pull_depth`, `finger_pull_width`

The plan was appropriately narrow at the output level and did not protect the targeted lid output. It did, however, protected `wall_thickness=3.0 mm` from the Design Plan even though the base source default is `2.5 mm`.

## Generated Source

The component-revision provider response added the intended finger-pull concept, but changed protected or out-of-scope details:

- Added `finger_pull_width` and `finger_pull_depth` parameters.
- Changed `wall_thickness` `ParameterSpec.default` from `2.5` to `3.0`.
- Left source output IDs as `base_body` and `lid_body`.
- Used comments for protected features such as `pcb_cavity`, `standoff_pattern`, and `cable_opening`; the current ownership scanner only treats decorators and contract metadata as source mappings.

The source contract hard checks passed. Revision compliance failed before compile.

One bounded `cadquery-scope-correction-v1` call ran. The corrected source still failed compliance, again before compile.

## Compliance Result

Final blocking findings from the corrected replay:

| Rule | Count | Meaning |
| --- | ---: | --- |
| `revision.unauthorized_parameter_change` | 1 | `wall_thickness` changed from the base source value `2.5` to `3.0`. |
| `revision.unauthorized_parameter_definition_change` | 1 | `wall_thickness` `ParameterSpec` declaration changed outside allowed scope. |
| `revision.protected_feature_removed` | 3 | Protected Design Plan features were not represented as source ownership markers. |
| `revision.required_output_removed` | 2 | Design Plan outputs `base` and `lid` are missing from source, whose outputs are `base_body` and `lid_body`. |
| `revision.undeclared_component_added` | 1 | Scope correction introduced a component ID not authorized by the Revision Plan. |
| `revision.undeclared_output_added` | 1 | Source output IDs do not match the Design Plan output inventory. |

No revised candidate was created. No revised STEP/STL artifacts exist for this run.

## Printability And Geometry

Base geometry:

- `base_body`: valid topology, one solid.
- `lid_body`: valid topology, one solid.

Revised geometry:

- Not executed.
- No topology, printability, B-Rep bounds, output preservation, or contact-sheet comparison was produced for a candidate because the pre-execution scope gate blocked the source.

The finger-pull geometry is visible in the rejected source as a lid-local subtractive pocket. Physical usefulness and support-free printability remain human-unverified.

## Provider Usage

Corrected replay provider usage:

| Stage | Estimated prompt tokens | Latency |
| --- | ---: | ---: |
| Revision Plan | 6,442 | 2,484.506 ms |
| Component revision | 5,711 | 5,741.331 ms |
| Scope correction | 7,069 | 5,838.755 ms |
| Total | 19,222 | 14,064.592 ms |

Provider: `gemini_api`

Model: `gemini-3.5-flash-lite`

Provider calls: 3

## Defects Discovered

The component-targeted revision lifecycle is blocked by base artifact traceability defects, not by missing live-provider capability alone:

1. The base Design Plan output IDs (`base`, `lid`) do not match generated CadQuery output IDs (`base_body`, `lid_body`).
2. The base Design Plan component IDs (`base_shell`, `snap_lid`) do not match generated CadQuery component IDs (`enclosure_base`, `enclosure_lid`).
3. The base Design Plan value `wall_thickness=3.0 mm` does not match the generated CadQuery `ParameterSpec.default=2.5 mm`.
4. Protected Design Plan features are not backed by source ownership metadata, so preservation can only detect their absence as markers, not their geometric preservation.
5. The component-revision prompt and scope correction prompt were forced to reconcile inconsistent authoritative sources and produced source changes that the deterministic gate correctly rejected.

The first stage where the evaluation becomes unsound is the base source/Design Plan contract before revision planning. The source was usable for a smoke compile, but not product-quality enough to serve as a component-targeted revision base.

## Implementation Correction

No production implementation correction was made in this pass.

The evidence supports a narrow next correction, but it should be its own pass:

- Add or tighten a deterministic "component-revision base readiness" gate before live Revision Plan creation.
- The gate should reject accepted/base revisions when approved Design Plan outputs, component IDs, protected/default parameter values, or protected feature IDs cannot be mapped to generated source ownership and execution parameters.
- The gate should fail before provider calls, with a recoverable state explaining that the base revision must be regenerated or repaired before component-targeted revision.
- Do not weaken the existing pre-compile preservation gate; it correctly prevented execution of a drifted source.

## Manual Classification

Classification: `target changed but preservation uncertain`

Rationale: Gemini produced a plausible lid-local finger-pull in rejected source, but the base Plan/source mismatch and `wall_thickness` drift prevented source approval, execution, topology validation, printability validation, and protected-output comparison.

## Recommended Next Task

Fix component-revision base readiness deterministically before rerunning this enclosure evaluation.

After that gate exists, rerun only this enclosure lid revision. Do not move to the organizer redesign until an enclosure component-targeted run produces a candidate or fails for a narrower, well-classified reason after passing base readiness.
