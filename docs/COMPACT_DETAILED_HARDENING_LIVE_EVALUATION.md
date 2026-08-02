# Compact/Detailed Planning Hardening Live Evaluation

Date: 2026-08-02

This report records the proportional-planning interoperability rerun. It is a
diagnostic evaluation of real Gemini, FastAPI, and the CadQuery worker. It does
not promote a candidate merely because planning normalization succeeds.

## Previous failures

The Product Validation Round 1 matrix showed four distinct failures:

- compact bracket ribs were emitted as components although the request was one
  printable bracket;
- the holder repeated-feature record lacked a usable owner/type contract;
- organizer local calculations were treated as unapproved Plan identities;
- detailed ventilation slots required a spacing parameter even though no
  reusable spacing control was requested.

## Corrections under test

The rerun uses the same five requests and no product-specific branches. The
compact parser now normalizes integral feature components and unambiguous
owners. Repeated layouts distinguish fixed/proposed numeric evidence from
configurable patterns. Compact and detailed prompts describe the same semantic
boundary. Successful source validation retains nonblocking local-variable
diagnostics.

## Results

The final live command was run on 2026-08-02 with the configured Gemini API,
FastAPI services, and CadQuery worker available. The authoritative raw JSON
evidence was produced by
`backend/scripts/run_live_multi_design_evaluation.py` and saved during the run
as `/tmp/volundr-compact-detailed-hardening-final-3.json`.

| Case | Route | Provider/planning result | First blocked stage | Worker/current version |
| --- | --- | --- | --- | --- |
| Circular spacer disk | direct brief | compact plan normalized; 2 geometry attempts | geometry-body result-shape proof | not reached / none |
| Irregular bracket | compact plan | legacy component/layout aliases still produced an invalid layout reference | compact-plan validation | not reached / none |
| Bottle holder | compact plan | plan normalized; canonical source identities remained strict | source-contract hard rejection | not reached / none |
| Organizer tray | compact plan | plan normalized; generated source did not preserve approved identities | design-artifact consistency | not reached / none |
| Two-piece enclosure | detailed plan | two detailed-plan attempts failed plan/provenance validation | detailed-plan validation | not reached / none |

The final run did not meet the evaluation threshold of two of three compact
cases reaching the worker, nor did the detailed case reach geometry. The
normalization changes did remove the original component/feature and
nonparametric-layout contract failures in several runs, but provider output
varied between attempts. The remaining blocks are not being reclassified as
successes: source identity mismatches, invalid result-shape proofs, malformed
feature references, and detailed-plan provenance errors remain genuine gates.

## Final-run evidence

- A: requirements succeeded, compact planning succeeded, geometry generation
  and bounded repair both failed on result-symbol shape verification; worker
  was not reached.
- B: requirements succeeded, compact planning failed on an unknown feature
  reference after the provider emitted an `irregular` layout; worker was not
  reached.
- C: requirements and compact planning succeeded; both geometry attempts were
  rejected by the source identity contract; worker was not reached.
- D: requirements and compact planning succeeded; geometry was blocked by a
  Design Plan/source identity consistency mismatch; worker was not reached in
  this final run.
- E: requirements succeeded; both detailed-plan attempts failed Plan
  validation/provenance, including a missing standard-lookup variant record;
  worker was not reached.

The attempts used the configured Gemini API and current fast model. The
recorded provider latency range was approximately 1.97–69.87 seconds per
attempt, with usage retained in the JSON report. No candidate was promoted and
no misleading Current working version was created.

No worker, topology, artifact, snapshot, or promotion success is claimed in
this document until the isolated live report contains that evidence. A blocked
case remains useful and is classified by its actual stage.

## Safety boundary

## 2026-08-02 — exact project rerun after alias normalization

The persisted request from project `3a66a1b7-8f2b-4de4-8980-abf5132a3009` was
rerun without rewriting its original wording. The provider's second pattern
record was:

```json
{
  "pattern_id": "tray_slot_linear_pattern",
  "feature_id": "tray_slots",
  "count": 5,
  "direction": [0, 0, 1],
  "spacing_mm": 48.4
}
```

Normalization mapped the feature alias to the owning feature, mapped the
cardinal vector to `Z`, converted spacing to fixed millimeters, and converted
the numeric count to a fixed count. No exposed count or spacing control was
invented. The resulting Plan validated and the compact-plan attempt recorded
provider response received, Plan validation passed, and geometry generation
not yet attempted in its routing metadata. A nonblocking
`plan.pattern_alias_normalized` finding was retained.

The run then reached structured geometry generation and passed the existing
source contract. It stopped at the existing pre-execution design-artifact
consistency gate with:

```text
design_artifact.requirement_trace_failed
The approved Design Plan no longer preserves explicit user requirements.
```

The CadQuery worker was not reached, and no candidate, snapshot, export, or
Current working version was promoted. This is a later artifact-consistency
failure, not a pattern-normalization failure. The one-output Plan declared a
single primary printable component and its frame, handle, retention, tray
slots, skeletonized walls, and mounting holes as owned features; no component
reclassification was required for this rerun. The preserved blocked event now
records the failed generation attempt, `design_artifact_inconsistent` failure
class, `artifact_consistency` stage, provider/geometry/worker reach evidence,
and the blocking revision finding so diagnosis can identify the actual stop.

