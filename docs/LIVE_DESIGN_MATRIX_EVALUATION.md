# Live Design Matrix Evaluation

Date: 2026-08-02

This is a diagnostic evaluation of the real Gemini API, FastAPI workflow, and
CadQuery worker. It is not a quality benchmark and no blocked candidate was
promoted. The second matrix run used the ordinary-plan source-contract
correction from `23d58ab`; prompts, validation gates, and provider model were
otherwise unchanged.

Provider: `gemini_api`, `gemini-3.5-flash-lite`
Prompt versions: `requirements-v3`, `compact-cad-plan-v1`, `design-plan-v6`,
`cadquery-geometry-body-v7`, `cadquery-geometry-body-repair-v7`
Clarification questions: none were presented in these runs.

## Summary

| Case | Route | Provider attempts | Worker | Result |
|---|---|---:|---|---|
| A circular spacer disk | direct_brief | 4 | reached | CAD selector syntax failure; blocked |
| B irregular bracket | compact_plan | 4 | not reached | planned rib components missing from source; blocked |
| C bottle holder | compact_plan | 3 | not reached | malformed pattern specification; blocked |
| D organizer | compact_plan | 5 | not reached | provider-added unapproved parameter identities; bounded source rejection |
| E two-piece enclosure | detailed_plan | 4 | not reached | detailed plan repeated missing pattern spacing; blocked |

All cases ended with no Current working version. The failed attempts and
provider evidence remain persisted in their isolated evaluation roots.

## A — Direct circular spacer disk

Prompt:

> Create a circular spacer disk 60 mm in diameter and 5 mm thick. Add a 12 mm
> centered through-hole and three 4 mm mounting holes positioned at irregular
> polar angles of 20, 145, and 265 degrees on a 42 mm bolt circle. Add a 1 mm
> chamfer to the outside top edge.

The router selected `direct_brief`, as expected. Requirements initially needed
one provider retry (`requirements-v3` failed once, then passed); no planning
provider call was made. Geometry generation and repair ran. The worker was
reached and produced a revision/output record, but CadQuery failed while
parsing the provider's selector expression:

```text
Expected end of text, found 'and' in >Z and not outer_d
```

The required output was not ready, topology metadata was absent, and the
candidate was blocked. This is a provider CadQuery statement defect, not a
route or artifact-promotion defect. No snapshots or export became available.

## B — Irregular bracket

Prompt:

> Create an L-shaped bracket with a 90 mm horizontal shelf, a 70 mm vertical
> mounting face, and 5 mm wall thickness. Add three 5 mm mounting holes to the
> vertical face. Place the lower hole 12 mm to the right of the vertical center
> line, the middle hole on the center line, and the upper hole 8 mm to the left
> of the center line. Add two triangular reinforcement ribs between the shelf
> and mounting face.

The router selected `compact_plan`. Requirements retried once. The compact
plan was valid enough to reach structured geometry, but it introduced
`comp_rib_left` and `comp_rib_right` without matching CadQuery source
components. The design-artifact consistency gate reported both missing
components and a failed explicit-requirement trace. The worker was not
submitted, and no artifacts or snapshots were generated.

The irregular hole positions were not rejected for being irregular; the block
was the plan/source identity mismatch.

## C — Compact bottle holder

Prompt:

> Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat,
> with one-handed removal and two #8 mounting screws.

The router selected `compact_plan`. Requirements retried once and the compact
plan provider call succeeded. The plan was then rejected during deterministic
pattern normalization because it contained a `vertical_screw_pattern` with an
empty owner and unsupported pattern type. The worker was not reached.

The earlier matrix run had also exposed an ordinary source-parameter false
positive for this case. The modern-plan correction removed that overrestriction;
the rerun shows the remaining failure is genuinely in the provider's compact
pattern record, not in ordinary numeric source sensitivity.

## D — Compact organizer

Prompt:

> Create a desktop organizer tray that is 180 mm wide, 120 mm deep, and 35 mm
> tall. Divide it into four compartments: two equal compartments across the
> rear half and two unequal compartments across the front half, with the
> front-left compartment 60 mm wide. Use 2.5 mm walls, a flat 3 mm base, and
> 6 mm outside corner radii.

The router selected `compact_plan`. Requirements retried once, the compact plan
passed, and geometry generation was attempted twice. Both source attempts
were rejected before execution for adding unapproved identities:

```text
derived_front_right_width
derived_rear_compartment_width
```

These are source-contract identities not present in the approved plan. This is
an identity/contract failure, not a requirement for all ordinary dimensions to
be parametric. No worker or artifact was produced.

## E — Detailed two-piece enclosure

Prompt:

> Create a two-piece enclosure for a 100 mm by 65 mm by 24 mm electronics
> board. Provide 1 mm clearance around the board. Use a removable lid secured
> with four M3 screws, a 16 mm by 10 mm cable opening centered on the left side
> and positioned 8 mm above the internal floor, twelve ventilation slots on the
> top, and four 3 mm internal mounting posts located 5 mm from each board
> corner. Use 2.5 mm walls and a 3 mm base.

The router selected `detailed_plan`. Requirements retried once. Detailed plan
generation failed twice with the same semantic contract error:

```text
pattern ventilation_slot_pattern requires spacing_parameter_id
```

No detailed plan, worker execution, artifacts, or snapshots were produced.
The detailed path remains appropriately strict for a multipart assembly, but
the repeated provider output identifies a plan-schema/prompt interoperability
problem for repeated features.

## Per-attempt evidence

The attempt counts and provider latency ranges were:

| Case | Prompt-version sequence | Latency per attempt (ms) | Worker time |
|---|---|---:|---|
| A | requirements, requirements, geometry, repair | 3271, 3289, 1863, 1877 | worker reached; CAD failure |
| B | requirements, requirements, compact, geometry | 2997, 2767, 6233, 3871 | not reached |
| C | requirements, requirements, compact | 1945, 1863, 4702 | not reached |
| D | requirements, requirements, compact, geometry, geometry | 2467, 2512, 4193, 2938, 2630 | not reached |
| E | requirements, requirements, detailed, detailed | 3628, 3456, 16436, 15463 | not reached |

Prompt and output token counts are preserved in each isolated report under
the `generation_attempts` records. The provider reported the same configured
model for every attempt; no model comparison was performed in this pass.

## Conclusion

Direct routing is working and can reach the worker, but provider CadQuery
syntax still blocks this direct variant. Compact cases are currently dominated
by plan/source identity contracts. The detailed case is dominated by repeated
pattern-plan validation. No change to topology, functional, artifact, or
promotion gates is justified by this matrix.
