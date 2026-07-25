# Volundr Model Generation Contract

This document is the contract between Volundr and the AI model. It defines the required OpenSCAD output structure, revision behavior, safety restrictions, and rejection conditions.

For the implementation-ready Gemini ruleset, use `docs/GEMINI_RULESET.md`. For staged prompt responsibilities and schemas, use `docs/GEMINI_PROMPT_ARCHITECTURE.md`.

## Purpose

This contract defines the required format and behavior of AI-generated OpenSCAD.

The AI is not free to return arbitrary prose, shell commands, external dependencies, or unexplained geometry.

## Required Output

The preferred response is a single OpenSCAD source block.

The backend may extract source from a fenced `scad` or `openscad` block, but prompts should request source only.

Clarification-capable stages must not return OpenSCAD when critical information is missing. They must return the structured clarification response defined in `docs/GEMINI_PROMPT_ARCHITECTURE.md`.

For new initial AI generations, OpenSCAD must be generated from a persisted `generation_ready` Design Specification. The raw user request may be included as secondary intent, but the Design Specification controls protected dimensions, required features, defaults, and assumptions.

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
part_width = 80;
part_depth = 40;
part_height = 20;
wall_thickness = 3;
fit_clearance = 0.6;

// ===== DERIVED VALUES =====
inner_width = part_width - (2 * wall_thickness);

// ===== VALIDATION =====
assert(part_width > 0, "part_width must be positive");
assert(wall_thickness >= 1.2, "wall_thickness is too small");

// ===== MODULES =====
module main_body() {
    cube([part_width, part_depth, part_height]);
}

// ===== FINAL MODEL =====
module main_model() {
    main_body();
}

main_model();
```

## Mandatory Rules

1. Use millimeters.
2. Include a clearly marked `USER PARAMETERS` section.
3. Give meaningful parameter names.
4. Avoid unexplained magic numbers.
5. Put repeated or conceptually distinct geometry into modules.
6. Include a `main_model()` module.
7. End with exactly one top-level call to `main_model();`.
8. Use assertions for clearly invalid parameter combinations.
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

When revising an existing model, the AI must:

1. Read the current source before editing.
2. Preserve the original functional intent.
3. Identify the smallest affected parameters or modules.
4. Return the complete revised source.
5. Preserve comments that remain accurate.
6. Update comments that are no longer accurate.
7. Avoid rewriting the entire model without necessity.
8. Preserve the accepted design record: critical dimensions, assumptions, parameter names, module names, print orientation, and unrelated validation fixes.
9. Add or change only the parameters/modules affected by the user's revision.

## Repair Prompt Rules

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
- no `main_model()` exists
- top-level structure is obviously incomplete
- OpenSCAD times out
- no STL is produced
- STL has zero volume
- dimensions exceed configured safety limits
- geometry is below the build plate
- an ordinary functional part is non-watertight
- generated source violates the ruleset skeleton or required assertion/parameter sections

Printability findings that depend on user preference, orientation, printer profile, or support strategy may create a candidate revision requiring user review instead of immediate rejection. Blocking and warning policy is defined in `docs/GENERATION_RELIABILITY_PLAN.md`.
