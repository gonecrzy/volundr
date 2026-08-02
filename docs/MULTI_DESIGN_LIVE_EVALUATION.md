# Multi-Design Live Evaluation

Date: 2026-08-01  
Mode: real Gemini API, real FastAPI services, real CadQuery worker, no browser  
Runner: `backend/scripts/run_live_multi_design_evaluation.py`

## Purpose and scope

This was a small diagnostic set for product-readiness evidence. It used one
isolated temporary data directory and created a separate project for each
case. It did not change CAD validation policy, retry a blocked design as a
different product mode, or claim physical compliance from incomplete evidence.

The cases were:

1. A compact wall-mounted tool bracket with two screw holes, a support ledge,
   and an open front.
2. A desktop organizer tray with four equal compartments, rounded outside
   corners, and a flat base.
3. A small electronics enclosure with a removable lid, cable opening, and
   mounting feet.

## Results

| Case | Requirements / plan result | Worker | Current working version | Result |
| --- | --- | --- | --- | --- |
| A wall bracket | Requirements completed; essential dimensional clarification requested | Not reached | None | Paused safely for user input |
| B organizer tray | Requirements completed; Design Plan response remained invalid after bounded attempts | Not reached | None | Blocked with provider/planning evidence |
| C lidded enclosure | Requirements completed; essential dimensional clarification requested | Not reached | None | Paused safely for user input |

No case reached geometry generation or the worker because none had a sufficient
validated plan. This is an accurate negative result: the runner did start the
real worker, but no job was submitted and no printable artifact, topology
result, or functional pass is claimed.

## Observed behavior

Cases A and C asked for dimensions needed to make a useful holder/enclosure
rather than silently inventing them. Their projects retained the extracted
requirements and active workflow state, with no candidate or misleading ready
state.

Case B exercised the bounded planning path. The provider returned a response
that did not pass the existing Design Plan contract after the allowed attempts.
The project retained the attempts and workflow evidence and did not create a
candidate. This is a provider/planning limitation, not evidence that the
organizer geometry is invalid.

Provider metadata and workflow timing remain in the persisted generation
attempts and workflow records. The redacted machine-readable run result was
written to a temporary path outside the repository; it contained no API key.

## Interpretation

The set demonstrates that the requirement-first workflow can keep different
designs separate, ask only when the current case is materially underspecified,
and stop invalid planning before worker execution. It does not yet establish
multi-design geometry quality because all three cases stopped upstream of
CadQuery execution.

The result also reinforces the testing split:

- deterministic fixtures are suitable for frontend usability testing;
- live CAD-quality testing must continue to report worker and physical
  evidence separately from upstream provider/planning failures.

## Limitations and next step

This was one run per case. It did not tune prompts, compare models, or infer a
model-quality ranking. A useful follow-up is to answer the clarification for
one case and rerun that case through the worker, while preserving this
upstream-blocked evidence as its own run.
