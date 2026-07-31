# Bottle Holder Provenance Live Evaluation

Date: 2026-07-31

## 1. Root Cause

The prior Design Plan validator treated every Plan value linked to a requirement as a direct copy. That rejected valid implementation derivations such as `81 mm + 0.8 mm = 81.8 mm` and conflated the `#8` screw designation with a metric hole diameter.

The exact request is now represented with separate identities and typed relationships. The latest live run reached Plan approval and scaffold generation. It did not reach the worker because Gemini returned a geometry function with one over-indented statement, producing `source_extraction_failure`. This is a real source-generation failure, not a provenance failure.

## 2. Relationship Model

Design Plan values now support:

- `direct`
- `derived_formula`
- `calculated`
- `standard_lookup`
- `product_default`
- `printer_default`
- `ai_proposal`
- `user_override`

Direct values are checked against the explicit requirement. Formula and calculated values are evaluated with the existing safe arithmetic evaluator. Lookup values are resolved against a versioned generic mapping and retain their key, variant, result field, and resolved result.

Derived expressions may be carried on the derived parameter or in its provenance block. Lookup-derived values may omit an arithmetic expression and are resolved from the lookup table.

## 3. Fastener Semantic Separation

The successful Plan preserved:

- `mounting_screw_designation = "#8"` as a direct user value,
- `screw_clearance_diameter_mm = 4.2 mm` as a `standard_lookup` result,
- `screw_head_diameter_mm = 8.5 mm` as a separate `standard_lookup` result.

The mapping table is `fastener-clearance-v1`. Variant and result-field metadata are validated deterministically; `#8` is never parsed as `8 mm`.

## 4. Formula and Lookup Verification

The latest successful Plan resolved:

- `holder_inner_diameter_mm = 81.8 mm`, from `bottle_diameter_mm + 2 * clearance_mm`,
- `holder_outer_diameter_mm = 87.8 mm`, from inner diameter plus wall thickness,
- `screw_clearance_diameter_mm = 4.2 mm`, from the `#8` lookup,
- `screw_head_diameter_mm = 8.5 mm`, from the `#8` lookup,
- `mounting_hole_spacing_mm = 106.8 mm`, from the declared dependency formula.

The explicit bottle diameter remained `81.0 mm` throughout the Plan. Missing lookup values are resolved before scaffold rendering so the scaffold receives canonical execution values.

## 5. Frontend Presentation

The Proposed design review now separates direct values into **Your requirements**, implementation choices into **Volundr proposes**, and derived values into **Calculated**. Relationship labels distinguish user values, formula-derived values, standard proposals, and defaults. Explanations from the Plan are shown without exposing formulas or lookup table IDs as primary UI text.

## 6. Live Run

The final exact-request run used a fresh SQLite database and the real Gemini provider:

- Project: `ced2ce1d-2c14-47f9-9ff7-cc3c26900344`
- Requirements attempt: `98229913-9631-4f27-9a2f-45e59645d112`
- Design Plan attempt: `5f30f6f2-7d06-447b-98e5-bb817f61c6b8`
- CadQuery attempt: `d1ef2111-269b-44e7-bf52-c8806e9aa3aa`
- Final result: blocked at source extraction before worker execution

The exact user request was used without additional construction dimensions. Requirements completed without clarification. The Plan completed after one invalid Plan response and a later valid response.

## 7. Scaffold Result

The deterministic scaffold was generated with canonical parameters, component/output registrations, and entrypoint ownership. Gemini supplied geometry functions only. The final geometry response preserved the expected function names but contained an unexpected indentation error in `_ai_component_holder_body`; the scaffold parser rejected it before execution.

This is the remaining narrow reliability issue. The run did not produce worker, topology, printability, or functional B-Rep evidence, so no physical plausibility claim is made.

## 8. Provider Usage

Four Gemini calls were persisted:

| Stage | Prompt tokens | Output tokens | Total | Duration |
| --- | ---: | ---: | ---: | ---: |
| Requirements | 971 | 684 | 1,655 | 2.35 s |
| Initial Design Plan | 4,416 | 3,938 | 8,354 | 9.95 s |
| Valid Design Plan | 7,890 | 3,941 | 11,831 | 9.03 s |
| CadQuery source | 6,626 | 1,187 | 7,813 | 3.57 s |
| **Total** | **19,903** | **9,750** | **29,653** | **24.90 s provider time** |

Authoritative Gemini usage metadata is persisted. No provider request ID was returned by this run.

## 9. Functional and Candidate Status

Functional verification did not run because source extraction failed first. The workflow correctly stopped before worker execution and did not present a physically ready candidate. Mounting-hole, support-floor, removal-path, and retention checks remain unproven for this live attempt.

## 10. Remaining Issues

The next narrow backend task is deterministic handling of malformed provider geometry bodies: either bounded source-body repair with scaffold-owned boundaries preserved, or a clear retry/blocked result with the malformed function evidence retained. The worker timeout and physical verifiers should not be changed based on this run because the worker was never reached.

## 11. Decision

Observed user testing remains paused. Provenance is now reliable enough to explain user values versus implementation values, but this request has not yet reached physical verification. User testing may resume only after the source-generation failure is resolved or consistently blocked with actionable evidence and a candidate that passes or explicitly holds on functional checks.
