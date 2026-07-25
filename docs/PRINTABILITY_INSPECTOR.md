# Printability Inspector

This document defines the Stage 7 orientation-aware printability inspection behavior.

The inspector gives practical warnings for the current model orientation and a configurable printer profile. It does not produce a printability percentage and must not claim a successful print is guaranteed.

## Default Printer Profile

Initial default profile:

```yaml
profile_version: printability-fdm-v1
printer_name: Generic FDM 256
process: FDM
material_behavior: general PLA/PETG
build_volume:
  x_mm: 256
  y_mm: 256
  z_mm: 256
nozzle_diameter_mm: 0.4
default_layer_height_mm: 0.2
```

The browser may expose editable profile fields. A user-provided profile can use the same shape, for example:

```yaml
printer_name: Bambu Lab H2C
build_volume:
  x_mm: 325
  y_mm: 320
  z_mm: 320
nozzle_diameter_mm: 0.4
default_layer_height_mm: 0.2
```

## Result Severities

Every rule returns one of:

```text
Pass
Notice
Warning
Critical
```

Each result must include:

- severity
- rule identifier
- detected value and units
- affected geometry count or area when available
- plain-language explanation
- suggested correction
- whether the result depends on orientation
- whether the user dismissed it intentionally

Results are advisory. They describe risks and likely corrections, not print guarantees.

## Rules

The inspector should evaluate:

1. Empty or zero-volume mesh
2. Non-watertight geometry
3. Disconnected components
4. Components or geometry beginning above the build plate
5. Geometry below the build plate
6. Small build-plate contact
7. Minimum wall or local feature thickness
8. Small positive features, gaps, and holes
9. Overhangs, using surface angle above the build plate
10. Horizontal bridge spans
11. Unsupported ceilings and inaccessible cavities where detection is reliable
12. Build-volume violations

## Thresholds

Thresholds must live in versioned configuration, not scattered through UI or service code.

### Wall and Feature Thickness

For a 0.4 mm nozzle:

- Critical below 0.40 mm
- Warning from 0.40 to below 0.80 mm
- Notice from 0.80 to below 1.20 mm
- General pass at 1.20 mm or greater
- Recommend 1.60 mm or greater for ordinary functional parts

Thresholds scale from nozzle diameter:

```text
critical = 1.0 * nozzle_diameter_mm
warning = 2.0 * nozzle_diameter_mm
notice = 3.0 * nozzle_diameter_mm
functional_recommendation = 4.0 * nozzle_diameter_mm
```

### Overhang Surface Angle

Measured as surface angle above the horizontal build plate:

- Pass: 60-90 degrees
- Notice: 45-59 degrees
- Warning: 30-44 degrees
- Critical or support likely: below 30 degrees

### Bridge Spans

- Pass: up to 5 mm
- Notice: over 5 through 15 mm
- Warning: over 15 through 30 mm
- Strong warning: over 30 through 50 mm
- Critical or support recommended: over 50 mm

## Initial Heuristic Limits

Some printability checks are reliable from an STL, while others are estimates. The initial implementation should be conservative:

- Build volume, build-plate Z position, zero volume, watertightness, component count, and bounding-box based contact are reliable enough for direct warnings.
- Overhangs can be estimated from face normals and face area in the current orientation.
- Bridge spans and unsupported ceilings can be detected only for simple horizontal downward-facing faces; otherwise report that only reliably detected cases were evaluated.
- Minimum wall/local feature thickness can start from conservative local proximity or bounding-box heuristics and should disclose that the result is an estimate.
- Inaccessible cavities should be reported only when detection is reliable. Otherwise the inspector should avoid claiming the model has no inaccessible cavities.

## Highlighting

The viewer should highlight affected geometry where practical. Initial highlight targets may include:

- build volume or Z-bound violations
- build-plate contact area
- overhang face regions
- detected bridge or ceiling regions

Highlighting is supporting evidence for the textual result. The textual result remains authoritative.
