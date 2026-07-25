# Generation Benchmarks

## Purpose

This benchmark set measures whether prompt and pipeline changes improve practical CAD reliability rather than merely increasing compile success.

## Run Policy

- Fake-provider deterministic regression: every commit.
- Core suite: frequent smoke coverage on every prompt or pipeline change.
- Full stability suite: all benchmark categories before declaring a prompt architecture stable.
- Gemini smoke suite: 1 run per core benchmark after prompt changes.
- Gemini stability suite: 5 runs for ordinary full-suite generation benchmarks; 10 runs for clarification, conflict, and revision benchmarks.
- Repair benchmarks: 3 runs per repair case.

Prompt changes are not considered improvements unless they reduce accepted models with blocking validation failures and preserve or improve extraction/compile success.

## Shared Acceptance Criteria

All generated OpenSCAD benchmarks must:

- follow `gemini-ruleset-v1`
- pass `source-contract-v1` hard checks before compile
- extract cleanly
- compile within timeout
- produce one intended printable part unless multiple parts are explicitly requested
- have nonzero volume
- be watertight for ordinary functional parts
- stay at or above Z=0
- expose required parameters in `USER PARAMETERS`
- map every protected critical dimension with `@volundr-requirement`
- map every protected functional requirement with `@volundr-feature`
- include `@volundr-geometry` markers for supported protected bounds, hole, hole-group, and wall-thickness invariants
- when an approved Design Plan is present, map its components, features, dependency edges, and printable outputs with the markers defined in `docs/MODEL_GENERATION_CONTRACT.md`
- when an approved Design Plan is present, use the selected-output contract and artifact lifecycle in `docs/MULTI_OUTPUT_GENERATION.md`
- compile every required printable output, persist component-scoped validation results, and produce a reproducible `output-manifest.json`
- for revision benchmarks, produce a `revision-plan-v1` artifact before source generation that names allowed changes, required dependencies, protected parameters/components/features/outputs, targeted outputs, and success criteria
- verify supported protected geometric invariants according to `docs/GEOMETRIC_INVARIANT_VALIDATION.md`
- avoid unrequested decorative or weight-reduction features
- classify assumptions and warnings
- preserve protected design invariants during repair and revision

Clarification benchmarks must not generate SCAD.

Protected design invariants include user-provided dimensions, required features, mating geometry, fastener geometry, print orientation, and unrelated modules.

Current deterministic fixtures live under `backend/tests/fixtures/generation_benchmarks/`. The core suite is used for frequent checks and now explicitly covers ready specifications, vague clarification, and conflicting dimensions. The full suite covers missing fit data, missing fastener data, inaccessible cavity ambiguity, and the remaining model categories.

Fixture-generated source must contain the required skeleton, pass hard source-contract validation, and preserve protected marker mappings before benchmark compile assertions are evaluated. Fixture-generated meshes should also include expected geometric invariant assertions for supported cases: bounding dimensions, build-plate placement, cylindrical hole diameter, hole count, hole spacing, and wall-thickness estimates.

The full machine-readable suite also includes parametric-product Design Plan expectations for:

- simple bracket
- electronics enclosure
- configurable organizer
- adapter
- case/carrier
- multi-part hinged box
- repeated-slot rack

These cases assert generic plan shape: parameters, derived dependencies, components, features, presets where useful, assembly strategy, printable outputs, risks, and design level. The case/carrier benchmark includes a fishing-tray carrier as one acceptance case, not as a schema template.

Multi-output fixture expectations:

- simple bracket: one output through the canonical output pipeline
- electronics enclosure: body and lid outputs
- configurable organizer: repeated printable output quantity where applicable
- adapter: one output unless the approved plan declares separate fittings
- case/carrier: body plus handle or retention output when planned separately
- multi-part hinged box: body, lid, and hinge pin when planned as printable
- repeated-slot rack: one or more outputs with quantity represented on the artifact rather than duplicate rows

Structured revision fixture expectations:

- critical-dimension revision: target only the changed dimension and derived hole-position parameters while protecting plate bounds and hole diameter
- new-feature revision: add only the requested feature while preserving original features and plate dimensions
- electronics enclosure revision: propagate PCB envelope changes through shell, lid, and standoff layout while protecting fit defaults and output separation
- case/carrier revision: propagate tray count/profile changes through guides, case height, retention, handle, and reinforcement without treating the fishing-tray case as schema-specific logic
- repeated-slot rack revision: propagate slot count through rack length and slot positions while protecting sheet thickness, clearance, slot spacing, and output identity

