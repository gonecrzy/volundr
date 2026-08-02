# Bottle Holder Structured Geometry Live Evaluation

Date: 2026-07-31

## 1. Root Cause

The preceding bottle-holder run failed because Gemini returned free-form Python geometry with malformed indentation. The scaffold could not safely insert that text into a deterministic source file.

The structured-body implementation removes that failure mode. The provider now returns JSON body statements, while Volundr owns function signatures, indentation, imports, registrations, stable IDs, and the build entrypoint.

The exact live request was then run without additional construction dimensions:

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.

The current live evidence reaches structured assembly, but the model is conservatively blocked before worker execution because it does not use every required canonical parameter. In particular, one response hard-coded the two mounting-hole locations instead of using `mounting_screw_count`. Another response used derived dimensions while omitting protected inputs from the geometry data flow. This is a semantic source-contract failure, not a serialization failure.

## 2. Structured Body Contract

The provider response uses `cadquery-geometry-bodies-v1`:

```json
{
  "schema_version": "cadquery-geometry-bodies-v1",
  "functions": [
    {
      "function_id": "_ai_component_primary_body",
      "body_lines": ["body = ...", "return body"]
    }
  ]
}
```

Each required function appears exactly once. Bodies contain statements only. They cannot declare functions, decorators, imports, runtime registrations, filesystem/network access, scaffold-owned identifiers, or undeclared parameters.

## 3. Deterministic Assembly

`backend/app/services/cad/geometry_bodies.py` parses JSON, permits only one JSON fence wrapper, normalizes line endings and tabs, dedents provider text, parses a synthetic function with the scaffold-owned signature, validates the AST, and canonicalizes it with `ast.unparse`.

The immutable scaffold then supplies:

- parameter declarations,
- component and feature registrations,
- output identities,
- function signatures,
- the `Product` structure,
- the `build(params)` entrypoint.

Equivalent provider indentation produces the same canonical function body and hash. The scaffold hash is independent of provider body formatting.

## 4. Geometry-Body Repair

One bounded repair mode is available as `cadquery-geometry-body-repair-v1`. It receives the rejected structured response, parser diagnostics, and the deterministic function inventory. It cannot change the Design Plan, parameter declarations, product IDs, function signatures, or scaffold-owned source.

Raw provider output, parsed JSON, original body lines, canonical bodies, assembled source, and scaffold manifests are retained as separate artifacts. A failed attempt is not overwritten by a repair attempt.

## 5. Scaffold Integrity

The fixture-backed deterministic workflows pass with the structured provider contract. The source scaffold remains `cadquery-scaffold-v1`; only the provider-owned geometry regions vary. Source identity and scope checks continue to run against the assembled complete source.

The production search found no new bottle-holder branch. Bottle/enclosure names remain confined to existing test fixtures and generic benchmark support; the structured assembler is generic.

## 6. Live Body-Generation Result

The completed preserved live smoke run used project `37c98a5a-7253-4f25-98f6-31fd7b1a3153` and produced a failure outcome rather than a candidate. Requirements and Design Plan generation succeeded. Both the initial structured body response and the bounded source repair assembled into complete Python source and were persisted.

The source-contract result stopped the workflow before worker submission for:

- `bottle_diameter` not reaching geometry through the canonical parameter,
- `mounting_screw_count` not being used,
- `removable_fit_clearance_per_side` not being used in the generated geometry.

A second preserved run also exercised structured body rejection and repair for an undeclared provider parameter. The repair path retained the rejected body evidence and rejected the repaired response when it still violated the canonical source contract.

Result: **blocked before CAD worker execution**. No candidate was created and no physically misleading result was presented as ready.

## 7. Worker Timing

No worker timing was recorded for the live bottle-holder runs because source-authority validation correctly prevented worker submission. The worker was not given malformed or semantically uncertified source, and the timeout was not increased.

The deterministic worker and existing timing instrumentation remain covered by the backend and browser fixture suites. A future live run that passes source authority must be inspected for component, feature, boolean, and export timing.

## 8. Functional Verification

The bottle-holder live runs did not reach B-Rep execution, so mounting-hole, support-floor, removal-path, and retention geometry verification did not run. This is the correct consequence of failing the earlier source-authority gate.

The Design Plan and functional interfaces were present in the preserved artifacts. The remaining blocker is before physical verification: canonical parameter use must be demonstrable in the generated geometry bodies.

## 9. Candidate State

The live run ended with no candidate revision. There was no current-design replacement, no worker result, and no opportunity for a structurally valid but functionally unverified holder to appear as ready.

## 10. Provider Usage

The completed preserved run used `gemini_api` with model `gemini-3.5-flash-lite`. Four provider attempts recorded authoritative Gemini usage metadata:

| Prompt version | Prompt tokens | Output tokens | Total tokens | Duration |
| --- | ---: | ---: | ---: | ---: |
| `requirements-v3` | 971 | 698 | 1,669 | 2.29 s |
| `design-plan-v3` | 4,351 | 3,873 | 8,224 | 9.96 s |
| `cadquery-generation-v6` | 8,013 | 1,332 | 9,345 | 3.86 s |
| `cadquery-contract-repair-v2` | 10,459 | 1,388 | 11,847 | 3.63 s |

Provider request IDs were unavailable in these responses. The latest rerun additionally recorded `cadquery-geometry-body-repair-v1` usage, confirming that the structured repair prompt is active.

## 11. Evidence and Redaction

The preserved debug bundle contains the run summary, event log, diagnosis, stage trace, raw provider evidence, structured body artifacts, assembled scaffold artifacts, source-contract evidence, and redaction report. Bundle scanning found no Gemini API key or authorization header. No worker artifacts were included because the worker was never submitted.

## 12. Remaining Issues

The next narrow reliability correction should improve how the geometry prompt and source contract enforce canonical protected-parameter use without weakening derived-parameter provenance. In particular:

- derived implementation values must retain their dependency path to explicit inputs,
- protected count parameters must control pattern/count geometry rather than be bypassed by literals,
- the provider should receive a clearer per-function required-parameter inventory.

These are semantic generation issues and should remain separate from the completed source-serialization work.

## 13. Recommendation

The structured source boundary is ready for deterministic and diagnostic use. The chat-first frontend should not yet be enabled for unrestricted live automatic drafts for this request: the live model still fails before physical verification on canonical parameter effects. Once the source contract is either satisfied or produces a stable, user-facing actionable block for this semantic failure, the chat-first transition can proceed without reintroducing full-source repair or indentation risk.
