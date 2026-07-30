# Geometric Invariant Validation

This document defines Volundr's first post-compile geometric invariant checks. It is intentionally narrower than reverse engineering arbitrary STL geometry.

## Pipeline Position

```text
cadquery-v1 source contract passes
  -> isolated CadQuery worker execution
  -> B-Rep topology validation
  -> STEP/STL artifact export
  -> mesh integrity inspection
  -> geometric invariant analysis
  -> printability analysis
  -> combined validation summary
  -> candidate classification
```

Geometric invariant analysis runs only after a mesh exists and topology validation has produced a successful printable output. It does not replace CadQuery/OpenCascade B-Rep validity checks.

## Supported Invariants

Current analyzer version: `geometric-invariants-v1`

Tolerance profile: `geometry-tolerance-v1`

Supported checks:

- Overall X/Y/Z bounds declared through geometry metadata.
- Build-plate placement from mesh minimum and maximum Z.
- Axis-aligned cylindrical through-hole diameter.
- Declared hole-group count.
- Two-hole center spacing.
- Coarse wall-thickness estimate for declared wall-thickness regions.

Unsupported in this pass:

- arbitrary feature recognition
- angled holes
- blind-hole proof
- thread, gear, snap-fit, seal, or fluid-tightness verification
- proof that source markers physically implement feature intent
- stress or load simulation

## Geometry Metadata

The current CadQuery product path derives source metadata from the `cadquery-v1` contract and the approved Design Plan:

- `ParameterSpec(...)` declarations provide source-mapped parameter defaults.
- `PrintableOutput(...)` declarations provide output IDs and component ownership.
- Approved Design Plan components and features provide product-structure context.
- Supported geometry mappings, when available, bind measurable invariants such as bounds, holes, hole groups, and wall thickness to source parameters.

Rules:

- Geometry mappings must reference stable Design Specification IDs through named source parameters.
- Geometry mappings are required when Volundr is expected to verify protected measurable invariants beyond generic build-plate placement.
- Missing parseable geometry mappings on a candidate with protected design invariants produce an advisory `geometry.invariants_unverified` finding.
- Geometry mappings declare what the model intended to implement; the mesh analyzer still verifies only what it can measure with confidence.

## Verification States

Every geometric check records one state:

```text
verified
violated
unverifiable
not_applicable
```

`unverifiable` is not treated as `verified`. It creates a visible advisory finding so the user can review the candidate.

## Tolerance Model

Initial tolerances are analysis tolerances, not manufacturing tolerances:

- Overall dimensions: max of `0.20 mm` and `0.25%`.
- Hole diameter: `0.20 mm`.
- Hole spacing: `0.25 mm`.
- Below build plate: `0.05 mm`.
- On-plate contact: `0.10 mm`.
- Wall thickness measurement tolerance: `0.20 mm`.
- Wall thickness uncertainty band: `0.30 mm`.

## Confidence Model

Confidence is analyzer evidence, not statistically calibrated probability:

- `0.90` to `1.00`: high confidence; may block protected violations.
- `0.70` to `0.89`: medium confidence; advisory unless corroborated.
- below `0.70`: unverifiable or informational.

Confirmed high-confidence protected violations block candidate acceptance. Unverifiable protected features warn rather than block.

## Persistence

Volundr persists a `GeometricAnalysisResult` linked to the revision and Design Specification. The result records:

- analyzer version
- tolerance-profile version
- mesh hash
- source hash
- analysis timing
- full machine-readable findings

Blocking or advisory non-pass findings are also persisted through `validation_findings` with category `geometry`. The JSON artifact links each persisted finding back to its `validation_finding_id` when one exists.

Legacy candidates without geometric analysis remain loadable and display as not evaluated.

## Blocking Rules

A geometric finding blocks candidate acceptance only when all conditions are true:

- the requirement is protected or the rule is a hard build-plate/build-volume placement rule
- the analyzer supports the feature
- detected evidence has high confidence
- the detected value violates the configured tolerance
- the mismatch is not explained by an approved user change

Examples:

- protected overall width expected `80 mm`, detected `90 mm`
- protected hole spacing expected `50 mm`, detected `60 mm`
- protected hole diameter expected `5 mm`, detected `7 mm`
- protected hole count expected `2`, detected `1`
- model extends below the build plate

## Known Limits

Wall thickness is currently a conservative coarse estimate, not CAD-level proof. Hole detection is limited to common axis-aligned cylindrical through-holes and can return `unverifiable` on coarse tessellation, chamfered/countersunk geometry, intersecting features, or ambiguous groups.
