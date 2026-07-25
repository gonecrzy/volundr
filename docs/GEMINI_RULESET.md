# Gemini Ruleset

Version: `gemini-ruleset-v1`

This is an implementation-ready ruleset for Gemini-generated functional OpenSCAD in Volundr. Rules are specific so they can become prompt assertions, source validators, and benchmark checks.

## Output Format

1. Return exactly one fenced `openscad` block for OpenSCAD stages.
2. Do not include prose outside the code block.
3. Do not return STL, binary data, base64, shell commands, file paths, or instructions to run commands.
4. If required information is missing and the stage allows clarification, return the required clarification JSON instead of OpenSCAD.
5. For source-contract repair, return complete corrected OpenSCAD only and do not provide design rationale.

## Required Source Skeleton

Every generated OpenSCAD source must follow this order:

```scad
// Volundr OpenSCAD v1
// Units: millimeters
// Purpose: ...
// Assumptions:
// - ...
// Print orientation: ...
// Supports: none expected | supports expected and why

// ===== QUALITY =====
$fn = 48;
eps = 0.01;

// ===== USER PARAMETERS =====
// @volundr-requirement protected_requirement_id

// ===== DERIVED VALUES =====

// ===== VALIDATION =====

// ===== PRIMITIVE HELPERS =====

// ===== FEATURE MODULES =====
// @volundr-feature protected_feature_id
// @volundr-geometry type=bounds x=width_parameter y=depth_parameter z=height_parameter

// ===== FINAL MODEL =====
selected_output = "body_output";

// @volundr-output body_output module=body_output required=true filename=body.stl components=main_body
module body_output() {
    main_body();
}

module render_selected_output() {
    if (selected_output == "body_output") {
        body_output();
    } else {
        assert(false, str("Unknown selected_output: ", selected_output));
    }
}

render_selected_output();
```

## Functional CAD Rules

1. Use millimeters.
2. Distinguish user-provided dimensions from assumptions in comments and parameter names where useful.
3. Every fit-critical dimension must be a named user parameter.
4. Every assumed fit-critical dimension must be listed in `Assumptions`.
5. Add explicit clearance parameters for mating parts.
6. Distinguish nominal fastener size from printed clearance hole diameter.
7. For fasteners, include head type, shaft clearance, head clearance, and tool access where applicable.
8. For load-bearing handles, hooks, brackets, and holders, include load-path geometry: ribs, gussets, overlap, or broad bearing faces.
9. Do not add decorative cutouts, weight-reduction pockets, vents, windows, labels, or unrelated holes unless the user requested them or the design plan explicitly requires them.
10. Every subtraction must directly serve a named function.
11. Do not remove support surfaces, retention features, tray rails, handles, walls, or load-bearing geometry unless the user explicitly asks.
12. For boxes, holders, and adapters, define insertion/removal direction and avoid trapped or inaccessible cavities.

## Parameter Rules

1. Put user-editable parameters only in `USER PARAMETERS`.
2. Put calculated values only in `DERIVED VALUES`.
3. Use descriptive parameter names: `mount_hole_diameter`, not `d1`.
4. Include lower-bound assertions for wall thickness, fastener clearance, slot pitch, lip height, and remaining material around holes.
5. Keep ordinary functional FDM walls at or above 1.6 mm for a 0.4 mm nozzle unless the user explicitly requests a thinner non-structural feature.
6. Preserve parameter names during revisions unless a rename is required to correct ambiguity.
7. Add new parameters only when a revision introduces a new user-controllable dimension or feature.

## Design Plan Rules

1. `design-plan-v1` must return JSON only and must not generate OpenSCAD.
2. The Design Specification is the requirements authority; the Design Plan must not weaken, omit, or contradict protected Design Specification values.
3. A Design Plan must be generic: use parameters, derived parameters, dependency edges, components, features, presets, assembly strategy, printable outputs, risks, and `design_level`; do not encode product-specific schema fields.
4. Every derived parameter must list its dependencies and have a corresponding dependency edge when that relationship affects component size, feature count, output layout, or assembly.
5. Every component must list the features and parameters it owns.
6. Every printable output must list component IDs and quantity; OpenSCAD generation uses the selected-output contract in `docs/MULTI_OUTPUT_GENERATION.md` even when there is one output.
7. Ask plan clarification when component structure, output separation, assembly strategy, or configuration dependencies cannot be chosen safely.
8. A ready Design Plan must enter review and be explicitly approved before OpenSCAD generation.

## Requirement Marker Rules

The authoritative marker format is defined in `docs/MODEL_GENERATION_CONTRACT.md`.

1. Every protected critical dimension in the Design Specification must have `// @volundr-requirement <id>` immediately before the parameter assignment that represents it.
2. Every protected functional requirement must have `// @volundr-feature <id>` immediately before the implementing module or statement.
3. Do not invent marker IDs. Use Design Specification requirement IDs exactly.
4. Preserve unrelated markers during revisions and repairs.
5. A marker is a static declaration of implementation intent; do not claim it proves physical geometry.
6. For newly generated measurable features, add `@volundr-geometry` markers as defined in `docs/GEOMETRIC_INVARIANT_VALIDATION.md`.
7. Use geometry markers for declared bounds, axis-aligned holes, hole groups, and wall-thickness regions only when the generated source implements the corresponding feature.
8. Preserve geometry markers during source-contract repair, compile repair, and AI revisions unless the related protected requirement is explicitly changed.
9. For `openscad-generation-v5`, add `@volundr-component`, Design Plan `@volundr-feature`, `@volundr-dependency`, and `@volundr-output` markers as defined in `docs/MODEL_GENERATION_CONTRACT.md`.

## Requirement Source Rules

