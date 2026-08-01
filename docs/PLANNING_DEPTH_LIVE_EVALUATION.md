# Planning Depth Live Evaluation

## Status

Implemented in this pass as the evidence record. Live provider execution is
reported only when the configured provider and worker are available.

## Cases and expected routing

1. **Direct brief** — a single rectangular spacer plate with explicit width,
   height, thickness, holes, positions, corner radius, and one output. The
   semantic route is `direct_brief`; the planning-provider call count is zero.
2. **Compact plan** — a wall-mounted holder with fit, mounting, support,
   retention, motion, and one-handed removal requirements. The route is
   `compact_plan`; routine dimensions remain Volundr proposals.
3. **Detailed plan** — a two-piece enclosure with a removable lid, screws,
   cable opening, ventilation, and mounting posts. The route is
   `detailed_plan` because multiple printable components and mating relationships
   are present.

## Actual live evidence — 2026-08-01

The three cases were run through the opt-in Playwright harness with the real
Gemini API, FastAPI service, and CadQuery worker process. The configured
provider was `gemini_api / gemini-3.5-flash-lite`; no provider credential or
live data was sent to the browser or worker.

| Case | Route/plan evidence | Provider calls | Worker / final state |
|---|---|---:|---|
| Spacer plate | `direct_brief`; `cad-brief-v1`; deterministic brief; no planning-provider call | 2 (requirements, geometry) | Worker reached; STEP/STL/BREP produced; topology passed; accepted as Current working version with `ready_with_warnings` output state and `functionally_verified` revision status |
| Bottle holder | `compact_plan`; `compact-cad-plan-v1`; compact plan persisted | 3 persisted calls in the isolated run (one requirements failure, one requirements retry, one compact-plan call) | No worker result was produced. The attempt was returned as a truthful blocked outcome; the source-generation child was terminally failed by the shipped cleanup path. No Current working version was promoted |
| Two-piece enclosure | `detailed_plan` route selected on the successful retry; no plan record because provider validation failed | 4 persisted calls across the Playwright retry (requirements calls, two detailed-plan attempts) | Worker was not reached. The provider plan failed existing pattern/provenance validation; no candidate or Current working version was created |

The direct case is the successful route proof: its `DesignPlan` row uses the
`cad-brief-v1` discriminator, its workflow artifacts include the route
decision, brief, normalized GeometryExecutionContext, and prompt context pack,
and its source reached the worker without a planning-provider call. The
compact case persisted its distinct compact contract and the detailed case
retained the existing detailed-plan validation path; neither was promoted
after failure.

Provider latency evidence was persisted on every attempt. Representative
successful direct-run latencies were 51,558 ms for requirements and 56,232 ms
for geometry. The live harness data was preserved separately at:

- `/tmp/volundr-live-e2e.t7vcmL` — spacer/direct run;
- `/tmp/volundr-live-e2e.Zf5kBP` — holder/compact run;
- `/tmp/volundr-live-e2e.3DqO8d` — enclosure/detailed run.

These paths are local diagnostic evidence, not repository artifacts.

The live results also exposed and corrected one workflow issue: source-gate
exceptions had been returned as HTTP 409 from chat. They now remain in the
attempt and workflow records while the primary chat operation returns a
structured blocked outcome with the selected planning route and unchanged
Current working version.

Do not claim geometry or worker success when the live path is unavailable or a
source/geometry gate stops execution. Deterministic browser fixtures remain the
UX evidence track; these cases are design-quality evidence.
