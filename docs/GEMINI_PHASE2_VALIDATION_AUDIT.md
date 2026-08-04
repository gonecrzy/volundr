# Gemini Phase 2 validation audit

This is an offline audit of `gemini-profile-ablation-01`. It reads preserved
Phase 2 report and live-data files only. The audit made zero Gemini calls, zero
Ollama calls, zero worker calls, and ran no projects.

The preserved run contains ten operations and 35 provider records:

| Arm | Projects | Provider calls | Model identity |
|---|---:|---:|---|
| current-production | 5 | 20 | `gemini-3.5-flash-lite` |
| profile-b-sampling | 5 | 15 | `gemini-3.5-flash-lite` |

The five cases are `case-001`, `case-002`, `case-003`, `case-006`, and
`case-008`. Each reconstructed record contains requirements, clarification,
Plan, geometry, source, worker, artifact, topology, verification, candidate,
provider-call IDs, response identities, parse/normalization state, blocker,
furthest valid stage, and evidence paths. The authoritative records are in
`data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports/phase-2-project-reconstruction.json`.

## Corrected interpretation

Profile B is the safer requirement-handling candidate in case-001 because it
requested missing fit dimensions rather than inventing them. The harness did
not submit the frozen continuation facts, so that arm cannot be compared
end-to-end for this case. A valid clarification stop is not a profile failure.

Case-002 reached the source-contract boundary in both arms and shared the
ambiguous accessory-compartment requirement trace/provenance blocker. Case-003
reached topology in both arms but both preserved output manifests remain
blocked/stale. Current case-006 reached topology; Profile B reached the worker
and failed with a concrete CadQuery loft exception. Case-008 stopped at the
same Plan provenance validation boundary in both arms.

Worker reach and topology are separate metrics. A worker runtime failure is
useful downstream evidence but is not CAD success. The corrected aggregate is
in `phase-2-comparison-corrected.json`; the case table is in
`phase-2-case-comparison-corrected.json`.

## Decision

The audited decision is `corrected_second_validation_required`. Profile B
remains qualified by corrected offline Phase 1 evidence, but the focused Phase
2 comparison is not a fair, complete production decision because case-001 has
harness asymmetry and the historical worker-ready aggregation discarded
preserved evidence. The exact future design is documented in
`GEMINI_PROFILE_B_SECOND_VALIDATION_PLAN.md`.