## Suites

Core suite:

- 1. Simple Mounting Plate
- 2. Cylindrical Holder
- 4. Spacer Or Bushing
- 10. Critical-Dimension Revision
- 12. Intentionally Vague Request
- 13. Conflicting Dimensions

Full stability suite:

- all 15 original reliability benchmarks plus parametric-product Design Plan cases in the machine-readable fixture

## Benchmarks

### 1. Simple Mounting Plate

- Input prompt: `Create an 80 mm by 35 mm by 6 mm mounting plate with two M4 clearance holes spaced 55 mm apart along the long axis.`
- Required dimensions: 80 x 35 x 6 mm, 4.5 mm clearance holes, 55 mm spacing.
- Allowed assumptions: `$fn=48`, edge margin derived from plate size and spacing.
- Expected clarification: none.
- Expected modules and parameters: `main_body`, `mounting_holes`; `plate_width`, `plate_depth`, `plate_thickness`, `hole_diameter`, `hole_spacing`.
- Printability constraints: flat on Z=0, no supports.
- Compile expectations: success without repair.
- Mesh expectations: watertight, nonzero volume, one component.
- Geometric invariant expectations: protected 80 x 35 x 6 mm bounds, two-hole count, 4.5 mm hole diameter, 55 mm hole spacing, and Z=0 placement verify.
- Revision expectations: changing `hole_spacing` alters only hole locations.
- Unacceptable outcomes: missing holes, wrong spacing, geometry below Z=0, no parameters.

### 2. Cylindrical Holder

- Input prompt: `Create a desk cup holder for a 74 mm diameter cup, 65 mm tall, with 1 mm clearance and a 4 mm thick base.`
- Required dimensions: 76 mm inner diameter, 65 mm wall height, 4 mm base.
- Allowed assumptions: 3 mm wall thickness, open top.
- Expected clarification: none.
- Expected modules and parameters: `outer_shell`, `inner_cavity`; `cup_diameter`, `fit_clearance`, `wall_thickness`, `holder_height`, `base_thickness`.
- Printability constraints: open top, no unsupported internal ceiling.
- Compile expectations: success.
- Mesh expectations: watertight holder body.
- Geometric invariant expectations: protected height, declared wall thickness, open top height where represented by bounds metadata, and Z=0 placement verify or produce non-blocking unverifiable findings.
- Revision expectations: changing cup diameter preserves wall and base.
- Unacceptable outcomes: closed cup cavity, unsupported top cap, no clearance.

### 3. Box With Lid

- Input prompt: `Create a small electronics box with an internal space 100 x 60 x 30 mm and a removable slip-on lid.`
- Required dimensions: internal 100 x 60 x 30 mm.
- Allowed assumptions: 3 mm walls, 0.4 mm lid clearance, lid lip 8 mm.
- Expected clarification: ask if exact board mounting holes are required; generation may proceed if no board mounting is requested.
- Expected modules and parameters: `box_body`, `lid`, `lid_lip`; separate body and lid modules if multiple printable pieces are intended.
- Printability constraints: open box body, lid printable flat, no trapped support-only cavity.
- Compile expectations: success.
- Mesh expectations: two intentional components allowed only if documented.
- Revision expectations: adding mounting bosses preserves internal volume.
- Unacceptable outcomes: sealed inaccessible box, no lid clearance, giant unsupported roof.

### 4. Spacer Or Bushing

- Input prompt: `Create a 12 mm tall bushing with 8 mm outer diameter and 4.2 mm through hole.`
- Required dimensions: 12 mm height, 8 mm OD, 4.2 mm ID.
- Allowed assumptions: `$fn=64`.
- Expected clarification: none.
- Expected modules and parameters: `bushing_body`, `through_hole`; `outer_diameter`, `inner_diameter`, `height`.
- Printability constraints: vertical cylinder on Z=0.
- Compile expectations: success.
- Mesh expectations: watertight ring, one component.
- Geometric invariant expectations: protected height, inner through-hole diameter, and Z=0 placement verify; outer diameter remains future exterior-cylinder verification unless represented by bounds metadata.
- Revision expectations: changing height preserves diameters.
- Unacceptable outcomes: solid cylinder with no hole, non-centered hole.

### 5. Hose Adapter

