# Pattern Coordinate-Space Contract

Status: Implemented 2026-08-02.

Repeated-feature points are geometry placements, not interchangeable tuples.
Every canonical pattern declares its coordinate space, frame, dimensionality,
arrangement axis, and intended consumer. The declaration is retained in the
normalized Plan, GeometryExecutionContext, scaffold manifest, prompt context,
and source/worker evidence.

## Coordinate spaces

- `workplane_local_2d`: the two in-plane coordinates accepted directly by
  `pushPoints()`.
- `workplane_local_3d`: three coordinates in the current workplane frame;
  direct `pushPoints()` use is valid only when every normal coordinate is zero.
- `component_local_3d`: placements in the owning component frame.
- `world_3d`: placements in the project/world frame.

Component- and world-space points must not be passed directly to a planar
CadQuery consumer. They require a known, unambiguous transform, a compatible
workplane, or per-placement cutter/workplane construction.

## `pushPoints()` and coplanarity

Volundr records the consuming workplane when it is statically visible, such as
`faces(">Z").workplane()` or an explicit plane. A point set is accepted when it
is local 2D or local 3D with zero normal coordinate. Varying normal values
produce `geometry_body.push_points_nonplanar`. Direct component/world use
produces `geometry_body.pattern_coordinate_space_mismatch`.

The validator never fixes a failure by dropping one coordinate or projecting a
point onto a plane. It records the original points, workplane frame, pattern
identity, and blocking decision.

## Safe conversion and placement

Component/world points may be converted to local 2D only when both source and
consumer frames are known, the transform is unambiguous, and every transformed
point lies in the consumer plane within tolerance. Original and transformed
points retain order and are persisted with a stable pattern hash.

When points are non-coplanar in one consumer plane, valid strategies are:

1. select a host plane that genuinely contains the arrangement;
2. create and place a cutter at each component-local placement;
3. create a separate workplane/feature at each valid placement.

The provider receives the approved strategy set and may choose among them, but
may not relabel component-space points as workplane-local points.

## Worker CadQuery API contract

The CAD worker is pinned to CadQuery `2.8.0`. The supported placement path for
nonplanar component-local patterns is the scaffold-owned
`place_pattern_cutters(profile, points, coordinate_space="component_local_3d")`
helper. It translates a validated profile to each canonical point and returns
a Workplane suitable for `cut()` or `union()`.

`Workplane.translate((x, y, z))`, `union()`, and `cut()` are supported in this
contract. `Workplane.assembly()` is not a CadQuery API. `cq.Assembly()` is an
assembly container and must not be returned directly as a printable output or
used as a boolean cutter without conversion to a supported shape. The worker
records the installed CadQuery version in each execution manifest so API
diagnostics are reproducible.

Placed cutter profiles must already be volumetric `Solid` or `Compound` shapes;
the helper rejects a bare 2D wire before it reaches a boolean. The worker also
limits OpenBLAS, OMP, MKL, NumExpr, and VTK thread pools to the bounded worker
budget. A CAD timeout sends a graceful process-group termination first and a
forced process-group kill after a short grace period, so a native OpenCascade
call cannot strand the worker indefinitely.

Live evidence (2026-08-02): the preserved tackle-tray attempt first failed on
an unavailable `Workplane.assembly()` path, then on a worker thread-budget
exhaustion while using a placed-cutter boolean. With the pinned API, a
volumetric profile, bounded thread pools, and the cleanup path, the same source
completed in the worker in 0.42 seconds and the real-provider rerun completed
in 4.57 seconds with one valid solid and STL/STEP/BREP artifacts. Promotion
remained blocked by the existing build-volume and mounting-requirement gates;
no CAD API failure was masked as a pass.

The CAD-first policy is now explicit: `profile.build_volume` remains measured
and persisted evidence, but an oversized model is an advisory warning rather
than a promotion blocker. A user can review, export, split, reorient, scale,
or select a larger printer profile. Topology, source, artifact, and functional
requirements remain blocking when they fail.

## Repair and findings

The geometry prompt identifies the pattern, owner, frame, canonical points,
and consumer rules. A localized worker traceback containing `wires not planar`
is classified as `worker.pattern_points_not_planar_for_workplane` when the
function and pattern can be identified. One bounded repair may change that
function only; identical repaired source is not retried.

Coordinate findings are source/geometry-construction evidence, not functional
or topology findings. A source rejection prevents worker submission. A worker
failure remains blocked and cannot promote a candidate.

## Non-goals

This contract does not add product-specific pattern code, force every pattern
to be parametric, choose one workplane globally, or weaken downstream
geometry, topology, functional, artifact, snapshot, or promotion gates.
