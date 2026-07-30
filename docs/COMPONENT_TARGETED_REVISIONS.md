# Component-Targeted Revisions

This document defines Volundr's component-targeted AI revision behavior.

## CadQuery Transition Status

The component-targeted lifecycle remains, but the source contract moves from OpenSCAD markers and module fingerprints to CadQuery Python ownership declarations and normalized AST fingerprints. Gemini must return complete CadQuery source, not source fragments or patches.

## Scope

Component-targeted revisions apply after an accepted revision has:

- an approved Design Specification
- an approved Design Plan
- a complete authoritative CadQuery source
- an output manifest
- one or more compiled printable outputs

Configuration-only changes remain deterministic and are handled by `docs/PARAMETER_CONFIGURATION.md`.

## Lifecycle

```text
accepted configured or unconfigured revision
  -> approved revision-plan-v1
  -> cadquery-component-revision-v1
  -> Python/CadQuery extraction
  -> source-contract validation
  -> component scope compliance
  -> full product multi-output compilation
  -> output preservation checks
  -> candidate review
  -> explicit accept or reject
```

Gemini always returns the complete authoritative CadQuery project source. Volundr does not splice source fragments.

## Revision Scope

A structural Revision Plan may name:

- targeted components, features, and outputs
- allowed shared modules
- protected components, features, outputs, and parameters
- protected interfaces and interface parameters
- targeted validation findings
- success criteria

A targeted component does not imply permission to change every global parameter.

## Source Ownership

CadQuery source uses AST-visible runtime metadata. `ParameterSpec(...)` identifies typed parameters and defaults. `PrintableOutput(...)` identifies output IDs and component ownership.

Current CadQuery ownership metadata:

```python
PARAMETERS = [
    ParameterSpec(id="lid_thickness", label="Lid thickness", type="float", default=3.0, unit="mm")
]

def build(params):
    lid = cq.Workplane("XY").box(80, 50, params["lid_thickness"])
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="lid",
                label="Lid",
                component_id="lid",
                component_ids=("lid",),
                model=lid,
                expected_solid_count=1,
            )
        ],
    )
```

Feature ownership is read from the approved Design Plan for now. CadQuery scope checks use parsed `ParameterSpec` and `PrintableOutput` metadata plus protected-output preservation evidence. Function-level CadQuery ownership annotations are still a planned extension.

## Source Compliance

After Gemini returns full source, Volundr compares parsed base and revised metadata.

Blocking failures include:

- protected component or output declaration changed
- protected feature mapping removed from the approved Design Plan context
- protected output mapping changed
- protected parameter changed
- protected interface parameter changed
- unapproved shared helper changed
- unrelated helper or output structure removed or changed
- undeclared component or output added
- source-contract hard violation

CadQuery currently uses ownership-level fingerprints before compile and protected-output preservation after compile.

## Scope Correction

If a component revision exceeds approved scope, Volundr may run one bounded `cadquery-scope-correction-v1` provider call.

Scope correction receives:

- the revised source that exceeded scope
- blocking scope findings
- the approved Revision Plan
- protected component/output/interface metadata

It must return complete source and revert unauthorized edits. It is separate from source-contract repair and compiler repair. If correction still fails source-contract or scope compliance, compilation does not begin and no candidate is created.

## Output Preservation

After compilation, Volundr compares protected outputs against the base output using `output-preservation-v1`.

Initial checks include:

- bounding dimensions
- volume
- connected component count
- STL hash equality when deterministic
- output ID and component mapping

Confirmed protected-output drift creates a blocking candidate finding. Unverifiable preservation is advisory.

## Interface Verification

Protected interfaces currently verify declared interface parameters from source constants. Examples:

- hole spacing
- hole diameter
- pin diameter
- slot width
- tab width

General mating proof, collision analysis, hinge motion, and structural simulation are out of scope.

## Configuration Preservation

When the base revision comes from a deterministic configuration change:

- the active override manifest is included in the revision prompt
- the revised source must still expose every configured parameter
- execution uses the same validated parameter manifest
- the candidate remains linked to the configuration context

The source default assignment does not need to equal the configured value because the validated parameter manifest is the active configuration authority.

## Candidate Summary

Volundr persists a `component-revision-summary-v1` artifact with:

- targeted output change states
- protected output preservation states
- interface verification results
- source compliance result linkage
- base and revised source hashes
- configuration context linkage

Targeted output states:

```text
changed_as_expected
change_not_detected
changed_but_failed_validation
unverifiable
```

Protected output states:

```text
verified_unchanged
changed_within_tolerance
unexpected_change
unverifiable
```

## Known Limitations

- no source-fragment generation
- no AST source splicing
- no visual mesh diff
- no arbitrary assembly fit proof
- no automatic geometry correction
- no slicer integration
- old development revisions without CadQuery ownership metadata are not component-targeted revision inputs; regenerate them through the staged CadQuery workflow
