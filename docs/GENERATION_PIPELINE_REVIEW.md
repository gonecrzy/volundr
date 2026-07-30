# Volundr Generation Pipeline Review

Date: 2026-07-25

Historical snapshot: this review describes the old OpenSCAD/Gemini CLI pipeline
before the CadQuery-primary transition. It is retained for failure taxonomy and
background only. Use `docs/CADQUERY_BACKEND.md` and
`docs/CADQUERY_TRANSITION_EVALUATION.md` for the current pipeline.

## Scope

This review inspected the current Volundr repository as a product, CAD, OpenSCAD, prompt, and reliability system. Specialist read-only agents reviewed functional CAD behavior, OpenSCAD quality, Gemini prompting, product workflow, and nondeterministic test strategy. The synthesis below is not a concatenation of those reports; it records the shared root causes and recommended stabilization path.

## Current Pipeline Map

The implemented generation path is:

```text
frontend prompt
  -> POST /api/projects/{id}/generate
  -> ProjectService.generate_initial_revision()
  -> GeminiCliProvider._build_prompt()
  -> gemini CLI text output
  -> extract_scad_source()
  -> OpenScadCliRunner.compile()
  -> inspect_stl()
  -> store revision assets
  -> mark revision accepted if compile and mesh metadata succeed
  -> optional one-shot Gemini repair after compile failure
```

Important implementation points:

- `backend/app/services/ai/gemini_cli.py` builds one prompt for initial generation, revision, and repair.
- `backend/app/services/ai/source_extraction.py` checks only for `module main_model` and exactly one top-level-looking `main_model();`.
- `backend/app/services/projects/service.py` accepts a generated revision when compile succeeds and mesh metadata exists.
- `backend/app/services/printability/inspector.py` is available but not part of automatic generation acceptance.
- `frontend/src/main.tsx` exposes a single "Message Gemini" input and a blocking "Sending" state.
- `docs/DATA_MODEL.md` defines `GenerationAttempt` and `CadJob`, but those durable records are not implemented.

## Observed Behavior

Automated checks:

- `cd backend && .venv/bin/python -m pytest -q`: 39 passed, 1 warning.
- `cd frontend && npm run build`: passed.
- `cd backend && pytest -q` through the generic wrapper found no tests.
- `backend/.venv/bin/python -m pytest -q backend/tests` from the repo root failed because root `.env` variables were treated as forbidden pydantic settings extras.

Controlled live Gemini attempt:

- One direct Gemini CLI probe without API-key auth failed with an `IneligibleTierError` for the local OAuth client.
- A `.env`-loaded API-key attempt was not run because the local hook blocked secret-loading commands. No further Gemini quota was spent.

Existing generated examples:

- The runtime database contained six AI-generated revisions and no failed AI revisions.
- Existing tackle-tray carrier generations compiled and were accepted.
- Static source review found repeated missing assertions and unsolicited cutout/pocket/vent features.
- Printability inspection of existing accepted tackle-tray STLs produced Critical findings for overhangs, bridge spans, unsupported ceilings/cavities, and build-volume violations.
- Existing user revision prompts such as "handle is not complete?", "why is there a hole through the box?", and "what holds the trays?" show that valid solids were not consistently useful parts.

## Root-Cause Analysis

Volundr works inconsistently because multiple independent weak boundaries line up in the same direction:

- User requirements remain unstructured. Critical dimensions, fit constraints, load paths, and assumptions are not extracted before generation.
- The live Gemini prompt is a single mode-mixed prompt. Initial generation, design revision, and compiler repair need different instructions and different context.
- Clarification is not representable. If Gemini asks a question, Volundr records that as an extraction failure rather than a waiting-for-clarification state.
- The documented OpenSCAD contract is stronger than the prompt and backend enforcement. Current generated examples violate assertions, skeleton, assumption, and print-note expectations.
- Acceptance is compile-first. A watertight STL with nonzero volume becomes active even when it is too large for the printer or contains severe printability risks.
- Observability is insufficient. Prompt version, exact prompt, provider/model, request payload, raw output, extracted source, validation results, and failure class are not recorded in one reproducible generation-run record.
- Revision context is thin. Revisions receive active source and user instruction, but not accepted requirements, assumptions, parameter schema, validation findings, or an explicit preserve list.
- Repair is conflated with revision. Failed source is labeled as "Current accepted OpenSCAD source" in the repair prompt path.

