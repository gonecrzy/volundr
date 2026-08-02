# Compact and Detailed Pipeline Diagnosis

Date: 2026-08-02

This diagnosis covers the five-case live matrix in
`docs/LIVE_DESIGN_MATRIX_EVALUATION.md`. It records where execution stopped;
it does not turn provider failures into product claims.

## Classification

| Case | Stage | Classification | Deterministic normalization? | Retry? | Execution safe? | Repeated? |
|---|---|---|---|---|---|---|
| Circular spacer | worker/CadQuery | unsupported source statement | No; selector meaning is provider-owned | bounded repair was attempted | no, the worker correctly failed | not yet across products |
| Irregular bracket | design-artifact consistency | missing critical component identity | No; inventing a component mapping is unsafe | a regeneration may be appropriate | no; source does not represent the approved plan | no |
| Bottle holder | compact-plan normalization | invalid pattern identity/type | No; owner/type cannot be inferred safely | bounded plan retry is reasonable | no; pattern contract is ambiguous | similar pattern failures exist historically |
| Organizer | source contract | unapproved identity | No; a provider-added identity changes the approved contract | bounded source regeneration is reasonable | no; source identity drift is blocking | no |
| Enclosure | detailed-plan validation | missing critical pattern relationship | No; spacing cannot be invented for twelve slots | one bounded plan retry is reasonable | no; plan is incomplete | yes, repeated unchanged |

## Compact path

The compact path is reaching the provider and performing semantic checks. The
dominant failures are not harmless formatting:

- the bracket plan named rib components that the source did not build;
- the bottle plan emitted a malformed repeated-feature record;
- the organizer source invented derived identities outside the approved plan.

These failures affect execution identity or geometry intent, so allowing them
through would create misleading output. The current gates are therefore
appropriate for these particular records. The narrow ordinary-plan correction
does allow ordinary numeric values to be implemented as literals or locals,
but it does not allow a provider to mutate approved component/parameter
identities.

The safe normalization opportunity is limited to harmless representation
variation after identity validation. It must not infer a pattern owner, create
missing components, or silently approve provider-added source parameters.

## Detailed path

The enclosure route was correctly classified as `detailed_plan` because it has
two printable components, a removable relationship, fasteners, openings,
ventilation, and mounting posts. The provider returned a plan that repeatedly
omitted `spacing_parameter_id` for the ventilation pattern. Since the current
detailed contract requires complete repeated-feature semantics, the plan was
rejected before geometry generation. This is a repeated provider/contract
interoperability problem and is the strongest candidate for a narrow planning
prompt/schema correction in the next phase.

No detailed-plan gate was weakened in this pass.

## Answers to the evaluation questions

1. Deterministic normalization can repair only harmless formatting variation;
   none of the blocking records qualify.
2. A bounded provider retry is appropriate for malformed plans or source
   identity output. Repeated identical errors should not loop indefinitely.
3. The compact contract is strict at identity boundaries, not at ordinary
   numeric source representation. The detailed contract is strict at
   multipart/repeated-feature semantics.
4. The missing component and pattern relationships are required to assemble
   the approved geometry contract. The organizer's invented identities are
   not required and are therefore rejected rather than accepted as new
   controls.
5. Allowing these records to execute would either omit requested features or
   make the resulting geometry untraceable to the approved plan.
6. The repeated detailed pattern failure is the only identical failure in this
   matrix. It is not enough evidence for a broad new architecture layer, but
   it is enough to prioritize a narrow contract/prompt alignment investigation.

## Recommendation

Recommend compact/detailed planning hardening as the next development phase,
with a narrow focus on provider interoperability for component identities and
repeated-feature records. Do not add visual review or another generalized
validation framework yet: most compact/detailed cases did not reach stable
worker geometry in this evaluation.
