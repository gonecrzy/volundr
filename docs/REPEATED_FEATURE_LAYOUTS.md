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
