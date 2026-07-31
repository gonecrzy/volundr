# Bottle Holder Functional Live Evaluation

Status: initial live evaluation complete; observed user testing remains paused.

## 1. Initial Request

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.

The request was run against the real Gemini API provider and an isolated CadQuery worker. No construction dimensions were added by the test.

- Primary preserved project: `9ad85556-9a97-4029-93cf-b0e0898c5994`
- Final root workflow: `8b3e590c-8ba5-4d94-93cb-bec712a68028`
- Diagnostic bundle: `workflow-debug-8b3e590c-8ba5-4d94-93cb-bec712a68028.zip`
- Preserved evidence directories: `/tmp/volundr-bottle-live-rerun.M0eGfO`, `/tmp/volundr-bottle-live-final.M0eGfO`, and `/tmp/volundr-bottle-live-diagnosed.M0eGfO`

The first browser attempt queried the Design Plan before opening the Proposed design stage and received a 404. This was a test sequencing defect, not a backend generation failure. A subsequent run reached real source generation and preserved those source attempts separately. The final diagnosed rerun was retained as the authoritative post-correction result.

## 2. Clarification Behavior

Gemini initially asked for two material values:

- bottle height / retention depth;
- mounting screw spacing.

The browser answered both in one clarification round with `20 mm`, while retaining the original 81 mm user measurement. No extra construction dimensions were supplied.

The final clarified Design Specification separated provenance correctly:

- user-provided: `bottle_diameter=81 mm` and the mounting/retention intent;
- clarification: `retention_height=20 mm`, `screw_spacing=20 mm`;
- AI assumptions: `clearance_removable=0.4 mm`, `wall_thickness=3 mm`.

The clarification was presented as a normal workflow step, not as an error.

## 3. Functional Design Plan

The approved plan resolved:

- primary frame with X horizontal, Y normal, Z vertical;
- XZ mounting plane with Y normal;
- Y mounting-hole axis;
- Z hole arrangement axis;
- concrete clearance-hole style;
- proposed 20 mm hole spacing;
- required bottom support;
- proposed 3 mm minimum floor thickness;
- +Z removal direction.

The earlier live run approved a plan that did not resolve retention sufficiently: it used `strategy: reviewed_proposal` and had no retention `feature_id`. After the narrow generic correction, the final diagnosed run rejected the same class of unresolved plan before approval with `functional.retention_strategy_unresolved`. This is now the expected safe behavior.

## 4. Proposed Versus User-Provided Values

The Design Specification and Plan preserved the 81 mm bottle diameter. The proposed values were 0.4 mm removable clearance, 3 mm wall thickness, and a 20 mm mounting-hole spacing and retention depth after clarification.

## 5. Parameter-Effect Results

The first live source run rejected both the initial source and the repair source before worker execution:

- `bottle_diameter` was used through derived local dimensions that reached cylinder geometry;
- `retention_height` was passed to cylinder geometry;
- `screw_spacing` was used to derive hole positions.

The validator reported all three as `cadquery.protected_parameter_no_geometry_effect`. Inspection showed that the checker did not propagate dependencies through derived local assignments and did not recognize all relevant CadQuery methods, including `cylinder` and `pushPoints`. This was a false rejection of parameter use, not evidence that the model used no geometry parameters. The generic AST correction now recognizes these transitive effects; the final live run did not reach source generation because the plan was correctly blocked earlier.

## 6. Feature Invocation Results

The generated source declared mounting, screw-hole, cradle, and bottom-support decorators on the component builder. In the source-reaching run, the generic checker falsely rejected transitive parameter use before execution; that correction is now covered by regression tests. In the final diagnosed run, plan validation stopped before source generation because retention metadata lacked a concrete feature target. Feature invocation and returned-geometry effects therefore remain unverified.

## 7. Mounting-Hole Verification

No worker job, STEP, BREP, STL, topology result, or B-Rep functional measurement was produced. The plan requested Y-axis holes normal to the XZ mounting plane, but the live geometry could not be accepted for execution because of the validator false rejection.

## 8. Support-Floor Verification

No physical verification was possible. The source contains a bottom plate construction, but source inspection is not a substitute for the required worker/B-Rep check.

## 9. Removal-Direction Verification

The plan proposed +Z removal. No executed geometry was available for conservative containment-path verification.

## 10. Retention Verification And Human-Review Limits

The plan's `reviewed_proposal` retention strategy was not concrete enough to establish feature ownership. One-handed usability cannot be certified automatically by the current verifier; it requires human review even after measurable retention geometry exists.

## 11. Functional Candidate State

No candidate was created. The source contract rejection correctly prevented worker execution and prevented a misleading ready candidate. This is safer than presenting the failed model as `ready_with_warnings`, but the functional-plan hold should occur earlier for unresolved retention strategy.

## 12. Manual Geometry Classification

Classification: **requires targeted revision or validation correction before classification**. No rendered views were generated because the source was rejected before CAD execution. The requested isometric, orthographic, and section views therefore could not be inspected in this run.

## 13. Revision Plan And Typed Criteria

The conditional revision was not run. The initial workflow did not produce a candidate with wrong-axis holes or a missing floor; it stopped at source-contract validation. Running a revision without an executed baseline would not provide trustworthy physical comparison evidence.

## 14. Revision Physical-Success Results

Not applicable for this run.

## 15. Provider Calls, Tokens, Latency, And Repairs

The source-reaching rerun recorded six Gemini attempts: three requirement attempts including one malformed response and a correction, one Design Plan call, one source-generation call, and one contract-repair call. The source-generation and repair calls both produced preserved source artifacts; no CadQuery worker call occurred because both sources failed the contract gate. The final diagnosed rerun recorded four attempts: two requirement attempts (7.358 s and 3.895 s), then Design Plan attempts at 6.963 s and 5.859 s. Provider token counts are not persisted by the current generation-attempt schema. Provider timing and raw responses are preserved in the run directories and diagnostic bundles. No API key is included in the evidence.

## 16. Workflow Diagnosis

The source-reaching run identified `source_contract_validation` as its first meaningful blocking stage, with preserved initial and repaired source attempts. The final diagnosed rerun identified `design_plan_validation` with rule `functional.retention_strategy_unresolved` as the confirmed root failure, and its root and child runs terminated as `failed` rather than remaining `running`. The final bundle contains the diagnosis, event log, stage trace, frontend events, artifacts manifest, requirements evidence, and redaction report. An earlier manually built bundle with unknown diagnosis is retained as historical evidence and was not rewritten.

## 17. Remaining Generic Defects

1. The source data-flow correction needs broader coverage as additional CadQuery idioms appear.
2. A live run with a concrete retention strategy and feature target is still required to exercise source, worker, and B-Rep functional verification.
3. Add standard geometry renders and section views once an executed candidate exists; this run could not exercise that path.

## 18. Decision On User Testing

Observed user testing must not resume. The corrected system now blocks the unresolved functional plan with an accurate diagnosis, but this evaluation did not reach physical verification. The next live rerun must either produce a concrete plan and a physically plausible functionally verified candidate or block at a specific physical-verification stage with actionable findings.
