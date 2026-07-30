# Gemini Ruleset

Version: `gemini-ruleset-v1`

This is the implementation-ready ruleset for Gemini-generated CadQuery source in
the CadQuery-primary Volundr lifecycle. Historical OpenSCAD prompt modes and
marker rules are superseded for product CAD by this document,
`docs/CADQUERY_BACKEND.md`, and the backend `cadquery-v1` source validator.

## Active Stages

Gemini is used only in staged, versioned prompts:

- `requirements-v1`
- `clarification-v1`
- `design-plan-v1`
- `cadquery-generation-v1`
- `cadquery-contract-repair-v1`
- `cadquery-execution-repair-v1`
- `revision-planning-v1`
- `cadquery-component-revision-v1`
- `cadquery-scope-correction-v1`
- `validation-feedback-v1`

Direct raw prompt-to-source generation is not the normal product path.

## CadQuery Source Output

For CadQuery source stages, return complete Python source only:

1. Return exactly one fenced `python` or `cadquery` block, or strict raw Python source when the caller requests raw source.
2. Do not include prose outside the source.
3. Do not return STL, STEP, BREP, base64, shell commands, file paths, or instructions to run commands.
4. Import CadQuery as `cq`.
5. Import Volundr runtime symbols from `volundr_cad.runtime`.
6. Declare typed module-level `PARAMETERS`.
7. Define exactly one `build(params)` entry point.
8. Return one `Product` containing named `PrintableOutput` records.
9. Use stable `output_id` and `component_id` values from the approved Design Plan.
10. Set `expected_solid_count` and `allow_disconnected_solids` intentionally for every output.
11. Do not write files or choose artifact paths. The worker owns STEP/STL/BREP exports.

## Functional CAD Rules

1. Use millimeters.
2. Model functional geometry before cosmetic detail.
3. Keep ordinary FDM wall thicknesses at or above 1.6 mm unless the approved requirements allow thinner non-structural geometry.
4. Preserve fit-critical dimensions as named editable or protected parameters.
5. Represent calculated dimensions as derived values inside source, backed by the approved Design Plan dependency graph.
6. Include explicit clearance parameters for mating parts.
7. For fasteners, distinguish shaft clearance, head clearance, spacing, and tool access.
8. For handles, brackets, hooks, and mounts, include positive-overlap load paths such as ribs, gussets, bearing faces, or reinforced bosses.
9. Do not add decorative cutouts, vents, pockets, labels, or unrelated holes unless requested or included in the approved Design Plan.
10. Keep generated parts near the origin and oriented for the intended first-layer contact unless the approved plan requires a different orientation.
11. Do not place geometry below the build plate.
12. Avoid fragile face-only or tangent contacts; connected geometry must overlap by positive material.

## Parameter Rules

1. `PARAMETERS` is the source of editable parameter metadata.
2. Every `Product` with parameters must use `parameters=PARAMETERS`.
3. Use `ParameterSpec` with supported types: `number`, `integer`, `boolean`, and `enum`.
4. Include defaults, units, ranges, enum choices, editability, and protected status where applicable.
5. Preserve parameter IDs during repairs and revisions unless the approved plan explicitly authorizes a rename.
6. Do not turn protected values into editable values.
7. Direct configuration changes must be executable by passing validated JSON parameter values to `build(params)`, without provider calls or source rewriting.

## Output Rules

1. Emit one `PrintableOutput` per approved printable output.
2. Required outputs must be present and executable.
3. Optional outputs may fail without accepting a partial assembly candidate only when the plan marks them optional.
4. Normal one-piece outputs use `expected_solid_count=1` and `allow_disconnected_solids=False`.
5. Intentional multi-body or print-in-place outputs must declare an expected count greater than one and `allow_disconnected_solids=True`.
6. Do not hide multiple loose solids in a normal output.

## Security Rules

Generated source is untrusted and must remain inside the `cadquery-v1` contract:

- no imports except approved CadQuery, math/typing helpers, and Volundr runtime symbols,
- no `open`, `exec`, `eval`, `compile`, or `__import__`,
- no `os`, `sys`, `pathlib`, `subprocess`, sockets, HTTP clients, or environment access,
- no dynamic code loading,
- no reflection or dangerous dunder access,
- no decorators, metaclasses, or uncontrolled global mutation,
- no top-level geometry execution,
- no artifact writing.

AST validation is defense in depth. Isolated worker execution remains the
security boundary.

## Repair Rules

`cadquery-contract-repair-v1` may fix only source-contract failures:

1. missing imports or incorrect import style,
2. missing or malformed `PARAMETERS`,
3. missing `build(params)`,
4. missing or malformed `Product`/`PrintableOutput` declarations,
5. syntax errors,
6. unsupported imports or prohibited calls that can be removed without changing design intent.

It must not redesign geometry, change protected requirements, remove outputs, or
modify Design Plan structure.

`cadquery-execution-repair-v1` may fix directly diagnosed CadQuery API or
geometry-operation failures such as invalid selectors, failed shells, failed
fillets, or straightforward boolean issues. It must preserve protected
parameters, components, outputs, topology expectations, and requirements.

`cadquery-scope-correction-v1` may revert unauthorized revision scope changes
only. It must not introduce a new design.

## Revision Rules

1. `revision-planning-v1` returns JSON only and does not generate source.
2. Component-targeted revision stages return complete authoritative CadQuery source, not fragments or patches.
3. Edit only the components, features, outputs, parameters, and helpers authorized by the approved Revision Plan.
4. Preserve protected unrelated functions, parameter metadata, outputs, and topology expectations.
5. Preserve active configuration values and ensure the revised source remains executable with them.
6. Do not add undeclared components or outputs during a component-targeted revision.

## Failure Behavior

1. Ask for clarification instead of inventing missing fit-critical or load-bearing dimensions.
2. Classify provider, JSON, source-contract, execution, topology, mesh, printability, and revision failures with stable failure classes.
3. Preserve raw provider output and extracted source separately.
4. Do not claim a generated model is guaranteed printable.
