# Multi-Output Generation

This document defines Volundr's canonical output pipeline for approved Design Plans.

## Output Model

A Design Plan `printable_outputs` entry represents one generated mesh artifact, not one physical copy. Quantity is stored on the output:

```json
{
  "id": "carry_handle",
  "label": "Carry handle",
  "component_id": "carry_handle",
  "component_ids": ["carry_handle"],
  "module_name": "carry_handle",
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

## OpenSCAD Selection Contract

Approved Design Plan source uses one authoritative OpenSCAD file and command-line output selection:

```scad
selected_output = "carrier_body";

// @volundr-output carrier_body module=carrier_body required=true filename=carrier_body.stl components=carrier_body
module carrier_body() {
    ...
}

// @volundr-output carry_handle module=carry_handle required=true filename=carry_handle.stl components=carry_handle
module carry_handle() {
    ...
}

module render_selected_output() {
    if (selected_output == "carrier_body") {
        carrier_body();
    } else if (selected_output == "carry_handle") {
        carry_handle();
    } else {
        assert(false, str("Unknown selected_output: ", selected_output));
    }
}

render_selected_output();
```

Rules:

- every planned printable output has one matching `@volundr-output` marker
- every output marker references an existing module
- output IDs are unique within the plan
- filenames are normalized before persistence
- required outputs cannot be silently omitted
- single-output plans use the same selector contract
- legacy/manual source may still use `main_model();`

## Compilation Lifecycle

```text
approved Design Plan
  -> generate authoritative SCAD
  -> source-contract validation
  -> resolve printable output manifest
  -> compile each output with -D selected_output="output_id"
  -> mesh inspection per output
  -> geometric and printability checks per output
  -> assembly validation summary
  -> assembly candidate classification
```

The assembly candidate is a normal revision. Component artifacts are persisted as child output records. A candidate is classified only after all required output jobs finish.

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
    "filename": "project.scad",
    "sha256": "..."
  },
  "outputs": [
    {
      "output_id": "carrier_body",
      "component_id": "carrier_body",
      "filename": "carrier_body.stl",
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

Retry recompiles a failed output from the same authoritative source hash and same `selected_output` value.

Retry does not call Gemini and does not modify source geometry. It is intended for OpenSCAD process failures, timeouts, transient worker failures, or artifact-write failures. Source-contract violations, missing markers, empty meshes, and blocking geometry/printability violations require a new generation or later structured revision.

## Export Package

The first export format is ZIP:

```text
project-name/
├── README.md
├── design-specification.json
├── design-plan.json
├── configuration.json              # present for configuration-generated revisions
├── parameter-overrides.json        # present for configuration-generated revisions
├── project.scad
├── output-manifest.json
├── assembly-notes.md
└── stl/
    ├── carrier_body.stl
    └── carry_handle.stl
```

Assembly notes are derived from structured Design Plan fields. Volundr does not claim collision-free assembly, hinge motion correctness, fastener compatibility, or load adequacy.

## Known Limitations

- structured revision planning exists, but component-targeted AI revisions are still pending
- no assembly collision analysis
- no exploded assembly viewer
- no 3MF export
- no slicer integration
- no automatic build-plate arrangement
