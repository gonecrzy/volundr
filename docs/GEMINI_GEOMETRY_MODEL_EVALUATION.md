# Gemini Geometry Model Evaluation

Date: 2026-08-01

## Routing architecture

Gemini routing is now resolved by prompt mode in `GeminiModelPolicy`, rather
than by scattered generation call sites. Requirements and Design Plan calls
use the fast-stage policy; structured CadQuery bodies and geometry-body repair
use their geometry-stage policies; revision planning remains on the planning
policy; and component geometry revisions use the component-revision policy.
Deterministic configuration does not call a provider.

Each `GenerationAttempt` stores redacted routing evidence: prompt mode,
provider, selected model, routing-policy version, routing reason, fallback
chain, actual provider model when reported, provider usage metadata, and
provider latency. The existing generation-attempt evidence API exposes these
fields for Technical details. The CAD worker receives only generated source,
parameters, and output requests; it does not receive Gemini credentials or
model policy.

Operational transport failures may retry once through the general configured
model when a stage-specific model was selected. Rate limits, timeouts, and
temporary service failures are recorded as `operational_fallback`. A
structured-body, source-contract, or parameter-effect failure is content
failure and is preserved as that attempt; it does not silently trigger a
model fallback. The existing bounded repair path remains explicit and is
routed to the geometry-repair model.

## Configured stage policy

The comparison used this temporary policy:

| Prompt mode | Model |
| --- | --- |
| requirements | `gemini-3.5-flash-lite` |
| design plan | `gemini-3.5-flash-lite` |
| CadQuery geometry bodies | comparison model |
| geometry-body repair | comparison model |
| revision planning | `gemini-3.5-flash-lite` |
| component revision | comparison model |

Unset stage values fall back to `VOLUNDR_GEMINI_MODEL`. The model identifiers
were checked against the configured account before the run. No model names or
credentials are sent to the browser or CAD worker.

## Frozen comparison inputs

The comparison loaded the latest successful upstream artifacts from
`/tmp/volundr-bottle-holder-return-live.json`:

- the exact user request;
- the persisted Design Specification;
- the persisted Design Plan and concrete retention contract;
- the source-authority inventory and parameter-effect manifest;
- the canonical repeated mounting-hole pattern;
- the deterministic scaffold and geometry-function obligations.

Requirements and planning provider calls were not repeated. The geometry
prompt, output-token allowance, temperature, thinking level, source authority,
scaffold, validators, parameters, and worker setup were held constant across
models. Each model received two geometry attempts.

## Models evaluated

- Fast baseline: `gemini-3.5-flash-lite`
- Stronger candidate: `gemini-3.5-flash`

## Controlled comparison result

| Model | Attempts | Structured response | Parameter effect | Scaffold | Worker reached | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `gemini-3.5-flash-lite` | 2 | 2/2 parsed far enough for effect validation | 0/2 | 0/2 | 0/2 | blocked: `mounting_screw_count` unverifiable |
| `gemini-3.5-flash` | 2 | 2/2 parsed far enough for effect validation | 0/2 | 0/2 | 0/2 | blocked: `mounting_screw_count` unverifiable |

The source body contract itself was reached: both models returned structured
geometry bodies with the required functions and scaffold-owned return shape
assembly could have proceeded. The unchanged parameter-effect gate rejected
both generated bodies before scaffold assembly because the mounting-hole
pattern still did not demonstrably depend on `mounting_screw_count`. The
stronger model was not accepted merely because it returned compilable-looking
body statements.

Provider observations:

- Fast attempts: provider latency approximately 2.6–3.6 seconds; total
  tokens approximately 19.3k.
- Stronger attempts: provider latency approximately 6.4–51.5 seconds; total
  tokens approximately 19.7k.
- No operational fallback occurred.
- No repair was invoked by the frozen comparison harness because the primary
  content failure was the protected parameter-effect gate.
- Worker, STEP/STL/BREP production, topology, and physical functional checks
  were not reached for either model.

The complete raw comparison record is the separately generated diagnostic
artifact `/tmp/volundr-gemini-geometry-comparison.json` and is intentionally
not committed because it contains provider-generated source material.

## Full chat-first rerun

The exact request was rerun with fast requirements/planning and
`gemini-3.5-flash` for geometry and geometry repair:

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving
> boat, with one-handed removal and two #8 mounting screws.

The run completed requirements and Design Plan progression. Its five recorded
provider attempts included fast requirements/planning, stronger geometry, and
stronger geometry repair. The primary geometry attempt and bounded repair
both failed the same semantic obligation. The final workflow state was:

- Current working version: unchanged (`null` in the isolated project);
- candidate: failed/blocked, with no misleading ready state;
- error: the mounting-hole pattern bypassed or did not verifiably depend on
  `mounting_screw_count`;
- worker execution: not reached;
- topology and mounting-hole/floor/removal/retention physical checks: not run;
- provider timing and token usage: persisted on each attempt.

The full rerun therefore confirms routing and observability, but does not
select `gemini-3.5-flash` as an acceptable geometry default. The repeated
failure is evidence that this model change alone has not solved the known
semantic geometry behavior; no new validator or prompt rule was added to
accommodate it.

## Recommendation

Keep the stage-specific routing infrastructure and use the fast model for
requirements, planning, and deterministic configuration. Do not promote the
tested geometry model based on this comparison. Live design-quality testing
for this holder remains paused until a geometry model consistently consumes
the canonical pattern and reaches worker/functional verification. Frontend
usability testing can continue with deterministic chat-first fixtures.

The next model experiment should use another stronger geometry-capable model
or a provider-side geometry strategy, with the same frozen-input protocol and
without weakening the existing semantic gate.
