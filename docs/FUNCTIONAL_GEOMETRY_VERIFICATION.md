# Functional Geometry Verification

Functional verification is a registry of conservative deterministic verifiers
over executed mesh/B-Rep evidence. It does not replace structural CAD
validation, topology, or printability checks.

Current registry entries:

- mounting-hole direction, count, diameter, and arrangement spacing where the
  interface supplies measurable values;
- support-floor presence and minimum-floor evidence at the containment center;
- supported axis-aligned removal-direction validation.

An absent or unmeasurable critical interface is not silently treated as a
pass. It produces a blocking violated or unverifiable finding. The verifier
uses stable plan identities and axes, never product names. Human review may
still be required for one-handed release, load certification, arbitrary motion,
and complex retention behavior.

Source authority additionally checks that protected or explicitly functional
parameters reach geometry operations, loop/pattern counts, or approved helper
geometry. A decorator alone does not prove feature implementation; required
feature builders must be invoked.

Results are persisted with geometric analysis findings and contribute to the
revision's separate `functional_status`. Repeated analysis produces new
evidence rather than replacing prior workflow artifacts.
