# Requirement-Driven Revision Live Evaluation

Date: 2026-08-01  
Request: “Create a wall-mounted holder for an 81 mm bottle, suitable for a
moving boat, with one-handed removal and two #8 mounting screws.”

## Previous overrestriction

The previous live path treated numeric Design Plan values as source-level
parameter obligations. It blocked ordinary generated geometry when the source
did not reference names such as `holder_inner_diameter` or
`mounting_hole_diameter`, even though the user had not requested reusable
controls. This confused a requirement about the resulting part with an
implementation preference.

## Revised product principle

Every design remains revisionable through chat. Parametric controls are
optional and explicitly requested. An ordinary design may be regenerated from
the active requirements, current working version, and revision delta without
exposing or preserving every internal dimension as a source parameter.

## Requirement-ledger behavior

The authoritative ledger persists active, superseded, and removed requirements.
It records origin, target, type, value, tolerance, explicit/proposed status,
originating message, and verification evidence. Revision deltas are immutable;
physical-test observations are stored separately from Volundr’s interpretation.

The initial request produced active requirements for bottle fit, clearance,
wall mounting, two mounting holes, fastener treatment, support, retention, and
one-handed removal. The generated Design Plan contained no exposed controls.
Its mounting layout was a fixed two-position layout, with two approved
positions and a Y hole axis. The plan’s concrete retention approach was a
flexible snap-arm arrangement.

## Source-validation changes

For a modern Design Plan with no exposed controls, source validation continues
to enforce safety, structured-body completeness, scaffold integrity, valid
result construction, and executable CadQuery structure. Missing canonical
parameter names are diagnostic only and do not block an ordinary candidate.

The existing parameter-effect contract remains active for explicitly exposed
controls and derived values needed to preserve those controls. A fixed two-hole
requirement is evaluated as geometry: count, approved/proposed positions,
diameter, axis, and intersection with the mounting structure. Even spacing or
future count sensitivity is not imposed when it is not an active requirement.

## Optional exposed-control behavior

Numeric values in the initial request did not create controls. An explicit
message such as “Expose bottle diameter as an adjustable control” adds only
that control to the revised Design Plan and activates strict source-effect
validation for it and its required derived relationships. Other dimensions
remain ordinary implementation details, and chat revisions remain available.

## Initial live request

The diagnostic command was:

```text
PYTHONPATH=. .venv/bin/python scripts/run_live_requirement_driven_revision_sequence.py \
  --report /tmp/volundr-requirement-driven-live-evaluation.json
```

It used the real Gemini API provider, FastAPI services, and the CadQuery
worker, with isolated temporary data and no browser. The first run completed
requirements extraction and Design Plan generation after bounded provider
repairs, generated structured geometry, and reached worker execution. The
candidate was not promoted.

Two subsequent exact attempts (`v2` and `v3`) stopped at Design Plan provider
validation with `planning returned invalid Design Plan`. The sequence runner
correctly did not invent later revisions without a Current working version.

## Worker execution evidence

In the completed first run:

- the structured geometry assembly succeeded;
- the worker compiled the model in approximately 3.77 seconds;
- one solid was detected;
- STEP, STL, and BREP artifacts were produced;
- the output was classified blocked rather than ready;
- provider timing and token usage were persisted for requirements, planning,
  and geometry attempts.

This confirms that removing ordinary source-effect blocking allows safe source
to reach the worker. It does not claim that this particular generated holder is
physically suitable.

## Requirement-compliance results

The first live candidate was blocked for genuine geometry and artifact reasons:

- `functional.mounting_hole_axis`: blocking; holes were detected along X
  instead of the required Y axis;
- `design_artifact.manifest_required_output_not_ready`: blocking;
- the generated artifact provided no reliable automatic evidence for several
  qualitative requirements, including bottle fit, boat suitability, and
  one-handed removal;
- orientation analysis recorded advisory overhang, bridge, and unsupported
  ceiling findings.

The former canonical-symbol and count-sensitivity failure did not block this
run. The actual output was judged instead. No Current working version was
created, and no misleading ready state was produced.

## Physical-review findings

The available evidence is insufficient to claim one-handed removal, retention
strength under boat motion, or successful bottle fit. These remain human-review
or test-print concerns unless reliable geometric evidence is available. The
wrong mounting-hole axis is a definitive blocking result.

## Revision 1: physical fit feedback

The intended message was:

```text
The printed fit is too tight. Add 0.5 mm clearance per side.
```

It would create a physical-test observation and replace the fit-clearance
requirement while preserving bottle size, mounting, support, retention, and
removal requirements. It was not executed in the live sequence because the
initial candidate did not produce a Current working version.

## Revision 2: structural feedback

The intended message was:

```text
Make the mounting plate thicker and reinforce it because it flexes.
```

It would persist the flex observation and structural revision delta without
creating an exposed thickness control. It was not executed for the same safe
lineage reason.

## Revision 3: irregular mounting change

The intended message was:

```text
Move the lower mounting hole 8 mm left to clear an obstruction.
```

The requirement-led model permits a revised explicit layout with two holes and
an irregular position; it does not impose uniform spacing. This was not
executed without an accepted base version.

## Optional-control result

Deterministic backend and browser fixtures cover adding an explicit control
after ordinary revisions. They verify that only the requested control is
activated and that later ordinary chat revisions remain possible. The live
control request was not attempted after the initial live block, so no live
provider result is claimed for it.

## Preserved history and working-version behavior

The workflow preserves failed attempts, artifacts, findings, requirement
deltas, and prior revisions. A blocked candidate leaves the previous Current
working version unchanged. Start-over creates a child revision lineage without
deleting the prior version. The live initial attempt had no prior working
version, so the project correctly remained without an active revision.

## Provider usage and timing

The first completed run used `gemini-3.5-flash-lite` for requirements, Design
Plan, and geometry. Requirements and Design Plan each required a bounded
repair after an invalid initial response; geometry completed without a source
contract retry. The persisted attempt records contain prompt version, model,
provider latency, token usage, and duration. The later two attempts failed
during Design Plan validation, demonstrating provider-response variability but
not a geometry-quality conclusion.

## Remaining limitations

- qualitative fit, retention, and one-handed removal still need physical or
  stronger evidence;
- the real provider can return invalid requirements or plans and requires the
  existing bounded repair behavior;
- the exact four-revision live chain awaits a valid initial Current working
  version;
- the initial geometry’s mounting-hole orientation remains a genuine design
  failure;
- no claim is made that the live holder is printable for the stated use.

## Recommendation for observed testing

Frontend usability testing may proceed with deterministic known-good and
known-failure chat-first fixtures. Live CAD-quality testing remains separate
and should resume for this holder only after a real candidate reaches the
worker and passes the available requirement and functional gates. The
requirement-first workflow should not be evaluated by whether Gemini happened
to preserve internal parameter names.
