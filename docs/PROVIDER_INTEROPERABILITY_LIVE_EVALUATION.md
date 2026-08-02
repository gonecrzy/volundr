# Provider Interoperability Live Evaluation

Date: 2026-08-02

This report records the final fixed five-case rerun after `b313df3` and the
focused interoperability corrections in this checkout. The run used the real
Gemini provider, FastAPI services, and CadQuery worker. It did not compare
models or change the user prompts between cases.

## Repository and evidence

- Matrix report: `/tmp/volundr-provider-interoperability-rerun-6.json`
- Geometry prompt used by that run: `cadquery-geometry-body-v7`
- The current prompt constant is v8 after the generic contract wording update;
  the v8 bump was not used to rewrite the recorded evidence.
- Requirements, Plan/brief, normalized context, prompt pack, provider output,
  repairs, source findings, worker results, artifacts, and candidate state are
  retained under each isolated live project.

## Failure reconstruction

| Case | Route | Final stage | Result | Responsible evidence |
|---|---|---|---|---|
| Circular spacer | `direct_brief` | worker/source repair | Working version | The provider body initially failed a geometry-body contract; a bounded repair produced executable geometry. Earlier frozen evidence also localized an invalid CadQuery selector. |
| Irregular bracket | `compact_plan` | worker/artifact gates | Working version | Compact plan and integral-rib ownership normalized correctly; the final source executed and passed promotion gates. |
| Bottle holder | `compact_plan` | focused Plan repair | Blocked attempt | The repair changed an unaffected layout, so preservation protection correctly stopped generation. No candidate was created. |
| Organizer | `compact_plan` | worker/execution or artifact consistency | Blocked attempt | The Plan passed, but generated CadQuery used an unsupported API form (`Workplane.box(..., combined=...)`) in the preceding execution evidence; the final attempt remained blocked with an approved-plan/generated-model mismatch. |
| Two-piece enclosure | `detailed_plan` | worker execution | Blocked attempt | Detailed Plan validation passed and geometry generation began. Worker evidence identified unsupported CadQuery usage (`workplane(..., centerPoint=...)`); no candidate was promoted. |

The failures are not one failure class. A and B demonstrate contract
interoperability can reach execution. C is a focused repair-preservation
failure. D and E are provider-generated CadQuery API/execution failures after
the Plan boundary. The matrix does not justify a model comparison yet.

## Contract-manifest evidence

Every source-generation attempt now persists `provider-contract-manifest-v1`.
The manifest records:

- approved component, feature, owner, role, and printable-output IDs;
- fixed, proposed, irregular, or configurable layout semantics;
- exposed controls and protected identity IDs;
- exact geometry-function inventory when available;
- permission for provider-local implementation names;
- prohibited provider-created identities;
- Plan, geometry-function, and worker repair boundaries;
- a stable manifest hash included in workflow/artifact evidence and prompt
  context.

This makes it possible to distinguish a missing instruction from a provider
violation. In the bracket case the manifest preserves integral rib ownership;
in the enclosure case it allows a fixed/proposed repeated layout without
inventing a spacing control.

## Focused Plan repair

Plan repair is now feature/relationship scoped. Its input includes the
rejected Plan, normalized findings, existing valid IDs, affected feature and
layout IDs, allowed layout alternatives, and prohibited changes. A comparison
records preserved, changed, removed, added, resolved, and repeated fields.

Equivalent layout aliases are compared by execution meaning, but an actual
change to an unaffected layout remains blocking. The bottle-holder result is
the intended safety behavior: the repair did not preserve an unaffected
layout, so the attempt stopped before geometry generation.

## Geometry-body repair

Geometry repair receives one affected provider function, its scaffold-owned
signature and symbol inventory, the exact finding, and hashes for unaffected
functions. It cannot change the Plan, requirements, identities, outputs,
exposed controls, or scaffold signature. The circular spacer reached a valid
working version through this bounded path.

## Worker-diagnostic repair

Worker diagnostics now classify localized provider-owned CadQuery failures
before downstream artifact-consistency early returns. The classifier records
the exception, function, source statement, traceback, and repair eligibility.
The generic TypeError path covers localized CadQuery API misuse without a
hardcoded selector replacement. One worker-diagnostic repair is allowed per
original generation and identical source hashes are not retried.

The matrix demonstrated both sides of the policy: a localized source repair
can recover a design, while unsupported provider CadQuery calls remain blocked
when a safe repaired result is not available. Runtime success never bypasses
topology, functional, artifact, snapshot, or promotion gates.

## Provider usage and timing

The preserved report contains per-attempt provider, model, prompt version,
request ID, token estimates, provider latency, total attempt duration, failure
class, and resulting revision. In the final rerun, the complete case wall
times were approximately 12.7 s (A), 23.1 s (B), 10.1 s (C), 13.8 s (D), and
43.5 s (E). Requirements/planning retries and repairs are represented as
separate attempts rather than hidden in one duration.

## Threshold result

The implementation threshold was met for the interoperability question:

- at least two compact cases reached the worker (bracket and organizer
  evidence; the bracket promoted and the organizer was blocked after
  execution);
- the detailed enclosure passed Plan validation and reached geometry
  generation/worker execution;
- the circular spacer reached valid geometry after bounded repair.

Promotion was intentionally not required. Only the spacer and bracket became
Current working versions in the final rerun. The remaining blocked cases did
not replace a Current working version and did not create misleading exports,
snapshots, or topology claims.

## Remaining blocker and recommendation

The dominant remaining issue is provider-generated CadQuery API reliability
after a clear Plan and source contract, with a separate focused Plan repair
preservation defect for the bottle-holder case. The next step should be a
small, evidence-driven repair or provider-quality investigation. A stronger
model comparison is justified only after the same frozen contract reaches the
provider and the localized repairs cannot resolve repeated runtime failures.

Observed frontend usability testing may proceed with deterministic fixtures.
Live CAD-quality testing should continue through this fixed matrix until
compact and detailed worker reliability is materially better.

## 2026-08-02 — Tackle-tray pattern coordinate-space rerun

The preserved project `9bebb910-9967-4148-88a4-457756639c2e` was rerun without
deleting earlier attempts. Its compact Plan defines `tray_slot_pattern` for
`tray_slots` on `tackle_tray_holder_body`, with five component-local 3D points
along Z in `root_frame`. The provider consumed those points through
`pushPoints()` on a Z-facing workplane, first directly and then through a
list-comprehension that dropped the Z coordinate.

The first post-contract run reached the worker. CadQuery completed, but the
result was correctly blocked after execution because the output had
disconnected solids and the wall-mount requirement was not satisfied. No
Current working version, snapshot, or export was promoted from that attempt.

The subsequent rerun and one bounded geometry repair were stopped before the
worker by `geometry_body.pattern_coordinate_space_mismatch`. The source
contract evidence records the original component-local points, `root_frame`,
the consuming `pushPoints()` statement, and the Z workplane. Dropping the
normal coordinate was not treated as a safe conversion. This is the intended
new failure boundary: the provider must choose a compatible plane, perform a
verified frame conversion, or place separate cutters.

The rerun did not create a candidate or alter the Current working version.
The worker was not reached on the final source-contract attempt, so there is
no new topology, snapshot, artifact-readiness, or physical-function pass to
claim. The exact blocker remains provider geometry construction, not Plan
semantics, requirement tracing, or promotion policy.

The same project’s chat ledger was corrected without destructive history
rewriting: the initial request is rendered once, the legacy workflow
instruction is an internal event, and `wall mounted` is persisted as explicit
`clarification_user` evidence linked to its clarification question, answer,
and project message.