1. In requirement-extraction stages, every dimension and requirement must use exactly one source: `user`, `clarification`, `calculated`, `printer_profile`, `product_default`, or `ai_assumption`.
2. User-supplied and clarification-supplied critical values are protected by default.
3. Product defaults may fill ordinary non-critical FDM choices, but they must be disclosed in the Design Specification.
4. AI assumptions may cover cosmetic or minor nonfunctional choices only. They must not replace missing critical fit, fastener, load, orientation, or mating-geometry data.

## OpenSCAD Code Rules

1. Define `$fn` once in `QUALITY`, normally 32 to 64. Use 96 only when a circular mating surface requires it.
2. Define `eps = 0.01` and use it for cutters and intentional overlaps.
3. Use `center=false` by default.
4. Keep the model near the XY origin and entirely at or above Z=0.
5. For approved Design Plan source, end with exactly one top-level `render_selected_output();` call.
6. For legacy/manual source, end with exactly one top-level `main_model();` call.
7. Do not emit top-level geometry outside the final output dispatcher.
8. Use modules for repeated or conceptually distinct features.
9. Use derived values instead of repeated arithmetic literals.
10. Avoid exact coplanar Boolean boundaries. Cutters should extend past target faces by `eps`; joined parts should overlap by at least `eps`.
11. Avoid zero-thickness contact. Tangent or face-only contact is not a structural connection.
12. Avoid unbounded loops, recursion, excessive nested Booleans, and high polygon counts.

## Printability Rules

1. Prefer the largest stable flat face on Z=0.
2. Avoid unsupported horizontal ceilings above 15 mm unless supports are explicitly accepted.
3. Avoid bridge spans above 15 mm for support-free FDM.
4. Avoid overhangs below 45 degrees unless chamfered, supported, split, or explicitly accepted.
5. Do not place geometry below Z=0.
6. Keep ordinary holes printable: include clearance and avoid tiny unprintable slots.
7. For vertical handles or hooks, address layer-direction weakness with orientation, ribs, or gussets.
8. For enclosed or hollow parts, include drainage, relief, or support access only when required by the function.

## Clarification Requirements

Ask a clarification question instead of generating when:

1. The part must fit a real object and a mating dimension is missing.
2. A commercial object is named but dimensions vary by brand or model.
3. Fastener size, head style, spacing, or access is needed but unspecified.
4. A load-bearing part lacks load direction or mounting orientation.
5. Dimensions conflict.
6. Axes or orientation are ambiguous and affect fit.
7. The request likely creates inaccessible internal cavities.
8. The request likely requires severe support or bridging and support acceptance is unknown.
9. A revision changes a critical dimension but does not state whether related clearances should change.

Ask the smallest useful set of questions. Prefer one primary question when it unblocks generation.

## Revision Rules

1. `revision-planning-v1` must return JSON only and must not generate OpenSCAD.
2. A Revision Plan must identify requested changes, targets, required dependency changes, protected parameters/components/features/outputs, prohibited changes, and success criteria.
3. Ask revision clarification when the target, value, affected component/output, dependency scope, or selected-finding correction strategy is ambiguous.
4. `openscad-revision-v2` must use the approved Revision Plan as the only authority for what may change.
5. Preserve original functional intent.
6. Preserve all unrelated parameters, modules, components, features, dependency markers, geometry markers, and output markers.
7. Preserve accepted assumptions unless the approved Revision Plan changes them.
8. Make the smallest source change that satisfies the approved plan and its required dependencies.
9. Do not rewrite the coordinate system, origin placement, or module architecture unless the approved plan requires it.
10. Do not remove or rename unrelated printable outputs.
11. If the requested revision conflicts with current critical dimensions, the planning stage must return `revision_conflict` or clarification.
12. Return the complete revised source after applying an approved plan.

## Compile Repair Rules

Source-contract repair happens before compile repair and has a separate prompt mode.

Contract repair may only:

1. Add missing required skeleton sections.
2. Add or correct requirement and feature markers.
3. Remove prohibited constructs.
4. Make protected values statically verifiable without changing their specified values.
5. Restore a removed protected parameter, marker, or required feature.
6. Preserve or restore required `@volundr-geometry` markers without claiming unsupported feature metadata.

Contract repair must not redesign geometry, alter protected dimensions, remove unrelated modules, or respond to compiler diagnostics.

Compile repair may only:

1. Repair only syntax, brace/semicolon/comma mistakes, OpenSCAD incompatibility, and directly proven invalid derived expressions.
2. Do not change user dimensions.
3. Do not add or remove functional features.
4. Do not redesign the part.
5. Do not change print orientation.
6. If the diagnostic does not support a bounded repair, return a repair failure.

## Prohibited Constructs

Do not use:

- `import()`
- `surface()`
- `include`
- `use`
- host file paths
- parent directory traversal
- shell commands
- dynamic recursion
- `children()` in generated V1 models
- text-heavy decorative geometry
- external libraries
- `$fn` above 96
- model dimensions beyond configured hard limits

## Failure Behavior

1. If source cannot satisfy the ruleset, return clarification or failure JSON for stages that allow it.
2. Do not silently invent critical dimensions.
3. Do not hide assumptions in comments without matching parameters.
4. Do not claim the model is guaranteed printable.

## Configuration Support

1. Place user-editable Design Plan inputs in `USER PARAMETERS`.
2. Mark each editable input with `@volundr-parameter <id> type=<number|integer|boolean|enum> editable=true`.
3. Keep derived parameters in `DERIVED VALUES` and preserve dependency markers.
4. Add assertions for invalid configuration ranges and impossible derived values.
5. Do not require Gemini for direct parameter edits or preset switching; those are deterministic `-D` override operations.
