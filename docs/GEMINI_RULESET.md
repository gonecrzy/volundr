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

// ===== FINAL MODEL =====
module main_model() {
    // final assembly
}

main_model();
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

## Requirement Marker Rules

The authoritative marker format is defined in `docs/MODEL_GENERATION_CONTRACT.md`.

1. Every protected critical dimension in the Design Specification must have `// @volundr-requirement <id>` immediately before the parameter assignment that represents it.
2. Every protected functional requirement must have `// @volundr-feature <id>` immediately before the implementing module or statement.
3. Do not invent marker IDs. Use Design Specification requirement IDs exactly.
4. Preserve unrelated markers during revisions and repairs.
5. A marker is a static declaration of implementation intent; do not claim it proves physical geometry.

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
5. End with exactly one top-level `main_model();` call.
6. Do not emit top-level geometry outside `main_model();`.
7. Use modules for repeated or conceptually distinct features.
8. Use derived values instead of repeated arithmetic literals.
9. Avoid exact coplanar Boolean boundaries. Cutters should extend past target faces by `eps`; joined parts should overlap by at least `eps`.
10. Avoid zero-thickness contact. Tangent or face-only contact is not a structural connection.
11. Avoid unbounded loops, recursion, excessive nested Booleans, and high polygon counts.

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

1. Preserve original functional intent.
2. Preserve all unrelated parameters and modules.
3. Preserve accepted assumptions unless the user changes them.
4. Make the smallest source change that satisfies the revision.
5. Do not rewrite the coordinate system, origin placement, or module architecture unless required.
6. If the requested revision conflicts with current critical dimensions, ask for clarification.
7. Return the complete revised source after applying the change.

## Compile Repair Rules

Source-contract repair happens before compile repair and has a separate prompt mode.

Contract repair may only:

1. Add missing required skeleton sections.
2. Add or correct requirement and feature markers.
3. Remove prohibited constructs.
4. Make protected values statically verifiable without changing their specified values.
5. Restore a removed protected parameter, marker, or required feature.

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
