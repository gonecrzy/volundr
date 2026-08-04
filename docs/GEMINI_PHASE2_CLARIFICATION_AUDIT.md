# Gemini Phase 2 clarification audit

Clarification is evaluated independently from CAD completion:

- `clarification_not_required`: the request was sufficiently specified.
- `clarification_required_correctly`: critical information was missing and
  the model requested it.
- `clarification_required_incorrectly`: the model stopped for information
  that was not required by the frozen facts and contract.
- `clarification_answered`: the frozen answer was submitted and the workflow
  resumed.
- `clarification_not_answered`: no answer was submitted.
- `clarification_answer_failed`: an answer attempt failed.
- `clarification_bypassed`: an answer existed but the workflow did not use it.
- `clarification_state_inconsistent`: persisted state contradicts the
  clarification decision.

## Case-001

The frozen corpus contains `phone_width: 78 mm`,
`phone_thickness_with_case: 12 mm`, and `desired_angle: approximately 65
degrees`. It does not contain a separate explicit `case_status` field; the
case condition is represented by the thickness-with-case fact. Profile B
asked for specific width, thickness, and case status to fit the phone slot and
ledge. That is a correct safety-preserving clarification request.

The current arm proceeded as generation-ready and reached topology. Profile B
stopped at valid `input_required`. No preserved evidence shows the frozen
facts being submitted to Profile B, so the continuation must not be invented.
The correct classification is:

`clarification_required_correctly` + `clarification_not_answered` +
`harness_incomplete_after_valid_clarification`.

This is a harness-incomplete comparison, not an ordinary Profile B failure.
Both arms must receive the same frozen clarification facts in any future
validation.

The machine-readable audit is
`reports/phase-2-clarification-audit.json` under the experiment evidence root.
