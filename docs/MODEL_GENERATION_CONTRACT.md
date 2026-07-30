# Volundr Model Generation Contract

This document is the historical OpenSCAD contract between Volundr and the AI model. It defines the old OpenSCAD output structure, revision behavior, safety restrictions, and rejection conditions.

`docs/CADQUERY_BACKEND.md` supersedes this document for product CAD. The current architecture uses a `cadquery-v1` Python source contract and removes OpenSCAD from normal product paths.

For the implementation-ready Gemini ruleset, use `docs/GEMINI_RULESET.md`. For staged prompt responsibilities and schemas, use `docs/GEMINI_PROMPT_ARCHITECTURE.md`.

## Purpose

This contract defines the required format and behavior of AI-generated OpenSCAD.

The AI is not free to return arbitrary prose, shell commands, external dependencies, or unexplained geometry.

## Required Output

The preferred response is a single OpenSCAD source block.

The backend may extract source from a fenced `scad` or `openscad` block, but prompts should request source only.

Clarification-capable stages must not return OpenSCAD when critical information is missing. They must return the structured clarification response defined in `docs/GEMINI_PROMPT_ARCHITECTURE.md`.

For new initial AI generations, OpenSCAD must be generated from a persisted `generation_ready` Design Specification. When an approved Design Plan exists, OpenSCAD must also be generated from that approved plan. The raw user request may be included as secondary intent, but the Design Specification controls protected requirements and the Design Plan controls product structure.

New AI-generated OpenSCAD is statically validated against `source-contract-v1` before OpenSCAD compilation. Hard source-contract or protected Design Specification violations stop before compile and do not create a candidate revision. Quality findings are persisted as advisory validation findings and may produce a `ready_with_warnings` candidate.

After successful compile and mesh inspection, Volundr runs `geometric-invariants-v1` for selected measurable protected invariants. The supported checks, tolerances, confidence behavior, and blocking policy are defined in `docs/GEOMETRIC_INVARIANT_VALIDATION.md`.

## Required Source Structure

Every generated model should follow this pattern:

```scad
/*
Project: Example
Units: millimeters
Purpose: Brief functional description

Assumptions:
- assumption one
- assumption two

Print notes:
- recommended orientation
- expected supports
*/

// ===== QUALITY =====
$fn = 64;

// ===== USER PARAMETERS =====
selected_output = "body_output";
// @volundr-requirement part_width
// @volundr-component main_body
part_width = 80;
part_depth = 40;
part_height = 20;
wall_thickness = 3;
fit_clearance = 0.6;

// ===== DERIVED VALUES =====
// @volundr-dependency part_width -> inner_width
inner_width = part_width - (2 * wall_thickness);

// ===== VALIDATION =====
assert(part_width > 0, "part_width must be positive");
assert(wall_thickness >= 1.2, "wall_thickness is too small");

// ===== MODULES =====
// @volundr-geometry type=bounds x=part_width y=part_depth z=part_height

// @volundr-feature main_body
// @volundr-output body_output module=main_body required=true filename=body.stl components=main_body
module main_body() {
    cube([part_width, part_depth, part_height]);
}

// ===== FINAL MODEL =====
module render_selected_output() {
    if (selected_output == "body_output") {
        main_body();
    } else {
        assert(false, str("Unknown selected_output: ", selected_output));
    }
}

render_selected_output();
```

## Machine-Readable Requirement Markers

Generated source must map protected Design Specification requirements and approved Design Plan structure to OpenSCAD source with simple comment markers. This is the authoritative marker format for Volundr:

```scad
// @volundr-requirement container_diameter
// @volundr-parameter container_diameter type=number editable=true
container_diameter = 81;

// @volundr-feature mounting_method
// @volundr-geometry type=hole_group count=2 diameter=mount_hole_diameter spacing=mount_hole_spacing axis=z
module mounting_holes() {
    ...
}

// @volundr-component holder_body
module holder_body() {
    ...
}

// @volundr-shared-module fastener_hole
module fastener_hole(diameter, depth) {
    ...
}

// @volundr-dependency tray_count -> guide_count
guide_count = tray_count + 1;

// @volundr-output holder_output module=holder_body required=true filename=holder.stl components=holder_body

// @volundr-geometry type=bounds x=part_width y=part_depth z=part_height

// @volundr-geometry type=wall_thickness value=wall_thickness region=main_body
```

