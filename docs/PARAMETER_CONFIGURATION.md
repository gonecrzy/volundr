# Parameter Configuration

This document defines direct parameter editing, preset switching, and deterministic regeneration without invoking Gemini.

## Scope

Configuration changes apply only to parameters already declared by the approved Design Plan and exposed by the accepted OpenSCAD source. They do not add components, move feature ownership, change assembly strategy, or introduce new printable outputs.

Escalate to structured AI revision when the user asks for:

- a new component, feature, output, or assembly relationship
- a parameter that is absent from the approved Design Plan
- a change to a non-editable parameter
- a direct edit to a derived parameter
- a value outside the approved configurable range
- a source parameter that is not safely exposed for `-D` override
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
- the parameter ID is a valid OpenSCAD identifier
- the accepted source exposes an assignment for that exact ID
- the change does not alter product structure

Derived parameters are recalculated by OpenSCAD and are not overridden directly.

## OpenSCAD Override Contract

Generated source should mark editable parameters:

```scad
// @volundr-parameter slot_count type=integer editable=true
slot_count = 6;
```

Volundr compiles configured candidates from unchanged source using command-line overrides:

```text
openscad -D 'selected_output="body"' -D 'slot_count=8' -o body.stl project.scad
```

The accepted source file is never rewritten for configuration changes.

## Presets

Design Plan presets and project-local presets are groups of input parameter values. Applying a preset creates a configuration preview; it does not mutate the Design Plan. Volundr stores selected preset values separately from user overrides.

## Candidate Behavior

Configuration generation uses the canonical multi-output pipeline:

```text
accepted source + override manifest
  -> compile each planned output
  -> inspect and validate each output
  -> classify assembly candidate
```

The resulting candidate links to `configuration_change_id`. The active accepted revision remains unchanged until the user accepts the candidate.

If a later component-targeted AI revision uses a configured revision as its base, Volundr preserves the configuration context:

- the override manifest is included in the component revision prompt
- revised source must still expose every active override parameter
- output compilation uses the same OpenSCAD `-D` overrides
- the new candidate remains linked to the configuration change

The source default assignment does not need to equal the configured override; the override manifest is the active configuration authority.

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
