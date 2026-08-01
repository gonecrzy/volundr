# Bottle-holder parametric-pattern live evaluation

Date: 2026-08-01  
Request: “Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.”

## Scope

This is the exact backend-only live diagnostic. It used the real Gemini API
provider, FastAPI services, and the configured CadQuery worker path. No
frontend or deterministic fixture was used.

Implementation under test: commit `1c73e10` (`Implement deterministic
parametric patterns`).

## Result

The run reached and passed automatic requirements extraction and Design Plan
validation. The persisted Plan contained a concrete retention strategy and a
generic centered linear mounting pattern:

```text
mounting_screw_count
  -> mounting_screw_pattern_points
  -> intended mounting-hole pushPoints operation
```

The recorded Plan specified:

- pattern type: `linear`
- count: `mounting_screw_count`
- spacing: `screw_vertical_spacing`
- arrangement axis: `Z`
- centered: `true`
- mounting plane: `XZ`
- wall-normal hole axis: `Y`

The current live attempt was then blocked during structured geometry-body
assembly because Gemini returned a component body without a required shape
return. The bounded body repair returned the same class of invalid body.
The attempt therefore did not reach source validation, the CadQuery worker,
or functional verification. No candidate was promoted and no misleading
Current working version was produced.

The user-visible result was:

> Volundr could not create a valid new version. Your current working version
> is unchanged.

This is a genuine provider geometry-body failure, distinct from the previous
hardcoded mounting-count failure. The pattern contract was not weakened.

## Evidence

Latest report:

`/tmp/volundr-bottle-holder-pattern-live-final2.json`

Latest workflow facts:

- action: `initial_design`
- stage: `blocked_attempt`
- requirements: passed after one provider retry
- Design Plan: passed
- pattern specification: persisted and normalized
- retention strategy: concrete `flexible_snap_arm`
- current working revision: none
- outputs: none
- worker execution: not reached because the structured body was invalid
- mounting-hole, floor, removal-direction, and retention checks: not run

The exact request was rerun after the deterministic pattern changes. One
intermediate provider response also returned an invalid Design Plan; it was
rejected by the Plan path and did not create a candidate.

## Interpretation

The scaffold now owns repeated-pattern arithmetic and canonical point
construction. Once a valid geometry body is supplied, the expected chain is
`count/spacing -> canonical pattern points -> pushPoints -> mounting-hole
geometry`, with count and spacing protected from provider replacement.

Live design-quality testing for this holder remains paused at the provider
geometry-body gate. Frontend UX testing remains independent and may continue
with the passing deterministic chat-first fixtures.