Rules:

1. `@volundr-requirement <id>` must appear immediately before the named parameter assignment representing that Design Specification requirement.
2. `@volundr-feature <id>` must appear immediately before the module or statement implementing that protected functional requirement.
3. Marker IDs must exactly match Design Specification requirement IDs.
4. Protected numeric values must be statically verifiable as simple constants or safe arithmetic over previously defined constants.
5. Revisions and repairs must preserve unrelated requirement and feature markers.
6. Marker presence records implementation intent only. It does not prove the geometry physically satisfies the feature.
7. `@volundr-geometry` markers are required in new AI source for measurable bounds, hole, hole-group, and wall-thickness invariants introduced in `openscad-generation-v3`.
8. Geometry marker attributes must reference named parameters where values are protected by the Design Specification.
9. `@volundr-component <id>` must map every Design Plan component to a nearby parameter, module, or statement.
10. `@volundr-feature <id>` must also map every Design Plan feature, not only protected Design Specification functional requirements.
11. `@volundr-dependency <from_id> -> <to_id>` must appear immediately before the derived assignment implementing each Design Plan dependency edge.
12. For approved Design Plan source, `@volundr-output <id> module=<module_name> required=<true|false> filename=<safe_filename.stl> components=<comma_separated_component_ids>` must appear before each printable output module. The complete output-selection lifecycle is defined in `docs/MULTI_OUTPUT_GENERATION.md`.
13. Editable Design Plan parameters belong in `USER PARAMETERS`; derived Design Plan parameters belong in `DERIVED VALUES`.
14. Editable parameters must include `@volundr-parameter <id> type=<number|integer|boolean|enum> editable=<true|false>` immediately before the assignment. Direct configuration behavior is defined in `docs/PARAMETER_CONFIGURATION.md`.
15. Assertions must reject impossible configurations implied by the Design Plan, such as nonpositive counts, negative clearances, invalid wall thicknesses, or derived dimensions that cannot fit their dependent features.
16. Shared reusable modules must use `@volundr-shared-module <module_name>` immediately before the module declaration. Component-targeted revisions may change shared modules only when the approved Revision Plan lists them in `allowed_shared_modules`.
17. A Design Plan parameter that declares `source_requirement_id` is a direct copy of that requirement's value and unit. Calculated dimensions such as tray stack height, case envelope, or overall product size must be derived parameters with dependency markers.

## Mandatory Rules

1. Use millimeters.
2. Include a clearly marked `USER PARAMETERS` section.
3. Give meaningful parameter names.
4. Avoid unexplained magic numbers.
5. Put repeated or conceptually distinct geometry into modules.
6. For legacy/manual single-output source, include `main_model()` and end with exactly one top-level `main_model();` call.
7. For approved Design Plan source, include `selected_output`, output modules, `render_selected_output()`, and exactly one top-level `render_selected_output();` call.
8. Use assertions for clearly invalid parameter combinations. Missing assertions are normally a quality finding, not a universal hard rejection.
9. Keep `$fn` reasonable, normally between 32 and 96.
10. Add comments for assumptions and print orientation.
11. Preserve existing parameter and module names during revisions unless renaming is required.
12. Make the smallest reasonable change during revisions.
13. Do not remove unrelated working features.
14. Do not add external library dependencies unless explicitly approved.
15. Do not use `import()`, `surface()`, or host file access in V1-generated models.
16. Do not execute shell commands or emit instructions to do so.
17. Do not return STL, binary data, or base64.
18. Avoid geometry located extremely far from the origin.
19. Prefer the model near the XY origin with Z at or above zero.
20. Avoid excessive polygon counts.
21. For `openscad-generation-v5`, preserve all approved Design Plan components, features, dependency edges, parameters, presets that affect parameters, and printable outputs.
22. For cases, trays, holders, and enclosures, do not use oversized subtractive cavities that remove required walls, top bridges, handle supports, retention features, or mounting surfaces.
23. A required handle, latch, stop, rail, rib, or hinge in a single printable output must be connected to the supporting component by positive overlapping material.

