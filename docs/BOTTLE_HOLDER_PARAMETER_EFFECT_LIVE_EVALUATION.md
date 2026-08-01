# Bottle-Holder Parameter-Effect Live Evaluation

Date: 2026-08-01  
Request: “Create a wall-mounted holder for an 81 mm bottle, suitable for a moving boat, with one-handed removal and two #8 mounting screws.”

Command: `backend/.venv/bin/python backend/scripts/run_live_bottle_holder_workflow.py --report /tmp/volundr-bottle-holder-live-result.json`

This was a browserless diagnostic run through a real `GeminiApiProvider`, real
FastAPI services, and a real CadQuery worker on `127.0.0.1`. The provider key
was supplied through the existing environment and is not included here or in
the JSON result.

## Result

The request was blocked accurately. No Current working version was created or
replaced:

- requirements passed without clarification;
- the Design Plan passed and was automatically approved for first-draft generation;
- deterministic derived values resolved, including `holder_inner_diameter =
  81.8 mm`, `holder_outer_diameter = 87.8 mm`, `holder_height = 101.25 mm`,
  `screw_spacing_vertical = 81.0 mm`, and `mounting_screw_hole_diameter = 4.2
  mm` for `#8`;
- the scaffold/source path reached structured geometry-body validation;
- the candidate and repair attempts were blocked because
  `mounting_screw_count` did not have a statically verifiable geometry effect;
- the final response was `blocked_attempt` with “Your current working version
  is unchanged.”;
- no printable output or ready candidate was produced, so no misleading ready
  state was emitted.

The relevant generation attempts were:

| Attempt | Prompt | Result | Time |
| --- | --- | --- | ---: |
| 1–2 | requirements | first invalid response repaired, then passed | 2.1 s / 1.9 s |
| 3 | Design Plan | passed | 9.4 s |
| 4 | geometry body | blocked: count effect unverifiable | 9.8 s |
| 5 | geometry-body repair | blocked: count effect unverifiable | 3.3 s |

The complete chat request elapsed time was approximately 29.8 s. The worker
process was started and remained alive, but the source was rejected before a
valid worker job could produce outputs. Mounting, floor/support, removal, and
retention functional checks therefore did not run; running them without a
validated geometry body would weaken the gate. This is a genuine semantic
failure, not a harness or provider failure.

The persisted correlated events include chat submission and intent
classification, automatic requirements and Design Plan progression, automatic
generation start, and `blocked_attempt.preserved`. The redacted raw result is
available from the command’s `--report` output when a rerun is needed.

## Follow-up

The next provider attempt must use `mounting_screw_count` (or an approved
derived cardinality) to construct the hole pattern. A fixed two-point list,
hardcoded range, or repeated literal calls must remain blocked even though the
current request has a count of two. Once that source contract passes, the
existing worker, topology, consistency, and functional checks should run in
the normal sequence.
