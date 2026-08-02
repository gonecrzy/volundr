# Bottle-Holder Scaffold Live Evaluation

## Scope

This evaluation used the exact request below with the configured Gemini API
provider and the isolated CadQuery worker. No construction dimensions were
added by the operator.

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving
> boat, with one-handed removal and two #8 mounting screws.

The run was performed against a fresh SQLite database under
`/tmp/volundr-bottle-live-scaffold-final`. Evidence is retained there rather
than committed to the repository.

## Result

The run did not reach source generation or the CadQuery worker. It was blocked
while validating the Design Plan after requirements clarification. This is a
planning/provenance failure, not evidence against the deterministic source
scaffold.

The relevant workflow was:

- project: `c410f395-fb4e-4ff0-ac47-73f6b432eb50`
- root workflow: `14c95bf4-a106-4741-adfa-ea3f7bb09e45`
- clarification child: `dd5a8255-c344-4b89-b5ac-1cb32b278322`
- Design Plan child: `71ea0da5-dc51-4a50-bdcb-0a7b2e5812c6`

The Design Plan retries returned parameters linked to direct requirements but
with calculated values:

- `bottle_inner_diameter=81.8` linked to user requirement
  `bottle_diameter=81`
- `fastener_size=4.2` linked to user requirement `fastener_size=8`

The validator correctly rejected both and instructed the provider to model
them as derived parameters. The plan child therefore terminated as failed.

## Scaffold implementation status

The deterministic CadQuery scaffold is implemented behind
`cadquery-scaffold-v1`:

- Volundr owns canonical parameter declarations.
- Volundr owns component, feature, and output registrations.
- Volundr owns the `build(params)` entrypoint and product structure.
- Gemini receives only the expected geometry function bodies.
- Provider output is rejected if it adds imports, registrations, decorators,
  unknown functions, or missing functions.
- Scaffold-owned source regions carry a fingerprint and cannot be changed by
  geometry-body repair.

The live run stopped before this contract was exercised. No source, worker,
topology, printability, functional-verification, or candidate artifacts were
created in this run.

## Timing instrumentation

The worker now persists function timing, supported CadQuery operation timing,
shape complexity before instrumented operations, per-output export timing, and
partial timeout diagnostics. No timeout occurred in this run, so there is no
new operation-level timeout evidence to classify.

Earlier retention evaluations still contain the prior worker timeout evidence;
those runs predate this scaffold path and are not conflated with this result.

## Decision

Observed user testing remains paused. The source scaffold is covered by
deterministic tests, but a live bottle-holder candidate has not yet reached
physical verification. The next narrow reliability task is to correct the
generic Design Plan provenance/repair failure so calculated values are emitted
as derived parameters, then rerun the exact request through the scaffold.