## Functional Design Guidelines

Where applicable:

- include explicit fit clearance
- distinguish hole diameter from fastener nominal diameter
- consider tool access
- avoid unsupported horizontal ceilings
- avoid paper-thin walls
- avoid accidental zero-thickness intersections
- use chamfers rather than decorative fillets when OpenSCAD simplicity matters
- expose mounting spacing and hole diameters as parameters
- expose critical mating dimensions as parameters
- include drainage or relief only when requested or functionally justified

## Revision Prompt Rules

New structured AI revisions must begin with an approved `revision-plan-v1` artifact as defined in `docs/STRUCTURED_REVISION_PLANNING.md`. The free-form user request is not enough authority to change source.

Component-targeted structural revisions use `openscad-component-revision-v1` and are defined in `docs/COMPONENT_TARGETED_REVISIONS.md`. Gemini may be told to edit only selected components, features, outputs, and shared modules, but it must still return the complete authoritative OpenSCAD project. Volundr does not accept source fragments or splice module replacements.

When revising an existing model, the AI must:

1. Read the current source before editing.
2. Treat the approved Revision Plan as the only authority for what may change.
3. Preserve the original functional intent.
4. Return the complete revised source.
5. Preserve comments that remain accurate.
6. Update comments that are no longer accurate.
7. Avoid rewriting the entire model without necessity.
8. Preserve the accepted design record: critical dimensions, assumptions, parameter names, module names, print orientation, and unrelated validation fixes.
9. Add or change only approved parameters, modules, features, outputs, and required dependency updates.
10. Preserve protected component, feature, dependency, geometry, shared-module, and output markers.
11. Preserve all unrelated printable outputs and the `selected_output` dispatcher.
12. Do not make a geometric or printability repair through compile-repair mode.

After source extraction and source-contract validation, Volundr performs revision compliance validation before compile. Unauthorized protected-value changes, removed protected markers, removed required outputs, unapproved shared-module changes, protected module drift, undeclared components/outputs, or missing required dependency updates reject the generation attempt before OpenSCAD compilation.

One bounded `scope-correction-v1` attempt may be used to revert unauthorized component-scope edits. Scope correction is not source-contract repair and not compiler repair.

## Repair Prompt Rules

When repairing a source-contract failure:

- fix only source-contract violations, missing markers, prohibited constructs, skeleton omissions, or protected-value verifiability failures
- preserve geometry, protected dimensions, required features, and unrelated modules
- do not compile-repair or redesign the part in this mode
- stop after the bounded contract-repair attempt

When repairing a compile failure:

- prioritize syntax and compatibility corrections
- do not redesign the part
- preserve dimensions and intent
- return complete corrected source
- make only the minimum required change
- treat the source as failed source, not accepted source
- do not add, remove, or reinterpret functional features

## Rejection Conditions

The backend should reject or flag output when:

- no valid SCAD source is found
- source is empty
- source exceeds configured size limits
- forbidden calls are present
- no valid final output call exists for the applicable contract
- top-level structure is obviously incomplete
- OpenSCAD times out
- no STL is produced
- STL has zero volume
- dimensions exceed configured safety limits
- geometry is below the build plate
- an ordinary functional part is non-watertight
- generated source violates the ruleset skeleton or required assertion/parameter sections
- protected Design Specification values are missing, changed, or statically unverifiable
- required protected feature markers are missing

Printability findings that depend on user preference, orientation, printer profile, or support strategy may create a candidate revision requiring user review instead of immediate rejection. Blocking and warning policy is defined in `docs/GENERATION_RELIABILITY_PLAN.md`.