These are a combination of unclear user requirements, prompt structure, weak OpenSCAD conventions, missing validation gates, product workflow gaps, and observability gaps. Model limitations contribute, but the current architecture does not give the model enough structure or give Volundr enough measurement to separate model variance from pipeline defects.

## Cross-Agent Findings

High-confidence agreement:

- Move from one-step generation to a staged workflow.
- Add requirement extraction and clarification before SCAD generation.
- Split initial generation, revision, and compile-repair prompts.
- Enforce a stricter OpenSCAD skeleton and source contract before compile.
- Persist durable generation-attempt records with prompt versions and full request context.
- Treat selected validation results as acceptance blockers, not only diagnostics.
- Surface assumptions, critical parameters, and validation findings in the UI.

Conflicting or product-dependent recommendations:

- Auto-accept policy: CAD and reliability reviews favor blocking acceptance on critical validation. Product review recommends candidate revisions with user acceptance. A pragmatic V1 policy can auto-accept manual compiles that pass hard mesh checks while making AI generations candidates when they contain warnings or assumptions.
- Build-volume handling: A default profile may not match the user's printer. Blocking on build volume should use the selected or saved profile; otherwise it should be a warning with a prompt to choose a printer profile.
- Printability severity: Critical zero volume, below-build-plate geometry, missing STL, compile failure, and ordinary non-watertight meshes should block. Overhangs and bridge spans may warn if the plan explicitly allows supports.

Deferred items:

- Full slicer integration.
- Automatic support generation.
- Multi-user workflow.
- External OpenSCAD libraries.
- STEP/CadQuery/build123d providers.

## Architecture Recommendations

Adopt this staged generation flow:

```text
request
  -> requirements-v1
  -> clarification-v1
  -> design-plan-v1
  -> openscad-generation-v2
  -> source-contract validation
  -> compile
  -> mesh validation
  -> printability validation
  -> bounded compile repair or candidate review
  -> user acceptance / revision
```

Required structured information before SCAD generation:

- part category
- purpose and success condition
- critical dimensions with units and source (`user_provided`, `assumed`, `derived`)
- mating parts and clearances
- fastener type, spacing, hole/counterbore/countersink geometry
- load path and expected orientation
- print orientation and support strategy
- wall thickness and minimum feature thresholds
- assembly/insertion/removal path
- explicit assumptions and blocked assumptions
- prohibited features for this design

Revisions should differ from initial generation:

- Use the accepted design record and active source as context.
- Identify affected parameters/modules.
- Preserve critical dimensions and unrelated modules.
- Add new parameters only for new user-controllable dimensions.
- Return a complete revised source, but avoid whole-model rewrites.

Compiler repair should differ from design revision:

- Input is failed source plus compiler stdout/stderr.
- Allowed changes are syntax, OpenSCAD compatibility, brace/semicolon fixes, and obvious invalid expression repairs.
- It must not change dimensions, add features, remove modules, or redesign the part.

## Product Recommendations

Use separate states for generation runs and revisions:

```text
draft_request
extracting_requirements
waiting_for_clarification
planning
generating_scad
extracting_source
compiling
repairing_compile
inspecting_mesh
inspecting_printability
ready_for_review
accepted
failed
cancelled
```

Show a user-facing timeline:

```text
Requirements -> Plan -> Generate -> Compile -> Validate -> Review
```

Add first-class displays for:

- known requirements
- missing decisions
- assumptions
- critical parameters
- validation blockers, warnings, and notices
- revision design delta
- dirty-source state when local editor changes are not compiled

Keep raw AI output, prompt payloads, and compiler logs in diagnostics. They are necessary for debugging, but should not be the primary product explanation.

## Risks And Limitations

- Live Gemini generation could not be sampled beyond one auth probe in this review.
- Existing generated runtime examples are useful evidence, but are not a controlled benchmark suite.
- STL-based printability inspection is necessarily heuristic for wall thickness, bridge spans, and inaccessible cavities.
- Some decisions need product policy: auto-accept vs candidate revisions, build-volume profile defaults, and which warnings are user-overridable.