The result remains blocked accurately. No downstream policy was weakened.

Source safety, protected component/output identity, topology, functional,
artifact, and Current working version gates were not weakened. Configurable
patterns and exposed controls remain strict. The correction only prevents
ordinary one-off numeric semantics from being mistaken for reusable controls.

## Revision behavior

The deterministic revision envelope now derives affected and preserved
components/features/outputs from the requirement delta. Physical observations
without a requested correction are persisted without generation; a requested
physical correction produces a normal revision delta and preserves unrelated
requirements.

## Remaining limitations

Provider CadQuery syntax and geometry omissions may still block after planning.
Qualitative fit, retention force, and one-handed removal remain review or test
print evidence unless existing deterministic verification can measure them.

## Recommendation

Do not advance to advisory visual review from this matrix. The evidence still
shows compact/detailed planning and provider source interoperability as the
dominant bottleneck: only one earlier organizer run reached worker execution,
and the final comparable run reached none of the five workers. Continue with
compact/detailed planning and source-contract interoperability diagnosis,
keeping the existing safety, topology, functional, artifact, and promotion
gates unchanged.

## 2026-08-02 — requirement-trace classification rerun

The preserved latest Plan/source pair for project
`3a66a1b7-8f2b-4de4-8980-abf5132a3009` was reconstructed before changing
production behavior. The previous generic failure was caused by
`tray_capacity` being treated as a required Plan parameter even though the
Plan represented it as a fixed pattern count.

| Requirement | Plan feature | Source function | Output | Classification/result |
| --- | --- | --- | --- | --- |
| `tray_capacity` = 5 | `tray_slots` / `vertical_slot_pattern` | `apply_feature_tray_slots` | `print_tackle_tray_holder_body` | `geometry_verification_required`; deferred to `val_tray_capacity` |
| hold five 3600 trays | `tray_slots` | `apply_feature_tray_slots` | `print_tackle_tray_holder_body` | `source_or_geometry_trace`; source trace |
| integrated carrying handle | `carrying_handle` | `apply_feature_carrying_handle` | `print_tackle_tray_holder_body` | `source_or_geometry_trace`; source trace |
| tray retention | `tray_retention_lip` | `apply_feature_tray_retention_lip` | `print_tackle_tray_holder_body` | `source_or_geometry_trace`; source trace |
| top loading | `tray_slots` | `apply_feature_tray_slots` | `print_tackle_tray_holder_body` | `source_or_geometry_trace`; source trace and `val_fit_clearance` |
| skeletonized walls | `skeletonized_walls` | `apply_feature_skeletonized_walls` | `print_tackle_tray_holder_body` | `source_or_geometry_trace`; source trace |

The old `design_artifact.requirement_trace_failed` finding disappeared for
the preserved artifacts. The consistency result contains an original and a
normalized trace manifest, and the redacted debug bundle contains both files.
The sole printable component and single connected-solid output are consistent;
no tray-specific production branch was added.

The exact request was submitted unchanged twice after this correction. The
first fresh provider attempt was blocked earlier at compact Plan pattern
validation because the provider emitted incomplete linear/grid pattern
records. A second unchanged attempt passed Plan normalization and source
validation, reached the CadQuery worker, and produced one valid solid plus
STL, STEP, and BREP artifacts. Worker time was approximately 4.84 seconds.
The candidate remained blocked because the output was marked unavailable by
the existing printability/build-volume gate; the design-artifact result had
`pre_execution_passed=true`, with only the nonblocking
`design_artifact.geometry_verification_deferred` trace warning. No Current
working version, snapshot promotion, or export promotion was created.

This confirms the former trace block was misclassification. The remaining
block is downstream artifact/printability evidence, not a missing source trace.

## 2026-08-02 — final persisted-project rerun after trace correction

The exact request was submitted again to the existing project without changing
its prior revisions or history. The new run was:

- workflow: `7427a394-43cd-4e2d-a520-4b169f0e9e3f`
- revision: `9de063c6-b5a6-4bcd-af95-2328ff20c846`
- route: `compact_plan`
- provider response: received; source contract: passed
- stopping stage: `artifact_consistency`
- worker reached: no
- Current working version: unchanged

This provider Plan represented `tray_slots` and the single printable holder
component, but supplied neither a pattern record nor a validation target for
the explicit `tray_capacity = 5` count. The normalized trace therefore recorded
`tray_capacity` as `geometry_verification_required` with status
`geometry_verification_unmapped`. The blocking finding was the typed
`design_artifact.requirement_trace_unverifiable`, with the persisted explanation
that the requirement had no Plan feature or geometry-verification target.

The run retained the original and normalized trace manifests at the revision
metadata paths and exposed the same finding through workflow diagnosis at the
`artifact_consistency` stage. No candidate, worker artifacts, snapshots, or
exports were created. This is a genuine missing verification path in the new
Plan, distinct from the former generic requirement-trace misclassification;
the implementation does not invent a feature or verification capability to
make the request pass.
