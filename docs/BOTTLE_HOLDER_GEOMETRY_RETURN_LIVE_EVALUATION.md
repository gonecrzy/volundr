# Bottle-holder scaffold-owned geometry returns: live evaluation

Date: 2026-08-01  
Request: “Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.”

## Change under test

Commit `66ddde4` moves geometry-function return ownership into Volundr.
Gemini now supplies ordered `statements` and one `result_symbol`; Volundr
validates the symbol, verifies its assignment and shape path, and appends the
only return statement. Provider return statements are rejected.

The deterministic fixture and bounded repair path use the same contract.

## Exact live rerun

Command:

```text
backend/.venv/bin/python backend/scripts/run_live_bottle_holder_workflow.py \\
  --report /tmp/volundr-bottle-holder-return-live.json
```

Requirements and Design Plan progression passed. The Plan contained a
concrete retention strategy and a centered linear mounting pattern:

```text
mounting_screw_count
  -> screw_hole_linear_pattern_points
  -> intended mounting-hole geometry
```

The geometry stage used the v4 statements/result-symbol prompt. The missing
provider-return failure did not recur: deterministic return assembly advanced
far enough for the existing parameter-effect contract to evaluate the
assembled function.

## Result

The attempt was blocked because the generated geometry did not provide a
statically verifiable geometry effect for the protected
`mounting_screw_count` parameter. The current working version remained
unchanged and no misleading candidate was created.

The user-visible response was:

> Volundr could not create a valid new version. Your current working version
> is unchanged.

The worker and physical mounting-hole, floor, removal-direction, and
retention checks did not run because source/effect validation correctly
blocked the invalid geometry before worker execution.

This is a different failure from the previous missing component-shape return:
the scaffold-owned return contract corrected that defect, while the provider
still failed the existing semantic parameter-effect gate. No additional CAD
validator was added for this result.

## Routing decision

The accumulated evidence supports separating model responsibilities:

- requirements and Design Plan: current fast/low-cost Gemini model;
- CadQuery geometry and geometry repair: stronger Gemini model;
- deterministic parameter configuration: no AI.

This is an evidence-based routing recommendation, not a model comparison
result. Live design-quality testing remains separate from frontend usability
testing. Deterministic chat-first fixtures remain suitable for observed UX
testing; users should not judge live bottle-holder physical quality until a
run reaches worker and functional verification.
