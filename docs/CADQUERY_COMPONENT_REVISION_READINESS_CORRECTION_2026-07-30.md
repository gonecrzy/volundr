# CadQuery Component Revision Readiness Correction - 2026-07-30

## Scope

This pass implemented deterministic design artifact consistency certification for CadQuery candidates and revision bases. It did not expand to the full 12-case benchmark.

## Why the enclosure base previously passed

The enclosure compiled and produced valid topology, but acceptance did not require Plan/source/output identity agreement. The old lifecycle checked source contract validity, topology, printability findings, and component-revision compliance later. It did not certify that:

- Plan component `base_shell` was implemented as source component `base_shell`.
- Plan output `base` was implemented as source output `base`.
- Plan parameter `wall_thickness = 3.0 mm` matched the generated source default.

The first deterministic mismatch stage was Plan-to-source validation.

## Certification Architecture

Added `design-artifact-consistency-v1`, persisted as `design_artifact_consistency_results` with a JSON artifact at each revision metadata path. The result stores hashes plus structured component, feature, output, and parameter mappings; it does not duplicate full source or Plan payloads.

Certification now runs:

- before CadQuery worker execution for approved-Plan revisions,
- after worker execution before candidate state derivation,
- before candidate acceptance,
- before provider-backed Revision Plan creation,
- before deterministic configuration review/generation,
- after failed-output retry before review-state refresh.

## Checks

Pre-execution checks verify Design Specification trace reuse, Plan component IDs, protected feature metadata, printable output IDs, output ownership, parameter IDs, parameter defaults/current values, type/unit/protected flags, source requirement IDs, expected solid-count policy, and execution parameter declarations.

Post-execution checks verify execution manifest presence, source hash, requested/returned output IDs, output manifest source hash, required output readiness, component ownership, topology metadata, and solid-count policy.

## Acceptance, Revision, And Configuration Behavior

CadQuery revisions with an approved Design Plan cannot be accepted without a passing certificate. Inconsistent revision bases are re-certified before Revision Plan provider calls; failures return internal mismatch details and consume zero revision-planning provider calls. Configuration parameter review, presets, preview, and generation require a consistent base.

Manual CadQuery revisions without an approved Design Plan retain their existing manual-source compile behavior.

## Stable Identity Rules

Stable product IDs must match from Design Plan through source decorators, `ParameterSpec.id`, `PrintableOutput.output_id`, execution manifests, and output manifests. Python function names remain implementation details when explicit decorators bind stable IDs.

Protected or revision-targetable features require source-visible `@feature(...)` metadata. Missing optional/nonprotected feature metadata is advisory.

## User-Facing Recovery

Candidate review now shows design consistency status. Blocked candidates display internal alignment issues and offer an explicit "Regenerate from approved plan" action plus technical details. The messaging does not ask users for additional dimensions or blame missing user input.

## Targeted Live Rerun

Run:

`output/live-benchmarks/live-benchmark-20260730T225034Z-consistency-correction-enclosure-rerun`

Selected cases:

- `parametric_electronics_enclosure`
- `component_revision_lid_only`

Provider:

- `gemini_api`
- `gemini-3.5-flash-lite`

Provider-call artifacts:

- 9 raw provider outputs
- 13,321 estimated prompt tokens

Results:

- Enclosure source probe: blocked before compile because generated source omitted protected `standoff_count` and `standoff_hole` parameters.
- Lid-only source probe: required one source repair; repaired source compiled with valid topology and one solid.
- Lid-only repaired source still used invented IDs (`lid_component`, `lid_body`), so it is not a certified structured-revision base/output identity result.
- Design Plan probe coverage averaged component `0.6667`, feature `0.5`, output `0.0`, dependency `0.6667`.

This is a narrower post-readiness result: the deterministic gate is working, but the live enclosure/lid generation still needs source identity and protected-parameter prompt quality before a component-targeted revision can be accepted.

## Verification

- Full backend suite: `269 passed`
- Targeted consistency/readiness tests: included in backend suite
- Frontend unit tests: `42 passed`
- Frontend build: passed
- Playwright suite: `4 passed`
- Migration verification: passed against fresh temp SQLite database
- Benchmark fixture validation: `32 passed`
- Organizer dry-run trace: `output/live-benchmarks/live-benchmark-20260730T225012Z-consistency-correction-organizer-dry-run`

## Remaining Issues

- Live enclosure generation still omits protected standoff parameters.
- Live lid-only repaired source still invents product IDs.
- The harness rerun is probe-based, not a full accepted-base lifecycle rerun.

## Recommended Next Task

Make the CadQuery source generation prompt and repair path preserve required stable identity tables under live Gemini, then rerun only the enclosure base and lid-only component revision lifecycle again.