- Input prompt: `Create a hose adapter from 19 mm ID hose to 25 mm ID hose with barbs.`
- Required dimensions: 19 mm and 25 mm hose interfaces.
- Allowed assumptions: 1.2 mm barb height, 3 barbs per side, 3 mm wall.
- Expected clarification: ask for hose wall stiffness or acceptable barb style if the system cannot safely assume.
- Expected modules and parameters: `hose_barb_section`, `transition_cone`, `through_bore`.
- Printability constraints: bore open through the part, no trapped cavity.
- Compile expectations: success after clarification/default acceptance.
- Mesh expectations: watertight shell with open bore represented by geometry.
- Revision expectations: changing one hose ID updates only that side and transition.
- Unacceptable outcomes: blocked bore, decorative ribs only, no clearance/taper.

### 6. Wall-Mounted Tool Holder

- Input prompt: `Create a wall-mounted holder for a 28 mm diameter flashlight with two screw holes.`
- Required dimensions: 28 mm flashlight diameter.
- Allowed assumptions: 0.8 mm clearance, M4 screws if not specified only after clarification/default acceptance.
- Expected clarification: ask screw size and mounting orientation if not defaulted by UX.
- Expected modules and parameters: `saddle`, `wall_plate`, `mounting_holes`, `retention_lip`.
- Printability constraints: orient plate flat; avoid weak layer-direction hook without gussets.
- Compile expectations: success.
- Mesh expectations: one component.
- Revision expectations: changing flashlight diameter preserves screw spacing unless requested.
- Unacceptable outcomes: unsupported cantilever without gussets, no fastener access.

### 7. T-Track Accessory

- Input prompt: `Create a sliding stop block for a 19 mm wide T-track slot with a 1/4-20 bolt hole.`
- Required dimensions: 19 mm slot width, 1/4-20 clearance hole.
- Allowed assumptions: 0.3 mm sliding clearance, 10 mm block height.
- Expected clarification: ask track profile depth if missing.
- Expected modules and parameters: `t_track_tongue`, `stop_block`, `bolt_hole`.
- Printability constraints: flat base, no fragile tongue thinner than 1.6 mm.
- Compile expectations: success after clarification/default acceptance.
- Mesh expectations: one component.
- Revision expectations: changing slot width adjusts tongue only.
- Unacceptable outcomes: generic cube with hole, no T-track mating geometry.

### 8. Replacement Handle

- Input prompt: `Create a replacement drawer handle with 96 mm screw spacing and a rounded grip.`
- Required dimensions: 96 mm screw spacing.
- Allowed assumptions: M4 clearance holes, 18 mm standoff height, 16 mm grip diameter.
- Expected clarification: ask screw type/head access if missing.
- Expected modules and parameters: `mounting_feet`, `grip`, `screw_holes`, `gussets`.
- Printability constraints: orient for strength or warn about layer direction.
- Compile expectations: success.
- Mesh expectations: one connected component.
- Revision expectations: changing screw spacing preserves grip diameter.
- Unacceptable outcomes: handle tangent to feet without overlap, no screw access.

### 9. Countersunk Holes

- Input prompt: `Create a 60 x 30 x 5 mm plate with two countersunk M3 holes 40 mm apart.`
- Required dimensions: plate 60 x 30 x 5 mm, M3 clearance, 40 mm spacing.
- Allowed assumptions: 3.4 mm shaft clearance, 6.2 mm head diameter, 2 mm countersink depth.
- Expected clarification: none if defaults are documented.
- Expected modules and parameters: `countersunk_hole`, `mounting_holes`.
- Printability constraints: flat plate, countersinks on top face.
- Compile expectations: success.
- Mesh expectations: watertight, holes open through.
- Revision expectations: changing countersink head diameter preserves shaft holes.
- Unacceptable outcomes: counterbore instead of countersink without disclosure, holes not through.

### 10. Critical-Dimension Revision

- Initial prompt: `Create an 80 x 35 x 6 mm mounting plate with two M4 clearance holes spaced 55 mm apart.`
- Revision prompt: `Change the hole spacing to 60 mm and keep everything else the same.`
- Required dimensions: only hole spacing changes from 55 to 60 mm.
- Allowed assumptions: none beyond initial.
- Expected clarification: none.
- Expected modules and parameters: same as initial.
- Printability constraints: unchanged.
- Compile expectations: success.
- Mesh expectations: one component, same plate bounds.
- Revision expectations: minimal diff; `hole_spacing` changed, unrelated modules preserved.
- Protected design invariants: plate width, plate depth, plate thickness, hole diameter, module names, Z=0 placement.
- Unacceptable outcomes: plate resized, hole diameter changed, whole rewrite.

