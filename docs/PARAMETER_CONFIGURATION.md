# Parameter Configuration

This document defines direct parameter editing, preset switching, and deterministic regeneration without invoking Gemini.

## CadQuery Transition Status

The primary configuration path is typed CadQuery parameter execution.

## Scope

Configuration changes apply only to parameters already declared by the approved Design Plan and accepted CadQuery source contract. They do not add components, move feature ownership, change assembly strategy, or introduce new printable outputs.

Escalate to structured AI revision when the user asks for:

- a new component, feature, output, or assembly relationship
- a parameter that is absent from the approved Design Plan
- a change to a non-editable parameter
- a direct edit to a derived parameter
- a value outside the approved configurable range
- a parameter that is not declared by the accepted source contract
- a configuration that changes product structure

## Configuration Change Record

`configuration-change-v1` is immutable after preview except for generation linkage fields:

```json
{
  "schema_version": "configuration-change-v1",
  "project_id": "uuid",
  "base_revision_id": "uuid",
  "generated_revision_id": null,
  "design_specification_id": "uuid",
  "design_plan_id": "uuid",
  "reason": "parameter_change",
  "selected_preset_id": "wide",
  "requested_changes": {"slot_count": 5},
  "preset_values": {"body_width": 100},
  "user_overrides": {"fit_class": "loose"},
  "resolved_parameters": {},
  "affected_parameters": [],
  "affected_components": [],
  "affected_outputs": [],
  "validation_state": "configuration_ready",
  "validation_errors": [],
  "base_source_hash": "...",
  "content_hash": "..."
}
```

Generation sets `generated_revision_id` and `approved_at`. It does not mutate the accepted base revision or the Design Plan.

## Validation States

```text
configuration_ready
clarification_required
invalid_configuration
requires_design_revision
configuration_failed
```

`configuration_ready` is the only state that can generate a candidate.

## Parameter Rules

A parameter may be edited directly when all are true:

- it exists in approved Design Plan `parameters`
- `editable` is `true`
- the type is `number`, `integer`, `boolean`, or `enum`
- the value passes type, enum, and range checks
- the parameter ID exists in the accepted CadQuery `PARAMETERS` declaration
- the change does not alter product structure

Derived parameters are recalculated by the CadQuery build path and are not overridden directly.

## CadQuery Parameter Contract

Generated CadQuery source declares typed parameter specifications. Configuration generation sends validated JSON values to the worker:

```json
{
  "slot_count": 8,
  "slot_width": 25.0,
  "wall_thickness": 3.0
}
```

The worker constructs the validated parameter object and calls `build(params)`. It does not rewrite source and it does not call Gemini.

The override manifest is provider-neutral and includes the full resolved parameter object:

```json
{
  "schema_version": "parameter-overrides-v1",
  "cad_backend": "cadquery",
  "source_language": "python",
  "parameter_values": {
    "body_width": 100,
    "slot_count": 5,
    "wall_thickness": 3
  },
  "parameter_hash": "sha256-of-canonical-parameter-json"
}
```

`parameter_hash` is computed from canonical sorted JSON so the same resolved values produce the same hash regardless of request key order.

## Source-Derived Parameter Discovery

Volundr also exposes a lightweight read-only discovery endpoint for accepted or candidate revision source:

```text
GET /api/revisions/{revision_id}/parameters
```

This endpoint derives candidate controls from the accepted CadQuery
`PARAMETERS` declaration and remains narrower than the Design Plan configuration
system. It intentionally ignores structural source changes. If AI output does
not expose useful typed parameters, improve generation prompts or Design Plan
parameterization before adding override workflows.

## Presets

Design Plan presets and project-local presets are groups of input parameter values. Applying a preset creates a configuration preview; it does not mutate the Design Plan. Volundr stores selected preset values separately from user overrides.

## Candidate Behavior

Configuration generation uses the canonical multi-output pipeline:

```text
accepted source + validated parameter manifest
  -> execute each required planned output
  -> inspect and validate each output
  -> classify assembly candidate
```

The resulting candidate links to `configuration_change_id`. The active accepted revision remains unchanged until the user accepts the candidate.

If a later component-targeted AI revision uses a configured revision as its base, Volundr preserves the configuration context:

- the override manifest is included in the component revision prompt
- revised source must still expose every active override parameter
- output execution uses the same resolved parameter manifest
- the new candidate remains linked to the configuration change

The accepted source defaults do not need to equal the configured values; the parameter manifest is the active configuration authority.

## Export

Configuration-generated exports include:

```text
configuration.json
parameter-overrides.json
```

The README lists the base revision, selected preset, explicit overrides, and standard output/validation summaries.

## Current Limitations

- Design Plan expressions are not evaluated by the application; dependency edges are expanded for impact reporting only.
- Component-targeted AI revisions preserve active configuration context but do not yet regenerate a Design Plan for new structural parameter sets.
- Legacy source without `@volundr-parameter` markers may be edited when exact assignment IDs are present, but new generated source should include markers.
