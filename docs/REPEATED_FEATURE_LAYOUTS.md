# Repeated Feature Layouts

Status: Implemented in this pass.

Repeated features describe the geometry requirement, not an automatic promise
of future configurability.

| Mode | Meaning | Parameter IDs required? |
| --- | --- | --- |
| `fixed_positions` | Approved one-off positions and count | No |
| `proposed_positions` | Volundr/provider-proposed positions and count | No |
| `uniform_linear` | Even linear distribution | Only for exposed count/spacing controls |
| `rectangular_grid` | Numeric row/column grid | Only for exposed row/column/spacing controls |
| `circular` | Numeric count/radius/angles or explicit irregular angles | Only for exposed controls |
| `distributed_within_region` | Count distributed within a named region | No, unless explicitly exposed |
| `derived_custom` | Approved derived layout relationship | Only when that relationship is protected |

The plan must retain the owning feature and component, count when known, axis
or plane, orientation, and positions or proposal guidance. Fixed and proposed
layouts may use numeric spacing as a disclosed proposal, but a missing spacing
control is not a plan error. Irregular explicit positions do not imply uniform
spacing.

`configurable_pattern` behavior remains strict. Exposed controls and protected
relationships still require deterministic source-effect evidence and canonical
pattern use. A fixed two-hole request is verified by count, positions,
orientation, diameter, and intersection after execution; it is not required to
regenerate three holes when a count was never exposed.

Pattern normalization records aliases and safe owner/layout interpretation. It
does not invent user-critical positions, multipart ownership, or reusable
controls.

## Provider aliases

Compact and detailed Plan normalization accepts equivalent one-off fields when
they are unambiguous:

- `feature_id` maps to the canonical owning-feature field;
- `direction` maps to `X`, `Y`, or `Z` only for an exact cardinal vector;
- `spacing_mm` maps to fixed millimeter spacing;
- numeric `count` maps to a fixed count.

When fixed count, fixed spacing, and a cardinal direction are all present, a
missing pattern type may be inferred as `linear`. A non-cardinal direction,
conflicting layout fields, missing owner, or unknown owner remains a typed
blocking Plan finding. Fixed layouts do not require count or spacing parameter
IDs.

## Placement coordinates

Every resolved layout also declares `coordinate_space`, `coordinate_frame_id`,
point dimensionality, arrangement axis, and intended consumer. See
[Pattern Coordinate-Space Contract](PATTERN_COORDINATE_SPACE_CONTRACT.md).
Component-local and world-space placements are not workplane-local
`pushPoints()` inputs; they must be transformed safely or constructed with
placed cutters.