### 11. New Feature Revision

- Initial prompt: `Create a 100 x 50 x 4 mm drill template with two 5 mm holes 70 mm apart.`
- Revision prompt: `Add a 10 mm hanging hole centered 8 mm from the top edge.`
- Required dimensions: new 10 mm hole, 8 mm top margin.
- Allowed assumptions: hole through full thickness.
- Expected clarification: none.
- Expected modules and parameters: add `hanging_hole_diameter`, `hanging_hole_edge_offset`.
- Printability constraints: flat plate.
- Compile expectations: success.
- Mesh expectations: one component.
- Revision expectations: add one feature module or extend hole module without changing original holes.
- Protected design invariants: original hole diameter, original hole spacing, plate size, existing module behavior.
- Unacceptable outcomes: moving original holes, adding decorative slots.

### 12. Intentionally Vague Request

- Input prompt: `Make me a bracket for my shelf.`
- Required dimensions: unknown.
- Allowed assumptions: none.
- Expected clarification: ask what it mounts to, shelf/load dimensions, fasteners, and orientation.
- Expected modules and parameters: none until clarified.
- Printability constraints: not applicable until clarified.
- Compile expectations: no SCAD generated.
- Mesh expectations: none.
- Revision expectations: not applicable.
- Unacceptable outcomes: generic bracket accepted as active revision.

### 13. Conflicting Dimensions

- Input prompt: `Create a 50 mm wide spacer that is 80 mm wide with a 10 mm center hole.`
- Required dimensions: width conflict between 50 and 80 mm.
- Allowed assumptions: none.
- Expected clarification: ask which width is correct.
- Expected modules and parameters: none until clarified.
- Printability constraints: not applicable.
- Compile expectations: no SCAD generated.
- Mesh expectations: none.
- Revision expectations: not applicable.
- Unacceptable outcomes: silently choosing either width.

### 14. Likely Unprintable Overhang

- Input prompt: `Create a one-piece wall shelf bracket with a 120 mm horizontal shelf arm and no supports.`
- Required dimensions: 120 mm arm.
- Allowed assumptions: wall plate size only after fastener clarification.
- Expected clarification: ask load, fasteners, and whether angled gussets are acceptable.
- Expected modules and parameters: `wall_plate`, `shelf_arm`, `gusset` if clarified.
- Printability constraints: no unsupported 120 mm horizontal ceiling; add gussets or require orientation/support warning.
- Compile expectations: no SCAD until load/support decisions are known.
- Mesh expectations: one component after clarified.
- Revision expectations: preserve load path.
- Unacceptable outcomes: plain horizontal cantilever with no gusset or warning.

### 15. Inaccessible Internal Cavity

- Input prompt: `Create a sealed hollow float, 80 mm diameter, with 2 mm walls.`
- Required dimensions: 80 mm OD, 2 mm walls.
- Allowed assumptions: none for sealed printing method.
- Expected clarification: ask whether a vent/drain hole or split halves are acceptable.
- Expected modules and parameters: none until clarified.
- Printability constraints: avoid trapped unsupported internal cavity unless split/vented.
- Compile expectations: no SCAD until clarified.
- Mesh expectations: none.
- Revision expectations: not applicable.
- Unacceptable outcomes: sealed sphere with inaccessible support/trapped cavity and no warning.

## Current-Implementation Sample

This review did not run the full benchmark through Gemini. One Gemini CLI auth probe failed through local OAuth, and `.env` secret loading was blocked by local policy. Existing generated runtime artifacts were inspected instead:

- 6 AI revisions sampled from `data/projects`.
- 6/6 compiled and were accepted.
- 6/6 lacked assertions.
- 6/6 included unsolicited cutout/pocket/vent terminology.
- 6/6 tackle-tray STLs had Critical printability findings under the default profile.

## Machine-Readable Fixtures

The canonical runnable fixtures live under `backend/tests/fixtures/generation_benchmarks/`.

- `core.json` contains the frequently run core suite.
- `full.json` contains the full stability suite.

Each fixture entry must include:

- `id`
- `suite`
- `input_prompt`
- `required_dimensions`
- `allowed_assumptions`
- `expected_clarification`
- `expected_modules`
- `expected_parameters`
- `expected_printability_constraints`
- `compile_expectation`
- `mesh_expectation`
- `revision_expectation`
- `protected_design_invariants`
- `unacceptable_outcomes`
