# Requirement Pipeline Audit

Status: Implemented in this pass. This is an implementation audit, not a new
workflow engine.

## Current call graph

```text
chat message
  -> deterministic explicit-requirement inventory
  -> requirements provider (when required)
  -> Design Specification normalization
  -> RequirementLedgerStore
  -> PlanningDepthRouter
  -> direct brief | compact Plan | detailed Plan
  -> Plan normalization and GeometryExecutionContext
  -> requirement trace manifest
  -> source-authority/consistency gates
  -> CadQuery source and worker
  -> topology, functional, artifact, snapshot, and requirement evidence
  -> candidate/promotion decision
  -> chat outcome and frontend workspace
```

Revision messages first produce a requirement delta and may also create a
physical-test observation. The same ledger, planning, execution, and
promotion path is then reused. The chat-first service owns orchestration;
staged/debug endpoints remain compatibility callers and do not own a second
lifecycle.

## Semantic coverage matrix

| Requirement concept | Extraction form | Ledger form | Plan form | Trace rule | Verification stage |
| --- | --- | --- | --- | --- | --- |
| exact dimension | typed value/unit | `kind=dimension`, `operator=exact` | proposal/value or brief constraint | geometry target unless exposed | worker geometry |
| minimum dimension | comparator/typed value | `minimum` or `at_least` | value and operator | geometry target | worker geometry |
| maximum dimension | comparator/typed value | `maximum` | value and operator | geometry target | worker geometry |
| numeric range | two typed bounds | `range` | bounds | geometry target | worker geometry |
| exact count | count phrase | `kind=count`, `exact` | fixed layout/count | geometry target | worker geometry |
| minimum capacity | capacity phrase | `capacity`, `at_least` | capacity feature | typed unique link | worker geometry |
| maximum capacity | “up to” phrase | `capacity`, `up_to` | capacity feature | typed unique link | worker geometry/human review |
| supported occupancy range | range phrase | `capacity`, `range` | layout/feature | typed unique link | worker geometry |
| feature presence | functional phrase | `feature`, `present` | feature/owner | source or geometry trace | worker or review |
| feature absence | “without/no longer needs” | `feature`, `absent` | absence/negative constraint | source/geometry evidence | worker/review |
| fit/clearance | fit phrase/value | typed kind/operator | feature and target | geometry target | worker geometry |
| spacing/position | typed layout/value | typed kind/operator | layout/target | geometry target | worker geometry |
| orientation/containment | typed functional phrase | typed kind | relationship/target | source or geometry trace | worker/review |
| support/retention/access | functional phrase | typed behavior | feature/relationship | source or geometry trace | worker/review |
| process constraint | print/process phrase | process requirement | output/process | source/output trace | source/artifact/review |
| qualitative behavior | typed functional phrase | `qualitative` | feature/relationship | human review unless provable | review/test print |
| Volundr proposal | deterministic/provider proposal | non-explicit proposal source | proposal field | not a user obligation by itself | review/verification |
| exposed reusable control | explicit request | exposed-control declaration | protected parameter | strict source trace | source plus regeneration |

## Legacy boundaries

Modern direct, compact, and detailed paths treat the ledger as authoritative
and ordinary values as implementation-flexible. `validate_design_plan_trace`
and strict parameter identity checks remain available for legacy/staged
fixtures and are activated for explicit exposed controls or an explicit strict
contract. Ordinary plans with `exposed_controls=[]` do not require every Plan
number to appear as a generated source parameter.

The source safety and structured-body contracts remain active in every route.
The distinction is only between requirement meaning and optional source
representation.

## Corrections made

- capacity semantics now preserve `up_to`, `at_least`, exact, and range;
- semantic fields are persisted and normalized when legacy type labels remain;
- generic feature presence/absence semantics are retained;
- product-vocabulary token scoring is not authoritative;
- a uniquely typed feature/target relationship can normalize without provider
  bookkeeping;
- a measurable requirement can create a deferred verification obligation;
- original and normalized trace evidence remain separate;
- exposed-control and execution-critical trace failures remain blocking;
- worker failures are not masked by downstream trace findings.

## Exact project evidence

The prior generation-ready artifact for project
`3a66a1b7-8f2b-4de4-8980-abf5132a3009` now resolves the provider alias
`req_tray_capacity` to canonical `tray_capacity`, links it to `tray_slots` and
`val_tray_capacity`, and preserves `operator=up_to`. The earlier worker run
reached CadQuery and stopped at `ValueError: Null TopoDS_Shape object` in the
provider tray-slot feature; it did not produce a candidate or artifacts.

The fresh exact-message replay on 2026-08-02 was provider-successful but asked
for missing standard 3600-tray dimensions during requirements extraction. It
is preserved as an input clarification, not misclassified as a trace failure.

## Remaining limitations

The current geometry verifier cannot prove every qualitative behavior or
maximum-capacity claim from source metadata alone. Such evidence remains
explicitly uncertain and must not be presented as a deterministic pass.
