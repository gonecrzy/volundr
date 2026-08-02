# Worker-Diagnostic Repair

Worker diagnostics are evidence about generated source execution, not evidence
that the requested geometry is physically correct.

## Eligible failures

Volundr may attempt one bounded repair when the traceback identifies:

- one provider-owned `_ai_...` function;
- one source statement;
- a source/runtime or CadQuery API/selector failure;
- a repair scope that can be checked against preserved function hashes.

Covered examples include unresolved names, selector parse errors, CadQuery
attribute errors, and localized CadQuery type errors involving a Workplane,
axis, or API call. The classifier is conservative and does not guess a
function when the traceback is ambiguous.

The same bounded path covers a localized `wires not planar` failure when the
trace identifies a provider function and pattern-consuming statement. It is
reported as `worker.pattern_points_not_planar_for_workplane` and receives the
pattern’s coordinate-space evidence; it is not converted into a functional
pass or a silent projection.

## Repair evidence

The repair request contains the exact traceback and statement, required feature
intent, allowed modules/helpers, protected identities, result-symbol contract,
and unaffected function hashes. The original source, repair prompt, provider
response, repaired body, repaired source, and second worker result are
immutable evidence.

At most one worker-diagnostic repair is attempted for an original generation.
An identical source hash is never repaired twice. If the repaired source still
fails, the attempt remains blocked and the original Current working version is
unchanged.

## Required-feature behavior

An optional proposal may be omitted only when the repair records that omission
and downstream evidence reflects it. An explicit requested feature cannot be
silently removed. Worker success still proceeds through topology, functional,
artifact, snapshot, and promotion gates.

## Current matrix evidence

In the final fixed matrix, the circular spacer reached the worker after a
localized geometry repair and became a working version. Other cases reached
the worker but exposed ordinary CadQuery API misuse such as unsupported
keyword arguments or invalid Workplane calls; those remained blocked where the
bounded repair did not produce a valid result.

## Non-goals

This is not a general CadQuery translator, selector replacement table, source
rewriter, visual critic, or unlimited retry mechanism.
