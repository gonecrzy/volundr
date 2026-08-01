# Bottle Holder Parameter-Effect Live Evaluation

Date: 2026-08-01

## Scope

The exact request was preserved without adding construction dimensions:

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.

This evaluation covers only the structured CadQuery geometry-body parameter-effect correction. The structured-body JSON format, deterministic scaffold, functional Design Plan model, and frontend workflow were not broadened.

## Deterministic contract result

The implementation now derives a `cadquery-parameter-effects-v1` contract from the approved Design Plan. Each derived parameter records its expression, direct dependencies, transitive protected dependencies, resolved value, and provenance version. Each component and feature function records its required effects, direct parameter IDs, and approved derived values.

The contract distinguishes direct use from valid transitive use. For example:

- `bottle_diameter` and `removable_fit_clearance_per_side` may reach cavity geometry through `bottle_inner_diameter` and `bottle_cavity_diameter`.
- `mounting_screw_count` must control pattern cardinality; a fixed two-point list, fixed range, or repeated literal geometry calls is blocked.
- `mounting_hole_spacing` must control the pattern spacing rather than being replaced by fixed coordinates.

The following blocking findings are emitted with function and parameter context:

- `geometry_body.required_effect_missing`
- `geometry_body.derived_dependency_broken`
- `geometry_body.pattern_count_hardcoded`
- `geometry_body.pattern_spacing_hardcoded`
- `geometry_body.dimension_bypassed_by_literal`
- `geometry_body.effect_unverifiable`

Valid direct use, one-level derived use, and multi-level derived use pass. Unrelated derived values do not satisfy an obligation. The same manifest is supplied to body generation, bounded body repair, structured scaffold assembly, structured source validation, and geometry diagnostics.

## Exact live smoke attempt

The exact opt-in command was run:

```text
VOLUNDR_RUN_LIVE_E2E=true npm run test:e2e:live -- bottle-holder.live.spec.ts
```

The harness started database migration and the CAD worker, but Playwright timed out waiting for its web-server health gate before the browser request was submitted. A retained retry confirmed that the API process reached application startup and the worker reported ready; the environment rejected the frontend Vite bind with `EPERM` on `127.0.0.1:4273`. Therefore this post-correction attempt produced no Gemini generation attempt, candidate, worker timing, or physical geometry verification. It is recorded as an environment-blocked live smoke, not as a model pass or failure.

The preceding preserved live evidence remains documented in [BOTTLE_HOLDER_STRUCTURED_GEOMETRY_LIVE_EVALUATION.md](BOTTLE_HOLDER_STRUCTURED_GEOMETRY_LIVE_EVALUATION.md). That run reached structured assembly and was correctly blocked before worker submission for missing canonical parameter effects; it predates this final contract implementation and is not presented as a post-change live result.

## Verification

The deterministic backend path verifies requirements/provenance and Design Plan propagation, resolves derived values in the scaffold, persists both manifests, validates assembled source before worker submission, and blocks poor geometry accurately. Mounting-hole, floor, one-handed-removal, retention, and worker-timing checks remain downstream of source validation; they do not run when the canonical parameter-effect contract is not satisfied.

No bottle-holder-specific production branch was added. The implementation is generic over parameter IDs, derived expressions, function IDs, and approved Design Plan interfaces.

