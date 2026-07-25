# Structured Revision Planning

This document defines Volundr's revision-planning lifecycle. It is the authority for bounded AI revisions after an accepted Design Plan and output manifest exist.

## Purpose

Structured revision planning turns a user revision request or selected validation finding into an immutable `revision-plan-v1` artifact before Gemini is allowed to modify OpenSCAD.

The plan answers:

- what is allowed to change
- which parameters, components, features, and outputs are targeted
- which dependent parameters must update together
- which values and product areas are protected
- whether the request needs clarification, conflicts with accepted requirements, or is unsupported
- how the revised source will be checked before compile and after candidate creation

Revision planning does not generate OpenSCAD.

## Lifecycle

```text
accepted assembly revision
  -> user request or validation finding
  -> revision-planning-v1
  -> clarification_required | revision_conflict | unsupported_revision | planning_failed
  -> revision_ready
  -> explicit plan approval
  -> openscad-revision-v2
  -> source-contract validation
  -> revision compliance validation
  -> per-output compile and validation
  -> candidate review
  -> explicit accept or reject
```

OpenSCAD generation is forbidden until the Revision Plan is `revision_ready` and `approved`.

## Revision Plan Record

Revision Plans are immutable and versioned. Clarification answers create a new plan version with `superseded_revision_plan_id` set.

Persisted fields include:

```text
id
project_id
base_revision_id
base_design_specification_id
base_design_plan_id
generation_attempt_id
superseded_revision_plan_id
generated_revision_id
revised_design_specification_id
revised_design_plan_id
version_number
schema_version
prompt_template_version
gemini_ruleset_version
provider
provider_model
user_instruction
reason
raw_response_path
plan_path
content_hash
base_source_hash
base_output_manifest_hash
base_design_specification_hash
base_design_plan_hash
outcome
review_state
clarification_required
revision_ready
approved_at
rejected_at
created_at
```

Stable outcomes:

```text
revision_ready
clarification_required
revision_conflict
unsupported_revision
planning_failed
```

Review states:

```text
clarification_required
pending_review
approved
rejected
```

## Plan Payload

`plan_path` stores JSON shaped like:

```json
{
  "schema_version": "revision-plan-v1",
  "reason": "user_request",
  "summary": "Increase lid thickness from 3 mm to 4 mm",
  "requested_changes": [
    {
      "target_type": "product_parameter",
      "target_id": "lid_thickness",
      "current_value": 3,
      "requested_value": 4,
      "change_type": "replace",
      "source": "user"
    }
  ],
  "targeted_components": ["lid"],
  "targeted_features": ["lid_lip"],
  "targeted_outputs": ["lid"],
  "targeted_findings": [],
  "allowed_parameter_changes": ["lid_thickness", "lid_lip_depth"],
  "required_dependency_changes": [
    {"parameter_id": "lid_lip_depth", "affects": ["lid_lip"]}
  ],
  "allowed_component_changes": ["lid"],
  "allowed_feature_changes": ["lid_lip"],
  "protected_parameters": [
    {"parameter_id": "body_width", "expected_value": 80, "unit": "mm"}
  ],
  "protected_components": ["body"],
  "protected_features": ["mounting_tabs"],
  "protected_outputs": ["body"],
  "prohibited_changes": ["Do not change body output geometry."],
  "success_criteria": [
    {"type": "parameter_value", "target_id": "lid_thickness", "expected_value": 4, "unit": "mm"},
    {"type": "parameter_unchanged", "target_id": "body_width", "expected_value": 80, "unit": "mm"},
    {"type": "output_exists", "target_id": "lid", "expected_value": true}
  ],
  "requires_design_specification_version": false,
  "requires_design_plan_version": false,
  "clarification_questions": [],
  "outcome": "revision_ready"
}
```

## Clarification

Ask revision clarification instead of generating when:

- the target component, feature, output, or parameter is ambiguous
- the requested value or unit is missing
- the request conflicts with protected requirements
- the request would require a new Design Specification or Design Plan version and the intended scope is unclear
- multiple dependency paths would produce materially different products
- a validation finding is selected but the desired correction strategy is unclear
- the request is outside current V1 scope

Questions must reference named parameters, components, outputs, or findings when possible.

## Compliance Checks

After `openscad-revision-v2` returns revised source and before compilation, Volundr compares base and revised source metadata against the approved Revision Plan.

Blocking compliance failures include:

- unauthorized protected parameter change
- missing protected parameter
- missing protected component marker
- missing protected feature marker
- missing protected output marker
- required output removed
- undeclared output rewrite that affects protected scope
- dependency update omitted when the plan requires it
- revision source introduces a source-contract hard violation

Allowed changes are limited to approved requested changes and required dependency changes. Static comparison is conservative; if a protected invariant cannot be verified from source metadata, the generation attempt fails before compile.

## Success Criteria

After a compliant source compiles and validates, Volundr persists Revision Success Results. Initial supported criterion types are:

```text
parameter_value
parameter_unchanged
output_exists
```

Failed blocking success criteria create candidate findings and can block acceptance.

## Finding-Driven Revisions

Candidate review may start a Revision Plan from a selected validation finding. The planner receives the finding ID, rule ID, expected value, detected value, affected feature/output metadata, and instruction to preserve unrelated requirements.

Finding-driven revisions still require explicit plan approval. Compiler repair is not used for geometric, printability, or product-scope violations.

## Legacy Compatibility

Accepted legacy revisions without an approved Design Plan remain loadable. Structured revision planning requires an accepted base revision with an approved Design Plan and output manifest. Legacy AI source editing paths may remain only as compatibility paths and should be clearly labeled when used.

## Known Limitations

- direct editable parameter changes and preset switching use the deterministic configuration workflow in `docs/PARAMETER_CONFIGURATION.md`
- no full Design Plan regeneration loop for complex revisions
- no automatic component-targeted partial source regeneration
- no geometric proof that untouched outputs are physically identical
- no automatic repair of geometric or printability violations
