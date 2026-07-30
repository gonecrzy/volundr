# Multi-Output Generation

This document defines Volundr's canonical output pipeline for approved Design Plans.

## CadQuery Transition Status

The canonical implementation is CadQuery `Product` output execution. Every
`PrintableOutput` has an output ID, component ID, quantity, required flag,
STEP/STL artifacts, optional BREP artifact, topology metadata, mesh metadata,
expected solid count, detected solid count, and disconnected-solid policy.

Current implementation: the CadQuery runner and worker boundary execute a
`cadquery-v1` `Product`, select requested `PrintableOutput` records, export
STEP/STL plus optional BREP artifacts, inspect STL mesh metadata, persist
topology metadata, preserve optional output failures, and fail the job when a
required output fails.

## Output Model

A Design Plan `printable_outputs` entry represents one generated mesh artifact, not one physical copy. Quantity is stored on the output:

```json
{
  "id": "carry_handle",
  "label": "Carry handle",
  "component_id": "carry_handle",
  "component_ids": ["carry_handle"],
  "entrypoint": "carry_handle",
  "filename": "carry_handle.stl",
  "quantity": 1,
  "required": true,
  "output_type": "printable_component",
  "preferred_orientation": null,
  "notes": null
}
```

Supported printable output types:

- `printable_component`
- `repeated_printable_component`
- `optional_printable_component`

Purchased hardware and non-printable reference objects may exist in a Design Plan, but they are not compiled as STL outputs.

## CadQuery Output Contract

Approved Design Plan source uses one authoritative CadQuery Python file and
declares outputs through `Product.outputs`:

```python
PARAMETERS = [...]

def build(params):
    body = ...
    handle = ...
    return Product(
        parameters=PARAMETERS,
        outputs=[
            PrintableOutput(
                output_id="carrier_body",
                label="Carrier body",
                component_id="carrier_body",
                component_ids=("carrier_body",),
                model=body,
                required=True,
                expected_solid_count=1,
            ),
            PrintableOutput(
                output_id="carry_handle",
                label="Carry handle",
                component_id="carry_handle",
                component_ids=("carry_handle",),
                model=handle,
                required=True,
                expected_solid_count=1,
            ),
        ],
    )
```

Rules:

- every planned printable output has one matching `PrintableOutput`
- output IDs are unique within the plan
- filenames are normalized before persistence
- required outputs cannot be silently omitted
- single-output plans use the same `Product` contract
- generated code does not choose artifact paths or write output files directly

## CadQuery Execution Lifecycle

```text
approved Design Plan
  -> generate authoritative CadQuery Python
  -> source-contract validation
  -> submit structured worker job
  -> validate typed parameters
  -> call build(params)
  -> resolve Product outputs
  -> validate B-Rep topology per output
  -> export STEP and STL per output
  -> mesh inspection per output
  -> printability checks per output
  -> assembly validation summary
  -> assembly candidate classification
```

The assembly candidate is a normal revision. Component artifacts are persisted as child output records. A candidate is classified only after all required output jobs finish.

Component-targeted full-source revisions use this same pipeline. After compilation, protected outputs from the approved Revision Plan are compared against the base revision using `output-preservation-v1`; see `docs/COMPONENT_TARGETED_REVISIONS.md`.

## Output States

```text
queued
compiling
compiled
validating
ready
ready_with_warnings
blocked
failed
skipped
```

Output states are separate from candidate review states.

## Assembly Classification

The assembly candidate is:

- `blocked` when any required output fails, is missing, has a blocking finding, or the output manifest does not match the approved Design Plan
- `ready_with_warnings` when all required outputs are usable but advisory output or assembly findings exist
- `ready` when all required outputs compile and validate without advisory findings

Volundr does not support accepting only part of an assembly candidate in this pass.

## Partial Failure

Successful component artifacts are preserved even when another output fails:

```text
Body: ready
Handle: failed
Retention bar: ready_with_warnings
Assembly: blocked
```

Users may inspect and download successful outputs, but accepting the assembly is blocked until required failures are resolved through retry or a new generation/revision.

## Artifact Manifest

Each assembly revision persists `output-manifest.json`:

```json
{
  "schema_version": "output-manifest-v1",
  "project_id": "uuid",
  "revision_id": "uuid",
  "design_plan_id": "uuid",
  "source": {
    "filename": "source.py",
    "sha256": "..."
  },
  "outputs": [
    {
      "output_id": "carrier_body",
      "component_id": "carrier_body",
      "step_path": "step/carrier_body.step",
      "stl_path": "stl/carrier_body.stl",
      "quantity": 1,
      "required": true,
      "state": "ready",
      "sha256": "...",
      "dimensions_mm": {
        "x": 280,
        "y": 190,
        "z": 300
      }
    }
  ]
}
```

The manifest is reproducible from persisted revision and output records.

## Retry Behavior

Retry executes a failed output from the same authoritative source hash, parameter hash, and output ID.

Retry does not call Gemini and does not modify source geometry. It is intended for CAD process failures, timeouts, transient worker failures, or artifact-write failures. Source-contract violations, missing outputs, invalid topology, empty meshes, and blocking geometry/printability violations require a new generation or later structured revision.

## Export Package

The first export format is ZIP:

```text
project-name/
├── README.md
├── design-specification.json
├── design-plan.json
├── configuration.json              # present for configuration-generated revisions
├── parameter-overrides.json        # present for configuration-generated revisions
├── source.py
├── output-manifest.json
├── assembly-notes.md
├── step/
│   ├── carrier_body.step
│   └── carry_handle.step
└── stl/
    ├── carrier_body.stl
    └── carry_handle.stl
```

Assembly notes are derived from structured Design Plan fields. Volundr does not claim collision-free assembly, hinge motion correctness, fastener compatibility, or load adequacy.

## Known Limitations

- component-targeted revisions can preserve and compare outputs, but do not prove assembled fit
- no assembly collision analysis
- no exploded assembly viewer
- no 3MF export
- no slicer integration
- no automatic build-plate arrangement
